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

import os
import sys
import unittest
from collections import deque

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


if __name__ == "__main__":
    unittest.main()
