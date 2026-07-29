#!/usr/bin/env python3
"""
Live checklist tracker for the Nucleares in-game startup checklist ([C] key).

The in-game checklist tracks what you *clicked*. This tracks what the plant is
actually *doing*, read from the API. Those are not the same thing: a command can
be accepted and stored while the actuator is still slewing, an indexed variable
can be `null` because the equipment is not there, and HTTP 200 certifies nothing.

Usage:
    python3 tools/checklist.py --loop 3
    python3 tools/checklist.py --loop 3 --watch 5

Statuses:
    OK          telemetry satisfies the item
    PENDING     telemetry does not satisfy it yet
    DONE        satisfied earlier, now superseded by a later checklist item
    SLEWING     ordered value is right, actual is still travelling
    NO-SIGNAL   the item has no API variable. NOT a pass. See below.
    NO-REF      observable, but the threshold is not knowable from the API
    ERROR       could not read. Never silently treated as pass or fail.

NO-SIGNAL is deliberate and load-bearing. Several checklist items (terminals,
external power switch, the grid request, the breaker close) have no writable or
readable variable at all, so an automated client can neither perform nor verify
them. Reporting them as "unknown" rather than skipping them is the whole point:
it makes the gap in the commandable surface visible instead of implicit.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from typing import Callable

BASE = "http://localhost:8785"
NOT_FOUND = "does not exist"

OK, PENDING, SLEWING, NO_SIGNAL, NO_REF, ERROR, DONE = (
    "OK", "PENDING", "SLEWING", "NO-SIGNAL", "NO-REF", "ERROR", "DONE")


def listener_up() -> bool:
    """Positive control via the kernel listener table.

    Not a connection attempt: the API binds IPv6 loopback only, so a probe over
    the wrong family shares the broken component it is testing.
    """
    try:
        out = subprocess.run(["ss", "-lntn"], capture_output=True,
                             text=True, timeout=5).stdout
    except Exception:
        return False
    return ":8785" in out


def read(name: str) -> tuple[str, str | None]:
    """Returns (status, value). Five outcomes, none collapsed into another."""
    try:
        with urllib.request.urlopen(f"{BASE}/?Variable={name}", timeout=5) as r:
            body = r.read().decode("utf-8", "replace").strip()
    except Exception as e:
        return ERROR, f"{type(e).__name__}"
    if NOT_FOUND in body:
        return ERROR, "no such variable"
    if body == "":
        return ERROR, "empty"
    if body == "null":
        return ERROR, "null (equipment absent / bay empty)"
    return "VALUE", body


def num(v: str | None) -> float | None:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class Ctx:
    """Reads variables once per pass and caches, so one item can reference
    several without re-fetching."""

    def __init__(self, loop: int):
        self.i = loop - 1          # checklist LOOP 3 -> API index 2
        self.loop = loop
        self._c: dict[str, tuple[str, str | None]] = {}

    def get(self, name: str) -> tuple[str, str | None]:
        if name not in self._c:
            self._c[name] = read(name)
        return self._c[name]

    def val(self, name: str) -> str | None:
        st, v = self.get(name)
        return v if st == "VALUE" else None

    def n(self, name: str) -> float | None:
        return num(self.val(name))


@dataclass
class Item:
    label: str
    check: Callable[[Ctx], tuple[str, str]]


def near(x: float | None, target: float, tol: float) -> bool:
    return x is not None and abs(x - target) <= tol


def simple(name_fn, pred, fmt="{}"):
    """Build a check over one variable, propagating read errors honestly."""
    def _c(c: Ctx):
        name = name_fn(c)
        st, v = c.get(name)
        if st == ERROR:
            return ERROR, f"{name}: {v}"
        return (OK if pred(v) else PENDING), fmt.format(v)
    return _c


def ordered_vs_actual(ordered_fn, actual_fn, target, tol=3.0):
    """Distinguish 'commanded correctly but still travelling' from 'not set'.

    This exists because _ACTUAL slews toward _ORDERED at a rate limit, so a
    naive check on _ACTUAL reports PENDING for an item that is already correctly
    commanded and simply in transit.
    """
    def _c(c: Ctx):
        o, a = c.n(ordered_fn(c)), c.n(actual_fn(c))
        if a is None:
            return ERROR, f"{actual_fn(c)}: unreadable"
        if near(a, target, tol):
            return OK, f"actual={a:g}"
        if near(o, target, tol):
            return SLEWING, f"ordered={o:g} actual={a:g}"
        return PENDING, f"ordered={o if o is not None else '?'} actual={a:g}"
    return _c


def no_signal(why: str):
    return lambda c: (NO_SIGNAL, why)


def build(loop: int) -> list[Item]:
    I = lambda c: c.i  # noqa: E731

    def gen_modes(c: Ctx):
        m1, m2 = c.val("EMERGENCY_GENERATOR_1_MODE"), c.val("EMERGENCY_GENERATOR_2_MODE")
        s1, s2 = c.val("EMERGENCY_GENERATOR_1_STATUS"), c.val("EMERGENCY_GENERATOR_2_STATUS")
        ok = m1 == "MANUAL" and m2 == "MANUAL" and s1 == "INACTIVO" and s2 == "INACTIVO"
        return (OK if ok else PENDING), f"g1={m1}/{s1} g2={m2}/{s2}"

    def pzr_temp(c: Ctx):
        t, op = c.n("PRESSURIZER_TEMPERATURE"), c.n("PRESSURIZER_TEMPERATURE_OPERATIVE")
        if t is None or op is None:
            return ERROR, "unreadable"
        d = t - op
        return (OK if abs(d) <= 10 else PENDING), f"{t:.1f} vs op {op:.0f} (dev {d:+.1f})"

    def fuel(c: Ctx):
        states = [(n, c.val(f"CORE_BAY_{n}_STATE")) for n in range(1, 10)]
        loaded = [n for n, s in states if s and s != "VACIO"]
        return (OK if loaded else PENDING), f"loaded bays: {loaded or 'none'}"

    def boiling(c: Ctx):
        t = c.n(f"COOLANT_SEC_{I(c)}_TEMPERATURE")
        bp = c.n(f"STEAM_GEN_{I(c)}_BOILING_POINT")
        ev = c.n(f"STEAM_GEN_{I(c)}_EVAPORATED")
        if t is None or bp is None:
            return ERROR, "unreadable"
        marg = t - bp
        st = OK if (ev or 0) > 0 else PENDING
        return st, f"sec {t:.1f} vs boil {bp:.1f} (margin {marg:+.1f}), evap={ev}"

    def breaker(c: Ctx):
        """Confirm real grid connection.

        Two traps here, both observed live:

        1. GENERATOR_{n}_BREAKER reads True even on idle, uninstalled units, so
           it carries no information.
        2. GENERATOR_{n}_KW is a potential figure during spin-up, not delivered
           power, when amps read 0. Observed reading 33702 kW at 15.14 Hz with
           0 amps. An earlier version of this check used kw > 0 and passed a
           generator that was delivering nothing. With amps above 0, KW is
           trustworthy: it equals V times A divided by 1000, exactly, see
           ../docs/value-semantics.md.

        POWER_FROM_TURBINE_KW is not a substitute reference for either
        regime above. It does not track generation at all, see the same doc.
        An earlier version of this comment cited a POWER_FROM_TURBINE_KW
        reading alongside the 0-amp observation as if it corroborated
        anything; it did not, it was coincidentally a low number in a low
        regime.

        Amps is the honest indicator, cross-checked against grid frequency.
        """
        amps = c.n(f"GENERATOR_{I(c)}_A")
        hz = c.n(f"GENERATOR_{I(c)}_HERTZ")
        kw = c.n(f"GENERATOR_{I(c)}_KW")
        if amps is None or hz is None:
            return ERROR, "unreadable"
        synced = 45 <= hz <= 55
        if amps > 0 and synced:
            return OK, f"{amps:g} A at {hz:g} Hz (kw={kw})"
        why = "no current" if amps <= 0 else f"off-frequency {hz:g} Hz"
        return PENDING, f"{why}; amps={amps:g} hz={hz:g} kw={kw} <- kw is not delivered power"

    return [
        Item("Activate all terminals", no_signal("no variable")),
        Item("External Power ON", simple(lambda c: "POWER_FROM_EXTERNAL_KW",
             lambda v: (num(v) or 0) > 0, "{} kW")),
        Item("Generators MANUAL / OFF", gen_modes),
        Item("Resistor Bank ON", simple(lambda c: "RESISTOR_BANKS_MAIN_SWITCH",
             lambda v: v == "True")),
        Item("PZR Thermostat & Heaters ON", simple(lambda c: "PRESSURIZER_HEATERS_ON",
             lambda v: v == "True")),
        Item("Primary Pump ~15%", ordered_vs_actual(
             lambda c: f"COOLANT_CORE_CIRCULATION_PUMP_{I(c)}_ORDERED_SPEED",
             lambda c: f"COOLANT_CORE_CIRCULATION_PUMP_{I(c)}_SPEED", 15, 3)),
        Item("Turbine Bypass 100%", ordered_vs_actual(
             lambda c: f"STEAM_TURBINE_{I(c)}_BYPASS_ORDERED",
             lambda c: f"STEAM_TURBINE_{I(c)}_BYPASS_ACTUAL", 100, 3)),
        Item("Main Steam Control Valve 0%", ordered_vs_actual(
             lambda c: f"MSCV_{I(c)}_OPENING_ORDERED",
             lambda c: f"MSCV_{I(c)}_OPENING_ACTUAL", 0, 2)),
        Item("Startup Motive Steam Valve 100%", ordered_vs_actual(
             lambda c: "STEAM_EJECTOR_STARTUP_MOTIVE_VALVE_ORDERED",
             lambda c: "STEAM_EJECTOR_STARTUP_MOTIVE_VALVE_ACTUAL", 100, 3)),
        Item("Operational Motive Steam Valve 0%", ordered_vs_actual(
             lambda c: "STEAM_EJECTOR_OPERATIONAL_MOTIVE_VALVE_ORDERED",
             lambda c: "STEAM_EJECTOR_OPERATIONAL_MOTIVE_VALVE_ACTUAL", 0, 3)),
        Item("Confirm PZR operating temperature", pzr_temp),
        Item("Plant Mode NOMINAL", simple(lambda c: "CORE_OPERATION_MODE",
             lambda v: v == "NOMINAL")),
        Item("Control Rods ~93%", simple(lambda c: "RODS_POS_ACTUAL",
             lambda v: near(num(v), 93, 1.5), "{}%")),
        Item("Load fuel", fuel),
        Item("Secondary Pump ~25%", ordered_vs_actual(
             lambda c: f"COOLANT_SEC_CIRCULATION_PUMP_{I(c)}_ORDERED_SPEED",
             lambda c: f"COOLANT_SEC_CIRCULATION_PUMP_{I(c)}_SPEED", 25, 3)),
        Item("Cooling Pump ~25%", ordered_vs_actual(
             lambda c: "CONDENSER_CIRCULATION_PUMP_ORDERED_SPEED",
             lambda c: "CONDENSER_CIRCULATION_PUMP_SPEED", 25, 3)),
        Item("STG Coolant operating level", lambda c: (
             NO_REF, f"COOLANT_SEC_{c.i}_VOLUME={c.val(f'COOLANT_SEC_{c.i}_VOLUME')} "
                     f"(shutdown guide targets ~50000)")),
        Item("Retention Tank ~50%", lambda c: (
             NO_REF, f"volume={c.val('VACUUM_RETENTION_TANK_VOLUME')} "
                     f"(no capacity variable exists, so percent is not computable)")),
        Item("Vacuum Pump STARTUP", simple(lambda c: "CONDENSER_VACUUM_PUMP_MODE",
             lambda v: v == "STARTUP")),
        Item("Turbine Bypass 0%", ordered_vs_actual(
             lambda c: f"STEAM_TURBINE_{I(c)}_BYPASS_ORDERED",
             lambda c: f"STEAM_TURBINE_{I(c)}_BYPASS_ACTUAL", 0, 2)),
        Item("Vacuum Pressure 0.1 bar", simple(lambda c: "CONDENSER_PRESSURE",
             lambda v: (num(v) if num(v) is not None else 9) <= 0.1, "{} bar")),
        Item("Vacuum Pump OPERATIONAL", simple(lambda c: "CONDENSER_VACUUM_PUMP_MODE",
             lambda v: v == "OPERACIONAL", "{} (reads Spanish, written English)")),
        Item("Startup Motive Steam Valve 0%", ordered_vs_actual(
             lambda c: "STEAM_EJECTOR_STARTUP_MOTIVE_VALVE_ORDERED",
             lambda c: "STEAM_EJECTOR_STARTUP_MOTIVE_VALVE_ACTUAL", 0, 3)),
        Item("Main Steam Control Valve >= 25%", simple(
             lambda c: f"MSCV_{c.i}_OPENING_ACTUAL",
             lambda v: (num(v) or 0) >= 25, "actual={}")),
        Item("Steam being generated", boiling),
        Item("Operational Motive Steam Valve >= 30%", simple(
             lambda c: "STEAM_EJECTOR_OPERATIONAL_MOTIVE_VALVE_ACTUAL",
             lambda v: (num(v) or 0) >= 30, "actual={}")),
        Item("Turbine Torque > 2.0", simple(
             lambda c: f"STEAM_TURBINE_{c.i}_TORQUE",
             lambda v: (num(v) or 0) > 2.0, "{}")),
        Item("Request STARTUP - Grid", no_signal("no variable")),
        # The in-game checklist text says "> 3050", but the synchroscope gate
        # that actually lets you close the breaker is 3060. Operator-confirmed.
        Item("Turbine RPM >= 3060 (sync gate)", simple(
             lambda c: f"STEAM_TURBINE_{c.i}_RPM",
             lambda v: (num(v) or 0) >= 3060, "{} rpm")),
        Item("Sync - CLOSE Breaker", breaker),
        # `(num(v) or 1) == 0` was the obvious spelling and it could never
        # pass. The `or 1` was meant to fail closed when the value does not
        # parse, substituting a non-zero so an unreadable reading is not
        # scored as OK. But 0.0 is falsy too, so the guard also swallowed
        # the one value that SHOULD pass, and this item read PENDING at a
        # plant with external power genuinely at 0. Found on a live plant.
        # The rule this is an instance of: never use `or` to default a
        # numeric when zero is a meaningful value. Test against None.
        Item("External Power OFF", simple(lambda c: "POWER_FROM_EXTERNAL_KW",
             lambda v: num(v) is not None and num(v) == 0, "{} kW")),
    ]


COLOR = {OK: "\033[32m", DONE: "\033[32m", PENDING: "\033[90m", SLEWING: "\033[33m",
         NO_SIGNAL: "\033[35m", NO_REF: "\033[36m", ERROR: "\033[31m"}


def run(loop: int, plain: bool) -> None:
    c = Ctx(loop)
    items = build(loop)
    ver = c.val("GAME_VERSION")
    inst = c.val(f"STEAM_TURBINE_{c.i}_INSTALLED")
    print(f"Nucleares startup checklist  |  LOOP {loop} (API index {c.i})  "
          f"|  build {ver}  |  turbine installed: {inst}")
    if inst == "False":
        print("  WARNING: this loop's turbine is not installed. Its variables "
              "will return confident, permanently-zero values.")
    print("-" * 96)
    # Some items are superseded later in the same checklist: bypass goes 100
    # then 0, MSCV goes 0 then >=25, the startup motive valve goes 100 then 0,
    # the vacuum pump goes STARTUP then OPERATIONAL. Once the later item is
    # satisfied the earlier one legitimately no longer matches, and reporting
    # that as PENDING reads as a regression rather than progress.
    SUPERSEDED_BY = {
        "Turbine Bypass 100%": "Turbine Bypass 0%",
        "Main Steam Control Valve 0%": "Main Steam Control Valve >= 25%",
        "Startup Motive Steam Valve 100%": "Startup Motive Steam Valve 0%",
        "Operational Motive Steam Valve 0%": "Operational Motive Steam Valve >= 30%",
        "Vacuum Pump STARTUP": "Vacuum Pump OPERATIONAL",
        "External Power ON": "External Power OFF",
    }
    results: dict[str, str] = {}
    counts: dict[str, int] = {}
    evaluated = []
    for it in items:
        try:
            st, detail = it.check(c)
        except Exception as e:                     # never let a bug read as pass
            st, detail = ERROR, f"check raised {type(e).__name__}: {e}"
        results[it.label] = st
        evaluated.append((it, st, detail))
    for i, (it, st, detail) in enumerate(evaluated):
        later = SUPERSEDED_BY.get(it.label)
        if st == PENDING and later and results.get(later) == OK:
            st, detail = DONE, f"superseded by '{later}' ({detail})"
            evaluated[i] = (it, st, detail)
    for it, st, detail in evaluated:
        counts[st] = counts.get(st, 0) + 1
        col, rst = ("", "") if plain else (COLOR.get(st, ""), "\033[0m")
        print(f"  {col}{st:<10}{rst} {it.label:<38} {detail}")
    print("-" * 96)
    print("  " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print("  NO-SIGNAL items have no API variable and cannot be verified. "
          "They are not passes.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--loop", type=int, default=3, choices=[1, 2, 3],
                    help="in-game LOOP number; API index is this minus one")
    ap.add_argument("--watch", type=float, metavar="SECONDS",
                    help="repeat every N seconds")
    ap.add_argument("--plain", action="store_true", help="no ANSI colour")
    a = ap.parse_args()

    if not listener_up():
        print("Webserver not listening on 8785. It unbinds on save load and "
              "needs re-enabling per save.\nCheck: ss -lntp | grep 8785",
              file=sys.stderr)
        return 1
    if not a.watch:
        run(a.loop, a.plain)
        return 0
    try:
        while True:
            print("\033[2J\033[H" if not a.plain else "")
            run(a.loop, a.plain)
            time.sleep(a.watch)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
