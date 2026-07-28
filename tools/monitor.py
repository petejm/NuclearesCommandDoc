#!/usr/bin/env python3
"""
Steady-state monitor for a running Nucleares plant.

Watches the conditions that actually require operator action and stays quiet
otherwise. Read-only: this tool contains no write method at all, and that
absence is the safety guarantee rather than a flag you could toggle.

    python3 tools/monitor.py --loop 3
    python3 tools/monitor.py --loop 3 --interval 10 --log run.tsv

Design notes, each from a failure this repository documents:

* **Relational guards, not thresholds.** The two conditions that nearly dried
  the secondary loop were both comparisons between variables, and no
  single-variable limit could express either. Steam balance is
  `OUTLET vs RETURN`; boiling is `secondary temperature vs a live boiling
  point` that moves with pressure.

* **Guard the integral, not the derivative.** Inventory is judged on level and
  the net balance, not on a rate sampled over one interval. Several of these
  signals are stepped sawtooths, so a short-window rate is noise.

* **Fail closed.** An unreadable variable raises an alert. It never reads as
  healthy.

* **No baked-in drift constants.** Trends come from this run's own history.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from collections import deque

BASE = "http://localhost:8785"


def listener_up() -> bool:
    try:
        out = subprocess.run(["ss", "-lntn"], capture_output=True,
                             text=True, timeout=5).stdout
    except Exception:
        return False
    return ":8785" in out


def read(name: str):
    """Returns (ok, value_or_reason). Never collapses an error into a value."""
    try:
        with urllib.request.urlopen(f"{BASE}/?Variable={name}", timeout=5) as r:
            body = r.read().decode("utf-8", "replace").strip()
    except Exception as e:
        return False, type(e).__name__
    if "does not exist" in body:
        return False, "no such variable"
    if body in ("", "null"):
        return False, f"'{body}'"
    return True, body


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class Monitor:
    def __init__(self, loop: int):
        self.i = loop - 1
        self.loop = loop
        self.hist: dict[str, deque] = {}

    def snap(self) -> tuple[dict, list[str]]:
        i = self.i
        names = {
            "sec_liq": f"COOLANT_SEC_{i}_LIQUID_VOLUME",
            "sec_temp": f"COOLANT_SEC_{i}_TEMPERATURE",
            "boil": f"STEAM_GEN_{i}_BOILING_POINT",
            "out": f"STEAM_GEN_{i}_OUTLET",
            "ret": f"STEAM_GEN_{i}_RETURN_FLOW_PLUS_CONDENSED",
            "mscv": f"MSCV_{i}_OPENING_ACTUAL",
            "rpm": f"STEAM_TURBINE_{i}_RPM",
            "hz": f"GENERATOR_{i}_HERTZ",
            "amps": f"GENERATOR_{i}_A",
            "gen_kw": f"GENERATOR_{i}_KW",
            "sec_pump": f"COOLANT_SEC_CIRCULATION_PUMP_{i}_SPEED",
            "core_t": "CORE_TEMP",
            "core_t_max": "CORE_TEMP_MAX",
            "core_p": "CORE_PRESSURE",
            "core_p_max": "CORE_PRESSURE_MAX",
            "crit": "CORE_STATE_CRITICALITY",
            "core_integ": "CORE_INTEGRITY",
            "pzr_p": "PRESSURIZER_PRESSURE",
            "pzr_p_op": "PRESSURIZER_PRESSURE_OPERATIVE",
            "pzr_fill": "PRESSURIZER_FILL_LEVEL",
            "pzr_integ": "PRESSURIZER_INTEGRITY",
            "pzr_heaters": "PRESSURIZER_HEATERS_ON",
            "demand": "POWER_DEMAND_MW",
        }
        vals, errs = {}, []
        for k, n in names.items():
            ok, v = read(n)
            if not ok:
                errs.append(f"{n}: {v}")
                vals[k] = None
            else:
                vals[k] = fnum(v) if fnum(v) is not None else v
        for k, v in vals.items():
            if isinstance(v, float):
                self.hist.setdefault(k, deque(maxlen=30)).append(v)
        return vals, errs

    def trend(self, key: str) -> float | None:
        """Net change across this run's own history. Not a one-interval rate."""
        h = self.hist.get(key)
        if not h or len(h) < 3:
            return None
        return h[-1] - h[0]

    def alerts(self, v: dict, errs: list[str]) -> list[tuple[str, str]]:
        a: list[tuple[str, str]] = []
        for e in errs:
            a.append(("ERROR", f"unreadable {e}"))

        out, ret = v.get("out"), v.get("ret")
        liq, tr = v.get("sec_liq"), self.trend("sec_liq")
        if isinstance(out, float) and isinstance(ret, float):
            bal = ret - out
            if bal < 0 and isinstance(tr, float) and tr < 0:
                a.append(("CRIT", f"secondary losing inventory: balance {bal:+.1f} "
                                  f"(out {out:.0f} vs return {ret:.0f}), "
                                  f"liquid {liq:.0f} and falling ({tr:+.0f} over window). "
                                  f"Lever: close MSCV or add makeup"))
            elif bal < 0:
                a.append(("WARN", f"steam draw exceeds return: {bal:+.1f}"))

        st, bp = v.get("sec_temp"), v.get("boil")
        if isinstance(st, float) and isinstance(bp, float) and st < bp:
            a.append(("WARN", f"secondary below boiling: {st:.1f} vs {bp:.1f} "
                              f"({st - bp:+.1f}). No steam will be made"))

        hz, rpm, amps = v.get("hz"), v.get("rpm"), v.get("amps")
        if isinstance(amps, float) and amps > 0:
            if isinstance(hz, float) and not (49.5 <= hz <= 50.5):
                a.append(("CRIT", f"on-grid but off-frequency: {hz} Hz"))
            if isinstance(rpm, float) and rpm < 3050:
                a.append(("CRIT", f"on-grid but RPM {rpm:.0f} below sync"))

        for lbl, cur, mx, frac in (
            ("core temp", v.get("core_t"), v.get("core_t_max"), 0.85),
            ("core pressure", v.get("core_p"), v.get("core_p_max"), 0.85),
        ):
            if isinstance(cur, float) and isinstance(mx, float) and mx and cur > mx * frac:
                a.append(("CRIT", f"{lbl} {cur:.0f} is above {frac:.0%} of max {mx:.0f}"))

        p, po = v.get("pzr_p"), v.get("pzr_p_op")
        if isinstance(p, float) and isinstance(po, float):
            d = p - po
            trend = self.trend("pzr_p")
            # Only complain if it is NOT already correcting itself. A deviation
            # that is closing needs no operator action.
            closing = isinstance(trend, float) and (d > 0) == (trend < 0) and abs(trend) > 0.5
            if abs(d) > 15 and not closing:
                a.append(("WARN", f"pressurizer {d:+.1f} bar off setpoint and not converging"))

        # Real Westinghouse plants cut ALL pressurizer heaters at 17% level,
        # because heaters run in a steam environment are destroyed. Nucleares
        # has no such interlock and the API cannot command the heaters, so only
        # a human can act on this. Observed live: heaters ON at 0.46% fill on a
        # pressurizer carrying three ALTA_TEMPERATURA deterioration entries.
        # See docs/reference-control-laws.md.
        fill, heat = v.get("pzr_fill"), v.get("pzr_heaters")
        if isinstance(fill, float) and heat == "True":
            if fill < 17:
                a.append(("CRIT", f"pressurizer heaters ON at {fill:.1f}% level. "
                                  f"A real plant cuts them at 17% because uncovered "
                                  f"heaters are destroyed. Turn them off from the "
                                  f"in-game panel; the API cannot"))
            elif fill < 25:
                a.append(("WARN", f"pressurizer level {fill:.1f}% is below the 25% "
                                  f"programmed low limit, heaters still on"))

        for lbl, key in (("core", "core_integ"), ("pressurizer", "pzr_integ")):
            x = v.get(key)
            if isinstance(x, float) and x < 100:
                sev = "CRIT" if x < 70 else "WARN"
                extra = " (below the 70% continuous-bleed threshold)" if x < 70 else ""
                a.append((sev, f"{lbl} integrity {x:.1f}%{extra}"))
        return a


def line(v: dict) -> str:
    def g(k, f="{:.0f}"):
        x = v.get(k)
        return f.format(x) if isinstance(x, float) else "?"
    return (f"liq {g('sec_liq')} | bal {g('ret')}-{g('out')} | mscv {g('mscv')} "
            f"| pump {g('sec_pump')} | rpm {g('rpm')} | {g('hz','{:.2f}')}Hz "
            f"| {g('amps')}A | gen {g('gen_kw','{:.1f}')}kW | demand {g('demand')}MW "
            f"| core {g('core_t','{:.1f}')}C {g('core_p','{:.0f}')}bar crit {g('crit','{:+.2f}')} "
            f"| pzr {g('pzr_p','{:.1f}')}/{g('pzr_p_op')} fill {g('pzr_fill')}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--loop", type=int, default=3, choices=[1, 2, 3])
    ap.add_argument("--interval", type=float, default=15)
    ap.add_argument("--count", type=int, default=0, help="0 = run until interrupted")
    ap.add_argument("--log", help="append TSV here")
    a = ap.parse_args()

    if not listener_up():
        print("Webserver not listening on 8785 (it unbinds on save load).",
              file=sys.stderr)
        return 1

    m = Monitor(a.loop)
    log = open(a.log, "a") if a.log else None
    n = 0
    try:
        while a.count == 0 or n < a.count:
            v, errs = m.snap()
            al = m.alerts(v, errs)
            ts = time.strftime("%H:%M:%S")
            print(f"{ts}  {line(v)}")
            for sev, msg in al:
                print(f"          [{sev}] {msg}")
            if not al:
                print("          all guards clear")
            if log:
                log.write(f"{ts}\t" + "\t".join(str(v.get(k)) for k in sorted(v)) + "\n")
                log.flush()
            n += 1
            if a.count == 0 or n < a.count:
                time.sleep(a.interval)
    except KeyboardInterrupt:
        pass
    finally:
        if log:
            log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
