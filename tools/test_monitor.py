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


if __name__ == "__main__":
    unittest.main()
