# What is read-only, what nobody has touched, and where the frontier is

## Not commandable at all

`VALVE_M01_OPEN`, `VALVE_M02_OPEN` and `VALVE_M03_OPEN` are **GET-only**
telemetry for the plant's manual hand valves.

They are in the 332-entry GET list, absent from the 91-entry POST list, and
absent from the 55-entry valve panel. There is no API path to actuate them. You
can read their position and nothing else.

This closes a question that consumed two full sessions of probing.

The general rule: anything in the GET list with no POST counterpart and no valve
panel entry is instrumentation, not a control surface. Temperatures, pressures,
flow rates, and the rest of the sensor set are all in this category.

## Where the community harvest and the manifest disagree

Seven community clients were read at source level and cross-referenced against
the manifest. 36 harvested write-names did not exact-match the 91-entry POST
list. Of those:

- **29 are valve identifiers.** Expected, and they are what revealed the
  indirection documented in [valves.md](valves.md). Not a discrepancy.
- **4 are template placeholders** (`MSCV_{n}_OPENING_ORDERED`,
  `RESISTOR_BANK_#{num}_SWITCH`) where the harvester left the interpolation
  syntax unexpanded. They resolve cleanly to already-matched numbered instances.
- **1 is the `FUN_DECERASE_INTEGRITY` typo**, covered in
  [fun-family.md](fun-family.md).

That leaves two genuine cases:

| Name | Client | Assessment |
|---|---|---|
| `FREIGHT_PUMP_CONDENSER_ACTIVE` | nathanctech | **RESOLVED 2026-07-28: not writable.** POSTing it returns HTTP **404** (`The writable variable ... does not exist.`) for both `True` and `1`. A positive control on `_SWITCH` in the same run worked and carried `_ACTIVE` with it. So `_ACTIVE` is purely the read-back twin, auto_nuke has it right (`auto_nuke:api/pumps.ex:59-60`), and nathanctech's POST at `Condenser.cs:56` is a **client bug whose code path has never worked**. |
| `ROD_BANK_{bank}_{rod}_POS` | nathanctech | Structurally different from the manifest's `ROD_BANK_POS_{n}_ORDERED`: two-dimensional bank-and-rod addressing, no `_ORDERED` suffix. Either a stale API surface the client was written against, or a naming error. Not present in the current manifest in this form. |

That question is now settled, and it settles a larger one:
**the manifest is ground truth for the writable surface.** It was the only
outstanding candidate for the live API being wider than the game advertises, and
it is not writable. Everything in this repository that treats the manifest as
authoritative stands.

## The 13 variables no client has ever written

This is the genuinely unexplored frontier. These appear in the manifest's POST
list and no surveyed client reads or writes them.

```
CORE_SCRAM_BUTTON                 EMERGENCY_GENERATOR_1_START_STOP
CORE_EMERGENCY_STOP               EMERGENCY_GENERATOR_2_START_STOP
CORE_END_EMERGENCY_STOP           EMERGENCY_GENERATOR_1_MODE  (read-observed)
STEAM_TURBINE_TRIP                EMERGENCY_GENERATOR_2_MODE  (read-observed)
RESET_AO                          EMERGENCY_BATTERIES_MODE    (read-observed)
FUN_WEATHER_CONTROL               FUN_FIRE_DRILL
FUN_DECREASE_INTEGRITY  (correct spelling; only the typo variant is used)
```

Three of them (`EMERGENCY_GENERATOR_1_MODE`, `EMERGENCY_GENERATOR_2_MODE`,
`EMERGENCY_BATTERIES_MODE`) have read-observed enum values from mct_nuke and
nuclearesOA even though no client writes them.

**10 of these 13 have now been live-tested**, with results in
[emergency-controls.md](emergency-controls.md). Nine resolved. The remaining
untested three are the `FUN_*` members, deliberately left alone because the
in-game consent gate was declined.

Notably, no client uses `CORE_SCRAM_BUTTON` at all. Every one of them emulates a
scram by posting `RODS_ALL_POS_ORDERED=100`
(`nathanctech:Settables/General.cs:13`). The dedicated scram endpoint was
entirely unexplored territory until it was tested here, and it works.

## Known gaps in this document

Stated plainly so nobody mistakes absence for completeness.

- **Value ranges are unconfirmed for 9 variables**, marked "range unconfirmed"
  in [writable-variables.md](writable-variables.md). The names are confirmed
  from client source; no client that writes them documents an accepted range.
- **`CORE_OPERATION_MODE`'s non-shutdown enum is disputed.** auto_nuke writes
  `NOMINAL`, GHXX reads `MAXIMUM`. The manifest gives no enum. Unresolved, and
  flagged rather than guessed. A live read at build V 2.2.25.220 returned
  `NOMINAL`, which supports auto_nuke but does not rule out `MAXIMUM` being a
  separate valid mode.
- **The decimal-comma locale hazard is untested.** See
  [wire-format.md](wire-format.md).
- **Three pressure variables have unreliable attribution** from the emergency
  probe harness, due to the disclosed null-probe aliasing bug.
- **The `FUN_*` effects are undocumented in detail** because the family was
  never enabled. Effects listed in [fun-family.md](fun-family.md) are inferred
  from names and client comments, not observed.

## Best next experiments

Ranked by value per unit of effort.

Three of the original five are now closed. Struck through with their outcomes,
so the record shows what was asked and what came back.

1. ~~Test whether `FREIGHT_PUMP_CONDENSER_ACTIVE` accepts writes.~~
   **Closed:** it does not, HTTP 404. Manifest confirmed as ground truth.
2. ~~Establish the generator 1 versus generator 2 asymmetry.~~
   **Closed:** generator 2 had `FUEL = 0`. Plant state, not an API defect.
3. ~~Brute-force `EMERGENCY_BATTERIES_MODE`'s enum.~~
   **Closed as negative:** 12 values tried, none set it, against a verified
   working harness. Appears not to be settable in practice.

4. ~~Confirm `RESET_AO`.~~
   **Closed as negative:** no change in `AO_AGENT_STATUS` or
   `POWER_FROM_EXTERNAL_KW` against a matched null. `AO_AGENT_STATUS` reports
   `runtime_state: NoInstalado` and `dlc_installed: false`, so there is no agent
   to reset. The earlier 60 kW delta was coincidence.

Still open, ranked by value per unit of effort:

1. **Re-run `STEAM_TURBINE_TRIP` under exclusive control**, and against an
   **installed** turbine. The original test evaluated turbine 0, which is not
   installed on that plant, so it could not have registered an effect
   regardless. Check `STEAM_TURBINE_{n}_INSTALLED` first.
2. **Determine whether `CORE_SCRAM_BUTTON` and `CORE_EMERGENCY_STOP` differ
   internally.** Indistinguishable through the API.
3. **Measure the integrity-to-leak relationship directly.** The game states
   `<70%` integrity causes continuous bleed. Nobody has measured the rate, or
   established whether it is pressure only or mass as well. Requires a vessel
   below 70% and a clean inventory recording from t=0.

## Correction 2026-07-28: background drift is not constant

An earlier version of this work recorded that pressure "falls about 0.2 bar
every 5 to 10 seconds with no command issued", and treated that as a property of
the simulation.

It is not. A 140-sample read-only capture over 280 simulated seconds found
`CORE_PRESSURE`, `PRESSURIZER_PRESSURE` and `PRESSURIZER_PRESSURE_DEVIATION`
**completely static**, zero changes, while `CORE_TEMP` moved on a roughly 2
second step.

The drift is **plant-state dependent**. It was real when originally measured,
during a pressurisation transient, and absent under different conditions.

The consequence for anyone building a probe harness: you cannot calibrate one
global settle window and reuse it. Drift rate is a function of plant condition,
so every probe has to derive its own baseline from its own matched null, taken
adjacent in time. A constant measured in an earlier session is not a constant.

Related: several vessel volumes fill in **steps, not smoothly**.
`VACUUM_RETENTION_TANK_VOLUME` was observed holding a value for 10 seconds and
then jumping. Sampling such a signal at a fixed rate and differencing yields a
confident and meaningless rate.

## The pressurizer is not commandable at all

Verified `live-probe` at build V 2.2.25.220. `PRESSURIZER` appears 8 times in
the 332-entry GET list and **zero** times in the 91-entry POST list. Seven
plausible write names were probed and all returned HTTP 404:

```
PRESSURIZER_HEATERS_ON        PRESSURIZER_THERMOSTAT
PRESSURIZER_HEATERS           PRESSURIZER_AUTO_THERMOSTAT
PRESSURIZER_HEATERS_SWITCH    PRESSURIZER_HEATERS_REQUESTED
PRESSURIZER_HEATER_POWER
```

You can read pressure, temperature, fill level, integrity, both `*_OPERATIVE`
references and the heater state. You cannot set any of them.

This is the largest gap in the commandable surface. In a PWR the pressurizer is
the primary pressure-control system, so an autonomous controller can observe a
pressurizer fault and has no direct means to correct it.

The only indirect path is the actuated valve panel, which does expose
`Valvula_Pressurizer_Spray`, `Valvula_Pressurizer_Vent` and
`Valvula_Pressurizer_Relief_Vent` through the `VALVE_OPEN`/`VALVE_CLOSE`/
`VALVE_OFF` meta-commands.

**Safety note on that path:** community reports state that an open spray valve
degrades pressurizer integrity very quickly while the thermostat is on. Since
the thermostat is also not commandable, an automated client cannot establish the
precondition that makes spraying safe. Treat the pressurizer spray valve as
requiring a human in the loop.
