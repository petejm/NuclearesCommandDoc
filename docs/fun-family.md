# The `FUN_*` family: read this before any write sweep

15 of the 91 writable variables are `FUN_*`. They need a hard blocklist in any
automated client, and they break the standard safety pattern people reach for.

## Why the usual safe-probe pattern does not work

The common way to test whether a variable is writable without changing anything
is: read the current value, write that same value back, confirm HTTP 200. A
no-op write.

**That pattern is invalid for this family.** These are *trigger* writes. The act
of writing is the action. For most of them the payload is irrelevant, a bare
POST with an empty body fires the effect. There is no current value to read and
restore, because there is no value, only an event.

Worse, most of them are write-only (a GET returns the does-not-exist sentence),
so there is nothing to read even if you wanted to.

**Do not include any `FUN_*` variable in a generic writability sweep.**

## They are an incident generator, not a cheat mode

This is worth stating clearly, because the name misleads. All 15 make the plant
*harder* to run. Nothing here grants resources, repairs damage, or gives you an
advantage:

| Variable | Effect | Payload |
|---|---|---|
| `FUN_REQUEST_ENABLE` | Gates the rest of the family | irrelevant |
| `FUN_DECREASE_INTEGRITY` | Damages plant integrity | trigger |
| `FUN_PUMP_JAM` | Jams a pump | trigger |
| `FUN_BREAKER_TRIP` | Trips a breaker | trigger |
| `FUN_OIL_SPILL` | Oil spill | trigger |
| `FUN_XENON_SPILL` | Xenon release | trigger |
| `FUN_IODINE_SPILL` | Iodine release | trigger |
| `FUN_FIRE_DRILL` | Fire drill | unknown |
| `FUN_AO_SABOTAGE_ONCE` | Auxiliary operator sabotage, one shot | trigger |
| `FUN_AO_SABOTAGE_TIME` | Sabotage interval | int hours |
| `FUN_TRIGGER_AUDIT` | Regulatory audit | trigger |
| `FUN_TOGGLE_RANDOM_SWITCH` | Flips a random switch | trigger |
| `FUN_WEATHER_CONTROL` | Weather | unknown |
| `FUN_BANK_ROBBERY` | Cosmetic event | trigger |
| `FUN_SHOW_MESSAGE` | Displays a message | free text string |

Gating adversity behind explicit consent is a sensible design in a way that
gating a cheat would not be. Treat the gate as intentional.

## The gate is real and it returns 412

`FUN_REQUEST_ENABLE` gates the family. With the in-game option declined, all
four attempted triggers returned **HTTP 412** and nothing fired.

That makes 412 the one honest status code on this API: it is the only case where
the HTTP layer tells you the truth about why a write did not take effect.

`FUN_IS_ENABLED` is the read-side status flag. It returns the literal string
`null` when the family has never been enabled, which is a third state distinct
from a boolean true or false. Parse accordingly.

`inferred`: the gate relationship between `FUN_REQUEST_ENABLE` and the rest is
reasoned from naming, from its position as the first entry in nathanctech's own
`Fun.cs` comment block, and from the observed 412s. No client source explicitly
documents the causal link.

## The spelling trap

The manifest spells it `FUN_DECREASE_INTEGRITY` (`live-manifest`, verified at
build V 2.2.25.220).

nathanctech's client posts `FUN_DECERASE_INTEGRITY`, with the letters
transposed, at `Nucleares-Controller/NukeWeb/Settables/Fun.cs:15,35`.

**The manifest wins.** The correct wire name is `FUN_DECREASE_INTEGRITY`. The
client's version is a typo that almost certainly no-ops silently against the
live game, since posting to an unknown variable returns 200 and does nothing.

That is a good illustration of the general hazard on this API: a misspelled
variable name is indistinguishable from a working one at the HTTP layer.

## Recommended blocklist

If you are building anything that writes to this API autonomously, block these
at the tool boundary in code, using an **allowlist** of permitted variables
rather than a blocklist of forbidden ones. An allowlist fails closed when the
game adds a variable you have not seen; a blocklist fails open.

Alongside the `FUN_*` family, the reasonable additions to a blocked set are
`CORE_SCRAM_BUTTON`, `CORE_EMERGENCY_STOP` and `STEAM_TURBINE_TRIP`. Not because
they are unsafe to the game, but because there is no working programmatic
recovery from a scram. See [emergency-controls.md](emergency-controls.md).
