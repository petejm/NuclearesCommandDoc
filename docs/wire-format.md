# Wire format and protocol gotchas

The Nucleares API does not use conventional HTTP semantics. Almost every failure
mode here is a silent one. Read this before writing a client.

## The API binds IPv6 loopback only

`[::1]:8785`. Not `127.0.0.1`. Full detail and the diagnostic command are in
[scraping.md](scraping.md). It is listed again here because it is the single
most common way to lose an hour.

## HTTP 200 has five meanings

This is the central hazard. None of these are distinguishable from the status
line, and four of the five look like success.

| Meaning | Example | How you can tell |
|---|---|---|
| Accepted and worked | `CORE_SCRAM_BUTTON` <- `true` | Rods moved 93 to 100, `CORE_STATE` flipped, temperature trajectory reversed |
| Accepted, value silently discarded | `EMERGENCY_BATTERIES_MODE` <- `MANUAL` | Reads back `1`, not `MANUAL`. Invalid enum thrown away without complaint |
| Accepted, genuinely does nothing | `CORE_END_EMERGENCY_STOP` <- `true` | Rods stayed 100, `CORE_STATE` stayed `NOREACTIVO`, no state moved anywhere |
| Wrote to a name that does not exist | bogus valve identifier posted to `VALVE_OPEN` | Nothing moves. The API does not reject unknown targets |
| Read of a nonexistent variable | `GET ?Variable=NOPE` | HTTP **200** with body `The readable variable 'NOPE' does not exist.` |

Plus a sixth status that at least uses a distinct code:

| Meaning | Example | Signal |
|---|---|---|
| Writable but gated | any `FUN_*` member | HTTP **412** |

**Read-back is the only source of truth.** A 200 certifies nothing about
effect, value acceptance, or target existence.

Note the fifth row especially: a failed *read* is a 200 with an error sentence
in the body, not a 404. If your client checks `resp.ok` and parses the body as a
value, it will happily ingest the string `The readable variable 'X' does not
exist.` as data.

## A write needs an explicit empty body

Omitting `Content-Length` produces **HTTP 411**, not a 400 or a helpful message.
Send an explicit empty body even for trigger writes that have no real payload.

```bash
curl -s -X POST --data "" "http://localhost:8785/?Variable=...&value=..."
```

In Python: `data=b""`, not `data=None`.

## 56 of 91 writable variables cannot be read back by name

A GET on those exact names returns the does-not-exist sentence. This does not
mean the effect is unobservable, it means the read-back lives under a
**different name**: you write `MSCV_0_OPENING_ORDERED` and read
`MSCV_0_OPENING_ACTUAL`.

Combined with "200 certifies nothing", this is the defining constraint on
writing a correct client. The full mapping is the Read-back column in
[writable-variables.md](writable-variables.md).

The manifest's GET and POST lists genuinely differ in membership. POST is not a
subset of GET. Verified by probing all 91 individually against a running game:
35 readable, 56 write-only, zero disagreement with the manifest.

## Some GET-list members return empty strings

`RODS_POS_ORDERED` and `RODS_STATUS` are both in the 332-entry GET list and both
return an empty body, while `RODS_POS_ACTUAL` right next to them returns `68`.

So "in the GET list" does not imply "returns a value". Treat empty as a distinct
outcome from both a value and the does-not-exist sentence. Three-state parsing,
not two.

## The same variable has different types on different endpoints

`CORE_STATE` returns:

- `REACTIVO` / `NOREACTIVO` from a single `?Variable=CORE_STATE` GET
- `1` / `0` from `WEBSERVER_BATCH_GET`

Same underlying variable, endpoint-dependent representation. Any client reading
both endpoints has to normalise. This is not documented anywhere upstream and is
an easy source of silent type confusion.

## Spanish and English are mixed on the same variable

`CONDENSER_VACUUM_PUMP_MODE` **reads** back `OPERACIONAL` but you **write**
`OPERATIONAL`. The write vocabulary and the read vocabulary are different
languages for one variable.

Enum values generally are Spanish: `REACTIVO`, `NOREACTIVO`, `INACTIVO`,
`INICIANDO`, `GENERANDO`, `PRESURIZANDO`, `AUTOMATICO`. Valve identifiers are
Spanish. Variable names are English. Do not assume a language from context.

## Boolean casing is not standardised

There is no single canonical boolean form, and clients disagree:

| Form | Where |
|---|---|
| `True` / `False` | what auto_nuke **reads** (`auto_nuke:lib/auto_nuke/api.ex:40-41` pattern-matches exactly these) |
| `true` / `false` | what auto_nuke **writes**, via Elixir `to_string(true)` |
| `TRUE` / `FALSE` | nathanctech's literal pool |
| `1` / `0` | `FREIGHT_PUMP_CONDENSER_ACTIVE` posted as int (`nathanctech:Condenser.cs:56`) |

Live reads at build V 2.2.25.220 return title case (`True` / `False`). Since
writes are silently discarded on mismatch rather than rejected, a casing error
here is invisible until you read back.

## Locale hazard on float writes

`GHXX:Controllers/CondenserController.cs:18` formats outgoing floats with
`.ToString("N2")` and no explicit `CultureInfo`. Under a comma-decimal locale
that emits `12,34` instead of `12.34`.

**Status: unverified against the live game.** Flagged as a hazard to test, not
asserted as a defect. If you run a comma-decimal locale and write floats, test
this before trusting it.

## Timing rules

- **Do not sample immediately after a save load.** Post-reload
  `CORE_STATE_CRITICALITY` read 5, the historical excursion threshold. Settled
  values 30 seconds later were 0.64 and falling.
- **The webserver unbinds on save load** and appears to need re-enabling per
  save. Check `ss -lntp | grep 8785` before assuming your client broke.
- **Check your sample rate against the signal period.** A 1 Hz sample of a
  roughly 2 second sawtooth yields a confident and meaningless rate.
- **The plant is never at rest.** Pressure drifts about 0.2 bar every 5 to 10
  seconds with no command issued. Any before-and-after diff attributes that
  drift to whatever you happened to do. See the matched null probe method in
  [scraping.md](scraping.md).

## Batch reads

`WEBSERVER_BATCH_GET` returns 321 variables in one call. Every community client
surveyed polls one variable per request instead. If you are writing a client,
use the batch endpoint, subject to the type-difference caveat above.
