# What a real PWR protection system does, and what Nucleares does not

Nucleares simulates a Westinghouse-style PWR. The reference for how such a plant
actually protects itself is the USNRC's own operator training material,
**Westinghouse Technology Systems Manual, Section 12.2, Reactor Protection
System: Reactor Trip Signals** (USNRC HRTD, Rev 0109, ADAMS `ML11223A301`).

This page compares that architecture against what the game exposes. It exists
because the gap decides what an automated client can responsibly attempt.

## The real architecture, in four ideas

**1. Coincidence voting.** No single sensor trips a reactor. Every trip is
`2/4`, `2/3`, `1/2`, or similar. A trip requires agreement across independent
channels, so an instrument fault degrades the plant rather than tripping it.

**2. Permissives gate trips by regime.** Protection-grade interlocks (`P-n`)
enable and block trips according to plant condition, because a trip that is
correct at power is wrong during startup. `P-7` (below 10% power) automatically
blocks the pressurizer low pressure trip, pressurizer high level trip, all RCS
low flow trips, and reactor-trip-on-turbine-trip. Blocked trips are
**automatically reinstated** when the permissive clears, which IEEE Std 279-1971
requires.

**3. Graduated response, not a binary trip.** Control-grade interlocks (`C-n`)
act before the trip does. As `ΔT` comes within **3%** of the OTΔT or OPΔT trip
setpoint, `C-3`/`C-4` block rod withdrawal and initiate a **turbine runback**.
The plant is walked away from the limit before the breakers open.

**4. Anticipatory trips fire on precursors.** Several trips exist to act on the
approach to a condition rather than the condition itself. The stated philosophy
is to trip "when the limits of a selected area of concern are approached".

## The trip that matters most here

**Trip 17, Low Feedwater Flow.** Coincidence: `1/2` flow mismatch **and** `1/2`
low level, on `1/4` steam generators. Setpoint: SG level **25.5%** AND a steam
flow / feed flow mismatch of **1.5x10^6 lbm/hr** with `Ws > Wf`. Purpose, quoted:
**"Anticipates loss of heat sink."**

That is steam flow exceeding feed flow, coincident with a falling level.

The steady-state guard in [`../tools/monitor.py`](../tools/monitor.py) was
derived independently, from a measured mass deficit on a live plant:
`STEAM_GEN_{n}_OUTLET` exceeding `STEAM_GEN_{n}_RETURN_FLOW_PLUS_CONDENSED`,
coincident with falling `COOLANT_SEC_{n}_LIQUID_VOLUME`. Same two conditions,
same physical quantity, same purpose.

The convergence is the point: **the relational form is the correct form**, not a
stylistic preference. A threshold on either variable alone catches neither
failure.

Related trips on the same theme:

| Trip | Setpoint | Purpose |
|---|---|---|
| 16. SG Low-Low Level | 11.5%, `2/3` on `1/4` SGs, **no interlocks** | Prevents loss of heat sink |
| 18. Turbine Trip | `2/3` low auto-stop oil pressure or `4/4` throttle valves closed | Removes heat **source** when steam load is lost |

## What Nucleares does not implement

Measured `live-probe` at build V 2.2.25.220, on a plant deliberately driven into
each condition.

**A turbine trip does not trip the reactor.** In a Westinghouse plant, trip 18
trips the reactor on turbine trip above `P-7` (10% power), or above 50% at
plants carrying the `P-9` permissive. In Nucleares, `STEAM_TURBINE_TRIP` left
`CORE_STATE` at `REACTIVO` while core temperature rose 13.9 C in two minutes,
because the heat sink had been removed. There is no reactor protection tied to
the turbine at all.

**No low-low steam generator level trip.** A secondary loop was driven from
roughly 12,000 down toward zero liquid volume, at up to 44 units/s, with no
automatic protective action of any kind. A real plant trips at 11.5% level and
anticipates it earlier with trip 17.

**No trip on the steam/feed mismatch.** The measured deficit reached 23 to 28
units per tick with no response.

**Consequence:** the game's plant will let you destroy it. Everything protective
here is either the operator or something a client implements. That is the
argument for building the monitor before building any controller.

## What the game does implement

**The negative temperature coefficient works**, and it is doing real protective
work. With rods fixed at 93, criticality was observed falling 1.25 to 1.07 while
temperature rose 129.7 to 163.0 C; and after a turbine trip removed the heat
sink, criticality fell 0.11 to 0.03 as the core heated. The reactor self-limits.

That is physics, not a protection system. It bounds excursions; it does not
prevent a slow loss of heat sink.

**Two working trip paths, no working reset.** `CORE_SCRAM_BUTTON` and
`CORE_EMERGENCY_STOP` both work; `CORE_END_EMERGENCY_STOP` returns HTTP 200 and
does nothing. See [emergency-controls.md](emergency-controls.md).

## What this repository's monitor actually guards

The comparison above is the game against the real plant. This is the monitor
in [`../tools/monitor.py`](../tools/monitor.py) against both.

| Protection | Real setpoint | What monitor.py does |
|---|---|---|
| Pressurizer heater cutoff | 17% level | Guarded, and directly. The game exposes `PRESSURIZER_FILL_LEVEL` as a percent, so the real setpoint transfers with no conversion needed |
| Low feedwater flow (Trip 17) | SG level 25.5% AND `Ws > Wf` | Guarded relationally, steam/feed balance against falling inventory, and now gated by regime: downgraded to `INFO` during startup rather than suppressed |
| Reactor trip on turbine trip (Trip 18) | Above P-7, 10% power | Detected and alerted, **not actioned**. The API has no path to trip the reactor from turbine state, and this tool is read-only by design, so the strongest response available is telling a human |
| SG low-low level (Trip 16) | 11.5% | **Not guarded as specified.** See below |

### Why SG low-low level is not guarded as specified

Trip 16 is defined as a percentage of SG nominal level. `COOLANT_SEC_{n}_LIQUID_VOLUME`
is an absolute volume, and no capacity or nominal variable exists anywhere in
the manifest for it, so 11.5% of nothing is not a number `monitor.py` can
compute. This is not a rounding gap or an approximation, it is a missing
input: the real setpoint needs a denominator this API does not expose.

What `monitor.py` substitutes instead is a run-local high-water mark, the
highest `COOLANT_SEC_{n}_LIQUID_VOLUME` observed while the loop looked healthy
this run, and a percent below that. That is a materially different
measurement from Trip 16. It resets every run, so it cannot generalize across
sessions or a game restart. It can be fooled low, treating an already-depressed
level as the ceiling if the monitor starts mid-drain. And if the monitor never
observes a healthy at-power sample, the guard never fires at all, silently, by
design, because a silent wrong number is worse than no number. None of that is
true of Trip 16, which is derived from a known plant nominal and holds
regardless of any one run's history.

### The calibration gap

Two computations a client would want are blocked by the same kind of missing
denominator, one for each of the two protections above that fall short of the
real setpoint.

**Power fraction.** Trip 18 is gated by P-7, 10% of rated power. `CORE_STATE_CRITICALITY`
is reactivity, not a power fraction. `GENERATOR_{n}_KW` is documented
elsewhere in this repository as misleading during spin-up (see
[`../tools/README.md`](../tools/README.md) and `tools/checklist.py`). No
`CORE_THERMAL_POWER` variable exists anywhere in the manifest. So a literal
percent-of-rated-power gate is not computable, and `regime()` substitutes "the
generator is actually carrying load, `GENERATOR_{n}_A` above zero, and
`CORE_OPERATION_MODE` reads `NOMINAL`", which is what P-7 is really asking,
without the missing denominator.

**SG level percent.** `COOLANT_SEC_{n}_LIQUID_VOLUME` has no capacity, nominal
or max variable anywhere in the manifest, so a literal percent of plant
nominal is not computable here either. There is a trap worth naming
precisely: `COOLANT_SEC_{n}_VOLUME` and `COOLANT_SEC_{n}_LIQUID_VOLUME` are
two different variables. The 50,000 restart target on the shutdown checklist
in [operations.md](operations.md) refers to the former, `COOLANT_SEC_{n}_VOLUME`
(see `tools/checklist.py`), not the latter, which is what `monitor.py`'s
inventory guard reads. Applying either the 50,000 figure or the "roughly
12,000" figure quoted earlier in this document to the wrong variable would
silently misjudge inventory. Both figures are single unsourced observations,
not documented capacities, and should be treated as that rather than as
calibration constants.

So the inventory guard falls back to a run-local high-water reference instead
of a plant nominal. That is a weaker and different thing than Trip 16, not a
stand-in for it, and the guard's own comments in `tools/monitor.py` say so
directly.

### Design note: a regime gate inverts the sign of "fail closed"

This repository's guiding rule for guards, stated in
[`../tools/README.md`](../tools/README.md), is fail closed: an unreadable
variable raises an alert, and never reads as healthy. A regime gate is not a
guard, and applying that direction to it unchanged would be a bug rather than
a safety improvement. The risky failure for a guard is under-alerting, so an
unreadable variable must raise `ERROR`. The risky failure for a regime gate is
the mirror image: an unreadable regime must leave guards armed, not disarm
them. `regime()` returns `"unknown"` when `amps` or `op_mode` cannot be read,
and `"unknown"` gates exactly like `"at_power"`, never like `"startup"`. Only
a positively established `"startup"` may downgrade a guard to `INFO`. Fail
closed, applied consistently rather than literally, means the gate defaults
to armed in exactly the way the guard defaults to alerting.

## Implications for an automated client

**Design the fast loop as an RPS, not as an LLM.** Trips are deterministic,
sub-second, coincidence-voted logic. Nothing about them wants a language model.
The supervisory layer, which chooses setpoints on a timescale of minutes, is
where judgement belongs.

**Gate guards by regime, the way permissives do.** A steam-balance guard is
correct at power and wrong during startup, when the checklist explicitly calls
for MSCV `>= 25%` and the loop is deliberately unbalanced. An always-on guard
here fires on every startup and gets ignored, which is worse than no guard.
This repository already made that mistake once: a steady-state ratio was used to
explain a plant that was still coming up. See
[operations.md](operations.md).

**Prefer graduated response.** Blocking an action and backing a setpoint off is
almost always better than tripping. The real plant blocks rod withdrawal and
runs the turbine back at 3% from the trip point. An automated client has the
same option and should exhaust it first.

**Recognise the recovery asymmetry.** A real RPS trips into a state that
operators can recover from by procedure. This API gives an abort with no
programmatic reset, so any autonomous controller must treat a trip as terminal
and hand back to a human. That is a stronger constraint than a real plant
imposes, and it is the single biggest argument against a fully autonomous
control half.

## Source

USNRC Human Resources Training and Development, *Westinghouse Technology Systems
Manual, Section 12.2: Reactor Protection System - Reactor Trip Signals*,
Rev 0109. NRC ADAMS accession `ML11223A301`. Public domain, US government work.
Tables 12.2-1 (21 reactor trips), 12.2-2 (14 protection-grade interlocks) and
12.2-3 (control-grade interlocks) are the dense reference.
