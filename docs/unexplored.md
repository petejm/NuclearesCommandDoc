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
| `FREIGHT_PUMP_CONDENSER_ACTIVE` | nathanctech | This is a GET-list member, the read-back twin of the POST-list `FREIGHT_PUMP_CONDENSER_SWITCH`. auto_nuke correctly reads `_ACTIVE` and writes `_SWITCH` (`auto_nuke:api/pumps.ex:59-60`, distinct `active_key`/`switch_key` fields). nathanctech instead POSTs to `_ACTIVE` itself (`Condenser.cs:56`, `active?1:0`). Either a client bug posting to a read-only variable, which would no-op silently, or the live write surface is quietly wider than the self-published manifest. **Unconfirmed. Worth a live test.** |
| `ROD_BANK_{bank}_{rod}_POS` | nathanctech | Structurally different from the manifest's `ROD_BANK_POS_{n}_ORDERED`: two-dimensional bank-and-rod addressing, no `_ORDERED` suffix. Either a stale API surface the client was written against, or a naming error. Not present in the current manifest in this form. |

The first of those two is the more interesting. If `_ACTIVE` really does accept
writes, then the manifest under-reports the writable surface, and everything in
this repository that treats the manifest as ground truth needs a caveat. Testing
it is cheap and it is the highest-value single experiment left.

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

1. **Test whether `FREIGHT_PUMP_CONDENSER_ACTIVE` accepts writes.** Cheap, and
   it either confirms the manifest is ground truth or breaks that assumption.
2. **Fix the null-probe aliasing and re-run the 10 emergency probes.** Three
   currently-published attributions are known-unreliable.
3. **Re-run `STEAM_TURBINE_TRIP` under exclusive control.** The only reason it
   is unattributed is a confounded observation, not a hard problem.
4. **Brute-force `EMERGENCY_BATTERIES_MODE`'s enum.** Read values suggest
   integers 1, 2, 3. Try posting those.
5. **Establish the generator 1 versus generator 2 asymmetry.** Identical
   command, different result, on a plant where both generators exist.
