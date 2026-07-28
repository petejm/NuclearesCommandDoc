#!/usr/bin/env python3
"""
Nucleares write-probe harness.

Measures what a POST actually does, without attributing background drift to
your command. Read tools/README.md before using it.

Design rules, each of which exists because violating it produced a wrong
published result:

1. Fail closed. Every request has three outcomes: a value, a documented
   not-found, or an ERROR. ERROR never collapses into either of the others.
   A harness that counted connection errors as successful reads once reported
   "91 readable, 0 write-only" when the truth was 35 and 56.

2. Multi-sample matched nulls. A single null sample aliases against any signal
   whose period is comparable to the settle window, which silently puts drift
   on both sides of the subtraction. This takes N null samples and requires a
   variable to exceed the null's own observed spread before counting as an
   effect.

3. Never assume a constant. Drift rate in this simulation is plant-state
   dependent, not a property of the game. Each probe derives its own baseline
   immediately adjacent in time.

4. Read back by the right name. 56 of 91 writable variables are write-only;
   their read-back lives under a different name. Pass it explicitly.

5. Hard blocklist. FUN_* are trigger writes with no safe no-op form.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

BASE = "http://localhost:8785"
NOT_FOUND = "does not exist"

# Trigger writes: the act of writing IS the action. No safe no-op form exists,
# so these can never appear in a sweep. See docs/fun-family.md.
BLOCKED_PREFIXES = ("FUN_",)
# Recoverable only by a human: the API has two working trip paths and no
# working reset. See docs/emergency-controls.md.
BLOCKED_EXACT = {
    "CORE_SCRAM_BUTTON",
    "CORE_EMERGENCY_STOP",
    "STEAM_TURBINE_TRIP",
}


class Blocked(Exception):
    pass


def guard(name: str, allow_dangerous: bool) -> None:
    if name.startswith(BLOCKED_PREFIXES):
        raise Blocked(
            f"{name} is a FUN_* trigger write. Writing IS the action and there "
            f"is no safe no-op form. Refusing."
        )
    if name in BLOCKED_EXACT and not allow_dangerous:
        raise Blocked(
            f"{name} has no programmatic recovery path. Re-run with "
            f"--allow-dangerous on a throwaway save if you mean it."
        )


def listener_up() -> bool:
    """Positive control. Inspects the kernel listener table.

    Deliberately not a connection attempt: the API binds IPv6 loopback only,
    so a probe over the wrong family shares the broken component it is testing
    and cannot detect its own fault.
    """
    try:
        out = subprocess.run(
            ["ss", "-lntn"], capture_output=True, text=True, timeout=5
        ).stdout
    except Exception:
        return False
    return ":8785" in out


@dataclass
class Reading:
    ok: bool
    value: str | None
    status: str  # VALUE | NOT_FOUND | EMPTY | ERROR
    detail: str = ""

    def numeric(self) -> float | None:
        if self.status != "VALUE" or self.value is None:
            return None
        try:
            return float(self.value)
        except ValueError:
            return None


def read(name: str, timeout: float = 5.0) -> Reading:
    url = f"{BASE}/?Variable={name}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace").strip()
    except Exception as e:
        # Never let this become a value. See design rule 1.
        return Reading(False, None, "ERROR", f"{type(e).__name__}: {e}")
    if NOT_FOUND in body:
        return Reading(True, None, "NOT_FOUND", body)
    if body == "":
        # Real third state: some GET-list members return empty, e.g.
        # RODS_POS_ORDERED and RODS_STATUS.
        return Reading(True, "", "EMPTY")
    return Reading(True, body, "VALUE")


def write(name: str, value: str, timeout: float = 5.0) -> Reading:
    """POST with an explicit empty body. Omitting it yields HTTP 411."""
    url = f"{BASE}/?Variable={name}&value={value}"
    req = urllib.request.Request(url, data=b"", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return Reading(True, r.read().decode("utf-8", "replace").strip(),
                           "VALUE", f"HTTP {r.status}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace").strip()
        # 404 = name not writable. 412 = writable but gated.
        return Reading(True, None, "NOT_FOUND" if e.code == 404 else "ERROR",
                       f"HTTP {e.code}: {body}")
    except Exception as e:
        return Reading(False, None, "ERROR", f"{type(e).__name__}: {e}")


def snapshot(names: list[str]) -> dict[str, Reading]:
    return {n: read(n) for n in names}


@dataclass
class NullModel:
    """Per-variable drift envelope measured immediately before the write."""

    spread: dict[str, float] = field(default_factory=dict)
    moved: set[str] = field(default_factory=set)
    errored: set[str] = field(default_factory=set)

    def is_effect(self, name: str, before: Reading, after: Reading) -> bool:
        if name in self.errored:
            return False  # could not measure, so cannot attribute
        if name in self.moved:
            # Variable drifts on its own. Require the change to exceed the
            # envelope the null itself displayed.
            b, a = before.numeric(), after.numeric()
            if b is None or a is None:
                return False
            return abs(a - b) > self.spread.get(name, 0.0) * 2.0
        return before.value != after.value


def measure_null(names: list[str], samples: int, interval: float) -> NullModel:
    """Sample with NO write issued, to learn what moves on its own.

    Multiple samples, not one. A single before/after pair cannot distinguish a
    static variable from one sampled twice at the same phase of a sawtooth.
    """
    series: dict[str, list[Reading]] = {n: [] for n in names}
    for i in range(samples):
        for n in names:
            series[n].append(read(n))
        if i < samples - 1:
            time.sleep(interval)

    m = NullModel()
    for n, rs in series.items():
        if any(r.status == "ERROR" for r in rs):
            m.errored.add(n)
            continue
        vals = [r.value for r in rs]
        if len(set(vals)) > 1:
            m.moved.add(n)
            nums = [r.numeric() for r in rs if r.numeric() is not None]
            m.spread[n] = (max(nums) - min(nums)) if len(nums) > 1 else 0.0
    return m


def probe(target: str, value: str, watch: list[str], readback: str | None,
          samples: int, interval: float, settle: float,
          allow_dangerous: bool) -> dict:
    guard(target, allow_dangerous)
    if not listener_up():
        raise SystemExit(
            "Webserver not listening on 8785. It unbinds on save load and "
            "needs re-enabling per save. Check: ss -lntp | grep 8785"
        )

    version = read("GAME_VERSION").value
    watch = sorted(set(watch) | ({readback} if readback else set()))

    null = measure_null(watch, samples, interval)
    before = snapshot(watch)
    resp = write(target, value)
    time.sleep(settle)
    after = snapshot(watch)

    effects = []
    for n in watch:
        if null.is_effect(n, before[n], after[n]):
            effects.append({"variable": n,
                            "before": before[n].value,
                            "after": after[n].value})

    verdict = "NO_EFFECT"
    if resp.status == "NOT_FOUND":
        verdict = "NOT_WRITABLE"          # HTTP 404
    elif "HTTP 412" in (resp.detail or ""):
        verdict = "GATED"                 # writable but consent-gated
    elif effects:
        verdict = "EFFECT"
    if readback and readback in after:
        rb = after[readback]
        if rb.status == "VALUE" and rb.value == value:
            verdict = "CONFIRMED"

    return {
        "game_version": version,
        "target": target,
        "value_posted": value,
        "response": resp.detail or resp.value,
        "verdict": verdict,
        "readback_variable": readback,
        "readback_value": after[readback].value if readback else None,
        "effects": effects,
        "drifting_during_null": sorted(null.moved),
        "unmeasurable": sorted(null.errored),
        "method": {
            "null_samples": samples,
            "null_interval_s": interval,
            "settle_s": settle,
            "note": "Variables listed in drifting_during_null required a "
                    "change exceeding twice their observed null spread to "
                    "count as an effect.",
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="variable to POST")
    ap.add_argument("value", help="value to post")
    ap.add_argument("--watch", nargs="+", required=True,
                    help="variables to observe for effects")
    ap.add_argument("--readback",
                    help="variable to confirm the write; 56 of 91 writables "
                         "read back under a DIFFERENT name")
    ap.add_argument("--null-samples", type=int, default=6)
    ap.add_argument("--null-interval", type=float, default=2.0)
    ap.add_argument("--settle", type=float, default=8.0)
    ap.add_argument("--allow-dangerous", action="store_true",
                    help="permit trip commands that have no reset path")
    a = ap.parse_args()

    try:
        result = probe(a.target, a.value, a.watch, a.readback,
                       a.null_samples, a.null_interval, a.settle,
                       a.allow_dangerous)
    except Blocked as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
