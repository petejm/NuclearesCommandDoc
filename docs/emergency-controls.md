# Emergency controls: first live test of 10 untested variables

Ten variables appear in the game's POST manifest, are written by no community
client surveyed, and are documented nowhere. This is the first live test of
them.

Measured 2026-07-27 against game build **V 2.2.25.220** on a throwaway save.
Results are stated as measured, including the two that came back ambiguous.
Nothing here is extrapolated.

## The lead finding: two trip paths, no reset

| Direction | Variable | Works |
|---|---|---|
| Trip | `CORE_SCRAM_BUTTON` | yes |
| Trip | `CORE_EMERGENCY_STOP` | yes |
| Reset | `CORE_END_EMERGENCY_STOP` | **no** |

`CORE_END_EMERGENCY_STOP` returns HTTP 200 and does nothing. Rods stayed at 100,
`CORE_STATE` stayed `NOREACTIVO`, no state moved anywhere.

**The consequence for anyone automating this plant:** you get a reliable ABORT
and no programmatic RECOVERY. A scram has to be treated as terminal, with
handback to a human to clear the plant and restart.

That is arguably correct engineering. You should not be able to withdraw control
rods by clearing a flag over HTTP. But it is a hard constraint on any control
design, and it is established here by measurement rather than by reading intent
into the API.

## Works

| Variable | Posted | Effect | Evidence |
|---|---|---|---|
| `CORE_SCRAM_BUTTON` | `true` | Full rod insertion under 3 s, subcritical by about t+11 s, temperature ramp reversed | timeline below |
| `CORE_EMERGENCY_STOP` | `true` | Observably identical to SCRAM | same `CORE_STATE` flip, same rod bank pair, no API-visible difference |
| `EMERGENCY_GENERATOR_1_START_STOP` | `START` | Generator 1 spun up | `EMERGENCY_GENERATOR_1_STATUS` went `INACTIVO` to `INICIANDO` to `GENERANDO`; `_PRESSURIZER` went `INACTIVO` to `PRESURIZANDO` |
| `EMERGENCY_GENERATOR_1_MODE` | `MANUAL` | Mode set | reads back `MANUAL` |

### SCRAM timeline

Starting state: `REACTIVO`, criticality 0.52, rods 93, 265.0 C, temperature
rising at +0.60 C/s.

| t | `CORE_STATE` | Rods actual/ordered | Criticality | Temp (C) |
|---|---|---|---|---|
| 0 | REACTIVO | 93 / 93 | 0.52 | 265.0 |
| +3s | NOREACTIVO | 100 / 100 | 0.37 | ramp reversing |
| +8s | NOREACTIVO | 100 / 100 | 0.14 | 262.4 |
| +18s | NOREACTIVO | 100 / 100 | -0.32 | 258.2 |

`ROD_BANK_POS_0_ORDERED` and `ROD_BANK_POS_0_ACTUAL` moved in lockstep with
`RODS_POS_ACTUAL`, 93 to 100, on both the scram and the emergency stop.

**This establishes rod polarity: 100 is fully inserted.** Previously ambiguous.

The generator results also confirm that auto_nuke's harvested Spanish enums
(`INACTIVO`, `INICIANDO`, `GENERANDO`, `PRESURIZANDO`) are real and correctly
cased, not a client-side guess.

## Does not work

| Variable | Posted | Result |
|---|---|---|
| `CORE_END_EMERGENCY_STOP` | `true` | HTTP 200, zero effect. See above |
| `EMERGENCY_GENERATOR_2_START_STOP` | `START` | HTTP 200, no effect at the time. **Now explained, see below** |
| `EMERGENCY_BATTERIES_MODE` | `MANUAL` | Value discarded. Reads back `1`. See the follow-up below |

### Resolved 2026-07-28: the generator asymmetry was not an API defect

Generator 2 was **out of fuel**.

```
EMERGENCY_GENERATOR_1_FUEL = 421
EMERGENCY_GENERATOR_2_FUEL = 0
```

Identical command, identical handling, different plant state. `START` on a
generator with no fuel returns HTTP 200 and does nothing, which is the
"accepted, genuinely does nothing" case in
[wire-format.md](wire-format.md).

The lesson generalises: before recording an API asymmetry between two instances
of the same equipment, read the equipment's own preconditions. The relevant
variable was one GET away for an entire session.

### Follow-up 2026-07-28: `EMERGENCY_BATTERIES_MODE` appears not to be settable

Twelve values were posted with read-back after each: `1`, `2`, `3`, `0`, `4`,
`AUTOMATICO`, `MANUAL`, `CHARGE`, `DISCHARGE`, `CARGA`, `DESCARGA`. Every one
returned HTTP 200. None reliably set the value.

The variable did transition `1` to `2` once, coincident with a `CHARGE` post.
**That transition is unattributed**, and the evidence argues against the write
having caused it: the variable subsequently refused every value including
`CHARGE` itself and including `2`, the value it currently holds.

Controls run at the same time:

- A **matched null probe** over 24 s with no POST showed the value completely
  stable, so it is not free-running drift.
- A **positive control** on a known-good setter (`STEAM_GEN_0_VENT_SWITCH`,
  False to True to False) worked cleanly in the same window, so the harness and
  the write path were both functioning.

Best current reading: `EMERGENCY_BATTERIES_MODE` is in the manifest's POST list
but is not settable in practice, at least under these plant conditions, and the
one observed transition was plant-driven. Stated as a working conclusion, not a
finding. Independent confirmation welcome.

## Unattributed: do not treat these as confirmed

| Variable | Posted | Observed coincidence | Why it does not count |
|---|---|---|---|
| `STEAM_TURBINE_TRIP` | `true` | `CONDENSER_CIRCULATION_PUMP_ACTIVE` False to True, `_SWITCH` False to True, `_ORDERED_SPEED` 0 to 25, `CONDENSER_TEMPERATURE` 20 to 22 | The operator was manually bringing the secondary up at that moment. Command effect and human action are not separable. Needs a re-run with exclusive control |
| `RESET_AO` | `true` | `POWER_FROM_EXTERNAL_KW` 179.4 to 239.4 | Weak signal, single observation |

## Method, and its disclosed limitation

Each real probe was preceded by a **matched null probe**: same snapshot logic,
same settle window, no POST. A variable counts as an effect only if it moved
during the POST window and did not move during its matched null. This exists
because an earlier sweep was voided by diffing against a moving baseline, where
one continuous flow ramp (30, 32, 34, 36, 38) looked like four independent
effects across four sequential probes.

**The null probe did not fully work.** `CORE_PRESSURE`,
`PRESSURIZER_PRESSURE` and `PRESSURIZER_PRESSURE_DEVIATION` appeared as
attributable in all 10 results. Separately verified that this is pure drift:
pressure falls about 0.2 bar every 5 to 10 seconds with no command issued at
all.

Root cause is step-period against settle-window aliasing. When the signal's
period is comparable to the settle window, the drift lands on both sides of the
subtraction and does not cancel.

**Treat any pressure-variable attribution from this harness as unreliable until
that is fixed.** The fix is multiple null samples per probe, or a settle window
set to a large multiple of the underlying step period.

This limitation is published rather than quietly omitted because a reader
reproducing these results needs to know which three rows not to trust.

## Related findings from the same session

**`CORE_STATE` has two representations.** Numeric `1`/`0` via
`WEBSERVER_BATCH_GET`, Spanish `REACTIVO`/`NOREACTIVO` via a single GET. Same
variable, endpoint-dependent type.

**Negative temperature coefficient confirmed working.** With rods fixed at 93,
criticality fell 1.25 to 1.07 over 30 seconds while temperature rose 129.7 to
163.0 C. The reactor self-limits. The practical consequence is that a routine
startup transits criticality above +1.4, so an alarm threshold has to sit above
the normal operating envelope rather than just below the failure point.

**Save-load transients are not trustworthy.** Immediately after a quick-save
reload, `CORE_STATE_CRITICALITY` read 5, the historical excursion threshold.
Settled readings 30 seconds later were 0.64 and falling. Do not sample or alarm
immediately after a load.

**The `FUN_*` family is gated and returns 412.** In-game consent was declined;
all four attempted triggers returned HTTP 412 and nothing fired. See
[fun-family.md](fun-family.md).

## Open questions

Contributions very welcome on any of these.

- Re-run `STEAM_TURBINE_TRIP` with exclusive operator control, so the command
  effect separates from manual action.
- Confirm `RESET_AO` with a repeat probe. One 60 kW power delta is not enough.
- Determine `EMERGENCY_BATTERIES_MODE`'s actual enum vocabulary. It rejected
  `MANUAL` and reads back `1`.
- Explain the generator 1 versus generator 2 asymmetry: identical command,
  different outcome.
- Establish whether `CORE_SCRAM_BUTTON` and `CORE_EMERGENCY_STOP` differ
  internally. Through the API they are indistinguishable.
- Fix the null-probe aliasing before trusting any future pressure attribution.
