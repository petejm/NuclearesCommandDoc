#!/usr/bin/env python3
"""
Unit tests for tools/monitor.py.

A real protection system is qualified with injected test signals, not by
waiting for a genuine transient to occur on the plant. The Nucleares API
cannot be relied on for that, the webserver unbinds on save load and the
transients that matter are exactly the ones you cannot schedule, so these
guards are exercised here against synthetic, hand-built snapshots instead.
No network calls. No game.

Run as, from the repo root:
    python3 tools/test_monitor.py
    python3 -m unittest discover -s tools

Bare `python3 -m unittest` from the repo root discovers 0 tests. tools/ has
no __init__.py, deliberately, see tools/README.md, and unittest's default
recursive discovery skips directories that are not packages. Use one of the
two invocations above instead.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from collections import deque
from unittest import mock

# Make "import monitor" work whether this file is run directly (repo root
# is not automatically on sys.path in that case) or picked up by unittest
# discovery. This adds the directory this file lives in, tools/, to the
# front of sys.path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import monitor  # noqa: E402


def healthy_snapshot(**overrides) -> dict:
    """A plausible healthy, at-power snapshot. Tests override individual
    keys so each test reads as a delta from healthy, rather than restating
    an entire plant state.
    """
    v = {
        "sec_liq": 12000.0,
        "sec_temp": 285.0,
        "boil": 270.0,
        "out": 500.0,
        "ret": 510.0,
        "mscv": 30.0,
        "rpm": 3060.0,
        "turb_p": 58.57,
        "turb_installed": "True",
        "turb_torque": 7.61,
        "hz": 50.0,
        "amps": 500.0,
        "gen_kw": 29660.0,
        "sec_pump": 25.0,
        # Confirmed readable live: only pump 2 running, pumps 0 and 1 read
        # 0.0 legitimately (not an error), aggregate flow matches pump 2.
        "core_pump_0": 0.0,
        "core_pump_1": 0.0,
        "core_pump_2": 25.0,
        "core_flow": 25.0,
        "core_qty": 116512.5,
        "core_state": "REACTIVO",
        "op_mode": "NOMINAL",
        "core_t": 300.0,
        "core_t_max": 400.0,
        "core_p": 150.0,
        "core_p_max": 200.0,
        "crit": 0.05,
        "core_integ": 100.0,
        "pzr_p": 150.0,
        "pzr_p_op": 150.0,
        "pzr_fill": 50.0,
        "pzr_integ": 100.0,
        "pzr_heaters": "True",
        "demand": 500.0,
    }
    v.update(overrides)
    return v


def find(alerts: list[tuple[str, str]], severity: str, contains: str) -> list[str]:
    """Alerts whose severity matches and whose message contains a substring."""
    return [msg for sev, msg in alerts if sev == severity and contains in msg]


def has_severity(alerts: list[tuple[str, str]], severity: str) -> bool:
    return any(sev == severity for sev, _ in alerts)


def fake_read_factory(overrides: dict, default=(True, "123.0")):
    """Builds a stand-in for monitor.read() that answers every variable
    name with `default` unless the name is a key in `overrides`, where it
    answers with the exact (ok, value) pair given. snap() calls
    monitor.read() by name for each entry in its own `names` dict plus
    RESISTOR_BANKS_JSON, so patching the module-level function is the
    seam that lets Monitor.snap() itself be exercised without any
    network access, still no curl, no game, just a swapped-out function.
    """
    def fake_read(name):
        return overrides.get(name, default)
    return fake_read


class TestRegime(unittest.TestCase):
    """Case 5: regime() classification for the three inputs it defines."""

    def test_at_power(self):
        m = monitor.Monitor(1)
        self.assertEqual(m.regime({"amps": 500.0, "op_mode": "NOMINAL"}), "at_power")

    def test_startup(self):
        m = monitor.Monitor(1)
        self.assertEqual(m.regime({"amps": 0.0, "op_mode": "SHUTDOWN"}), "startup")

    def test_unknown(self):
        m = monitor.Monitor(1)
        self.assertEqual(m.regime({"amps": None, "op_mode": None}), "unknown")


class TestSteamFeedBalanceGate(unittest.TestCase):
    """Cases 1-4: the P-7 analog gating the existing steam/feed guard."""

    def test_healthy_at_power_no_crit(self):
        """Case 1: a clean at-power snapshot produces no alerts at all."""
        m = monitor.Monitor(1)
        v = healthy_snapshot()
        alerts = m.alerts(v, [])
        self.assertEqual(alerts, [])

    def test_imbalance_at_power_is_crit(self):
        """Case 2: steam/feed imbalance while at_power stays CRIT, as before."""
        m = monitor.Monitor(1)
        # A falling trend is required for the CRIT branch (bal < 0 and
        # trend < 0). Populate hist directly rather than calling snap().
        m.hist["sec_liq"] = deque([12000.0, 11500.0, 11000.0], maxlen=30)
        v = healthy_snapshot(out=550.0, ret=500.0, sec_liq=11000.0)
        alerts = m.alerts(v, [])
        self.assertTrue(find(alerts, "CRIT", "secondary losing inventory"))

    def test_same_imbalance_during_startup_is_info(self):
        """Case 3: the identical imbalance during startup is downgraded to
        INFO, not suppressed and not CRIT. The checklist explicitly calls
        for MSCV >= 25 with the loop unbalanced during startup, so a CRIT
        here would be the "fires on every startup and gets ignored" failure
        this repository already made once (docs/protection-system.md).
        """
        m = monitor.Monitor(1)
        m.hist["sec_liq"] = deque([12000.0, 11500.0, 11000.0], maxlen=30)
        v = healthy_snapshot(out=550.0, ret=500.0, sec_liq=11000.0,
                              amps=0.0, op_mode="SHUTDOWN")
        alerts = m.alerts(v, [])
        self.assertTrue(find(alerts, "INFO", "expected during startup"))
        self.assertFalse(has_severity(alerts, "CRIT"))

    def test_same_imbalance_with_unreadable_op_mode_stays_crit(self):
        """Case 4: fail-closed regression test. If op_mode cannot be read,
        regime() must return "unknown", and "unknown" must gate exactly like
        "at_power", never like "startup". A regime gate that fails open here
        would suppress a real CRIT the moment telemetry degrades, which is
        the worst possible time to go quiet.
        """
        m = monitor.Monitor(1)
        m.hist["sec_liq"] = deque([12000.0, 11500.0, 11000.0], maxlen=30)
        v = healthy_snapshot(out=550.0, ret=500.0, sec_liq=11000.0, op_mode=None)
        alerts = m.alerts(v, [])
        self.assertTrue(find(alerts, "CRIT", "secondary losing inventory"))


class TestTurbineTripGuard(unittest.TestCase):
    """Cases 6-9: Trip 18 analog, turbine trip with the reactor still critical."""

    def test_trip_with_core_reactivo_is_crit(self):
        """Case 6: pre-trip pressure above the was_live threshold, current
        pressure collapsed, core still REACTIVO -> CRIT mentioning the
        turbine.
        """
        m = monitor.Monitor(1)
        m.hist["turb_p"] = deque([58.57, 55.0, 40.0], maxlen=30)
        v = healthy_snapshot(turb_p=1.0, turb_installed="True", core_state="REACTIVO")
        alerts = m.alerts(v, [])
        self.assertTrue(find(alerts, "CRIT", "turbine tripped"))

    def test_turbine_never_started_does_not_fire(self):
        """Case 7: pressure was never meaningfully up in this run's history,
        so this is a turbine that never started, not one that tripped. The
        guard must not fire, that is exactly the distinction was_live exists
        to draw.
        """
        m = monitor.Monitor(1)
        m.hist["turb_p"] = deque([0.0, 1.0, 1.0], maxlen=30)
        v = healthy_snapshot(turb_p=1.0, turb_installed="True")
        alerts = m.alerts(v, [])
        self.assertFalse(find(alerts, "CRIT", "turbine tripped"))
        self.assertFalse(find(alerts, "WARN", "turbine tripped"))

    def test_absent_turbine_does_not_fire(self):
        """Case 8: turb_installed == "False" must block the guard even when
        the pressure history looks exactly like a real trip, an absent unit
        must never fire it.
        """
        m = monitor.Monitor(1)
        m.hist["turb_p"] = deque([58.57, 55.0, 40.0], maxlen=30)
        v = healthy_snapshot(turb_p=1.0, turb_installed="False")
        alerts = m.alerts(v, [])
        self.assertFalse(find(alerts, "CRIT", "turbine tripped"))
        self.assertFalse(find(alerts, "WARN", "turbine tripped"))

    def test_trip_with_core_not_reactivo_is_warn(self):
        """Case 9: same trip signature, but the core is not REACTIVO, so
        there is no live heat source to worry about. WARN, not CRIT.
        """
        m = monitor.Monitor(1)
        m.hist["turb_p"] = deque([58.57, 55.0, 40.0], maxlen=30)
        v = healthy_snapshot(turb_p=1.0, turb_installed="True", core_state="NOREACTIVO")
        alerts = m.alerts(v, [])
        self.assertTrue(find(alerts, "WARN", "turbine tripped"))
        self.assertFalse(find(alerts, "CRIT", "turbine tripped"))


class TestSecondaryInventoryReference(unittest.TestCase):
    """Cases 10-11: the run-local secondary-inventory reference guard."""

    def test_reference_established_then_drop_is_crit(self):
        """Case 10: a healthy at-power sample seeds the reference, then the
        level drops 35% with a falling trend -> CRIT.
        """
        m = monitor.Monitor(1)
        # Seed the reference: at_power, balance not negative.
        v1 = healthy_snapshot(sec_liq=12000.0, out=500.0, ret=510.0,
                               amps=500.0, op_mode="NOMINAL")
        m.alerts(v1, [])
        self.assertEqual(m.sec_liq_ref, 12000.0)

        # Now the drop. out/ret left unreadable so the balance block (and
        # any re-seeding) does not run this tick, isolating the inventory
        # guard.
        m.hist["sec_liq"] = deque([12000.0, 10000.0, 7800.0], maxlen=30)
        v2 = healthy_snapshot(sec_liq=7800.0, out=None, ret=None)
        alerts = m.alerts(v2, [])
        crit = find(alerts, "CRIT", "secondary inventory")
        self.assertTrue(crit)
        self.assertIn("35%", crit[0])
        self.assertIn("run-local", crit[0])

    def test_never_seeded_mid_drain_does_not_fire(self):
        """Case 11: documented weakness, asserted deliberately. If the
        monitor is started mid-drain and never observes a healthy at-power
        sample, no reference is ever established, so this guard cannot fire
        even though the plant is genuinely low. A silent wrong number is
        worse than no number, so this is the intended behavior, not a bug.
        """
        m = monitor.Monitor(1)
        v = healthy_snapshot(sec_liq=3000.0, out=None, ret=None)
        alerts = m.alerts(v, [])
        self.assertIsNone(m.sec_liq_ref)
        self.assertFalse(find(alerts, "CRIT", "secondary inventory"))
        self.assertFalse(find(alerts, "WARN", "secondary inventory"))


class TestInventorySeedRegimeIndependent(unittest.TestCase):
    """Cases 22-26. Fixed 2026-07-28: the inventory reference seed in
    alerts() was gated by `rg == "at_power" and bal >= 0`. `at_power` has
    been removed, `bal >= 0` stays. See the seeding comment in monitor.py
    for the full reasoning: Westinghouse Trip 16 (SG low-low level) carries
    NO INTERLOCKS, a flow mismatch is regime dependent (Trip 17, P-7) but a
    level is dangerous in every regime, so gating the seed by regime was a
    category error that made the guard inert during startup, exactly the
    phase a secondary was measured draining in.
    """

    def test_live_regression_startup_seed_then_crit(self):
        """Case 22: the live regression, reproducing the 21:18 to 21:26
        sequence measured on a live plant, startup regime throughout (amps
        0.0, op_mode "NOMINAL": regime() requires amps > 0 for "at_power",
        so this reads as "startup").

        21:18: sec_liq 44586, out 11, ret 50 (balance +39, clean and
        healthy). The pre-fix code refused to seed here because regime()
        was "startup", not "at_power". Post-fix this must seed the
        reference to 44586.

        21:26: sec_liq 27141, out 71, ret 50 (balance -21.4), a 39% drop
        with a falling trend. Pre-fix, with no reference ever seeded, the
        monitor could only produce "[INFO] steam draw exceeds return", no
        CRIT, because the inventory guard had nothing to compare against.
        Post-fix the reference is 44586, frac = (44586-27141)/44586 =
        0.391, which crosses the 0.30 CRIT threshold given the falling
        trend, and a CRIT mentioning inventory must be produced.
        """
        m = monitor.Monitor(1)
        v1 = healthy_snapshot(sec_liq=44586.0, out=11.0, ret=50.0,
                               amps=0.0, op_mode="NOMINAL")
        self.assertEqual(m.regime(v1), "startup")
        m.alerts(v1, [])
        self.assertEqual(m.sec_liq_ref, 44586.0)

        m.hist["sec_liq"] = deque([44586.0, 36000.0, 27141.0], maxlen=30)
        v2 = healthy_snapshot(sec_liq=27141.0, out=71.0, ret=50.0,
                               amps=0.0, op_mode="NOMINAL")
        self.assertEqual(m.regime(v2), "startup")
        alerts = m.alerts(v2, [])
        self.assertTrue(find(alerts, "CRIT", "secondary inventory"))

    def test_reference_still_seeds_at_power(self):
        """Case 23: no regression for the case that already worked. A
        healthy at-power sample with balance not negative still seeds the
        reference, exactly as before the fix.
        """
        m = monitor.Monitor(1)
        v = healthy_snapshot(sec_liq=12000.0, out=500.0, ret=510.0,
                              amps=500.0, op_mode="NOMINAL")
        self.assertEqual(m.regime(v), "at_power")
        m.alerts(v, [])
        self.assertEqual(m.sec_liq_ref, 12000.0)

    def test_reference_not_seeded_when_balance_negative_any_regime(self):
        """Case 24: the mid-drain protection is not lost. A negative
        balance must never seed the reference, in any regime, at_power or
        startup alike.
        """
        m_power = monitor.Monitor(1)
        v_power = healthy_snapshot(sec_liq=9000.0, out=600.0, ret=500.0,
                                    amps=500.0, op_mode="NOMINAL")
        m_power.alerts(v_power, [])
        self.assertIsNone(m_power.sec_liq_ref)

        m_startup = monitor.Monitor(1)
        v_startup = healthy_snapshot(sec_liq=9000.0, out=600.0, ret=500.0,
                                      amps=0.0, op_mode="NOMINAL")
        m_startup.alerts(v_startup, [])
        self.assertIsNone(m_startup.sec_liq_ref)

    def test_reference_rises_with_higher_reading_not_lowered_by_drop(self):
        """Case 25: high-water mark behaviour, explicit. A later, higher
        healthy reading raises the reference; a subsequent healthy but
        lower reading must not lower it, the reference only ever rises or
        holds.
        """
        m = monitor.Monitor(1)
        v1 = healthy_snapshot(sec_liq=10000.0, out=500.0, ret=510.0)
        m.alerts(v1, [])
        self.assertEqual(m.sec_liq_ref, 10000.0)

        v2 = healthy_snapshot(sec_liq=15000.0, out=500.0, ret=510.0)
        m.alerts(v2, [])
        self.assertEqual(m.sec_liq_ref, 15000.0)

        # Balance still not negative (ret 500 >= out 490), liquid lower
        # than the established reference: must not pull the reference down.
        v3 = healthy_snapshot(sec_liq=8000.0, out=490.0, ret=500.0)
        m.alerts(v3, [])
        self.assertEqual(m.sec_liq_ref, 15000.0)

    def test_steam_feed_balance_guard_still_downgraded_in_startup(self):
        """Case 26: proves the two guards are treated differently ON
        PURPOSE. The steam/feed balance guard (Trip 17 analog, gated by
        P-7 through regime()) is unchanged by this fix and still
        downgrades to INFO during startup, in contrast to the inventory
        reference seed above, which is no longer regime gated at all.
        """
        m = monitor.Monitor(1)
        m.hist["sec_liq"] = deque([12000.0, 11500.0, 11000.0], maxlen=30)
        v = healthy_snapshot(out=550.0, ret=500.0, sec_liq=11000.0,
                              amps=0.0, op_mode="NOMINAL")
        self.assertEqual(m.regime(v), "startup")
        alerts = m.alerts(v, [])
        self.assertTrue(find(alerts, "INFO", "expected during startup"))
        self.assertFalse(has_severity(alerts, "CRIT"))


class TestLossOfForcedCirculationGuard(unittest.TestCase):
    """Cases 27-32: loss of forced primary circulation with the reactor
    critical, the RCS low flow trips analog. See the guard's own comment in
    monitor.py for why this is deliberately not gated by regime().
    """

    def test_reactivo_with_zero_aggregate_flow_is_crit(self):
        """Case 27: core_flow reading a float 0.0 is sufficient on its own
        to call flow absent, regardless of what the pumps say.
        """
        m = monitor.Monitor(1)
        v = healthy_snapshot(core_state="REACTIVO", core_flow=0.0)
        alerts = m.alerts(v, [])
        self.assertTrue(find(alerts, "CRIT", "circulation"))

    def test_reactivo_with_pumps_zero_and_flow_unreadable_is_crit(self):
        """Case 28: fail closed on the aggregate being missing. All three
        pump speeds read 0.0 but core_flow is unreadable (None), the guard
        must still fire, not stay quiet because one of the two readings is
        gone.
        """
        m = monitor.Monitor(1)
        v = healthy_snapshot(core_state="REACTIVO", core_flow=None,
                              core_pump_0=0.0, core_pump_1=0.0, core_pump_2=0.0)
        alerts = m.alerts(v, [])
        self.assertTrue(find(alerts, "CRIT", "circulation"))

    def test_reactivo_with_flow_present_no_alert(self):
        """Case 29: healthy flow, reactor critical, produces no circulation
        alert at all.
        """
        m = monitor.Monitor(1)
        v = healthy_snapshot(core_state="REACTIVO", core_flow=25.0,
                              core_pump_0=0.0, core_pump_1=0.0, core_pump_2=25.0)
        alerts = m.alerts(v, [])
        self.assertFalse(find(alerts, "CRIT", "circulation"))
        self.assertFalse(find(alerts, "WARN", "circulation"))

    def test_not_reactivo_with_zero_flow_no_crit(self):
        """Case 30: shut down with the pumps off is not the same emergency
        as critical with the pumps off. core_state not REACTIVO must not
        produce a CRIT from this guard even with flow at 0.0.
        """
        m = monitor.Monitor(1)
        v = healthy_snapshot(core_state="NOREACTIVO", core_flow=0.0)
        alerts = m.alerts(v, [])
        self.assertFalse(find(alerts, "CRIT", "circulation"))

    def test_nonzero_flow_with_all_pumps_zero_is_crit_and_warn(self):
        """Case 31: contradiction between the aggregate and the parts,
        core_flow reads 25.0 (moving) while all three pumps read 0.0
        (stopped). Fixed 2026-07-28: this used to let the WARN suppress the
        CRIT, trusting the optimistic aggregate over the dangerous parts,
        which is fail-open and backwards for this repository. A
        disagreement between two readings is not a reason to relax, it is a
        reason to believe the worse reading. All pumps at zero is the
        dangerous reading, so the CRIT must fire regardless of what the
        aggregate says, and the WARN about the disagreement must fire
        alongside it, not instead of it. Both alerts are required here.
        """
        m = monitor.Monitor(1)
        v = healthy_snapshot(core_state="REACTIVO", core_flow=25.0,
                              core_pump_0=0.0, core_pump_1=0.0, core_pump_2=0.0)
        alerts = m.alerts(v, [])
        self.assertTrue(find(alerts, "WARN", "disagree"))
        self.assertTrue(find(alerts, "CRIT", "circulation"))

    def test_fires_in_startup_regime_intentionally_ungated(self):
        """Case 32: proves the guard is intentionally NOT gated by
        regime(), mirroring TestInventorySeedRegimeIndependent above. amps
        0.0 and op_mode SHUTDOWN put regime() at "startup", and the CRIT
        must fire anyway: loss of circulation with a critical core is
        dangerous in every regime, including startup, the same reasoning
        that leaves the secondary inventory guard ungated.
        """
        m = monitor.Monitor(1)
        v = healthy_snapshot(core_state="REACTIVO", core_flow=0.0,
                              amps=0.0, op_mode="SHUTDOWN")
        self.assertEqual(m.regime(v), "startup")
        alerts = m.alerts(v, [])
        self.assertTrue(find(alerts, "CRIT", "circulation"))


class TestErrorsAlwaysReported(unittest.TestCase):
    """Case 12: unreadable variables produce ERROR alerts regardless of
    regime. Fail closed applies before any regime gating happens.
    """

    def test_errs_at_power(self):
        m = monitor.Monitor(1)
        v = healthy_snapshot()
        alerts = m.alerts(v, ["SOME_VAR: TimeoutError"])
        self.assertTrue(find(alerts, "ERROR", "SOME_VAR"))

    def test_errs_during_startup(self):
        m = monitor.Monitor(1)
        v = healthy_snapshot(amps=0.0, op_mode="SHUTDOWN")
        alerts = m.alerts(v, ["SOME_VAR: TimeoutError"])
        self.assertTrue(find(alerts, "ERROR", "SOME_VAR"))


class TestLivenessTracking(unittest.TestCase):
    """Cases 13-15: note_liveness() and outage_secs() as pure functions of
    a caller-supplied `now`, driven by hand-picked monotonic values, no
    sleeping, no network. This is the same rationale as the module
    docstring: a real protection system is qualified with injected test
    signals, not by waiting for a genuine outage to happen.
    """

    def test_falling_edge_sets_down_since_and_is_idempotent(self):
        """Case 13: the first False observation sets down_since. A second,
        later False observation while already down must NOT reset it,
        note_liveness is idempotent in the down state, it records when the
        outage started, not when it was last observed.
        """
        m = monitor.Monitor(1)
        m.note_liveness(False, 100.0)
        self.assertEqual(m.down_since, 100.0)
        m.note_liveness(False, 105.0)
        self.assertEqual(m.down_since, 100.0)

    def test_rising_edge_clears_down_since_and_records_duration(self):
        """Case 14: recovery clears down_since and records the completed
        outage's duration in last_outage_secs.
        """
        m = monitor.Monitor(1)
        m.note_liveness(False, 100.0)
        m.note_liveness(True, 137.0)
        self.assertIsNone(m.down_since)
        self.assertEqual(m.last_outage_secs, 37.0)

    def test_outage_secs_healthy_vs_down(self):
        """Case 15: outage_secs is 0.0 while healthy, and the correct
        elapsed delta while down.
        """
        m = monitor.Monitor(1)
        self.assertEqual(m.outage_secs(500.0), 0.0)
        m.note_liveness(False, 500.0)
        self.assertEqual(m.outage_secs(512.5), 12.5)


class TestOutageGuard(unittest.TestCase):
    """Cases 16-18: the outage alert alerts() emits based on
    outage_secs() vs down_threshold, and the invariant that alerts() can
    never come back empty while an outage is in progress.
    """

    def test_outage_below_threshold_is_warn(self):
        """Case 16: an outage shorter than down_threshold is WARN, not
        CRIT, and reads as the benign, expected-during-a-save-load case.
        """
        m = monitor.Monitor(1, down_threshold=10.0)
        m.note_liveness(False, 0.0)
        alerts = m.alerts(healthy_snapshot(), [], now=5.0)
        self.assertTrue(find(alerts, "WARN", "API unreachable"))
        self.assertFalse(has_severity(alerts, "CRIT"))

    def test_outage_at_threshold_is_crit(self):
        """Case 17: an outage at exactly down_threshold escalates to CRIT,
        and the message says the plant is unobserved.
        """
        m = monitor.Monitor(1, down_threshold=10.0)
        m.note_liveness(False, 0.0)
        alerts = m.alerts(healthy_snapshot(), [], now=10.0)
        self.assertTrue(find(alerts, "CRIT", "UNOBSERVED"))

    def test_outage_beyond_threshold_is_crit(self):
        """Case 17 (continued): well beyond down_threshold is still CRIT,
        same message.
        """
        m = monitor.Monitor(1, down_threshold=10.0)
        m.note_liveness(False, 0.0)
        alerts = m.alerts(healthy_snapshot(), [], now=25.0)
        self.assertTrue(find(alerts, "CRIT", "UNOBSERVED"))

    def test_alerts_never_empty_during_outage(self):
        """Case 18: during an outage alerts() must never return an empty
        list, this is what prevents main() from printing "all guards
        clear" while the plant is actually unobserved. Every per-variable
        guard is naturally inert on an all-None snapshot, so if alerts()
        is non-empty here, the outage guard is the only thing that could
        have put something in it.
        """
        m = monitor.Monitor(1)
        m.note_liveness(False, 0.0)
        v = {k: None for k in healthy_snapshot()}
        alerts = m.alerts(v, [], now=3.0)
        self.assertTrue(alerts)


class TestErrorCollapse(unittest.TestCase):
    """Cases 19-20: a wholesale transport-failure outage collapses to one
    ERROR alert instead of one line per variable; a single bad variable,
    or a mix of transport and non-transport failures, does not collapse.
    """

    def test_wholesale_transport_failure_collapses(self):
        """Case 19: the motivating incident, reproduced directly. 24
        entries, all transport failures (URLError), must collapse to
        exactly ONE ERROR alert, not 24.
        """
        m = monitor.Monitor(1)
        errs = [f"VAR_{i}: URLError" for i in range(24)]
        alerts = m.alerts(healthy_snapshot(), errs)
        error_alerts = [msg for sev, msg in alerts if sev == "ERROR"]
        self.assertEqual(len(error_alerts), 1)
        self.assertIn("24", error_alerts[0])

    def test_single_bad_variable_not_collapsed(self):
        """Case 20: regression test that the collapse does not hide real
        signal. One unreadable variable still produces its own
        per-variable ERROR alert, never a collapsed summary, because a
        single bad name is a genuine, different fact from a wholesale
        outage (for example a name that does not exist on this build).
        """
        m = monitor.Monitor(1)
        alerts = m.alerts(healthy_snapshot(), ["WEIRD_NAME: no such variable"])
        self.assertTrue(find(alerts, "ERROR", "WEIRD_NAME"))
        self.assertFalse(find(alerts, "ERROR", "API unreachable"))

    def test_mixed_transport_and_non_transport_not_collapsed(self):
        """Case 20 (continued): a batch that is mostly transport failures
        but includes one non-transport failure is NOT all-transport, so it
        does not collapse either. Only a uniform, wholesale transport
        failure does.
        """
        m = monitor.Monitor(1)
        errs = [f"VAR_{i}: URLError" for i in range(24)] + ["ODD_NAME: no such variable"]
        alerts = m.alerts(healthy_snapshot(), errs)
        error_alerts = [msg for sev, msg in alerts if sev == "ERROR"]
        self.assertEqual(len(error_alerts), 25)
        self.assertTrue(any("ODD_NAME" in msg for msg in error_alerts))


class TestOutageRecovery(unittest.TestCase):
    """Case 21: the "readings resumed" recovery message fires exactly
    once, on the first snapshot after recovery, not again on the one
    after that.
    """

    def test_recovery_warn_fires_once(self):
        m = monitor.Monitor(1)
        m.note_liveness(False, 0.0)
        m.note_liveness(True, 20.0)
        self.assertEqual(m.last_outage_secs, 20.0)

        first = m.alerts(healthy_snapshot(), [], now=21.0)
        self.assertTrue(find(first, "WARN", "readings resumed"))

        second = m.alerts(healthy_snapshot(), [], now=22.0)
        self.assertFalse(find(second, "WARN", "readings resumed"))


class TestVesselTemperatureDivergence(unittest.TestCase):
    """Cases 33-34: the vessel_t/core_t divergence guard. Both names have
    read byte identical (309.4696) in every sample taken so far; this
    guard exists to detect whether that ever stops being true, not
    because a small gap is itself dangerous. 1.0 is an uncalibrated
    heuristic, see monitor.py.
    """

    def test_within_tolerance_no_warn(self):
        """Case 33: a 0.5 gap, within the 1.0 tolerance, produces no
        divergence WARN.
        """
        m = monitor.Monitor(1)
        v = healthy_snapshot(vessel_t=300.5, core_t=300.0)
        alerts = m.alerts(v, [])
        self.assertFalse(find(alerts, "WARN", "diverged"))

    def test_beyond_tolerance_is_warn(self):
        """Case 34: a 2.0 gap, beyond the 1.0 tolerance, produces the
        divergence WARN, and it is informative severity (WARN), not
        CRIT, per the guard's own comment: firing is informative, not an
        emergency.
        """
        m = monitor.Monitor(1)
        v = healthy_snapshot(vessel_t=302.0, core_t=300.0)
        alerts = m.alerts(v, [])
        self.assertTrue(find(alerts, "WARN", "diverged"))


class TestResistorBankParsing(unittest.TestCase):
    """Case 35: RESISTOR_BANKS_JSON parsing via parse_resistor_banks(),
    a pure function so this can be tested directly without network
    access. Only installed banks count towards either the installed
    count or the max temperature; the important case is that a naive
    max() or count over all four entries would return an uninstalled
    bank's fake Temperature 0.0 as the hottest bank, or inflate the
    count. Fixture is the measured live payload: one installed bank at
    29.6399632, three uninstalled banks at 0.0.
    """

    def test_only_installed_banks_counted_and_maxed(self):
        raw = json.dumps({"resistors": {
            "Resistor_Bank_01": {"IsInstalled": 1, "Temperature": 29.6399632},
            "Resistor_Bank_02": {"IsInstalled": 0, "Temperature": 0.0},
            "Resistor_Bank_03": {"IsInstalled": 0, "Temperature": 0.0},
            "Resistor_Bank_04": {"IsInstalled": 0, "Temperature": 0.0},
        }})
        count, max_t, err = monitor.parse_resistor_banks(raw)
        self.assertIsNone(err)
        self.assertEqual(count, 1.0)
        self.assertAlmostEqual(max_t, 29.6399632)

    def test_second_installed_bank_sets_max_not_the_raw_entry_count(self):
        """A second, hotter installed bank must set the max; the count
        must reflect the two installed banks, not the four raw entries.
        """
        raw = json.dumps({"resistors": {
            "Resistor_Bank_01": {"IsInstalled": 1, "Temperature": 29.6},
            "Resistor_Bank_02": {"IsInstalled": 1, "Temperature": 45.2},
            "Resistor_Bank_03": {"IsInstalled": 0, "Temperature": 0.0},
            "Resistor_Bank_04": {"IsInstalled": 0, "Temperature": 0.0},
        }})
        count, max_t, err = monitor.parse_resistor_banks(raw)
        self.assertIsNone(err)
        self.assertEqual(count, 2.0)
        self.assertEqual(max_t, 45.2)

    def test_malformed_json_returns_error_and_does_not_raise(self):
        """The pure-function half of case 36: a malformed body returns
        an error string instead of raising, and both derived values come
        back None.
        """
        count, max_t, err = monitor.parse_resistor_banks("{not valid json")
        self.assertIsNone(count)
        self.assertIsNone(max_t)
        self.assertIsNotNone(err)


class TestResistorBankSnapIntegration(unittest.TestCase):
    """Case 36: the snap()-level half of the malformed-JSON case, proving
    the parse failure actually reaches `errs` the way every other
    per-variable read failure in this file does, and that snap() itself
    does not raise. monitor.read() is monkeypatched so this stays a unit
    test, no network, no game; see fake_read_factory().
    """

    def test_malformed_resistor_json_appends_to_errs_not_raise(self):
        fake = fake_read_factory(
            {"RESISTOR_BANKS_JSON": (True, "{not valid json")})
        m = monitor.Monitor(1)
        with mock.patch.object(monitor, "read", fake):
            vals, errs = m.snap()  # must not raise
        self.assertIsNone(vals["res_installed"])
        self.assertIsNone(vals["res_max_t"])
        self.assertTrue(any("RESISTOR_BANKS_JSON" in e for e in errs))

    def test_clean_resistor_json_reaches_vals_via_snap(self):
        """Regression guard for the integration wiring itself, not just
        the pure parser: a clean payload read through snap() ends up in
        vals under the expected keys.
        """
        raw = json.dumps({"resistors": {
            "Resistor_Bank_01": {"IsInstalled": 1, "Temperature": 29.6399632},
            "Resistor_Bank_02": {"IsInstalled": 0, "Temperature": 0.0},
        }})
        fake = fake_read_factory({"RESISTOR_BANKS_JSON": (True, raw)})
        m = monitor.Monitor(1)
        with mock.patch.object(monitor, "read", fake):
            vals, errs = m.snap()
        self.assertEqual(vals["res_installed"], 1.0)
        self.assertAlmostEqual(vals["res_max_t"], 29.6399632)
        self.assertFalse(any("RESISTOR_BANKS_JSON" in e for e in errs))


class TestDumpedPowerGuard(unittest.TestCase):
    """Cases 37-39: dumped-power guards, resistor bank thermal trend and
    the majority-of-generation waste guard, plus the fabricated-KW
    regression that must suppress both when amps read 0.
    """

    def test_dumped_power_not_computed_when_amps_zero(self):
        """Case 37: fabricated-KW regression. GENERATOR_{i}_KW reads a
        fabricated potential figure when GENERATOR_{i}_A is 0 (measured
        live: 33702 kW at 0 amps, docs/value-semantics.md section 9). If
        dumped power were computed from that fabricated KW, an unsynced
        plant reading a large idle KW figure against a small demand
        could fire a dump-related alert with no basis in reality. Dumped
        power must simply not be computed when amps is 0, not computed
        as some fallback value, so neither dump guard may fire here even
        with a rising bank-temperature trend and a huge nominal KW.
        """
        m = monitor.Monitor(1)
        m.hist["res_max_t"] = deque([29.0, 29.3, 29.64], maxlen=30)
        v = healthy_snapshot(amps=0.0, gen_kw=33702.0, demand=1.0,
                              res_installed=1.0, res_max_t=29.64)
        alerts = m.alerts(v, [])
        self.assertFalse(find(alerts, "WARN", "resistor bank absorbing"))
        self.assertFalse(find(alerts, "WARN", "being dumped as heat"))

    def test_dumped_power_with_rising_temp_trend_is_warn(self):
        """Case 38: measured live, 26,548 kW generated against 7 MW
        demand, dumping about 19.5 MW into the single installed bank.
        hist is populated directly, per this file's convention for trend
        tests, rather than through snap().
        """
        m = monitor.Monitor(1)
        m.hist["res_max_t"] = deque([29.64, 29.70, 29.80], maxlen=30)
        v = healthy_snapshot(amps=500.0, gen_kw=26548.0, demand=7.0,
                              res_installed=1.0, res_max_t=29.80)
        alerts = m.alerts(v, [])
        warn = find(alerts, "WARN", "resistor bank absorbing")
        self.assertTrue(warn)
        self.assertIn("19.5", warn[0])

    def test_dumped_power_flat_temp_trend_no_warn(self):
        """Companion to case 38: the same dumped power, but the bank
        temperature is flat rather than rising, must not produce the
        thermal-trend WARN. Guarding the trend, not the dump alone, is
        the point.
        """
        m = monitor.Monitor(1)
        m.hist["res_max_t"] = deque([29.64, 29.64, 29.64], maxlen=30)
        v = healthy_snapshot(amps=500.0, gen_kw=26548.0, demand=7.0,
                              res_installed=1.0, res_max_t=29.64)
        alerts = m.alerts(v, [])
        self.assertFalse(find(alerts, "WARN", "resistor bank absorbing"))

    def test_dumped_power_majority_of_generation_is_warn(self):
        """Case 39: dumped power exceeding half of generation triggers
        the waste guard independent of the thermal-trend guard. 26,548
        kW generated, 7 MW demand: dumping about 19.5 MW is roughly 74%
        of output, matching the measured live figure in
        docs/protection-system.md ("73.6 percent of generation").
        """
        m = monitor.Monitor(1)
        v = healthy_snapshot(amps=500.0, gen_kw=26548.0, demand=7.0,
                              res_installed=1.0, res_max_t=29.64)
        alerts = m.alerts(v, [])
        warn = find(alerts, "WARN", "being dumped as heat")
        self.assertTrue(warn)
        self.assertIn("74%", warn[0])


if __name__ == "__main__":
    unittest.main()
