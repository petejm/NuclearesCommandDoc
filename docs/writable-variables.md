# The 91 writable variables

Complete. Every name below comes from the game's own manifest at build **V 2.2.25.220**,
and every one was individually GET-probed against a running game to establish whether
it is also readable. See [scraping.md](scraping.md) to regenerate all of this yourself.

Counts: **91 writable**, of which **35 are also readable under the same name** and
**56 are write-only**. Write-only means a GET on that exact name returns
`The readable variable 'X' does not exist.` It does not mean the effect is unobservable:
most write-only variables have a differently named read-back twin, listed in the Read-back column.

**This is the single most important structural fact for anyone writing a controller.**
Since [HTTP 200 certifies nothing](wire-format.md), you must read back after every write,
and for 56 of 91 variables you cannot read back the name you just wrote.

Column meanings are in the [evidence key](../README.md#how-claims-are-marked).
`R/W` = readable and writable under one name. `W-only` = write-only.

## Core: fuel bays (18)

| Variable | Access | Payload | Values | Status | Read-back | Evidence |
|---|---|---|---|---|---|---|
| `CORE_BAY_1_HATCH` | W-only | enum | `OPEN`, `CLOSE` | confirmed | `CORE_BAY_{n}_HATCH_OPEN` | `auto_nuke:lib/mix/tasks/refill/fuel_cells.ex:111-112` |
| `CORE_BAY_1_FUEL_LOADING` | W-only | enum | `LOAD`, `UNLOAD` | confirmed | `CORE_BAY_{n}_STATE` | `auto_nuke:lib/mix/tasks/startup.ex:357` |
| `CORE_BAY_2_HATCH` | W-only | enum | `OPEN`, `CLOSE` | confirmed | `CORE_BAY_{n}_HATCH_OPEN` | `auto_nuke:lib/mix/tasks/refill/fuel_cells.ex:111-112` |
| `CORE_BAY_2_FUEL_LOADING` | W-only | enum | `LOAD`, `UNLOAD` | confirmed | `CORE_BAY_{n}_STATE` | `auto_nuke:lib/mix/tasks/startup.ex:357` |
| `CORE_BAY_3_HATCH` | W-only | enum | `OPEN`, `CLOSE` | confirmed | `CORE_BAY_{n}_HATCH_OPEN` | `auto_nuke:lib/mix/tasks/refill/fuel_cells.ex:111-112` |
| `CORE_BAY_3_FUEL_LOADING` | W-only | enum | `LOAD`, `UNLOAD` | confirmed | `CORE_BAY_{n}_STATE` | `auto_nuke:lib/mix/tasks/startup.ex:357` |
| `CORE_BAY_4_HATCH` | W-only | enum | `OPEN`, `CLOSE` | confirmed | `CORE_BAY_{n}_HATCH_OPEN` | `auto_nuke:lib/mix/tasks/refill/fuel_cells.ex:111-112` |
| `CORE_BAY_4_FUEL_LOADING` | W-only | enum | `LOAD`, `UNLOAD` | confirmed | `CORE_BAY_{n}_STATE` | `auto_nuke:lib/mix/tasks/startup.ex:357` |
| `CORE_BAY_5_HATCH` | W-only | enum | `OPEN`, `CLOSE` | confirmed | `CORE_BAY_{n}_HATCH_OPEN` | `auto_nuke:lib/mix/tasks/refill/fuel_cells.ex:111-112` |
| `CORE_BAY_5_FUEL_LOADING` | W-only | enum | `LOAD`, `UNLOAD` | confirmed | `CORE_BAY_{n}_STATE` | `auto_nuke:lib/mix/tasks/startup.ex:357` |
| `CORE_BAY_6_HATCH` | W-only | enum | `OPEN`, `CLOSE` | confirmed | `CORE_BAY_{n}_HATCH_OPEN` | `auto_nuke:lib/mix/tasks/refill/fuel_cells.ex:111-112` |
| `CORE_BAY_6_FUEL_LOADING` | W-only | enum | `LOAD`, `UNLOAD` | confirmed | `CORE_BAY_{n}_STATE` | `auto_nuke:lib/mix/tasks/startup.ex:357` |
| `CORE_BAY_7_HATCH` | W-only | enum | `OPEN`, `CLOSE` | confirmed | `CORE_BAY_{n}_HATCH_OPEN` | `auto_nuke:lib/mix/tasks/refill/fuel_cells.ex:111-112` |
| `CORE_BAY_7_FUEL_LOADING` | W-only | enum | `LOAD`, `UNLOAD` | confirmed | `CORE_BAY_{n}_STATE` | `auto_nuke:lib/mix/tasks/startup.ex:357` |
| `CORE_BAY_8_HATCH` | W-only | enum | `OPEN`, `CLOSE` | confirmed | `CORE_BAY_{n}_HATCH_OPEN` | `auto_nuke:lib/mix/tasks/refill/fuel_cells.ex:111-112` |
| `CORE_BAY_8_FUEL_LOADING` | W-only | enum | `LOAD`, `UNLOAD` | confirmed | `CORE_BAY_{n}_STATE` | `auto_nuke:lib/mix/tasks/startup.ex:357` |
| `CORE_BAY_9_HATCH` | W-only | enum | `OPEN`, `CLOSE` | confirmed | `CORE_BAY_{n}_HATCH_OPEN` | `auto_nuke:lib/mix/tasks/refill/fuel_cells.ex:111-112` |
| `CORE_BAY_9_FUEL_LOADING` | W-only | enum | `LOAD`, `UNLOAD` | confirmed | `CORE_BAY_{n}_STATE` | `auto_nuke:lib/mix/tasks/startup.ex:357` |

## Control rods (10)

| Variable | Access | Payload | Values | Status | Read-back | Evidence |
|---|---|---|---|---|---|---|
| `RODS_ALL_POS_ORDERED` | W-only | numeric | 0-100 float percent. 100 = fully inserted (`live-probe`). Posting 100 is how every known client emulates a SCRAM | confirmed | `RODS_POS_ACTUAL` | `auto_nuke:shutdown.ex:404`; `GHXX:CoreController.cs:72`; `nathanctech:ControlRods.cs:84`; `BurtBR:mainwindow.cpp:187` |
| `ROD_BANK_POS_0_ORDERED` | R/W | numeric | range unconfirmed by any client that writes this exact name. Reads back a 0-100 value (`live-probe`), so 0-100 percent is the working assumption | confirmed (name); range `inferred` | `ROD_BANK_POS_{n}_ACTUAL` | `auto_nuke:lib/auto_nuke/operator/control_rods.ex:256` |
| `ROD_BANK_POS_1_ORDERED` | R/W | numeric | range unconfirmed by any client that writes this exact name. Reads back a 0-100 value (`live-probe`), so 0-100 percent is the working assumption | confirmed (name); range `inferred` | `ROD_BANK_POS_{n}_ACTUAL` | `auto_nuke:lib/auto_nuke/operator/control_rods.ex:256` |
| `ROD_BANK_POS_2_ORDERED` | R/W | numeric | range unconfirmed by any client that writes this exact name. Reads back a 0-100 value (`live-probe`), so 0-100 percent is the working assumption | confirmed (name); range `inferred` | `ROD_BANK_POS_{n}_ACTUAL` | `auto_nuke:lib/auto_nuke/operator/control_rods.ex:256` |
| `ROD_BANK_POS_3_ORDERED` | R/W | numeric | range unconfirmed by any client that writes this exact name. Reads back a 0-100 value (`live-probe`), so 0-100 percent is the working assumption | confirmed (name); range `inferred` | `ROD_BANK_POS_{n}_ACTUAL` | `auto_nuke:lib/auto_nuke/operator/control_rods.ex:256` |
| `ROD_BANK_POS_4_ORDERED` | R/W | numeric | range unconfirmed by any client that writes this exact name. Reads back a 0-100 value (`live-probe`), so 0-100 percent is the working assumption | confirmed (name); range `inferred` | `ROD_BANK_POS_{n}_ACTUAL` | `auto_nuke:lib/auto_nuke/operator/control_rods.ex:256` |
| `ROD_BANK_POS_5_ORDERED` | R/W | numeric | range unconfirmed by any client that writes this exact name. Reads back a 0-100 value (`live-probe`), so 0-100 percent is the working assumption | confirmed (name); range `inferred` | `ROD_BANK_POS_{n}_ACTUAL` | `auto_nuke:lib/auto_nuke/operator/control_rods.ex:256` |
| `ROD_BANK_POS_6_ORDERED` | R/W | numeric | range unconfirmed by any client that writes this exact name. Reads back a 0-100 value (`live-probe`), so 0-100 percent is the working assumption | confirmed (name); range `inferred` | `ROD_BANK_POS_{n}_ACTUAL` | `auto_nuke:lib/auto_nuke/operator/control_rods.ex:256` |
| `ROD_BANK_POS_7_ORDERED` | R/W | numeric | range unconfirmed by any client that writes this exact name. Reads back a 0-100 value (`live-probe`), so 0-100 percent is the working assumption | confirmed (name); range `inferred` | `ROD_BANK_POS_{n}_ACTUAL` | `auto_nuke:lib/auto_nuke/operator/control_rods.ex:256` |
| `ROD_BANK_POS_8_ORDERED` | R/W | numeric | range unconfirmed by any client that writes this exact name. Reads back a 0-100 value (`live-probe`), so 0-100 percent is the working assumption | confirmed (name); range `inferred` | `ROD_BANK_POS_{n}_ACTUAL` | `auto_nuke:lib/auto_nuke/operator/control_rods.ex:256` |

## Core mode (1)

| Variable | Access | Payload | Values | Status | Read-back | Evidence |
|---|---|---|---|---|---|---|
| `CORE_OPERATION_MODE` | R/W | enum | `SHUTDOWN`, `NOMINAL` (write). GHXX reads `SHUTDOWN`/`MAXIMUM` from the same variable, so the non-shutdown spelling is disputed | confirmed, enum disputed | *self* | `auto_nuke:shutdown.ex:110-111`, `startup.ex:346-347`; conflict: `GHXX:CoreController.cs:31` |

## Emergency and trip (10)

| Variable | Access | Payload | Values | Status | Read-back | Evidence |
|---|---|---|---|---|---|---|
| `CORE_SCRAM_BUTTON` | W-only | any | `true` accepted. Payload appears irrelevant, the write is the trigger | **confirmed live** | `CORE_STATE`, `RODS_POS_ACTUAL` | `live-probe` 2026-07-27 |
| `CORE_EMERGENCY_STOP` | W-only | any | `true` accepted | **confirmed live** | `CORE_STATE`, `RODS_POS_ACTUAL` | `live-probe` 2026-07-27 |
| `CORE_END_EMERGENCY_STOP` | W-only | any | `true` accepted and **does nothing** | **confirmed live: no effect** | none, no state moves | `live-probe` 2026-07-27 |
| `STEAM_TURBINE_TRIP` | W-only | any | `true` accepted | **unattributed**, effect not separable from concurrent operator action | `STEAM_TURBINE_{n}_RPM` | `live-probe` 2026-07-27 |
| `RESET_AO` | W-only | any | `true` accepted | **unattributed**, single weak observation | `POWER_FROM_EXTERNAL_KW` (weak) | `live-probe` 2026-07-27 |
| `EMERGENCY_GENERATOR_1_MODE` | R/W | enum | `MANUAL`, `AUTOMATICO` | **confirmed live** (gen 1) | *self* | `live-probe` 2026-07-27; `mct_nuke:data.ex:1480,1527` |
| `EMERGENCY_GENERATOR_1_START_STOP` | W-only | enum | `START` confirmed working | **confirmed live** | `EMERGENCY_GENERATOR_1_STATUS` | `live-probe` 2026-07-27 |
| `EMERGENCY_GENERATOR_2_MODE` | R/W | enum | `MANUAL`, `AUTOMATICO` | **confirmed live** (gen 1) | *self* | `live-probe` 2026-07-27; `mct_nuke:data.ex:1480,1527` |
| `EMERGENCY_GENERATOR_2_START_STOP` | W-only | enum | `START` accepted, **no effect**. Asymmetry with generator 1 unexplained | **confirmed live: no effect** | `EMERGENCY_GENERATOR_2_STATUS` | `live-probe` 2026-07-27 |
| `EMERGENCY_BATTERIES_MODE` | R/W | enum | **unknown vocabulary**. Rejected `MANUAL`, reads back `1`. Observed read values `1`=Auto, `2`=Charge, `3`=Discharge | **value set unresolved** | *self* | `live-probe` 2026-07-27; reads: `mct_nuke:data.ex:1587` |

## Pumps (15)

| Variable | Access | Payload | Values | Status | Read-back | Evidence |
|---|---|---|---|---|---|---|
| `COOLANT_CORE_CIRCULATION_PUMP_0_ORDERED_SPEED` | R/W | numeric | 0-100 int percent | confirmed | *self* | `auto_nuke:lib/auto_nuke/api/pumps.ex:23-24`; `nathanctech:Coolant.cs:145,243` |
| `COOLANT_CORE_CIRCULATION_PUMP_1_ORDERED_SPEED` | R/W | numeric | 0-100 int percent | confirmed | *self* | `auto_nuke:lib/auto_nuke/api/pumps.ex:23-24`; `nathanctech:Coolant.cs:145,243` |
| `COOLANT_CORE_CIRCULATION_PUMP_2_ORDERED_SPEED` | R/W | numeric | 0-100 int percent | confirmed | *self* | `auto_nuke:lib/auto_nuke/api/pumps.ex:23-24`; `nathanctech:Coolant.cs:145,243` |
| `COOLANT_SEC_CIRCULATION_PUMP_0_ORDERED_SPEED` | R/W | numeric | 0-100 int percent | confirmed | *self* | `auto_nuke:pumps.ex:36-37`; `nathanctech:Coolant.cs:185,230` |
| `COOLANT_SEC_CIRCULATION_PUMP_1_ORDERED_SPEED` | R/W | numeric | 0-100 int percent | confirmed | *self* | `auto_nuke:pumps.ex:36-37`; `nathanctech:Coolant.cs:185,230` |
| `COOLANT_SEC_CIRCULATION_PUMP_2_ORDERED_SPEED` | R/W | numeric | 0-100 int percent | confirmed | *self* | `auto_nuke:pumps.ex:36-37`; `nathanctech:Coolant.cs:185,230` |
| `CONDENSER_CIRCULATION_PUMP_ORDERED_SPEED` | R/W | numeric | 0-100 int percent | confirmed | *self* | `auto_nuke:pumps.ex:50-51`; `nathanctech:Condenser.cs:28,51` |
| `CONDENSER_CIRCULATION_PUMP_SWITCH` | R/W | boolean | `True`/`False` | confirmed | *self* | `auto_nuke:pumps.ex:52` |
| `FREIGHT_PUMP_CONDENSER_SWITCH` | R/W | boolean | `True`/`False` (auto_nuke) vs `true`/`false` (GHXX). Case is not standardised, see wire-format | confirmed | self, plus `FREIGHT_PUMP_CONDENSER_ACTIVE` | `auto_nuke:pumps.ex:60`; `GHXX:CondenserController.cs:23` |
| `FREIGHT_PUMP_INTERNAL_SWITCH` | R/W | boolean | `True`/`False` | confirmed | *self* | `auto_nuke:pumps.ex:76` |
| `FREIGHT_PUMP_EXTERNAL_SWITCH` | R/W | boolean | `True`/`False` | confirmed | *self* | `auto_nuke:pumps.ex:68` |
| `FREIGHT_PUMP_FEEDWATER_SWITCH` | R/W | boolean | `True`/`False` | confirmed | *self* | `auto_nuke:pumps.ex:84` |
| `CORE_POOL_PUMP` | R/W | enum | `REMOVE`, `OFF`, `LOAD`. Wire value is the string; reads back as int 1/2/3 | confirmed | self (int) | `auto_nuke:lib/mix/tasks/refill/core_pool.ex:127,133` |
| `CONDENSER_VACUUM_PUMP_START_STOP` | W-only | enum | `START`, `STOP` | confirmed | `CONDENSER_VACUUM_PUMP_ACTIVE` | `auto_nuke:lib/auto_nuke/api/vacuum_pump.ex:4-6` |
| `CONDENSER_VACUUM_PUMP_MODE` | R/W | enum | `STARTUP`, `OPERATIONAL`. **Write English, read Spanish**: reads back `OPERACIONAL` | confirmed | self (Spanish) | `auto_nuke:vacuum_pump.ex:11-27`; `live-probe` |

## Valves: meta-command triad (3)

| Variable | Access | Payload | Values | Status | Read-back | Evidence |
|---|---|---|---|---|---|---|
| `VALVE_OPEN` | W-only | valve identifier string | One of the 55 `VALVE_PANEL_JSON` keys. **The value is the target, not a setting.** See valves.md | confirmed | `VALVE_PANEL_JSON` | `auto_nuke:lib/auto_nuke/api/valves.ex:322,345-347` |
| `VALVE_CLOSE` | W-only | valve identifier string | One of the 55 `VALVE_PANEL_JSON` keys. **The value is the target, not a setting.** See valves.md | confirmed | `VALVE_PANEL_JSON` | `auto_nuke:lib/auto_nuke/api/valves.ex:322,345-347` |
| `VALVE_OFF` | W-only | valve identifier string | One of the 55 `VALVE_PANEL_JSON` keys. **The value is the target, not a setting.** See valves.md | confirmed | `VALVE_PANEL_JSON` | `auto_nuke:lib/auto_nuke/api/valves.ex:322,345-347` |

## Steam path (12)

| Variable | Access | Payload | Values | Status | Read-back | Evidence |
|---|---|---|---|---|---|---|
| `MSCV_0_OPENING_ORDERED` | W-only | numeric | valve position | confirmed | `MSCV_{n}_OPENING_ACTUAL` | `auto_nuke:valves.ex:40`; `BurtBR:mainwindow.cpp:277` |
| `MSCV_1_OPENING_ORDERED` | W-only | numeric | valve position | confirmed | `MSCV_{n}_OPENING_ACTUAL` | `auto_nuke:valves.ex:40`; `BurtBR:mainwindow.cpp:277` |
| `MSCV_2_OPENING_ORDERED` | W-only | numeric | valve position | confirmed | `MSCV_{n}_OPENING_ACTUAL` | `auto_nuke:valves.ex:40`; `BurtBR:mainwindow.cpp:277` |
| `STEAM_TURBINE_0_BYPASS_ORDERED` | W-only | numeric | range unconfirmed | confirmed (name only) | `STEAM_TURBINE_{n}_BYPASS_ACTUAL` | `auto_nuke:valves.ex:48` |
| `STEAM_TURBINE_1_BYPASS_ORDERED` | W-only | numeric | range unconfirmed | confirmed (name only) | `STEAM_TURBINE_{n}_BYPASS_ACTUAL` | `auto_nuke:valves.ex:48` |
| `STEAM_TURBINE_2_BYPASS_ORDERED` | W-only | numeric | range unconfirmed | confirmed (name only) | `STEAM_TURBINE_{n}_BYPASS_ACTUAL` | `auto_nuke:valves.ex:48` |
| `STEAM_GEN_0_VENT_SWITCH` | R/W | boolean | `True`/`False` | confirmed | *self* | `auto_nuke:lib/auto_nuke/api/steam_gen.ex:35,38` |
| `STEAM_GEN_1_VENT_SWITCH` | R/W | boolean | `True`/`False` | confirmed | *self* | `auto_nuke:lib/auto_nuke/api/steam_gen.ex:35,38` |
| `STEAM_GEN_2_VENT_SWITCH` | R/W | boolean | `True`/`False` | confirmed | *self* | `auto_nuke:lib/auto_nuke/api/steam_gen.ex:35,38` |
| `STEAM_EJECTOR_STARTUP_MOTIVE_VALVE` | W-only | numeric | range unconfirmed | confirmed (name only) | `..._ACTUAL` / `..._ORDERED` | `auto_nuke:valves.ex:65` |
| `STEAM_EJECTOR_OPERATIONAL_MOTIVE_VALVE` | W-only | numeric | 0-100 float. GHXX formats with `.ToString("N2")` and no `CultureInfo`, a decimal-comma hazard under comma locales | confirmed | `..._ACTUAL` / `..._ORDERED` | `auto_nuke:valves.ex:74`; `GHXX:CondenserController.cs:18` |
| `STEAM_EJECTOR_CONDENSER_RETURN_VALVE` | W-only | numeric | range unconfirmed | confirmed (name only) | `..._ACTUAL` / `..._ORDERED` | `auto_nuke:valves.ex:83` |

## Chemical treatment (2)

| Variable | Access | Payload | Values | Status | Read-back | Evidence |
|---|---|---|---|---|---|---|
| `CHEM_BORON_DOSAGE_ORDERED_RATE` | W-only | numeric | range unconfirmed | confirmed (name only) | `CHEM_BORON_DOSAGE_ACTUAL` | `auto_nuke:pumps.ex:105` |
| `CHEM_BORON_FILTER_ORDERED_SPEED` | W-only | numeric | range unconfirmed | confirmed (name only) | `CHEM_BORON_FILTER_ACTUAL` | `auto_nuke:pumps.ex:114` |

## Electrical (5)

| Variable | Access | Payload | Values | Status | Read-back | Evidence |
|---|---|---|---|---|---|---|
| `RESISTOR_BANK_01_SWITCH` | R/W | boolean | `True`/`False` | confirmed | *self* | `auto_nuke:shutdown.ex:363-364` |
| `RESISTOR_BANK_02_SWITCH` | R/W | boolean | `True`/`False` | confirmed | *self* | `auto_nuke:shutdown.ex:363-364` |
| `RESISTOR_BANK_03_SWITCH` | R/W | boolean | `True`/`False` | confirmed | *self* | `auto_nuke:shutdown.ex:363-364` |
| `RESISTOR_BANK_04_SWITCH` | R/W | boolean | `True`/`False` | confirmed | *self* | `auto_nuke:shutdown.ex:363-364` |
| `RESISTOR_BANKS_MAIN_SWITCH` | R/W | boolean | `True`/`False` | confirmed | *self* | `auto_nuke:shutdown.ex:354-355`, `startup.ex:309-310` |

## FUN family (see fun-family.md before touching) (15)

| Variable | Access | Payload | Values | Status | Read-back | Evidence |
|---|---|---|---|---|---|---|
| `FUN_AO_SABOTAGE_ONCE` | W-only | trigger | none, the write is the action | confirmed | *none* | `nathanctech:Settables/Fun.cs` |
| `FUN_AO_SABOTAGE_TIME` | W-only | numeric | int hours | confirmed | *none* | `nathanctech:Fun.cs:51` |
| `FUN_BANK_ROBBERY` | W-only | trigger | none, the write is the action | confirmed | *none* | `nathanctech:Settables/Fun.cs` |
| `FUN_BREAKER_TRIP` | W-only | trigger | none, the write is the action | confirmed | *none* | `nathanctech:Settables/Fun.cs` |
| `FUN_DECREASE_INTEGRITY` | W-only | trigger | none | **manifest-only** (clients post a misspelled variant) | *none* | manifest wins; typo `FUN_DECERASE_INTEGRITY` at `nathanctech:Fun.cs:15,35` |
| `FUN_FIRE_DRILL` | W-only | unknown | none | **manifest-only** | *none* | no harvest mention |
| `FUN_IODINE_SPILL` | W-only | trigger | none, the write is the action | confirmed | *none* | `nathanctech:Settables/Fun.cs` |
| `FUN_OIL_SPILL` | W-only | trigger | none, the write is the action | confirmed | *none* | `nathanctech:Settables/Fun.cs` |
| `FUN_PUMP_JAM` | W-only | trigger | none, the write is the action | confirmed | *none* | `nathanctech:Settables/Fun.cs` |
| `FUN_REQUEST_ENABLE` | W-only | trigger | payload irrelevant. Gates the rest of the family | confirmed | `FUN_IS_ENABLED` | `nathanctech:Settables/Fun.cs:31` |
| `FUN_SHOW_MESSAGE` | W-only | string | free text | confirmed | *none* | `nathanctech:Fun.cs:79` |
| `FUN_TOGGLE_RANDOM_SWITCH` | W-only | trigger | none, the write is the action | confirmed | *none* | `nathanctech:Settables/Fun.cs` |
| `FUN_TRIGGER_AUDIT` | W-only | trigger | none, the write is the action | confirmed | *none* | `nathanctech:Settables/Fun.cs` |
| `FUN_WEATHER_CONTROL` | W-only | unknown | none | **manifest-only** | *none* | no harvest mention |
| `FUN_XENON_SPILL` | W-only | trigger | none, the write is the action | confirmed | *none* | `nathanctech:Settables/Fun.cs` |

## Live values at capture time

The 35 read/write variables, as read from the running plant when this document was generated.
Included so the value *shapes* are visible (int vs float vs Spanish enum vs `True`/`False`).

| Variable | Value read |
|---|---|
| `CONDENSER_CIRCULATION_PUMP_ORDERED_SPEED` | `70` |
| `CONDENSER_CIRCULATION_PUMP_SWITCH` | `True` |
| `CONDENSER_VACUUM_PUMP_MODE` | `OPERACIONAL` |
| `COOLANT_CORE_CIRCULATION_PUMP_0_ORDERED_SPEED` | `0` |
| `COOLANT_CORE_CIRCULATION_PUMP_1_ORDERED_SPEED` | `0` |
| `COOLANT_CORE_CIRCULATION_PUMP_2_ORDERED_SPEED` | `75` |
| `COOLANT_SEC_CIRCULATION_PUMP_0_ORDERED_SPEED` | `0` |
| `COOLANT_SEC_CIRCULATION_PUMP_1_ORDERED_SPEED` | `0` |
| `COOLANT_SEC_CIRCULATION_PUMP_2_ORDERED_SPEED` | `30` |
| `CORE_OPERATION_MODE` | `NOMINAL` |
| `CORE_POOL_PUMP` | `2` |
| `EMERGENCY_BATTERIES_MODE` | `1` |
| `EMERGENCY_GENERATOR_1_MODE` | `AUTOMATICO` |
| `EMERGENCY_GENERATOR_2_MODE` | `MANUAL` |
| `FREIGHT_PUMP_CONDENSER_SWITCH` | `False` |
| `FREIGHT_PUMP_EXTERNAL_SWITCH` | `False` |
| `FREIGHT_PUMP_FEEDWATER_SWITCH` | `False` |
| `FREIGHT_PUMP_INTERNAL_SWITCH` | `False` |
| `RESISTOR_BANKS_MAIN_SWITCH` | `True` |
| `RESISTOR_BANK_01_SWITCH` | `True` |
| `RESISTOR_BANK_02_SWITCH` | `False` |
| `RESISTOR_BANK_03_SWITCH` | `False` |
| `RESISTOR_BANK_04_SWITCH` | `False` |
| `ROD_BANK_POS_0_ORDERED` | `68` |
| `ROD_BANK_POS_1_ORDERED` | `100` |
| `ROD_BANK_POS_2_ORDERED` | `100` |
| `ROD_BANK_POS_3_ORDERED` | `100` |
| `ROD_BANK_POS_4_ORDERED` | `100` |
| `ROD_BANK_POS_5_ORDERED` | `100` |
| `ROD_BANK_POS_6_ORDERED` | `100` |
| `ROD_BANK_POS_7_ORDERED` | `100` |
| `ROD_BANK_POS_8_ORDERED` | `100` |
| `STEAM_GEN_0_VENT_SWITCH` | `False` |
| `STEAM_GEN_1_VENT_SWITCH` | `False` |
| `STEAM_GEN_2_VENT_SWITCH` | `False` |

