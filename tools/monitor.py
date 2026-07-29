#!/usr/bin/env python3
"""
Steady-state monitor for a running Nucleares plant.

Watches the conditions that actually require operator action and stays quiet
otherwise. Read-only: this tool contains no write method at all, and that
absence is the safety guarantee rather than a flag you could toggle.

    python3 tools/monitor.py --loop 3
        watches secondary loop 3, once every 15s, until Ctrl-C. --count
        defaults to 0, which means "run forever", not "run 3 times". --loop
        selects WHICH secondary loop (1, 2 or 3), it is not a repeat count.

    python3 tools/monitor.py --loop 1 --interval 10 --count 20 --log run.tsv
        watches loop 1, once every 10s, for 20 snapshots, also logs to
        run.tsv

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

* **Gate by regime, don't suppress on doubt.** A guard correct at power can be
  wrong during startup, the way a real permissive like P-7 gates trips by
  plant condition. But when the regime itself can't be read, that is a reason
  to treat the plant as if it were at power, not a reason to go quiet. See
  `regime()`.
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
        # Run-local high-water mark for secondary liquid volume, raised by
        # the balance block in alerts() and consumed by the inventory guard
        # right after it. None until a healthy at-power sample seeds it. See
        # the comments at both use sites for why this is a run-local
        # reference and not a plant nominal.
        self.sec_liq_ref: float | None = None

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
            "turb_p": f"STEAM_TURBINE_{i}_PRESSURE",
            "turb_installed": f"STEAM_TURBINE_{i}_INSTALLED",
            "turb_torque": f"STEAM_TURBINE_{i}_TORQUE",
            "hz": f"GENERATOR_{i}_HERTZ",
            "amps": f"GENERATOR_{i}_A",
            "gen_kw": f"GENERATOR_{i}_KW",
            "sec_pump": f"COOLANT_SEC_CIRCULATION_PUMP_{i}_SPEED",
            "core_state": "CORE_STATE",
            "op_mode": "CORE_OPERATION_MODE",
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

    def regime(self, v: dict) -> str:
        """Classify plant regime for gating guard severity, the way a real
        RPS permissive (P-7, below 10% power) gates trips by plant condition.

        Returns "at_power", "startup" or "unknown".

        CRITICAL DESIGN POINT: the risky failure mode for a regime gate is
        SUPPRESSION, not over-alerting. "unknown" must therefore never
        suppress a guard, it behaves exactly like "at_power" for gating
        purposes. Only a positively established "startup" may downgrade
        anything. A regime gate that fails open, suppressing when it cannot
        tell, would silently disarm protection exactly when telemetry is
        degraded, which is the one moment protection matters most.
        """
        amps, op_mode = v.get("amps"), v.get("op_mode")
        if not isinstance(amps, float) or not isinstance(op_mode, str):
            return "unknown"
        if amps > 0 and op_mode == "NOMINAL":
            return "at_power"
        # Both readable, and not at_power: we positively know the plant is
        # not carrying load at NOMINAL, which is what "startup" means here.
        return "startup"

    def alerts(self, v: dict, errs: list[str]) -> list[tuple[str, str]]:
        a: list[tuple[str, str]] = []
        for e in errs:
            a.append(("ERROR", f"unreadable {e}"))

        # Regime gates severity below. Per regime()'s docstring, "unknown"
        # must never suppress, so gated guards treat "unknown" exactly like
        # "at_power" and only "startup" may downgrade.
        rg = self.regime(v)

        out, ret = v.get("out"), v.get("ret")
        liq, tr = v.get("sec_liq"), self.trend("sec_liq")
        if isinstance(out, float) and isinstance(ret, float):
            bal = ret - out
            # Reference for the inventory guard below: seed/raise the
            # run-local secondary-liquid high-water mark only when the loop
            # looks healthy, at_power and balance not negative. Seeding on a
            # depressed reading would lock in an already-bad level as
            # "normal" if the monitor is started mid-drain.
            if rg == "at_power" and bal >= 0 and isinstance(liq, float):
                if self.sec_liq_ref is None or liq > self.sec_liq_ref:
                    self.sec_liq_ref = liq
            # This is the P-7 analog (docs/protection-system.md, Trip 17,
            # Low Feedwater Flow). A real plant blocks this class of trip
            # below 10% power because a trip that is correct at power is
            # wrong during startup, when MSCV is deliberately held low. No
            # rated-power constant exists in this API, so a literal "10%
            # power" gate is not computable. What P-7 is really asking is
            # "is the generator actually carrying load and does the plant
            # report NOMINAL", which is exactly what regime() answers.
            # Detection is unchanged from before, only severity is gated.
            if bal < 0 and isinstance(tr, float) and tr < 0:
                if rg == "startup":
                    a.append(("INFO", f"secondary losing inventory: balance {bal:+.1f} "
                                      f"(out {out:.0f} vs return {ret:.0f}), "
                                      f"liquid {liq:.0f} and falling ({tr:+.0f} over window). "
                                      f"expected during startup, the checklist calls for MSCV >= 25"))
                else:
                    a.append(("CRIT", f"secondary losing inventory: balance {bal:+.1f} "
                                      f"(out {out:.0f} vs return {ret:.0f}), "
                                      f"liquid {liq:.0f} and falling ({tr:+.0f} over window). "
                                      f"Lever: close MSCV or add makeup"))
            elif bal < 0:
                if rg == "startup":
                    a.append(("INFO", f"steam draw exceeds return: {bal:+.1f}. "
                                      f"expected during startup, the checklist calls for MSCV >= 25"))
                else:
                    a.append(("WARN", f"steam draw exceeds return: {bal:+.1f}"))

        # Secondary inventory guard, against a run-local reference. This is
        # NOT Westinghouse Trip 16 (SG low-low level, 11.5% of nominal), and
        # it cannot be, because no capacity/nominal variable exists for
        # COOLANT_SEC_{n}_LIQUID_VOLUME, so a percent of plant nominal is not
        # computable (docs/protection-system.md documents that gap). What
        # this actually measures is percent below the highest healthy level
        # this run has observed, a run-local reference, not a plant nominal.
        # Known weakness, and it is deliberate: if the monitor never
        # observes a healthy at-power period, no reference is ever
        # established and this guard never fires. A silent wrong number is
        # worse than no number.
        #
        # The 0.30 and 0.15 fractions below are themselves uncalibrated
        # heuristics, the same status as the turbine guard's 10.0 above, not
        # traceable to any measurement in this repository. They are also NOT
        # derived from the real 11.5% and 25.5% Westinghouse setpoints,
        # because those are percentages of plant nominal SG level, a
        # different quantity this API does not expose, and scaling them onto
        # a run-local high-water mark would just be a different guess wearing
        # a real number's clothes. Treat both fractions as placeholders and
        # recalibrate against a measured drain before trusting either one.
        if self.sec_liq_ref and isinstance(liq, float):
            frac = (self.sec_liq_ref - liq) / self.sec_liq_ref
            if frac >= 0.30 and isinstance(tr, float) and tr < 0:
                a.append(("CRIT", f"secondary inventory {frac:.0%} below this run's "
                                  f"reference of {self.sec_liq_ref:.0f} (run-local, not a "
                                  f"plant nominal), current {liq:.0f} and falling"))
            elif frac >= 0.15:
                a.append(("WARN", f"secondary inventory {frac:.0%} below this run's "
                                  f"reference of {self.sec_liq_ref:.0f} (run-local, not a "
                                  f"plant nominal), current {liq:.0f}"))

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

        # Turbine trip with the reactor still critical: the analog of
        # Westinghouse Trip 18 (reactor trip on turbine trip). Nucleares
        # does not implement it. Measured, docs/emergency-controls.md:190-198
        # (the RESOLVED 2026-07-28 section): after STEAM_TURBINE_TRIP,
        # CORE_STATE stayed REACTIVO while CORE_TEMP rose 310.9 to 324.7
        # over two minutes, because the heat sink was gone and the heat
        # source kept running.
        #
        # STEAM_TURBINE_{n}_PRESSURE is the unambiguous signal there: it
        # drops to 1 and stays there, observed 58.57 -> 1, and unlike RPM or
        # kW it moves immediately. Corroborating, same doc: TORQUE
        # 7.61 -> 3.77 -> 0, GENERATOR_KW 29660 -> 14622 -> 0, RPM/Hz coast
        # down linearly at -1.00 Hz/s.
        #
        # was_live requires the pressure to have been meaningfully up at
        # some point in this run's own history. Without it, a turbine that
        # NEVER STARTED reads pressure 1 forever and looks identical to one
        # that TRIPPED, and those are opposite situations: one needs no
        # action, the other needs the reactor addressed. 10.0 is not a
        # measured threshold, it is an uncalibrated heuristic, a wide margin
        # picked between the two single observed values in this repository,
        # 58.57 live and 1 tripped.
        #
        # The hist deque has maxlen=30, so this guard has a finite memory
        # window and stops firing once the pre-trip pressure ages out of
        # it. That is intentional, this is a transition detector, not a
        # latching trip.
        #
        # turb_installed guards against firing on a unit that is simply
        # absent, per docs/plant-mechanics.md: uninstalled equipment reports
        # confident values rather than errors, so this cannot rely on errs.
        hist_p = self.hist.get("turb_p")
        turb_p = v.get("turb_p")
        if hist_p and v.get("turb_installed") != "False":
            was_live = max(hist_p) >= 10.0
            collapsed = isinstance(turb_p, float) and turb_p <= 1.0
            if was_live and collapsed:
                core_t_tr = self.trend("core_t")
                corrob = (f", core temp trend {core_t_tr:+.1f} over window"
                          if isinstance(core_t_tr, float) else "")
                sev = "CRIT" if v.get("core_state") == "REACTIVO" else "WARN"
                a.append((sev, f"turbine tripped: pressure {turb_p:.1f}, was up to "
                               f"{max(hist_p):.1f} in this window{corrob}. A real plant "
                               f"trips the reactor on turbine trip above P-7, this game "
                               f"does not. Lever: the API cannot trip the reactor from "
                               f"turbine state, so restore the heat sink or scram"))

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
    ap.add_argument("--loop", type=int, default=3, choices=[1, 2, 3],
                     help="which secondary loop to watch: 1, 2 or 3. This "
                          "selects the loop, it is not a repeat count")
    ap.add_argument("--interval", type=float, default=15,
                     help="seconds to sleep between snapshots")
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
