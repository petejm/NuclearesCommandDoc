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

That first line is a **quantified threshold**, and it resolves a class of
"where is my water going" mysteries. A vessel below 70% integrity bleeds
continuously, with no valve open and no command issued. Any mass-balance
accounting that does not include an integrity term will fail to close, and the
missing volume will look like an instrumentation fault when it is a modelled
leak.

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
