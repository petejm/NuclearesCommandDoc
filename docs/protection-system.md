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

**No resistor-bank overheat protection.** Measured live: `Resistor_Bank_01`,
absorbing about 19.4 MW, held `Temperature` at 29.64 C, rising to only 29.65 C
over 10 seconds, with no automatic response of any kind and no automatic
load-shed to the other banks. `RESISTOR_BANKS_JSON` exposes `Temperature` per
bank as an instrument, but the game takes no protective action on it. The
human operator had to intervene manually and close MSCV to keep the single
installed bank from overheating.

The compounding factor: of the four banks the manifest defines,
`RESISTOR_BANKS_JSON` shows only `Resistor_Bank_01` with `IsInstalled: 1`.
Banks 02 through 04 read `IsInstalled: 0` with `Temperature: 0.0`, and their
switches, `RESISTOR_BANK_02_SWITCH` through `RESISTOR_BANK_04_SWITCH`, all
read `False`, alongside `RESISTOR_BANK_01_SWITCH` and
`RESISTOR_BANKS_MAIN_SWITCH` both reading `True`. So every watt the grid does
not take lands on one bank, not four.

This is the fifth protection found missing in this repository, in the same
honest style as the pressurizer heater cutoff in
[reference-control-laws.md](reference-control-laws.md): the game exposes the
instrument, `Temperature` per bank, but provides no protective action, so
only an operator or a client watching that instrument can act.

**The operating rule this implies, from the operator:** on this plant, more
steam does not mean more useful power. The grid takes only what it demands,
`POWER_DEMAND_MW`, and everything generated above that becomes heat in the
resistor banks. Measured live: generating 26,548 kW against a demand of 7 MW
dumped about 19.5 MW, 73.6 percent of generation, into the bank. Later in the
same session generation reached roughly 50 MW against a demand of 10.5 MW,
the same pattern at larger scale. Generation above demand is waste with a
thermal consequence on this plant, not merely inefficiency, and a controller
that maximises steam output without checking demand is choosing to heat a
resistor bank that has no automatic protection.

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
| Loss of forced primary circulation, reactor critical (RCS low flow trips analog) | Below P-7, 10% power | Guarded, and deliberately not gated by regime. See below |

### Why SG low-low level is not guarded as specified

Trip 16 is defined as a percentage of SG nominal level. `COOLANT_SEC_{n}_LIQUID_VOLUME`
is an absolute volume, and no capacity or nominal variable exists anywhere in
the manifest for it, so 11.5% of nothing is not a number `monitor.py` can
compute. This is not a rounding gap or an approximation, it is a missing
input: the real setpoint needs a denominator this API does not expose.

What `monitor.py` substitutes instead is a run-local high-water mark, the
highest `COOLANT_SEC_{n}_LIQUID_VOLUME` observed while the loop's balance
(`RETURN_FLOW_PLUS_CONDENSED` minus `OUTLET`) was not negative, in any
regime, and a percent below that. That is a materially different
measurement from Trip 16. It resets every run, so it cannot generalize across
sessions or a game restart. It can be fooled low, treating an already-depressed
level as the ceiling if the monitor starts mid-drain, which is why the
balance condition, not a regime condition, is what guards the seed. And if
the monitor never observes a sample with balance not negative, the guard
never fires at all, silently, by design, because a silent wrong number is
worse than no number. None of that is true of Trip 16, which is derived
from a known plant nominal and holds regardless of any one run's history.

### An instrumentation gap, not a design choice: the primary loop was invisible

Before this fix, `monitor.py` read `COOLANT_SEC_CIRCULATION_PUMP_{n}_SPEED` for
the secondary loop and nothing at all about the primary loop. Primary coolant
flow is a first-order driver of both `CORE_TEMP` and `CORE_PRESSURE`, two of the
numbers this tool watches most closely, so the tool was blind to the cause of
its own headline signals.

Measured live, on a plant with the reactor critical: the operator raised
primary flow from 15 to 25. `CORE_TEMP` fell from about 312.4 to 306.3, roughly
3.8 C per minute, and `CORE_PRESSURE` fell from 170.5 to 161.7 over the same
window. With no column for the cause, the temperature and pressure drop looked
uncaused, and an automated client sitting in that position naturally
misattributes a change like that to whatever it last did itself. That is the
fail-open measurement failure mode this repository documents elsewhere,
showing up on a different signal.

`monitor.py` now reads `COOLANT_CORE_CIRCULATION_PUMP_{0,1,2}_SPEED` and
`COOLANT_CORE_FLOW_SPEED`, surfaces primary flow in the terminal status line
next to core temperature and pressure, and carries a guard for loss of forced
circulation with the reactor critical, the RCS low flow trips analog. That
guard is the subject of the next section.

### A permissive gates a mismatch, never a level or a state

The reference above seeds in any regime, not only at power, and that was a
fix, not the original design. The first version gated the seed by
`regime() == "at_power"`, on the same reasoning as the Trip 17 analog: a
guard correct at power can be wrong during startup. That reasoning does not
transfer to a level, and Trip 16 itself is the evidence: `2/3` on `1/4` SGs,
**no interlocks**, per the table above. A flow mismatch, the subject of
Trip 17, is genuinely regime dependent, expected during startup while the
bypass and the ejectors draw steam, which is why Trip 17 carries the `P-7`
permissive. A level is dangerous in every regime, which is why the real
plant gates it with nothing at all. Applying a permissive to a level guard
is a category error, and the effect was concrete: gating the seed by
`at_power` made the level guard inert during exactly the phase this
document already describes a secondary draining in, turbine startup and
synchronisation.

Measured on a live plant, minutes apart: at 21:18, secondary liquid 44586,
balance +39 (outlet 11, return 50), a clean sample that should have seeded
the reference. At 21:26, secondary liquid 27141, balance -21.4 (outlet 71,
return 50), falling roughly 33 units/s, a 39% drop from the first reading.
Regime was `startup` at both timestamps, so the `at_power`-gated code never
seeded a reference, and the inventory guard had nothing to compare against;
the monitor logged only `[INFO] steam draw exceeds return`, no CRIT. With
the gate removed, the reference seeds at 44586, and the fraction at 21:26 is
`(44586-27141)/44586 = 0.391`, which crosses the 0.30 CRIT threshold given
the falling trend. That is the case that exposed the bug.

This does not make the run-local reference Trip 16. It is still a run-local
high-water mark, not a plant nominal, still reset every run, and still
silent if no sample with balance not negative is ever observed. The fix
only removes a gate that should never have been there; it does not close
the calibration gap described below.

The same rule applies a second time in this file, to a different kind of
guard. Loss of forced primary circulation with the reactor critical is
guarded by `CORE_STATE` reading `REACTIVO` together with primary flow
reading absent, either `COOLANT_CORE_FLOW_SPEED` at 0.0 or all three
`COOLANT_CORE_CIRCULATION_PUMP_{n}_SPEED` readings at 0.0. That is a STATE,
not a mismatch between two variables, and it is dangerous in every regime,
including startup, for the same reason a level is: heat production does not
pause for plant regime. The RCS low flow trips this guard mirrors carry no
such exception on the real plant either, they exist specifically so a
critical core is never left without a heat removal path. So this guard,
like the inventory-reference seed above it, is not gated by `regime()`.

Honest deviation from the reference architecture, stated plainly rather
than left as an oversight: the real RCS low flow trips ARE gated by `P-7`,
below 10% power, because there is not enough heat below that point to
matter. `monitor.py` does not gate on `P-7` here, and the reason is a
missing input, not an oversight. No computable power fraction exists
anywhere in this API, see "The calibration gap" below, so a literal `P-7`
gate cannot be built, and `regime()`'s substitute for `P-7`, generator
carrying load and `CORE_OPERATION_MODE` at `NOMINAL`, is a proxy for load,
not a measurement of power fraction. Gating a critical-core guard on a
proxy that could be wrong in exactly the direction that suppresses a real
emergency is worse than leaving the guard armed everywhere the core reads
critical. The guard stays armed in every regime as a deliberate, documented
choice, not a stand-in for the real permissive.

### The calibration gap

Two computations a client would want are blocked by the same kind of missing
denominator, one for each of the two protections above that fall short of the
real setpoint.

**Power fraction.** Trip 18 is gated by P-7, 10% of rated power. `CORE_STATE_CRITICALITY`
is reactivity, not a power fraction. `GENERATOR_{n}_KW` is documented
elsewhere in this repository as trustworthy only when `GENERATOR_{n}_A` is
above zero, and fabricated otherwise (see
[`../tools/README.md`](../tools/README.md), `tools/checklist.py`, and
[value-semantics.md](value-semantics.md)). No `CORE_THERMAL_POWER` variable
exists anywhere in the manifest. So a literal percent-of-rated-**thermal**-power
gate is not computable, and `regime()` substitutes "the generator is
actually carrying load, `GENERATOR_{n}_A` above zero, and
`CORE_OPERATION_MODE` reads `NOMINAL`", which is what P-7 is really asking,
without the missing denominator.

**Update 2026-07-28: the denominator half of this gap is resolved for
electrical power, the thermal-power half is not.**
`POWER_MAX_THEORETICAL_PLANT_OUTPUT_MW` reads 400, a genuine rated-output
constant for this plant's installed configuration (see
[value-semantics.md](value-semantics.md)). Paired with `GENERATOR_{n}_KW`
when `GENERATOR_{n}_A` is above zero, that supplies a computable electrical
percent-of-rated-output figure. It is still not the literal P-7 permissive:
Westinghouse defines P-7 against 10 percent of rated **thermal** power, and
no thermal-power variable exists anywhere in this API. An electrical-output
gate built on 400 is a proxy for P-7, not the permissive itself, and must be
labelled as one. `regime()`'s substitute is unchanged by this: it still
gates on load and mode, not on the new proxy, pending a decision about
whether the proxy is worth adopting over the existing substitute.

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
