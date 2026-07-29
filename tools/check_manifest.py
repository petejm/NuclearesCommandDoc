#!/usr/bin/env python3
"""
Checks the game's own variable manifest against data/manifest.json.

WEBSERVER_LIST_VARIABLES_JSON is the game's own list of every variable it
serves, shaped {"GET": [...], "POST": [...]}. data/manifest.json is a
verbatim capture of that same call (see docs/scraping.md, step 1). Measured
at build V 2.2.25.220: 332 GET names, 91 POST names, 35 of the POST names
also readable under the same name (see docs/writable-variables.md), so the
union of GET and POST is 388 names, and the live game and the checked-in
manifest agreed exactly, zero missing in either direction.

That agreement is a snapshot, not a guarantee. A future game build can add,
remove or rename a variable at any time. This script exists so that drift
fails loudly instead of the map silently going stale, the same property
CONTRIBUTING.md already requires of the docs/writable-variables.md
generator ("If a future build adds a variable, generation fails loudly
instead of silently dropping it").

Usage:
    python3 tools/check_manifest.py                 # live, hits the API
    python3 tools/check_manifest.py --fixture F.json # offline, no network

Exit codes:
    0   game and manifest agree exactly (GET, POST, and their union), and
        none of the four source lists contains a duplicated name
    1   drift detected (a name is missing from one side or the other), or a
        name is duplicated within one of the four source lists (game GET,
        game POST, manifest GET, manifest POST). A duplicate is reported as
        a distinct condition, separately from drift, because the set-based
        comparison below silently dedups: a name duplicated in a future
        build changes what len(list) would report without the set-based
        comparison ever seeing it, so duplicates are checked for
        explicitly rather than assumed away.
    2   could not load one of the two sides at all (network failure,
        missing file, malformed JSON, or a GET/POST value present but not
        shaped as a list). Never raises for this, per the fail-closed
        convention the rest of this repository's tools use (see
        tools/probe.py, tools/checklist.py): a read resolves to a value, a
        documented failure, or an ERROR, and ERROR never collapses into
        either of the other two.

stdlib only, no third-party dependencies.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://localhost:8785"
VARIABLE = "WEBSERVER_LIST_VARIABLES_JSON"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "data" / "manifest.json"


def validate_get_post_shape(data: dict, source: str) -> str | None:
    """Checks that GET and POST, when present, are JSON lists.

    Returns an error string naming the offending key and the type that
    arrived, or None if the shape is fine. A missing key is not an error
    here; diff_manifests() already treats a missing key as an empty list.
    This exists because set() on a non-list value either raises (None) or
    silently decomposes a string into characters, and both of those are
    schema failures that should be caught here rather than surfacing as an
    uncaught exception or a meaningless comparison downstream.
    """
    for key in ("GET", "POST"):
        if key not in data:
            continue
        value = data[key]
        if not isinstance(value, list):
            return (f"{source}: {key!r} is present but not a list "
                     f"(got {type(value).__name__})")
    return None


def load_json_file(path: str | Path) -> tuple[dict | None, str | None]:
    """Reads and parses a JSON object from disk.

    Returns (data, error). Never raises: a missing file, an unreadable
    file, malformed JSON, and a GET/POST value present but not shaped as a
    list are all reported back as a clean error string rather than an
    exception, so a caller can fail closed instead of crashing.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        return None, f"cannot read {path}: {e}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"malformed JSON in {path}: {e}"
    if not isinstance(data, dict):
        return None, f"{path} did not contain a JSON object at the top level"
    shape_err = validate_get_post_shape(data, str(path))
    if shape_err:
        return None, shape_err
    return data, None


def fetch_live(timeout: float = 5.0) -> tuple[dict | None, str | None]:
    """Fetches WEBSERVER_LIST_VARIABLES_JSON from a running game.

    Same (data, error) contract as load_json_file, and the same reason:
    a transport failure or a malformed response must not raise or be
    mistaken for an empty-but-valid manifest.
    """
    url = f"{BASE}/?Variable={VARIABLE}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        return None, f"could not reach {url}: {type(e).__name__}: {e}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"malformed JSON from {url}: {e}"
    if not isinstance(data, dict):
        return None, f"{url} did not return a JSON object at the top level"
    shape_err = validate_get_post_shape(data, url)
    if shape_err:
        return None, shape_err
    return data, None


def find_duplicates(names: list) -> list:
    """Returns the names that appear more than once in a list, sorted.

    Exists because every comparison in diff_manifests() below is set-based,
    and a set silently collapses a duplicate to one entry. That means a
    duplicated name in a future build would change what len(list) reports
    without len(set) ever registering it as drift: the count as measured by
    this script's set comparison could stay the same while the underlying
    list actually grew. This is checked separately, on the raw list, before
    anything is converted to a set.
    """
    seen: set = set()
    dupes: set = set()
    for n in names:
        if n in seen:
            dupes.add(n)
        else:
            seen.add(n)
    return sorted(dupes)


def diff_manifests(game: dict, manifest: dict) -> dict:
    """Pure comparison, no I/O, so it can be exercised directly by tests.

    Compares GET and POST separately (catching, for example, a variable
    that moved from read-only to writable, which the union alone would
    hide) and also compares the union of the two, which is the 388-name
    figure this script's docstring cites.

    Also checks each of the four raw source lists for internal duplicates,
    independently of the set-based drift comparison, see find_duplicates().
    """
    game_get_list = game.get("GET", [])
    game_post_list = game.get("POST", [])
    man_get_list = manifest.get("GET", [])
    man_post_list = manifest.get("POST", [])

    game_get = set(game_get_list)
    game_post = set(game_post_list)
    man_get = set(man_get_list)
    man_post = set(man_post_list)
    game_union = game_get | game_post
    man_union = man_get | man_post

    return {
        "game_get_count": len(game_get),
        "game_post_count": len(game_post),
        "game_union_count": len(game_union),
        "manifest_get_count": len(man_get),
        "manifest_post_count": len(man_post),
        "manifest_union_count": len(man_union),
        "get_only_in_game": sorted(game_get - man_get),
        "get_only_in_manifest": sorted(man_get - game_get),
        "post_only_in_game": sorted(game_post - man_post),
        "post_only_in_manifest": sorted(man_post - game_post),
        "union_only_in_game": sorted(game_union - man_union),
        "union_only_in_manifest": sorted(man_union - game_union),
        "duplicates": {
            "game_get": find_duplicates(game_get_list),
            "game_post": find_duplicates(game_post_list),
            "manifest_get": find_duplicates(man_get_list),
            "manifest_post": find_duplicates(man_post_list),
        },
    }


DRIFT_KEYS = (
    "get_only_in_game",
    "get_only_in_manifest",
    "post_only_in_game",
    "post_only_in_manifest",
    "union_only_in_game",
    "union_only_in_manifest",
)

DUPLICATE_KEYS = (
    "game_get",
    "game_post",
    "manifest_get",
    "manifest_post",
)


def has_drift(result: dict) -> bool:
    return any(result[k] for k in DRIFT_KEYS)


def has_duplicates(result: dict) -> bool:
    return any(result["duplicates"][k] for k in DUPLICATE_KEYS)


def format_report(result: dict) -> str:
    lines = [
        f"game:     GET {result['game_get_count']}  "
        f"POST {result['game_post_count']}  "
        f"union {result['game_union_count']}",
        f"manifest: GET {result['manifest_get_count']}  "
        f"POST {result['manifest_post_count']}  "
        f"union {result['manifest_union_count']}",
    ]
    drift = has_drift(result)
    dupes = has_duplicates(result)

    if not drift and not dupes:
        lines.append("MATCH: game and manifest agree exactly, zero drift "
                      "in either direction, no duplicate names in any "
                      "source list.")
        return "\n".join(lines)

    if drift:
        lines.append("DRIFT DETECTED:")
        labels = {
            "get_only_in_game": "in game GET list, missing from manifest GET",
            "get_only_in_manifest": "in manifest GET list, missing from game GET",
            "post_only_in_game": "in game POST list, missing from manifest POST",
            "post_only_in_manifest": "in manifest POST list, missing from game POST",
            "union_only_in_game": "in game, missing from manifest (union)",
            "union_only_in_manifest": "in manifest, missing from game (union)",
        }
        for key in DRIFT_KEYS:
            names = result[key]
            if not names:
                continue
            lines.append(f"  {labels[key]} ({len(names)}):")
            for n in names:
                lines.append(f"    {n}")

    if dupes:
        lines.append("DUPLICATE NAMES DETECTED (a data-quality issue in a "
                      "source list itself, distinct from drift between the "
                      "two sides):")
        dup_labels = {
            "game_get": "duplicated within the game GET list",
            "game_post": "duplicated within the game POST list",
            "manifest_get": "duplicated within the manifest GET list",
            "manifest_post": "duplicated within the manifest POST list",
        }
        for key in DUPLICATE_KEYS:
            names = result["duplicates"][key]
            if not names:
                continue
            lines.append(f"  {dup_labels[key]} ({len(names)}):")
            for n in names:
                lines.append(f"    {n}")

    return "\n".join(lines)


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fixture", metavar="PATH",
                    help="read the game's variable list from a saved JSON "
                         "payload instead of the live API")
    ap.add_argument("--manifest", metavar="PATH", default=str(DEFAULT_MANIFEST),
                    help=f"path to the checked-in manifest "
                         f"(default: {DEFAULT_MANIFEST})")
    args = ap.parse_args(argv)

    manifest_data, err = load_json_file(args.manifest)
    if err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2

    if args.fixture:
        game_data, err = load_json_file(args.fixture)
    else:
        game_data, err = fetch_live()
    if err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2

    result = diff_manifests(game_data, manifest_data)
    print(format_report(result))
    return 1 if (has_drift(result) or has_duplicates(result)) else 0


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
