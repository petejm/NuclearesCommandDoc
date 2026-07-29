#!/usr/bin/env python3
"""
Unit tests for tools/check_manifest.py.

A new file rather than an addition to test_monitor.py: that file's own
docstring scopes it to "Unit tests for tools/monitor.py", and monitor.py
and check_manifest.py are unrelated tools (one is a live-plant guard, the
other is a manifest-drift check run against a static capture). Keeping them
separate keeps each test file's failures attributable to one tool.

All fixtures are hand-built JSON, written to temp files. No network calls,
no game, matching the no-network convention tools/test_monitor.py already
documents for this repository's test suite.

Run as, from the repo root:
    python3 tools/test_check_manifest.py
    python3 -m unittest discover -s tools

Bare `python3 -m unittest` from the repo root discovers 0 tests, same
reason as tools/test_monitor.py: tools/ has no __init__.py.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_manifest  # noqa: E402


def write_json(tmpdir: str, name: str, data) -> str:
    path = os.path.join(tmpdir, name)
    with open(path, "w", encoding="utf-8") as f:
        if isinstance(data, str):
            f.write(data)  # deliberately raw, for malformed-JSON cases
        else:
            json.dump(data, f)
    return path


class TestLoadJsonFile(unittest.TestCase):
    """load_json_file never raises: missing file, malformed JSON and a
    valid object are three distinct, non-exception outcomes.
    """

    def test_valid_object(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_json(d, "m.json", {"GET": ["A"], "POST": ["B"]})
            data, err = check_manifest.load_json_file(path)
        self.assertIsNone(err)
        self.assertEqual(data, {"GET": ["A"], "POST": ["B"]})

    def test_missing_file_returns_error_not_raise(self):
        data, err = check_manifest.load_json_file("/nonexistent/path/does-not-exist.json")
        self.assertIsNone(data)
        self.assertIsNotNone(err)

    def test_malformed_json_returns_error_not_raise(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_json(d, "bad.json", "{not valid json")
            data, err = check_manifest.load_json_file(path)
        self.assertIsNone(data)
        self.assertIsNotNone(err)
        self.assertIn("malformed JSON", err)

    def test_non_object_top_level_returns_error(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_json(d, "list.json", ["A", "B"])
            data, err = check_manifest.load_json_file(path)
        self.assertIsNone(data)
        self.assertIsNotNone(err)


class TestGetPostShapeValidation(unittest.TestCase):
    """GET and POST, when present, must be JSON lists. Without this check,
    a null value makes diff_manifests() call set(None) and raise an
    uncaught TypeError, and a bare string is silently decomposed by set()
    into individual characters instead of being compared as names. Both
    are schema failures load_json_file must catch and turn into the same
    (None, error) shape it already uses for a missing file or malformed
    JSON, never an exception.
    """

    def test_null_get_returns_error_not_raise(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_json(d, "m.json", {"GET": None, "POST": ["B"]})
            data, err = check_manifest.load_json_file(path)
        self.assertIsNone(data)
        self.assertIsNotNone(err)
        self.assertIn("GET", err)

    def test_null_post_returns_error_not_raise(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_json(d, "m.json", {"GET": ["A"], "POST": None})
            data, err = check_manifest.load_json_file(path)
        self.assertIsNone(data)
        self.assertIsNotNone(err)
        self.assertIn("POST", err)

    def test_bare_string_get_returns_error_not_silent_decompose(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_json(d, "m.json", {"GET": "ABC", "POST": []})
            data, err = check_manifest.load_json_file(path)
        self.assertIsNone(data)
        self.assertIsNotNone(err)
        self.assertIn("GET", err)

    def test_dict_get_returns_error(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_json(d, "m.json", {"GET": {"A": 1}, "POST": []})
            data, err = check_manifest.load_json_file(path)
        self.assertIsNone(data)
        self.assertIsNotNone(err)
        self.assertIn("GET", err)

    def test_number_get_returns_error(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_json(d, "m.json", {"GET": 42, "POST": []})
            data, err = check_manifest.load_json_file(path)
        self.assertIsNone(data)
        self.assertIsNotNone(err)
        self.assertIn("GET", err)

    def test_missing_get_key_is_not_a_shape_error(self):
        """A missing key is existing, unchanged behaviour (diff_manifests()
        treats it as empty); only a present-but-wrong-type value is new.
        """
        with tempfile.TemporaryDirectory() as d:
            path = write_json(d, "m.json", {"POST": ["A"]})
            data, err = check_manifest.load_json_file(path)
        self.assertIsNone(err)
        self.assertEqual(data, {"POST": ["A"]})


class TestDiffManifests(unittest.TestCase):
    """Pure comparison logic, no I/O."""

    def test_exact_match_no_drift(self):
        game = {"GET": ["A", "B", "C"], "POST": ["B", "D"]}
        manifest = {"GET": ["A", "B", "C"], "POST": ["B", "D"]}
        result = check_manifest.diff_manifests(game, manifest)
        self.assertFalse(check_manifest.has_drift(result))
        # union is {A, B, C, D} = 4, matching the repo's own measured
        # relationship: union size = GET + POST - overlap.
        self.assertEqual(result["game_union_count"], 4)
        self.assertEqual(result["manifest_union_count"], 4)

    def test_name_only_in_game_get_is_drift(self):
        game = {"GET": ["A", "B", "NEW_VAR"], "POST": []}
        manifest = {"GET": ["A", "B"], "POST": []}
        result = check_manifest.diff_manifests(game, manifest)
        self.assertTrue(check_manifest.has_drift(result))
        self.assertIn("NEW_VAR", result["get_only_in_game"])
        self.assertIn("NEW_VAR", result["union_only_in_game"])
        self.assertEqual(result["get_only_in_manifest"], [])

    def test_name_only_in_manifest_get_is_drift(self):
        game = {"GET": ["A", "B"], "POST": []}
        manifest = {"GET": ["A", "B", "REMOVED_VAR"], "POST": []}
        result = check_manifest.diff_manifests(game, manifest)
        self.assertTrue(check_manifest.has_drift(result))
        self.assertIn("REMOVED_VAR", result["get_only_in_manifest"])
        self.assertIn("REMOVED_VAR", result["union_only_in_manifest"])
        self.assertEqual(result["get_only_in_game"], [])

    def test_name_only_in_game_post_is_drift(self):
        game = {"GET": [], "POST": ["A", "NEW_WRITABLE"]}
        manifest = {"GET": [], "POST": ["A"]}
        result = check_manifest.diff_manifests(game, manifest)
        self.assertTrue(check_manifest.has_drift(result))
        self.assertIn("NEW_WRITABLE", result["post_only_in_game"])

    def test_name_only_in_manifest_post_is_drift(self):
        game = {"GET": [], "POST": ["A"]}
        manifest = {"GET": [], "POST": ["A", "GONE_WRITABLE"]}
        result = check_manifest.diff_manifests(game, manifest)
        self.assertTrue(check_manifest.has_drift(result))
        self.assertIn("GONE_WRITABLE", result["post_only_in_manifest"])

    def test_variable_moving_from_get_only_to_readwrite_is_drift(self):
        """A variable gaining POST access (or losing it) is drift even
        though the union set is unaffected, which is exactly why GET and
        POST are diffed separately and not only as a union.
        """
        game = {"GET": ["A"], "POST": ["A"]}
        manifest = {"GET": ["A"], "POST": []}
        result = check_manifest.diff_manifests(game, manifest)
        self.assertTrue(check_manifest.has_drift(result))
        self.assertEqual(result["union_only_in_game"], [])
        self.assertEqual(result["union_only_in_manifest"], [])
        self.assertIn("A", result["post_only_in_game"])

    def test_missing_keys_treated_as_empty_not_raise(self):
        game = {}
        manifest = {"GET": ["A"], "POST": []}
        result = check_manifest.diff_manifests(game, manifest)
        self.assertTrue(check_manifest.has_drift(result))
        self.assertIn("A", result["get_only_in_manifest"])


class TestDuplicateDetection(unittest.TestCase):
    """The set-based comparisons in diff_manifests() silently dedup, so a
    duplicated name in one of the four raw source lists has to be caught
    separately, on the list itself, before it is ever turned into a set.
    """

    def test_find_duplicates_empty_on_clean_list(self):
        self.assertEqual(check_manifest.find_duplicates(["A", "B", "C"]), [])

    def test_find_duplicates_finds_repeated_name(self):
        self.assertEqual(
            check_manifest.find_duplicates(["A", "B", "A", "C", "B", "B"]),
            ["A", "B"],
        )

    def test_no_duplicates_no_drift_is_clean(self):
        payload = {"GET": ["A", "B"], "POST": ["C"]}
        result = check_manifest.diff_manifests(payload, payload)
        self.assertFalse(check_manifest.has_drift(result))
        self.assertFalse(check_manifest.has_duplicates(result))

    def test_duplicate_in_game_get_is_flagged_without_being_drift(self):
        """A duplicate in the game GET list changes nothing about set
        membership (A is still just 'present'), so this must not be
        reported as drift; it must be reported as a duplicate instead.
        """
        game = {"GET": ["A", "A", "B"], "POST": []}
        manifest = {"GET": ["A", "B"], "POST": []}
        result = check_manifest.diff_manifests(game, manifest)
        self.assertFalse(check_manifest.has_drift(result))
        self.assertTrue(check_manifest.has_duplicates(result))
        self.assertIn("A", result["duplicates"]["game_get"])
        self.assertEqual(result["duplicates"]["game_post"], [])
        self.assertEqual(result["duplicates"]["manifest_get"], [])
        self.assertEqual(result["duplicates"]["manifest_post"], [])

    def test_duplicate_in_manifest_post_is_flagged(self):
        game = {"GET": [], "POST": ["X"]}
        manifest = {"GET": [], "POST": ["X", "X"]}
        result = check_manifest.diff_manifests(game, manifest)
        self.assertFalse(check_manifest.has_drift(result))
        self.assertTrue(check_manifest.has_duplicates(result))
        self.assertIn("X", result["duplicates"]["manifest_post"])

    def test_duplicate_does_not_change_the_set_based_count(self):
        """The exact failure mode this feature closes: without an explicit
        duplicate check, a duplicated name changes the true list length
        while the set-based *_count fields stay identical, so nothing
        downstream would ever notice from the counts alone.
        """
        clean = {"GET": ["A", "B"], "POST": []}
        with_dupe = {"GET": ["A", "A", "B"], "POST": []}
        result_clean = check_manifest.diff_manifests(clean, clean)
        result_dupe = check_manifest.diff_manifests(with_dupe, clean)
        self.assertEqual(result_clean["game_get_count"],
                          result_dupe["game_get_count"])
        self.assertFalse(check_manifest.has_duplicates(result_clean))
        self.assertTrue(check_manifest.has_duplicates(result_dupe))

    def test_run_exits_nonzero_on_duplicate_with_no_drift(self):
        with tempfile.TemporaryDirectory() as d:
            fixture = write_json(d, "game.json", {"GET": ["A", "A"], "POST": []})
            manifest = write_json(d, "manifest.json", {"GET": ["A"], "POST": []})
            code = check_manifest.run(["--fixture", fixture, "--manifest", manifest])
        self.assertEqual(code, 1)


class TestRunExitCodes(unittest.TestCase):
    """End-to-end through run(), using --fixture so nothing touches the
    network, per this repository's own testing convention.
    """

    def test_exact_match_exits_zero(self):
        with tempfile.TemporaryDirectory() as d:
            payload = {"GET": ["A", "B", "C"], "POST": ["B", "D"]}
            fixture = write_json(d, "game.json", payload)
            manifest = write_json(d, "manifest.json", payload)
            code = check_manifest.run(["--fixture", fixture, "--manifest", manifest])
        self.assertEqual(code, 0)

    def test_name_only_in_game_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as d:
            fixture = write_json(d, "game.json",
                                  {"GET": ["A", "B", "NEW_VAR"], "POST": []})
            manifest = write_json(d, "manifest.json", {"GET": ["A", "B"], "POST": []})
            code = check_manifest.run(["--fixture", fixture, "--manifest", manifest])
        self.assertEqual(code, 1)

    def test_name_only_in_manifest_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as d:
            fixture = write_json(d, "game.json", {"GET": ["A", "B"], "POST": []})
            manifest = write_json(d, "manifest.json",
                                   {"GET": ["A", "B", "REMOVED_VAR"], "POST": []})
            code = check_manifest.run(["--fixture", fixture, "--manifest", manifest])
        self.assertEqual(code, 1)

    def test_malformed_fixture_fails_cleanly(self):
        """Case: malformed JSON on the game side must exit non-zero
        without raising, not crash the process with a traceback.
        """
        with tempfile.TemporaryDirectory() as d:
            fixture = write_json(d, "game.json", "{not valid json")
            manifest = write_json(d, "manifest.json", {"GET": [], "POST": []})
            code = check_manifest.run(["--fixture", fixture, "--manifest", manifest])
        self.assertEqual(code, 2)

    def test_malformed_manifest_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as d:
            fixture = write_json(d, "game.json", {"GET": [], "POST": []})
            manifest = write_json(d, "manifest.json", "{not valid json")
            code = check_manifest.run(["--fixture", fixture, "--manifest", manifest])
        self.assertEqual(code, 2)

    def test_null_get_in_fixture_exits_two_without_raising(self):
        """The exact defect this feature closes: a null GET must not reach
        diff_manifests() and blow up as set(None), it must fail closed at
        load time with the documented exit code.
        """
        with tempfile.TemporaryDirectory() as d:
            fixture = write_json(d, "game.json", {"GET": None, "POST": []})
            manifest = write_json(d, "manifest.json", {"GET": [], "POST": []})
            try:
                code = check_manifest.run(["--fixture", fixture, "--manifest", manifest])
            except Exception as e:  # pragma: no cover - failure path
                self.fail(f"run() raised {type(e).__name__}: {e}")
        self.assertEqual(code, 2)

    def test_null_post_in_manifest_exits_two_without_raising(self):
        with tempfile.TemporaryDirectory() as d:
            fixture = write_json(d, "game.json", {"GET": [], "POST": []})
            manifest = write_json(d, "manifest.json", {"GET": [], "POST": None})
            try:
                code = check_manifest.run(["--fixture", fixture, "--manifest", manifest])
            except Exception as e:  # pragma: no cover - failure path
                self.fail(f"run() raised {type(e).__name__}: {e}")
        self.assertEqual(code, 2)

    def test_bare_string_get_in_fixture_exits_two_not_silent(self):
        """Without the fix, set('ABC') silently becomes {'A','B','C'} and
        the tool would run to a (meaningless) exit 0 or 1. It must instead
        be rejected as a schema failure.
        """
        with tempfile.TemporaryDirectory() as d:
            fixture = write_json(d, "game.json", {"GET": "ABC", "POST": []})
            manifest = write_json(d, "manifest.json", {"GET": [], "POST": []})
            try:
                code = check_manifest.run(["--fixture", fixture, "--manifest", manifest])
            except Exception as e:  # pragma: no cover - failure path
                self.fail(f"run() raised {type(e).__name__}: {e}")
        self.assertEqual(code, 2)

    def test_dict_get_in_fixture_exits_two_without_raising(self):
        with tempfile.TemporaryDirectory() as d:
            fixture = write_json(d, "game.json", {"GET": {"A": 1}, "POST": []})
            manifest = write_json(d, "manifest.json", {"GET": [], "POST": []})
            try:
                code = check_manifest.run(["--fixture", fixture, "--manifest", manifest])
            except Exception as e:  # pragma: no cover - failure path
                self.fail(f"run() raised {type(e).__name__}: {e}")
        self.assertEqual(code, 2)

    def test_number_get_in_fixture_exits_two_without_raising(self):
        with tempfile.TemporaryDirectory() as d:
            fixture = write_json(d, "game.json", {"GET": 42, "POST": []})
            manifest = write_json(d, "manifest.json", {"GET": [], "POST": []})
            try:
                code = check_manifest.run(["--fixture", fixture, "--manifest", manifest])
            except Exception as e:  # pragma: no cover - failure path
                self.fail(f"run() raised {type(e).__name__}: {e}")
        self.assertEqual(code, 2)

    def test_missing_fixture_file_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = write_json(d, "manifest.json", {"GET": [], "POST": []})
            code = check_manifest.run([
                "--fixture", "/nonexistent/path/does-not-exist.json",
                "--manifest", manifest,
            ])
        self.assertEqual(code, 2)

    def test_real_manifest_matches_itself(self):
        """Sanity check against the actual checked-in manifest: comparing
        it against itself must always be a clean, driftless match. This is
        the offline equivalent of the live 388/388/zero-drift measurement
        this script's docstring cites, using the manifest as its own
        fixture instead of the network.

        Comparing a file against itself is tautological on its own, so this
        also pins the actual counts (332 GET, 91 POST, 388 union) against
        the real checked-in manifest, not just against a copy of itself.
        Several docs (README.md, tools/README.md, this script's own
        docstring) quote those exact numbers in prose; an edit to
        data/manifest.json that silently changed the counts would pass a
        pure self-comparison but must fail this test, so those docs cannot
        go stale without a test noticing.
        """
        manifest_data, err = check_manifest.load_json_file(
            check_manifest.DEFAULT_MANIFEST)
        self.assertIsNone(err)
        result = check_manifest.diff_manifests(manifest_data, manifest_data)
        self.assertEqual(result["game_get_count"], 332)
        self.assertEqual(result["game_post_count"], 91)
        self.assertEqual(result["game_union_count"], 388)
        self.assertFalse(check_manifest.has_duplicates(result))

        code = check_manifest.run([
            "--fixture", str(check_manifest.DEFAULT_MANIFEST),
            "--manifest", str(check_manifest.DEFAULT_MANIFEST),
        ])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
