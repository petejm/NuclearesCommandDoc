# How to regenerate everything in this repository

Every table here is derived from the running game. Nothing is hand-maintained
that could be machine-generated. This page tells you how to reproduce all of it,
so you can verify these findings or refresh them for a newer build.

## Before you start: the API binds IPv6 loopback only

This costs people hours, so it goes first.

The Nucleares webserver listens on `[::1]:8785`. It does **not** listen on
`127.0.0.1`. A health check written against the literal IPv4 loopback gets
connection-refused while the server is up and serving perfectly.

```bash
# Positive control. Inspects the kernel listener table directly.
ss -lntp | grep 8785
# expected: LISTEN 0 500 [::1]:8785 [::]:*
```

Use the hostname `localhost` in every request and let the resolver pick IPv6.
Do not hardcode `127.0.0.1`.

Two related traps:

- A reachability probe over `127.0.0.1` shares the broken component with the
  thing it is testing, so it cannot detect its own fault. It will report "port
  never bound" indefinitely. `ss` is the check that actually works.
- Some HTTP clients resolve `localhost` to IPv4 first and give up. Python's
  `urllib` did exactly this during the writing of this repository and produced a
  completely wrong result set, because the script counted connection errors as
  successful reads. If you write a probe, give it three outcome buckets
  (readable, not-readable, **error**) and never let the error bucket collapse
  into either of the other two.

The webserver also **unbinds when you load a save**, and appears to need
re-enabling per save. If requests suddenly fail, check `ss` before debugging
your client.

## Enable the webserver

Turn on the web server in the game's in-game settings. Confirm with the `ss`
command above before doing anything else.

## 1. The manifest: what is readable and what is writable

This is the single most valuable call in the API. The game publishes its own
variable lists.

```bash
curl -s "http://localhost:8785/?Variable=WEBSERVER_LIST_VARIABLES_JSON" \
  | python3 -m json.tool > data/manifest.json

python3 -c "
import json; d=json.load(open('data/manifest.json'))
print('GET:', len(d['GET']), 'POST:', len(d['POST']))"
# GET: 332 POST: 91
```

No probing, no guessing, no brute-forcing name candidates. If you are
maintaining a Nucleares client, call this once at startup and you will never
need a hardcoded variable list again.

Caveat worth stating plainly: the manifest gives you **names only**. It does not
give payload types, accepted enum values, or the valve identifier indirection.
Those need the sources in [Credit](../README.md#credit) plus live testing.

## 2. Game version, so your capture is attributable

```bash
curl -s "http://localhost:8785/?Variable=GAME_VERSION"
# V 2.2.25.220
```

Always record this next to a capture. A variable map without a build stamp is
not verifiable later.

## 3. The valve panel: 55 valve identifiers

The valve identifiers do not appear in the manifest at all. They live only as
keys inside this structure.

```bash
curl -s "http://localhost:8785/?Variable=VALVE_PANEL_JSON" \
  | python3 -m json.tool > data/valve_panel.json

python3 -c "
import json; d=json.load(open('data/valve_panel.json'))
print('top-level keys:', list(d))
print('valves:', len(d['valves']))"
# top-level keys: ['valves', 'pumps', 'pipes', 'vessels']
# valves: 55
```

See [valves.md](valves.md) for why those identifiers matter and how to use them.

## 4. Which writable variables are also readable

The manifest already answers this by set membership, but it is worth verifying
against the live server, because agreement between the two is itself a finding
(they agree exactly, 91 out of 91, at build V 2.2.25.220).

```bash
# GET-probe every POST name. Read-only, safe to run, changes nothing.
python3 -c "
import json; print('\n'.join(sorted(json.load(open('data/manifest.json'))['POST'])))" \
| while read -r n; do
    body=$(curl -s --max-time 5 -w '\n%{http_code}' "http://localhost:8785/?Variable=$n")
    code=$(printf '%s' "$body" | tail -1)
    val=$(printf '%s' "$body" | sed '$d')
    if [ -z "$code" ] || [ "$code" = "000" ]; then cls=ERROR
    elif printf '%s' "$val" | grep -qF 'does not exist'; then cls=WRITE_ONLY
    else cls=READABLE; fi
    printf '%s\t%s\t%s\n' "$n" "$cls" "$val"
  done > data/get_probe.tsv

cut -f2 data/get_probe.tsv | sort | uniq -c
# 35 READABLE
# 56 WRITE_ONLY
```

Note the explicit `ERROR` bucket. That is not defensive padding. Without it,
this exact script reports "91 readable, 0 write-only", which is the opposite of
the truth.

This sweep is safe because it only issues GETs. **Do not** write the equivalent
sweep with POSTs. See [fun-family.md](fun-family.md).

## 5. Reading many variables in one call

Every community client polls one variable per request. There is a batch
endpoint, and it returns 321 variables in a single call:

```bash
curl -s "http://localhost:8785/?Variable=WEBSERVER_BATCH_GET"
```

Be aware that batch and single-GET **disagree on types** for the same variable.
`CORE_STATE` returns the Spanish string `REACTIVO` from a single GET and the
integer `1` from the batch endpoint. Normalise at the boundary. See
[wire-format.md](wire-format.md).

## 6. Writing, if you must

```bash
# The empty body is mandatory. Without it you get HTTP 411, not a 400.
curl -s -X POST --data "" \
  "http://localhost:8785/?Variable=CONDENSER_VACUUM_PUMP_START_STOP&value=START"

# Then read back. Always. The status code tells you nothing.
curl -s "http://localhost:8785/?Variable=CONDENSER_VACUUM_PUMP_ACTIVE"
```

For 56 of the 91 writable variables the read-back uses a **different name** than
the one you wrote. The mapping is the Read-back column in
[writable-variables.md](writable-variables.md).

## 7. Measuring an effect honestly

If you are testing what a write actually does, diffing a snapshot before against
a snapshot after will attribute background drift to your command. This plant is
never at rest: pressure falls roughly 0.2 bar every 5 to 10 seconds with no
command issued at all.

Use a **matched null probe**. For each real probe, run an identical probe with
the same snapshot logic and the same settle window but no POST, and subtract.
A variable counts as an effect only if it moved during the POST window and did
not move during its matched null.

That method has a known failure mode, disclosed here because it bit us: if the
signal's period is comparable to your settle window, aliasing puts drift on both
sides and the subtraction does not clear it. Three pressure variables survived a
matched null and were still pure drift. Fix it with multiple null samples per
probe, or a settle window that is a large multiple of the underlying step
period.

Two more sampling rules learned the hard way:

- **Do not sample immediately after a save load.** Post-reload
  `CORE_STATE_CRITICALITY` read 5, the historical excursion threshold. Settled
  readings 30 seconds later were 0.64 and falling.
- **Check your sample rate against the signal.** A 1 Hz sample of a roughly 2
  second sawtooth produced a confident, meaningless rate figure.

## Reproducing the docs in this repo

`docs/writable-variables.md` is generated from `data/manifest.json` plus the
GET-probe TSV, with assertions that all 91 names are grouped and all 91 have a
semantics entry. If a future build adds a variable, the generator fails loudly
rather than silently omitting it.
