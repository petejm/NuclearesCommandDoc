# Plant mechanics an API client needs to know

This repository is mostly a protocol map. This page is the exception: a short
set of *simulation* behaviours that will otherwise make you misread the
telemetry.

Sources are the game's own diagnostics payload plus community documentation,
cited inline. Where a claim rests on a player report rather than the game or the
official FAQ, it says so.

## Wear and integrity are different mechanics

Conflating them is the most common way to misdiagnose a plant from the API.

| | Meaning | Repair |
|---|---|---|
| **Wear** | Scheduled degradation from normal running. Accumulates toward 100% | Maintenance task. Some require a shutdown, some do not |
| **Integrity** | Damage. Falls from 100% under abusive conditions | Welder on tubes and containers; unreachable damage has to be delegated to the in-game assistant |

The game's own `pressure_loss_factors.notes` states the operational rule:

```
Low integrity (<70%) causes continuous pressure bleed.
```

**That is a threshold, not a gradient.** A component at 90% integrity is
damaged, has a recorded reason for the damage, and is worth repairing, but it is
not above this rule's trigger. Do not read "integrity below 100" as "leaking".

Community reports go further and describe integrity loss as causing water loss
directly. That is plausible and consistent with the note, but it is a player
claim, not something the game or the official FAQ states. Treated here as
`inferred`.

## Damage causes are logged, and they name the abuse

`maintenance_summary.attention_items[].deterioration_logs` records *why* each
component lost integrity. Observed reason codes:

| Code | Meaning |
|---|---|
| `ALTA_PRESION` | Pressure above the operating maximum |
| `ALTA_TEMPERATURA` | Temperature above the operating maximum |
| `ENERGIA_SIN_SALIDA` | Electricity generated but not carried to transformers or dissipated by resistor banks |

That third one is a trap for anyone automating startup: bringing a generator
online without first providing a load path damages it. Resistor banks exist to
absorb generation that the grid connection is not yet taking.

Remember this data is a **snapshot**. See
[diagnostics-endpoint.md](diagnostics-endpoint.md).

## Pressurizer level is driven by temperature, not by a fill valve

This one explains a plant state that otherwise looks like a leak.

The pressurizer holds a steam bubble over water. Level is controlled indirectly
through temperature, via heaters and spray. Community-documented thresholds:

| Condition | Effect on level |
|---|---|
| Water temperature below ~330 C | Level rises very quickly |
| Water temperature above ~365 C | Level drops very quickly |

Source: player reports on the Steam discussions. Consistent with observed
behaviour but not stated in the official FAQ, so `inferred`.

A worked example measured at build V 2.2.25.220:

```
PRESSURIZER_TEMPERATURE            395.70   (falling 0.01 C/s)
PRESSURIZER_TEMPERATURE_OPERATIVE  350
PRESSURIZER_FILL_LEVEL               0.4626 (static to 7 dp over 40 s)
PRESSURIZER_HEATERS_ON             True
PRESSURIZER_INTEGRITY               90.51
```

That pressurizer is empty and **stays** empty: 30 C above the level-recovery
threshold, with heaters on and the thermostat holding it there. The level is
pinned, not draining. An automated monitor differencing `FILL_LEVEL` sees no
change and reports healthy; a monitor comparing temperature to
`_OPERATIVE` sees a 45 C deviation and the real fault.

**Implication for guard design:** alarm on the deviation from the `*_OPERATIVE`
reference, not on the rate of change of the level. A stuck-bad value has zero
rate.

Recovery, per community reports: reduce heater power or disconnect the
thermostat to let temperature fall below the threshold; brief vent-valve pulses;
or feed with a primary coolant pump at low speed so it does not fill too fast.

## Uninstalled equipment reports confident values

Indexed equipment variables exist whether or not the equipment does.

```
STEAM_TURBINE_0_INSTALLED  False    STEAM_TURBINE_0_RPM  0
STEAM_TURBINE_1_INSTALLED  False    STEAM_TURBINE_1_RPM  0
STEAM_TURBINE_2_INSTALLED  True     STEAM_TURBINE_2_RPM  3050
```

`POWER_FROM_TURBINE_KW` read 271.8 at that moment, all of it from turbine 2.

**Check `_INSTALLED` before trusting any indexed variable**, and note that an
experiment targeting a non-existent unit measures nothing while looking like a
clean negative result.

## Post-save-load readings are not trustworthy

The webserver unbinds on save load and appears to need re-enabling per save.
Immediately after a reload, `CORE_STATE_CRITICALITY` was observed reading 5, the
historical excursion threshold, with settled values 30 seconds later at 0.64 and
falling.

Do not sample, alarm, or difference across a save-load boundary.

## Negative temperature coefficient works

With rods fixed at 93, criticality fell 1.25 to 1.07 over 30 seconds while
temperature rose 129.7 to 163.0 C. The reactor self-limits.

The practical consequence for alarm design: a routine startup transits
criticality above +1.4, so a threshold has to sit above the normal operating
envelope rather than just below the failure point, or it will fire on every
startup.

## Core maintenance has hard preconditions

Core maintenance tasks require the plant in SHUTDOWN mode with core temperature
below 50 C. Any automation that plans repairs has to sequence a full cooldown
first, which is a much longer operation than the repair itself.
