# NuclearesCommandDoc

A complete map of the writable web API in [Nucleares](https://store.steampowered.com/app/1585670/Nucleares/).

Verified against game build **V 2.2.25.220**.

The game's official documentation repository ships a `settable.md` that is 0 bytes.
This repository fills that gap: all 91 writable variables, their payload types,
their accepted values where known, and an explicit honesty marker on everything
that is not known.

## The headline: the game publishes its own manifest

You do not need to probe for writable variables. Ask the game:

```
GET http://localhost:8785/?Variable=WEBSERVER_LIST_VARIABLES_JSON
→ {"GET":[...332 names...],"POST":[...91 names...]}
```

One call returns ground truth for *what* is writable. A verbatim capture is in
[`data/manifest.json`](data/manifest.json).

That call does **not** tell you accepted values, payload types, or the valve
addressing indirection. Those required cross-referencing seven community client
codebases plus live testing against a running game. That is what the rest of
this repository is.

## Contents

| Document | Covers |
|---|---|
| [docs/writable-variables.md](docs/writable-variables.md) | All 91 POST variables, grouped by subsystem, with payloads, read-back twins and evidence |
| [docs/valves.md](docs/valves.md) | The valve meta-command indirection, plus all 55 valve identifiers |
| [docs/wire-format.md](docs/wire-format.md) | Protocol gotchas: HTTP 411, the five meanings of HTTP 200, enum casing, locale hazards |
| [docs/emergency-controls.md](docs/emergency-controls.md) | Live test results for 10 emergency variables no client had ever written |
| [docs/fun-family.md](docs/fun-family.md) | The 15 `FUN_*` incident triggers, and why they need a hard blocklist |
| [docs/unexplored.md](docs/unexplored.md) | What is read-only, what no client touches, and where the frontier is |
| [docs/diagnostics-endpoint.md](docs/diagnostics-endpoint.md) | `AO_AGENT_DIAGNOSTICS_JSON`, a 10 KB pre-computed plant model no client reads |
| [docs/value-semantics.md](docs/value-semantics.md) | What the API does with what you send: no range validation, slewing actuators, `null`, type errors |
| [docs/operations.md](docs/operations.md) | Startup and shutdown procedures, setpoints, and the thermal balance ratios |
| [docs/plant-mechanics.md](docs/plant-mechanics.md) | Simulation behaviours that make telemetry easy to misread: wear vs integrity, pressurizer level, uninstalled equipment |
| [docs/scraping.md](docs/scraping.md) | **How to regenerate every table here yourself**, and the traps that make it hard |

Raw captures live in [`data/`](data/). Working tools are in [`tools/`](tools/): a
write-probe harness implementing the measurement method, and a live tracker for
the in-game startup checklist.

## Five findings worth reading even if you skip the rest

**1. Valves are not addressed by name.** There are exactly three valve POST
endpoints (`VALVE_OPEN`, `VALVE_CLOSE`, `VALVE_OFF`) and the *value* you post is
the target valve's identifier, for example `VALVE_OPEN` with body
`value=VALVULA_ENTRADA_NUCLEO_01`. Those 55 identifiers are Spanish-language
engineering names, they live only as keys inside `VALVE_PANEL_JSON`, and they
never appear as top level `?Variable=` names. Probing for them as variable names
finds nothing. Details in [docs/valves.md](docs/valves.md).

**2. HTTP 200 certifies nothing.** It has five distinct meanings on this API,
none distinguishable from the status line. Read back after every write. Details
in [docs/wire-format.md](docs/wire-format.md).

**3. 56 of the 91 writable variables cannot be read back by name.** A GET on
those exact names returns `The readable variable 'X' does not exist.` The
read-back lives under a *different* name: you write `MSCV_0_OPENING_ORDERED` and
read `MSCV_0_OPENING_ACTUAL`. Combined with finding 2, this is the defining
constraint on writing a correct client, and the full mapping is the Read-back
column in [docs/writable-variables.md](docs/writable-variables.md). Verified by
GET-probing all 91 names individually: 35 readable, 56 write-only, zero
disagreement with the manifest.

**4. One unread endpoint returns the whole plant, already interpreted.**
`AO_AGENT_DIAGNOSTICS_JSON` gives roughly 10 KB of derived state in a single
call: evaluated safety booleans, the game's own causal rules for pressure loss
(including the quantified "below 70% integrity bleeds continuously"), and
per-component damage logs naming *why* each item was damaged. It works with the
AO DLC uninstalled. Details in
[docs/diagnostics-endpoint.md](docs/diagnostics-endpoint.md).

**5. There are two working trip paths and no working reset.**
`CORE_SCRAM_BUTTON` and `CORE_EMERGENCY_STOP` both scram the reactor.
`CORE_END_EMERGENCY_STOP` returns HTTP 200 and does nothing. Anything automating
this plant gets a reliable abort with no programmatic recovery, so a scram has
to be treated as terminal and handed back to a human. Details in
[docs/emergency-controls.md](docs/emergency-controls.md).

## How claims are marked

Every claim in this repository carries an evidence tag. The point is that you
can tell measurement from inference at a glance, and nothing is asserted more
strongly than the evidence supports.

| Tag | Meaning |
|---|---|
| `live-manifest` | Pulled from the game's own `WEBSERVER_LIST_VARIABLES_JSON` endpoint against a running game |
| `live-probe` | Verified by direct request against a running game, with read-back |
| `repo:file:line` | Cited from a community client's source, at that exact location |
| `inferred` | Reasoned from adjacent facts, not directly evidenced. Explicitly flagged, never asserted as fact |

Where community client evidence conflicts with the manifest, **the manifest
wins**, and the conflict is documented rather than silently resolved.

Findings that came back ambiguous are published as ambiguous. See the
"Unattributed" section of
[docs/emergency-controls.md](docs/emergency-controls.md) and the method
limitation disclosed in the same document.

## Safety

Read [docs/fun-family.md](docs/fun-family.md) before writing anything.

The 15 `FUN_*` variables are trigger writes: the act of writing *is* the action.
That makes the usual "write the current value back" no-op safety pattern invalid
for them, because there is no current value to restore. Do not include them in a
generic writability sweep.

## Credit

The manifest endpoint gives names. It does not give semantics. Those came from
reading the source of seven community clients, and this map would not exist
without them:

- [wisq/auto_nuke](https://github.com/wisq/auto_nuke), which is where the valve
  indirection was finally cracked, and by a distance the richest source here
- [mct_nuke](https://github.com/mct/mct_nuke)
- [nuclearesOA](https://github.com/nuclearesOA)
- [LibNuclearesWeb](https://github.com/LibNuclearesWeb)
- [GHXX/NuclearesController](https://github.com/GHXX/NuclearesController)
- [nathanctech/Nucleares-Controller](https://github.com/nathanctech/Nucleares-Controller)
- [BurtBR](https://github.com/BurtBR)

Upstream documentation project:
[DaRealCodeWritten/NuclearesWSDoc](https://github.com/DaRealCodeWritten/NuclearesWSDoc).
This repository is complementary, not a fork, and is offered upstream freely.

## Contributing

Corrections are very welcome, particularly live test results for anything marked
`manifest-only` or `inferred`. See [CONTRIBUTING.md](CONTRIBUTING.md) for the
evidence standard.

## License

[CC BY 4.0](LICENSE). Use it, fork it, merge it upstream. Attribution keeps the
provenance of the measurements traceable.
