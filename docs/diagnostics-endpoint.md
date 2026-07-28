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
| `maintenance_summary` | 131 tracked elements, with per-item integrity, wear, and **`deterioration_logs` giving the reason each item was damaged** |

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

## Gotcha: uninstalled equipment still reports confident values

At capture time:

| Turbine | `_INSTALLED` | `_RPM` |
|---|---|---|
| 0 | False | 0 |
| 1 | False | 0 |
| 2 | **True** | 3050 |

while `POWER_FROM_TURBINE_KW` read 271.8, generated entirely by turbine 2.

**Check `_INSTALLED` before trusting any indexed equipment variable.** A client
reading turbine 0 on this plant sees a plausible, permanently-zero turbine that
does not exist. Any experiment targeting turbine 0 here measures nothing, which
is a good way to record a false negative.

The same applies to `maintenance_summary.attention_items`: it lists what is
actually installed, by real object name (`TG_2`, `GE_Generador03`,
`BC_2_REFRIGERANTE_CIRCULACION`), which is a more reliable equipment inventory
than probing indexed variable names.
