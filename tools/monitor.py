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
  `regime()`. This applies to a guard judging a MISMATCH, the steam/feed
  balance guard's regime gate below. A guard judging a single-variable LEVEL
  carries no such gate, the way Westinghouse Trip 16 (SG low-low level)
  carries no interlocks at all. See the inventory-reference seeding comment
  in `alerts()`.

* **Fail closed applies to the observation channel too, not just a
  variable.** A monitor instance was found running 2 hours after the game
  had exited, having written 5,740 lines that were entirely per-variable
  "unreadable ...: URLError" ERROR alerts, one per variable, roughly 24 per
  cycle. It never once said the webserver was gone, only that every
  individual thing it asked for had failed. An outage is a fact about the
  monitor's ability to see, not about any one variable, and it is reported
  as one. See `Monitor.note_liveness()`, `Monitor.outage_secs()`, and the
  outage guard in `alerts()`.

* **A threshold finer than the sample period is decorative.** `--interval`
  defaults to 15s; a 10s outage threshold checked only once per snapshot
  could never actually fire within its own window, an outage could start
  and end entirely between two samples. `--poll` exists to check liveness
  more often than snapshots are taken, independent of `--interval`.

* **An instrument only sees what it was told to read.** The secondary loop
  had a pump-speed column; the primary loop had none, so a real cause
  (primary flow changing) showed up only as an effect (core temperature and
  pressure moving) with no column to explain it. See
  `docs/protection-system.md` for the measured incident this exposed, and
  the loss-of-circulation guard in `alerts()` it led to.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
import urllib.request
from collections import deque

BASE = "http://localhost:8785"


def api_alive(timeout: float = 1.0) -> bool:
    """Liveness probe, socket-based rather than shelling out to `ss`.

    `ss` is Linux only, and this gets called once per poll interval for
    hours at a time (see --poll below), so a subprocess per check is wasted
    work a plain connect avoids.

    CRITICAL: the host must be the literal string "localhost", never
    "127.0.0.1". docs/wire-format.md documents that this API binds
    `[::1]:8785`, IPv6 loopback only. A v4 literal would never resolve to
    that socket, so a hardcoded "127.0.0.1" here would make this probe
    report a permanent false outage regardless of whether the game is
    actually running. "localhost" lets the resolver pick the address
    family that actually works.
    """
    try:
        with socket.create_connection(("localhost", 8785), timeout=timeout):
            return True
    except OSError:
        return False


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


# read() formats a transport-level failure as f"{name}: {type(e).__name__}"
# (see read() above). These are the exception class names that can appear
# there for a socket/HTTP failure, as opposed to "no such variable" or an
# empty/null body, which are informative reads about one specific name, not
# evidence the API itself is gone. This distinction is what lets alerts()
# tell "the whole plant went dark" apart from "this one variable is broken".
TRANSPORT_FAILURES = ("URLError", "timeout", "TimeoutError",
                      "ConnectionRefusedError", "OSError", "gaierror")


class Monitor:
    def __init__(self, loop: int, down_threshold: float = 10.0):
        self.i = loop - 1
        self.loop = loop
        self.hist: dict[str, deque] = {}
        # Run-local high-water mark for secondary liquid volume, raised by
        # the balance block in alerts() and consumed by the inventory guard
        # right after it. None until a sample with balance not negative
        # seeds it, in any regime. See the comments at both use sites for
        # why this is a run-local reference and not a plant nominal, and
        # for why seeding is not regime gated.
        self.sec_liq_ref: float | None = None

        # Outage tracking. A monitor found running 2 hours after the game
        # had exited had written 5,740 lines, entirely per-variable
        # "unreadable ...: URLError" ERROR alerts, and never once said the
        # webserver was gone. down_since and last_outage_secs exist to turn
        # "every variable is suddenly unreadable" into the single fact it
        # actually is: an outage, with a duration, that either resolves
        # briefly (save load, benign, see docs/wire-format.md) or persists
        # (game exited or crashed, not benign).
        self.down_threshold = down_threshold
        # Monotonic timestamp of the first observed failure, None while
        # healthy. time.monotonic(), not time.time(): this is a duration
        # measurement and wall clock can jump under NTP or suspend/resume,
        # which would corrupt an outage duration silently.
        self.down_since: float | None = None
        # Duration of the most recently completed outage, held only long
        # enough to report once on the recovery snapshot, then reset to 0.
        self.last_outage_secs: float = 0.0

    def note_liveness(self, alive: bool, now: float) -> None:
        """Record a liveness observation. `now` is a caller-supplied
        time.monotonic() value rather than one taken internally, so tests
        can drive falling and rising edges deterministically without
        sleeping.

        Idempotent: calling this repeatedly with the same `alive` value
        while already in that state does nothing further, so it is safe to
        call once per poll tick (see --poll) as well as once per snapshot.
        """
        if not alive:
            if self.down_since is None:
                self.down_since = now  # falling edge
            return
        if self.down_since is not None:
            self.last_outage_secs = now - self.down_since  # rising edge
            self.down_since = None

    def outage_secs(self, now: float) -> float:
        """0.0 when healthy, else how long the current outage has run."""
        if self.down_since is None:
            return 0.0
        return now - self.down_since

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
            # Primary (core) loop circulation. Added after the monitor was
            # found blind to it: primary flow is a first-order driver of
            # both CORE_TEMP and CORE_PRESSURE, and this tool had a column
            # for secondary pump speed but none for the primary loop
            # (docs/protection-system.md documents the incident that
            # exposed the gap). On this plant only pump 2 is running, pumps
            # 0 and 1 legitimately read 0.0, that is a real value, not an
            # unreadable or error condition.
            "core_pump_0": "COOLANT_CORE_CIRCULATION_PUMP_0_SPEED",
            "core_pump_1": "COOLANT_CORE_CIRCULATION_PUMP_1_SPEED",
            "core_pump_2": "COOLANT_CORE_CIRCULATION_PUMP_2_SPEED",
            "core_flow": "COOLANT_CORE_FLOW_SPEED",
            "core_qty": "COOLANT_CORE_QUANTITY_IN_VESSEL",
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

    def alerts(self, v: dict, errs: list[str],
               now: float | None = None) -> list[tuple[str, str]]:
        """`now` defaults to time.monotonic() so existing callers, and the
        pre-outage-guard tests, keep working unchanged. main() passes an
        explicit value taken once per loop iteration instead, so every
        guard evaluated in one pass agrees on what "now" was.

        ASSERTION (not a runtime assert, just the invariant this file
        depends on): during an outage, a is never empty. See the outage
        guard below. That is what stops main() from printing "all guards
        clear" while the plant is actually unobserved, which is the exact
        failure this file exists to close: a monitor that goes quiet is
        indistinguishable from a monitor that checked and found nothing
        wrong, and only one of those is true during an outage.
        """
        if now is None:
            now = time.monotonic()
        a: list[tuple[str, str]] = []

        # A wholesale outage and a single bad variable are different facts
        # and must not be conflated. A monitor left running after the game
        # exited was observed to write 5,740 lines over 2 hours, all of
        # them "[ERROR] unreadable <NAME>: URLError", one line per variable,
        # roughly 24 per cycle, and never once said the webserver was gone.
        # If every entry in errs is a transport failure (see
        # TRANSPORT_FAILURES) and there are more than a handful of them,
        # that is one fact: the API is unreachable. Collapse it to one
        # alert. A single unreadable variable, or a mix of transport and
        # non-transport failures, is a different, genuine per-variable
        # signal (for example a name that does not exist on this build) and
        # must not be hidden inside a collapsed summary.
        transport = [e for e in errs if e.endswith(TRANSPORT_FAILURES)]
        if errs and len(transport) == len(errs) and len(errs) > 3:
            reason = ", ".join(sorted({e.rsplit(": ", 1)[-1] for e in errs}))
            a.append(("ERROR", f"API unreachable: all {len(errs)} variables "
                               f"unread ({reason})"))
        else:
            for e in errs:
                a.append(("ERROR", f"unreadable {e}"))

        # Outage guard. During an outage every value in v is None, so every
        # guard below this point is naturally inert, each already checks
        # isinstance(x, float) before firing. That silence is exactly the
        # danger: fail closed applied to a single variable means "raise an
        # ERROR for that variable", but fail closed applied to the whole
        # observation channel means the operator needs to be told the
        # channel itself is gone, not just that nothing below fired. This
        # alert is that message, and it is the reason a can never be empty
        # while self.down_since is set.
        #
        # secs == 0 and briefly < threshold cover the benign case: the
        # webserver unbinds on save load (docs/wire-format.md), so a short
        # outage is expected and is downgraded to WARN rather than treated
        # as a plant failure. secs >= threshold means the outage has run
        # longer than a save load plausibly takes, so it escalates to CRIT:
        # either the game exited or crashed, not the same condition.
        secs = self.outage_secs(now)
        if secs == 0:
            if self.last_outage_secs > 0:
                a.append(("WARN", f"API was unreachable for "
                                  f"{self.last_outage_secs:.0f}s, readings resumed"))
                self.last_outage_secs = 0.0  # report the recovery once, not every snapshot
        elif secs < self.down_threshold:
            a.append(("WARN", f"API unreachable for {secs:.0f}s. Expected "
                              f"briefly during a save load, the webserver unbinds"))
        else:
            a.append(("CRIT", f"API unreachable for {secs:.0f}s, beyond the "
                              f"{self.down_threshold:.0f}s threshold. The plant is "
                              f"UNOBSERVED, no guard below is running"))

        # Regime gates severity below. Per regime()'s docstring, "unknown"
        # must never suppress, so gated guards treat "unknown" exactly like
        # "at_power" and only "startup" may downgrade.
        rg = self.regime(v)

        out, ret = v.get("out"), v.get("ret")
        liq, tr = v.get("sec_liq"), self.trend("sec_liq")
        if isinstance(out, float) and isinstance(ret, float):
            bal = ret - out
            # Reference for the inventory guard below: seed/raise the
            # run-local secondary-liquid high-water mark whenever balance is
            # not negative, in ANY regime. This is not regime gated, and
            # that is a deliberate fix, not the original design. See the
            # long comment below for the reasoning; short version: a
            # permissive may gate a mismatch, never a level.
            #
            # bal >= 0 stays: seeding on an already negative balance would
            # lock in a reading taken mid-drain as "normal" if the monitor
            # is started while the loop is already losing inventory. That
            # hazard has nothing to do with regime, and it is the one
            # condition that still guards this block.
            #
            # at_power was removed, and was wrong to begin with: Westinghouse
            # Trip 16, SG low-low level, carries NO INTERLOCKS
            # (docs/protection-system.md), by design, not by omission. A
            # flow MISMATCH is regime dependent, genuinely expected during
            # startup while the bypass and the ejectors draw steam, which is
            # exactly why Trip 17 exists with the P-7 permissive just below
            # this block. A low LEVEL is dangerous in every regime, which is
            # why the level trip carries no permissive at all. Gating this
            # seed by at_power applied a permissive to a level guard, a
            # category error, and it made the guard inert during precisely
            # the phase this repository already documents a secondary
            # observed draining (turbine startup and synchronisation).
            # Measured on a live plant, minutes apart:
            # 21:18 liquid 44586, balance +39 (out 11, ret 50), clean and
            # healthy, an ideal reference; 21:26 liquid 27141, balance -21.4
            # (out 71, ret 50), falling roughly 33 units/s, a 39% drop from
            # the first reading. Regime was "startup" at both timestamps, so
            # the old code never seeded a reference and the inventory guard
            # below had nothing to compare against; the monitor logged only
            # "[INFO] steam draw exceeds return" for the 21:26 reading, no
            # CRIT. With the gate removed, the reference seeds at 44586, and
            # frac at 21:26 is (44586-27141)/44586 = 0.391, which crosses
            # the 0.30 CRIT threshold given the falling trend, the correct
            # answer the old code could not reach.
            #
            # Residual weakness, unchanged by this fix and still worth
            # stating: this is a run-local high-water mark, not a plant
            # nominal, and if no sample with balance not negative is ever
            # observed, the guard still never fires. See the inventory
            # guard's own comment below.
            if bal >= 0 and isinstance(liq, float):
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
            #
            # Contrast with the reference seed just above: a MISMATCH
            # (this guard) is regime dependent and correctly gated here.
            # A LEVEL (the inventory guard below) is not, and is no longer
            # gated above. The two guards are treated differently on
            # purpose, matching Trip 17's P-7 permissive against Trip 16's
            # complete absence of one, not inconsistently.
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
        # this actually measures is percent below the highest level this run
        # has observed with balance not negative (see the seeding comment
        # above; seeding is not regime gated, a permissive may gate a
        # mismatch, never a level), a run-local reference, not a plant
        # nominal. Known weakness, and it is deliberate: if the monitor
        # never observes a sample with balance not negative, no reference
        # is ever established and this guard never fires. A silent wrong
        # number is worse than no number.
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

        # Loss of forced primary circulation with the reactor critical: the
        # analog of the Westinghouse RCS low flow reactor trips (Table
        # 12.2-1, docs/protection-system.md), the same table Trip 17 and
        # Trip 18 above come from. Loss of forced circulation while the
        # core is critical is one of the most serious PWR transients there
        # is, heat keeps being produced with nothing carrying it away.
        #
        # COOLANT_CORE_CIRCULATION_PUMP_{0,1,2}_SPEED and
        # COOLANT_CORE_FLOW_SPEED are two independent readings of the same
        # underlying fact, an aggregate and its parts. Flow is treated as
        # absent when either reading says so on its own: COOLANT_CORE_FLOW_
        # SPEED reads a float 0.0, or all three pump speeds read float 0.0.
        # This is deliberately an OR, not an AND, either reading failing is
        # enough to mean nothing is moving.
        core_flow = v.get("core_flow")
        core_pumps = [v.get("core_pump_0"), v.get("core_pump_1"), v.get("core_pump_2")]
        pumps_readable = all(isinstance(p, float) for p in core_pumps)
        pumps_all_zero = pumps_readable and all(p == 0.0 for p in core_pumps)
        flow_readable = isinstance(core_flow, float)
        flow_zero = flow_readable and core_flow == 0.0
        flow_nonzero = flow_readable and core_flow != 0.0

        # Contradiction: the aggregate says flow IS moving while the parts
        # say every pump is off. Those cannot both be true, and a
        # disagreement is not a reason to relax, it is a reason to believe
        # the worse reading and say the instruments conflict. All three
        # pumps reading zero is the dangerous reading, so it drives the
        # CRIT below regardless of what the aggregate claims, and the WARN
        # below fires alongside the CRIT to record the disagreement itself,
        # never instead of it. An earlier version of this guard let the WARN
        # suppress the CRIT here, trusting the optimistic aggregate over the
        # dangerous parts. That is fail-open, and it is backwards for this
        # repository: when two readings disagree about whether a
        # safety-relevant condition exists, the dangerous interpretation
        # must win, not the comfortable one.
        if flow_nonzero and pumps_all_zero:
            a.append(("WARN", f"primary flow readings disagree: aggregate flow "
                              f"{core_flow:.1f} but all three core circulation "
                              f"pump readings are 0.0. Not resolved automatically, "
                              f"check both instruments. The dangerous reading is "
                              f"believed below, this WARN does not suppress the CRIT"))

        flow_absent = flow_zero or pumps_all_zero
        # CRITICAL DESIGN POINT: this guard is NOT regime gated,
        # deliberately, for the same reason the secondary inventory
        # guard above is not, see that guard's seeding comment. A
        # permissive gates a MISMATCH, never a LEVEL or a STATE. This is
        # the second instance of that rule in this file. Westinghouse
        # Trip 16 (SG low-low level, a LEVEL) carries no interlocks at
        # all. This guard is keyed to CORE_STATE reading REACTIVO, a
        # STATE, not a mismatch between two variables, and loss of
        # circulation with a critical core is dangerous in every
        # regime, including startup. So it carries no permissive here
        # either.
        #
        # Honest deviation from the reference architecture, stated
        # plainly rather than left as an oversight: the REAL RCS low
        # flow trips ARE gated by P-7 on a Westinghouse plant, because
        # below 10% power there is not enough heat to matter. regime()
        # exists and gates the steam/feed balance guard above the same
        # way, the P-7 analog for a MISMATCH. It is not used here
        # because no computable power fraction exists anywhere in this
        # API (docs/protection-system.md, "The calibration gap"), and a
        # proxy for load is not the same thing as a measurement of
        # power fraction. Given no way to compute the real condition,
        # the conservative choice is to leave the guard armed rather
        # than gate a critical-core guard on a substitute that could be
        # wrong in exactly the direction that suppresses a real
        # emergency.
        #
        # This CRIT is deliberately evaluated unconditionally, not in an
        # else branch off the disagreement check above: flow_absent is
        # True whenever pumps_all_zero is True, regardless of what
        # core_flow says, so the contradiction case above and the CRIT
        # below both fire together on the same snapshot. See the
        # contradiction comment above for why suppressing either one
        # would be the fail-open pattern this repository bans.
        if v.get("core_state") == "REACTIVO" and flow_absent:
            a.append(("CRIT", "reactor critical with no forced primary "
                              "circulation: heat is being produced with "
                              "nothing carrying it away. Lever: restore a "
                              "primary circulation pump immediately"))

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
            f"| cflow {g('core_flow')} | core {g('core_t','{:.1f}')}C {g('core_p','{:.0f}')}bar crit {g('crit','{:+.2f}')} "
            f"| pzr {g('pzr_p','{:.1f}')}/{g('pzr_p_op')} fill {g('pzr_fill')}")


def poll_sleep(m: Monitor, interval: float, poll: float) -> None:
    """Sleep `interval` seconds, but check liveness every `poll` seconds
    instead of only at the next snapshot.

    This is what makes --down-threshold actually observable. --interval
    defaults to 15s; a 10s outage threshold checked only once per snapshot
    could begin and fully end inside a single sleep, invisible to anyone
    watching. A threshold finer than the sample period is decorative unless
    something polls faster than it samples, this is that something.

    Paced against a monotonic deadline rather than by subtracting the sleep
    steps, because api_alive() is not free: its timeout is 1s, and a probe
    that HANGS (a dropped SYN rather than a refused connection) burns most
    of that. Counting only the sleeps would let a 15s interval take 30s of
    wall clock during exactly the outage this function exists to watch, and
    the sample rate would silently halve when it matters most. Charging the
    probe's own cost against the deadline keeps the snapshot cadence honest.

    Does not swallow KeyboardInterrupt, it propagates straight out of
    time.sleep() to main()'s existing try/except.

    Prints a transition line the instant the API goes down or comes back,
    rather than waiting for the next snapshot to notice up to `interval`
    seconds later, because a human watching the terminal wants to know at
    the moment it happens.
    """
    deadline = time.monotonic() + interval
    while True:
        now = time.monotonic()
        remaining = deadline - now
        if remaining <= 0:
            return
        time.sleep(poll if poll < remaining else remaining)
        was_down = m.down_since is not None
        m.note_liveness(api_alive(), time.monotonic())
        now_down = m.down_since is not None
        if now_down != was_down:
            ts = time.strftime("%H:%M:%S")
            if now_down:
                print(f"{ts}  [WARN] API went unreachable")
            else:
                print(f"{ts}  [WARN] API reachable again after "
                      f"{m.last_outage_secs:.0f}s")


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
    # Both defaults below are uncalibrated heuristics, not measurements.
    # Nothing in this repository records how long the webserver actually
    # stays unbound across a save load, which is the one number that would
    # calibrate --down-threshold: it wants to sit above a normal save load
    # and below a crash. 10s is a guess pending that measurement. --poll at
    # 1s is chosen only to be comfortably finer than that threshold, so the
    # threshold is resolvable, see poll_sleep() and the granularity warning
    # below. Measure a save load and set both from it.
    ap.add_argument("--down-threshold", type=float, default=10.0,
                     help="seconds of continuous API unreachability before "
                          "the outage alert escalates from WARN to CRIT")
    ap.add_argument("--poll", type=float, default=1.0,
                     help="how often liveness is checked while sleeping "
                          "between snapshots, independent of --interval")
    a = ap.parse_args()

    # The period-vs-threshold granularity trap: a threshold cannot be
    # resolved any finer than the period it is checked against. Warn, don't
    # exit, the run is still usable, just coarser than what was asked for.
    if a.down_threshold < a.poll:
        print(f"warning: --down-threshold ({a.down_threshold:.1f}s) is "
              f"finer than --poll ({a.poll:.1f}s), it cannot be resolved "
              f"more finely than the poll period", file=sys.stderr)

    if not api_alive():
        print("Webserver not listening on 8785 (it unbinds on save load).",
              file=sys.stderr)
        return 1

    m = Monitor(a.loop, down_threshold=a.down_threshold)
    log = open(a.log, "a") if a.log else None
    n = 0
    try:
        while a.count == 0 or n < a.count:
            v, errs = m.snap()
            now = time.monotonic()
            # "Snapshot succeeded" means at least one variable read OK, not
            # "errs is empty". read()/snap() only ever leave vals[k] as None
            # on the failure path, so any non-None value is proof the API
            # answered at least one request this tick, even if the rest of
            # the batch failed. That is enough to call this tick alive; a
            # single bad variable name is a different problem from the API
            # being gone, see TRANSPORT_FAILURES and alerts().
            snapshot_ok = any(x is not None for x in v.values())
            m.note_liveness(snapshot_ok, now)
            al = m.alerts(v, errs, now)
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
                poll_sleep(m, a.interval, a.poll)
    except KeyboardInterrupt:
        pass
    finally:
        if log:
            log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
