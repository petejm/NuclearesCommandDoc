# Operating the plant: procedures and setpoints

This repository is mostly a protocol map. This page is the operational context an
automation author needs in order to know whether a reading is good or bad.

Compiled from community documentation (linked at the bottom) and cross-checked
against live telemetry at build V 2.2.25.220 where possible. Community-sourced
numbers are marked `community`; anything verified against the API is marked
`live-probe`.

Caveat worth stating: one of the checklists carries a reader comment saying
"probably outdated". Numbers below agree across at least two sources where
possible, and disagreements are shown rather than averaged.

## The game ships its own checklist. Use it.

Press **`[C]`** in game. It opens a live, per-loop startup checklist that tracks
completion state, with a **LOOP 1 / 2 / 3** selector so it targets the loop you
actually have installed.

This is authoritative and supersedes community guides where they disagree, and
they do disagree. Two corrections to an earlier version of this page, both
sourced from community guides and both wrong:

| Item | Community guides said | In-game checklist says |
|---|---|---|
| Turbine bypass at startup | `000` | **`100%`**, dropping to `0%` later |
| Main steam control valve | open to `5` | **`>= 25%`** |

The `MSCV x 5 = secondary pump` relation below is a **steady-state demand
matching heuristic**, not a startup setpoint. Do not use it to judge a plant
that is still coming up.

## Startup sequence (from the in-game checklist, loop 3)

Verified `live-probe` by reading the checklist directly at build V 2.2.25.220.

```
Activate all terminals
External Power ON
Generators MANUAL / OFF
Resistor Bank ON
PZR Thermostat & Heaters ON
Primary Pump ON - Set to ~15%
Turbine Bypass 100%
Main Steam Control Valve 0%
Startup Motive Steam Inlet Valve 100%
Operational Motive Steam Inlet Valve 0%
Confirm PZR operating temperature
Primary Pump at ~15%
Plant Mode NOMINAL
PZR Heater LOW                          [optional]
Control Rods at ~93%
Load fuel
Secondary Pump ON - Set to ~25%
Cooling Pump ON - Set to ~25%
STG Coolant operating level
Retention Tank ~50%
Vacuum Pump STARTUP
Turbine Bypass 0%
Vacuum Pressure 0.1 bar
Vacuum Pump OPERATIONAL
Startup Motive Steam Inlet Valve 0%
Main Steam Control Valve >= 25%
Wait Retention Tank < 50%
Operational Motive Steam Inlet Valve >= 30%
Turbine Torque > 2.0%
Request STARTUP - Grid
Wait Turbine RPM > 3050
Wait confirmation to begin operations
Sync - CLOSE Breaker
External Power OFF
```

### Mapping the checklist to API variables

| Checklist item | API variable |
|---|---|
| Primary Pump ~15% | `COOLANT_CORE_CIRCULATION_PUMP_{n}_ORDERED_SPEED` |
| Secondary Pump ~25% | `COOLANT_SEC_CIRCULATION_PUMP_{n}_ORDERED_SPEED` |
| Cooling Pump ~25% | `CONDENSER_CIRCULATION_PUMP_ORDERED_SPEED` |
| Turbine Bypass | `STEAM_TURBINE_{n}_BYPASS_ORDERED` |
| Main Steam Control Valve | `MSCV_{n}_OPENING_ORDERED` |
| Startup Motive Steam Inlet Valve | `STEAM_EJECTOR_STARTUP_MOTIVE_VALVE` |
| Operational Motive Steam Inlet Valve | `STEAM_EJECTOR_OPERATIONAL_MOTIVE_VALVE` |
| Vacuum Pump STARTUP / OPERATIONAL | `CONDENSER_VACUUM_PUMP_MODE` (write `OPERATIONAL`, reads `OPERACIONAL`) |
| Retention Tank ~50% | `VACUUM_RETENTION_TANK_VOLUME` |
| Turbine Torque > 2.0% | `STEAM_TURBINE_{n}_TORQUE` |
| Control Rods ~93% | `RODS_ALL_POS_ORDERED`, read `RODS_POS_ACTUAL` |
| Plant Mode NOMINAL | `CORE_OPERATION_MODE` |
| Load fuel | `CORE_BAY_{n}_FUEL_LOADING`, read `CORE_BAY_{n}_STATE` |

Remember the indexing offset: checklist **LOOP 3** is API index **2**. See
[value-semantics.md](value-semantics.md).

**PZR heaters, the thermostat, external power, the grid request and the breaker
have no writable variable at all.** An automated client cannot complete this
checklist. See [unexplored.md](unexplored.md).

## The resistor bank warning

**Turn the resistor bank on before the generator spins up.** Without a path for
the electricity, the generator damages itself.

This is not folklore. The game logs it as a named deterioration cause, visible
in `AO_AGENT_DIAGNOSTICS_JSON`:

```json
{"reason": "ENERGIA_SIN_SALIDA", "title": "Electrical overload",
 "detail": "Electricity was not carried to transformers or dissipated by
            resistor blocks.", "amount": 0.5}
```

Observed `live-probe` on a plant with four such entries against
`GE_Generador03`, integrity down to 97.5%.

The counter-warning: resistor banks **overheat** if left running too long before
grid connection, which damages them instead. They are a transient sink for
spin-up, not somewhere to park indefinitely.

## Meeting demand: the thermal balance ratios

These are the most useful numbers here, because they turn "is this plant
balanced" into arithmetic.

```
secondary pump speed  =  MSCV x 5
coolant inlet         ~=  secondary pump speed x 2
steam outlet          ~=  MSCV x 10
power                 ~=  4 MW per 1 point of MSCV
```

`community`. To change output, move MSCV by 1 and the secondary pump by 5
together, then watch steam outlet.

Compliance target: **>= 90% of city demand**, averaged over each hour.

### Why this matters for a monitor

A plant can sit at a perfectly plausible-looking MSCV and secondary pump setting
and still be badly out of balance. Observed `live-probe` on a plant that would
not make steam:

```
MSCV_2_OPENING_ACTUAL                        30
COOLANT_SEC_CIRCULATION_PUMP_2_ORDERED_SPEED 30
```

By the ratio, MSCV 30 wants a secondary pump at 150, which is off the top of the
scale. Equivalently, a pump at 30 wants MSCV at 6. The valve was five times too
far open for the feed rate, so the steam generator could not hold pressure.

**A guard on the ratio `MSCV x 5 / secondary_pump_speed` catches this**, and no
single-variable limit or rate check would.

## Shutdown sequence

Order matters more here than in startup.

| # | Step | Note |
|---|---|---|
| 1 | Request shutdown from the city | Approves **after** the next hour, unlike startup |
| 2 | Operating mode to `SHUTDOWN` | |
| 3 | Resistor banks ON | |
| 4 | Wait for green SHUTTING DOWN on the demand board | |
| 5 | **Open the circuit breaker** | Must disconnect **before** spinning the turbine down |
| 6 | Fully insert control rods | 100 = fully inserted (`live-probe`) |
| 7 | Emergency generators to MANUAL | |
| 8 | External power on | or start backup generators |
| 9 | Bypass valve to **100** | spins the turbine down |
| 10 | MSCV to **100** | drops steam generator pressure |
| 11 | Primary pump to **50** | accelerates core cooling |
| 12 | Secondary pump to **25** | manages steam generator level |
| 13 | Condenser pump to **25** | |
| 14 | Secondary pump OFF | once steam gen temp **< 100 C** |
| 15 | Primary pump OFF | once core temp **< 50 C** |
| 16 | Condenser pump OFF | |
| 17 | Steam generator coolant level | target **50,000** for restart |

Core maintenance requires `SHUTDOWN` mode **and** core temp below 50 C, so a
repair plan has to sequence a full cooldown first.

## Steam generation

Water in the steam generator boils once it is above its boiling point, and the
MSCV is the aperture that lets steam out toward the turbines.

**The boiling point is not fixed.** `STEAM_GEN_{n}_BOILING_POINT` is a live
variable and tracks secondary pressure. Observed `live-probe`:

```
COOLANT_SEC_2_TEMPERATURE   308.32
STEAM_GEN_2_BOILING_POINT   321.17
STEAM_GEN_2_EVAPORATED        0
```

Secondary 12.9 C below its boiling point, therefore zero evaporation, therefore
no steam and a stationary turbine. Every valve in the path was correctly lined
up. **Compare the two variables rather than alarming on an absolute
temperature**, because the threshold moves.

## Recovering from a turbine trip

`STEAM_TURBINE_TRIP` opens the turbine vent valves; the inlet stays open. See
[emergency-controls.md](emergency-controls.md).

There is no automatic reset. Recovery observed `live-probe`:

1. Close `VALVULA_VENT_TURBINA_{01,02,03}` with `VALVE_CLOSE`. They **slew**;
   expect intermediate readings where the valve is neither open nor closed.
2. Bring MSCV back down before the vent closes, or full steam hits a stationary
   turbine.
3. Close `STEAM_GEN_{n}_VENT_SWITCH` if open, otherwise steam is dumped instead
   of sent to the turbine.
4. Restart the condenser vacuum pump. Vacuum was observed decaying 0.999 to
   0.659 after a trip, and it is needed for turbine operation.
5. Re-establish boiling. This is the step that actually gates restart, and it
   needs reactor power, since after a trip the core settles to exactly critical
   with no margin to push the secondary back over its boiling point.

## Pressurizer

Level is controlled indirectly through temperature. Community-reported
thresholds:

| Condition | Effect |
|---|---|
| Water temperature below ~330 C | Level rises very quickly |
| Water temperature above ~365 C | Level drops very quickly |

Healthy reference, `live-probe` on a fresh save: `PRESSURIZER_FILL_LEVEL = 60`,
`PRESSURIZER_TEMPERATURE = 140` cold / ~350 at power, `INTEGRITY = 100`.

Recovery from an empty pressurizer: reduce heater power or disconnect the
thermostat to let it cool below the threshold; brief vent-valve pulses; or feed
with a primary coolant pump at low speed.

**Do not open the spray valve while the thermostat is on.** Community reports
say it destroys integrity quickly. Note that neither the heaters nor the
thermostat are commandable through the API, so an automated client cannot
establish the precondition that makes spraying safe. See
[unexplored.md](unexplored.md).

## Sources

- [Beginner's Guide 2025: Starting up, Meeting Demand, Shutting Down](https://steamcommunity.com/sharedfiles/filedetails/?id=3478759609)
- [Nucleares Reactor Start-Up Checklist](https://steamcommunity.com/sharedfiles/filedetails/?id=3517654768)
- [Reactor startup for dummies](https://steamcommunity.com/app/1428420/discussions/2/4142816460194494594/)
- [Maintenance and Repairs FAQ](https://steamcommunity.com/app/1428420/discussions/4/4027969835239419244/)
- [Maintenance and repairs (official blog)](https://nuclearesgame.blogspot.com/2023/11/maintenance-and-repairs.html)
- [Pressurizer Level discussion](https://steamcommunity.com/app/1428420/discussions/2/7599331480046842254/)
- [NUCLEARES User Manual for Simulator](https://www.scribd.com/document/743178267/Nucleares-User-Manual)
