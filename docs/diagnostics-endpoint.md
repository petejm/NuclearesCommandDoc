# `AO_AGENT_DIAGNOSTICS_JSON`: the endpoint nobody was reading

The single most useful read on this API, and no surveyed community client
touches it.

```bash
curl -s "http://localhost:8785/?Variable=AO_AGENT_DIAGNOSTICS_JSON"
```

Roughly 10 KB of pre-computed plant diagnostics in one call. Not raw telemetry:
**derived state**, including causal explanations for equipment damage that are
not reconstructable from the individual variables.

## Structure

Seven top-level sections at build V 2.2.25.220:

| Section | Contents |
|---|---|
| `reactor_overview` | 15 fields. Temperatures, pressures, flow in/out, plus derived booleans `critical_mass_reached`, `steam_in_primary`, `dangerous_steam_in_primary` |
| `pressurizer_state` | 16 fields, including `is_pressure_operative` and `is_temperature_operative`, which are the deviation checks already evaluated for you |
| `pressure_loss_factors` | Why pressure is being lost right now, plus a `notes` array stating the game's own causal rules |
| `active_alarms` | Currently firing alarms |
| `situations` | Active scenario events |
| `pressure_trend` | Historical pressure entries |
| `maintenance_summary` | `element_count` varies per capture, 131 in the example below and 128 in a later capture cited further down this document, with per-item integrity, wear, and **`deterioration_logs` giving the reason each item was damaged** |

## Why it matters more than the batch endpoint

`WEBSERVER_BATCH_GET` returns 321 raw values. This returns *judgements*.

Fields like `is_pressure_operative`, `dangerous_steam_in_primary` and
`circulation_pumps_dry` are conclusions the simulation has already reached. A
monitor recomputing them from raw variables is reimplementing game logic it
cannot see, and will drift from it.

## The causal model is published

`pressure_loss_factors.notes` states the game's own rules verbatim:

```
Low integrity (<70%) causes continuous pressure bleed.
Open pressurizer relief valve causes large BAR losses each tick.
Unsafe fuel hatches open cause core pressure loss.
Heaters off allow natural cooling and pressure drop.
```

That first line is a **quantified threshold**: below 70% integrity a vessel
bleeds continuously, with no valve open and no command issued. Any mass-balance
accounting that omits an integrity term can fail to close for reasons that are
modelled, not instrumental.

**Read the threshold precisely.** A component at 90% integrity is damaged but is
*not* above this rule's trigger. Do not read "integrity below 100" as "leaking".
The game distinguishes **wear** (scheduled degradation, repairable on a
maintenance task) from **integrity** (damage). This note applies only to
integrity, and only under 70%.

## The staleness trap: `maintenance_summary` is a snapshot, not telemetry

**This section is the most likely thing in the whole payload to be misread.**

`maintenance_summary` is not live. It is the cached result of the in-game
Operational Assistant's preventive-maintenance walkaround, which the player has
to explicitly request. The assistant physically navigates the plant to produce
it. If no analysis has been run, there is no data.

The payload says so, in fields that are easy to skim past:

```json
"analysis_timestamp": "D: 3 | 18:58",
"age_minutes": 209,
"age_description": "hace 3 hora(s) de tiempo de simulación",
"element_count": 131,
"attention_count": 16
```

`age_minutes` **counts up between calls** (observed 209 then 222). Every
integrity, wear and deterioration figure under `attention_items` is as of
`analysis_timestamp`, not now.

A second, later capture makes the point harder to miss: `age_minutes` read
**1431**, roughly 23 game-hours stale. At that age, `maintenance_summary`
reported `element_count: 128`, `attention_count: 4`, with these four
elements flagged and their `wear_percent`:

```
CORE                          15.91
condenser circulation pump    13.79
resistor bank                 13.04
transformer                   19.29
```

**Always check `age_minutes` before quoting anything from `maintenance_summary`,
in every place this data is quoted, not just here.** A 23-hour-old wear
figure presented as current is a wrong answer with a confident number
attached.

Only two components expose live integrity as ordinary variables:

| Live variable | Everything else |
|---|---|
| `CORE_INTEGRITY` | snapshot only |
| `PRESSURIZER_INTEGRITY` | snapshot only |

So a storage-tank or turbine integrity figure read from this endpoint may be
hours of simulated time out of date, while the core and pressurizer figures can
be confirmed against a live GET. Always check `age_minutes` before quoting
anything from `attention_items`, and prefer the live variable where one exists.

`MAINTENANCE_REPORT_HTML` is a related GET-list member holding the rendered
report. Same provenance, same staleness caveat.

## Deterioration logs name the cause

Each damaged element carries a log of *why*:

```json
{
  "label": "PRESSURIZER (Pressurizer)",
  "integrity_percent": 90.51,
  "deterioration_logs": [
    {"reason": "ALTA_PRESION",     "title": "High pressure",     "amount": 1.0},
    {"reason": "ALTA_TEMPERATURA", "title": "High temperature",  "amount": 0.66}
  ]
}
```

Observed `reason` codes so far: `ALTA_PRESION`, `ALTA_TEMPERATURA`,
`ENERGIA_SIN_SALIDA` (electricity generated but not carried to transformers or
dissipated by resistor banks). Codes are Spanish, `title` and `detail` are
localised to the game language setting.

This is not derivable from the variable API. Nothing else tells you that a
pressurizer lost integrity to overpressure rather than overtemperature.

## Gotcha: it works with the AO DLC uninstalled

`AO_AGENT_STATUS` reports the auxiliary-operator agent itself:

```json
{"dlc_installed": false, "runtime_state": "NoInstalado",
 "llm_engine": "LLMUnity", "llm_reachable": false,
 "response_mode": "heuristic", "model_path": "AOAgent/model.gguf"}
```

The AO is a local LLM shipped as DLC. **The diagnostics endpoint is populated
regardless**, so you get the full structured plant model without owning the DLC.

Corollary for `RESET_AO`: with `runtime_state: NoInstalado` it has nothing to
reset. Posting it produced no change in `AO_AGENT_STATUS` and no change in
`POWER_FROM_EXTERNAL_KW`, against a matched null. The 60 kW delta recorded in an
earlier session was coincidence.

**This qualifies, rather than contradicts, the claim that the AO subsystem is
inert without the DLC** ([unexplored.md](unexplored.md) makes exactly that
claim about `RESET_AO`). Two things are true of the same payload at once:
`AO_AGENT_STATUS` reports `dlc_installed: false` and `runtime_state:
NoInstalado`, and in that same call `maintenance_summary` reports `available:
true`, `status: ready`, with real per-component data (see "The staleness
trap" above). The inert part is the conversational LLM agent specifically.
The maintenance journal, the causal deterioration logs, and the rest of the
structured plant model are a separate feature that runs whether or not the
DLC is installed. Do not read "AO subsystem is inert" as covering
`AO_AGENT_DIAGNOSTICS_JSON` as a whole. It does not.

## Gotcha: uninstalled equipment still reports confident values

At capture time:

| Turbine | `_INSTALLED` | `_RPM` |
|---|---|---|
| 0 | False | 0 |
| 1 | False | 0 |
| 2 | **True** | 3050 |

while `POWER_FROM_TURBINE_KW` read 271.8. That reading is not a measure of
turbine 2's output: the variable does not track generation at all, see
[value-semantics.md](value-semantics.md).

**Check `_INSTALLED` before trusting any indexed equipment variable.** A client
reading turbine 0 on this plant sees a plausible, permanently-zero turbine that
does not exist. Any experiment targeting turbine 0 here measures nothing, which
is a good way to record a false negative.

The same applies to `maintenance_summary.attention_items`: it lists what is
actually installed, by real object name (`TG_2`, `GE_Generador03`,
`BC_2_REFRIGERANTE_CIRCULACION`), which is a more reliable equipment inventory
than probing indexed variable names.

## Open contradiction, flagged and not resolved: `circulation_pumps_dry` versus the flat `_DRY_STATUS` variable

`pressure_loss_factors.circulation_pumps_dry` reports `running_dry: true` for
primary pump indices `0`, `1` **and** `2`. Pumps 0 and 1 do not exist on this
plant, only pump 2 is installed (see
[plant-mechanics.md](plant-mechanics.md), "Primary circulation rate is a
first-order input"), so those two entries are at best noise about equipment
that is not there.

Pump 2 is the one that matters, and it is where the two sources disagree.
Measured at the same moment: pump 2 was circulating at 25 percent, with
`coolant_flow_in` 50.0 and `coolant_flow_out` 50.0, both nonzero and equal.
Its own flat variable, `COOLANT_CORE_CIRCULATION_PUMP_2_DRY_STATUS`, read
`4`, which section 15 of [value-semantics.md](value-semantics.md) establishes
as "absent or disabled", not running dry. The structured diagnostic says this
pump is running dry. The flat telemetry says it is not, and is moving flow
in both directions at once.

**This is recorded as an open contradiction, not resolved either way.** The
two pumps that do not exist are easy to write off as the diagnostic
including uninstalled equipment, the same pattern documented elsewhere in
this file. The one pump that does exist is not so easy to write off, and
nothing in this session's data says which source is right. Do not pick a
side. If a future capture resolves this, whichever source turns out to be
correct, document the resolution here rather than quietly changing which
one gets cited.
