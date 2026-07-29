# Reference control laws from a real PWR

Nucleares simulates a Westinghouse-style PWR, and the USNRC publishes its
operator training material for exactly that plant. Where this repository has been
reverse-engineering behaviour, those documents state the intended control law
outright.

This page records the laws that map onto systems Nucleares exposes, and cites
the source section so you can read the original.

Source series: **Westinghouse Technology Systems Manual**, USNRC HRTD, public
domain. Cited by NRC ADAMS accession number, e.g. `ML11223A293`.

## Three-element feedwater control

Section 11.1, Steam Generator Water Level Control System (`ML11223A293`).

This is the system that governs the failure mode most likely to catch a Nucleares
operator: the secondary loop draining while every valve looks correct.

**Inputs**, four of them:

| Input | Note |
|---|---|
| Steam flow | **pressure-compensated**, because steam is compressible and mass flow depends on density |
| Feedwater flow | no compensation needed, water is incompressible |
| Actual SG level | single channel, no alternate |
| Programmed level | generated from turbine first-stage (impulse) pressure |

**The control law, quoted:**

> An opening signal to the valve results when either (1) the actual level is less
> than the programmed level or (2) feed flow is less than steam flow. A closing
> signal results from one of the converse conditions.

Two errors are computed and summed:

```
level error = programmed level - actual level      -> PI controller, 2 min integral
flow  error = steam flow - feed flow
total error = level error + flow error             -> PI controller -> valve position
```

**Why the integral time constant is two minutes:** it lets the *flow* error
control the valve first, and prevents rapid response to level error. Level is the
slow, authoritative signal; flow mismatch is the fast one.

That ordering is the design insight. A controller that chases level directly will
fight the transient. One that acts on flow mismatch first and lets level integrate
in behind it will not.

**Programmed level tracks power**, since impulse pressure is proportional to power:

| Power | Programmed narrow-range level |
|---|---|
| Hot zero power | 33% |
| ramps linearly to 20% power | 33% -> 44% |
| 20% to 100% power | constant 44% |

**Below 20% power the loop is manual**, through smaller bypass valves. Automatic
three-element control only runs from 20% to 100%. That is a real plant declining
to automate a regime where the signals are poor, and it is a reasonable precedent
for a copilot that hands startup back to a human.

## Shrink and swell: level moves the wrong way first

The same section explains why the actual level signal is passed through a lag
unit before use:

> Lagging the actual level signal prevents shrink and swell effects from masking
> actual steam generator inventory changes and thus allows the flow error to
> initially control the feed regulating valve position during a transient.

During a load *reduction* the level **shrinks**; during a load *increase* it
**swells**. Both are the opposite of what inventory is actually doing, because
changing pressure changes the void fraction in the water.

**Consequence for any monitor:** steam generator level is not trustworthy during
a transient. A guard that reads level alone will alarm on a swell that is not a
real inventory gain, and stay quiet through a shrink that is. The mass balance
(`steam flow` vs `feed flow`) is the honest signal in the first seconds, and
level becomes authoritative only after things settle.

This repository's monitor already alerts on balance **and** level together, which
is the correct pairing for the wrong reason: it was derived from a measured
deficit, not from knowing about shrink and swell.

The 44% programmed level is itself chosen so that the shrink during a 50% load
reduction does not reach the low-low level trip, and the swell during a 10% step
load increase does not back water up into the moisture separators. The setpoint
exists to absorb both directions of the artefact.

## Pressurizer level is programmed, not held constant

Section 10.3, Pressurizer Level Control System (`ML11223A290`).

A constant-level pressurizer would be simple and wrong. As coolant heats it
expands, level rises, the controller cuts charging flow, and with letdown fixed the
plant ends up diverting coolant to the holdup tanks as liquid waste. On cooldown
the reverse puts a large demand on makeup.

So **level is programmed as a function of auctioneered high Tavg**, following the
natural thermal expansion of the coolant. It is supposed to move.

### The interlocks, and the one that matters most

| Level | Action |
|---|---|
| **17%** | Low alarm, isolates letdown (letdown isolation valve plus all orifice isolation valves), and **turns off all pressurizer heaters** |
| 25% | Programmed low limit. Prevents emptying after a reactor trip, and ensures a 10% step load increase does not uncover the heaters |
| program +5% | Energizes backup heaters, anticipating the pressure reduction from a cool insurge |
| 61.5% | Programmed high limit. Keeps the pressurizer from going solid after a turbine trip from 100% with no reactor trip |
| 70% | High alarm, redundant letdown isolation, heaters off |
| 92% | Reactor trip |

The 17% heater cutoff exists for a blunt reason, quoted:

> the heater cutoff protects the heaters which would be damaged if operated in a
> steam environment.

**Nucleares has no equivalent interlock.** A plant was observed live with
`PRESSURIZER_HEATERS_ON = True` at `PRESSURIZER_FILL_LEVEL = 0.4626`, which is
0.46%, roughly sixteen points below the real cutoff. The heaters were running
fully uncovered. That pressurizer carried three `ALTA_TEMPERATURA` deterioration
entries and integrity down to 90.51%.

This is the fourth protection found missing, and the most awkward: the API cannot
command the heaters either, so **only a human can prevent it.** A monitor can
alarm on it, and should.

For calibration, a healthy Nucleares pressurizer reads `FILL_LEVEL = 60`, which
sits just under the real programmed high limit of 61.5%.

### A second instrumentation artefact

Level is measured as a differential pressure between a sealed reference leg and
the variable leg inside the vessel. Water density varies with temperature, so
**indicated level depends on pressurizer temperature**, and the transmitters are
calibrated against it. Real plants carry a separately cold-calibrated transmitter
used only in cold shutdown or while drawing a steam bubble, and it is deliberately
excluded from control and protection.

Same lesson as shrink and swell: the level reading is a derived quantity with
known lies in it.

## Steam dump: the turbine bypass has four jobs

Section 11.2, Steam Dump Control System (`ML11223A294`). This is what
`STEAM_TURBINE_{n}_BYPASS_ORDERED` corresponds to.

Its purpose is to remove excess energy when reactor power exceeds secondary load,
which happens whenever load drops faster than the rods can follow.

**The rate limit worth memorising:** the automatic rod control system can absorb a
**5%/min ramp or a 10% step** decrease in power without a trip. Beyond that, the
steam dump has to make up the difference. A 40% dump capacity plus the rod
system's 10% step is what allows a **50% load rejection without a reactor trip**.

The four modes:

| Mode | Purpose |
|---|---|
| Tavg | Accept a 50% loss of load without a trip |
| Tavg | Remove stored energy and decay heat after a turbine trip, returning to no-load without lifting SG safety valves |
| Steam pressure | Control steam pressure at low or no load; manual cooldown |
| Steam pressure | **Provide constant steam flow during turbine startup and synchronisation, to facilitate manual feedwater control** |

That last mode is the one to notice. During startup and sync, a real plant
deliberately holds steam flow **constant** so that manually controlled feedwater
has a stable target. That is precisely the regime in which a Nucleares secondary
loop was observed draining, with the operator chasing a moving steam demand while
trying to sync a turbine.

The in-game checklist calling for turbine bypass at 100% during startup is the
same idea.

Note also that the steam dump is explicitly **control-grade**, not safety-grade,
and is not required for safe shutdown. It exists to avoid trips, not to prevent
accidents.

## Xenon: the poison that moves the wrong way first

Section 2.1, Reactor Physics Review (`ML11223A207`).

Xe-135 has a thermal neutron capture cross section of **2.6 million barns**. It
is formed only 0.3% directly from fission; the other 5.9% arrives down a decay
chain whose timing is the whole story:

```
Te-135  --19.2 s-->  I-135  --6.6 hr-->  Xe-135  --9.1 hr-->  Cs-135 (stable)
```

Xenon is removed two ways: burnout by neutron capture (fast, proportional to
flux) and radioactive decay (slow, fixed). Production is dominated by iodine
decay, which **cannot change quickly** because iodine's half life is 6.6 hours.

That asymmetry, fast removal against slow production, is why every xenon
transient runs backwards at first.

| Event | Xenon does this **first** | Then |
|---|---|---|
| Power **increase** | **decreases** (burnout jumps, iodine cannot follow) | rises to a *higher* equilibrium, about 96 hr |
| Power **decrease** | **increases** (burnout drops, iodine keeps decaying in) | falls to a lower equilibrium, about 200 hr |
| **Shutdown** | increases sharply, **peaks 8 to 9 hours later** | nearly gone in about 3 days |

Equilibrium after a xenon-free startup takes roughly **48 hours** of power
operation. Any power change takes about **2 days** to settle to its new
equilibrium.

**The trap:** trip a reactor that has been at power, then try to restart near the
8-to-9 hour xenon peak, and the accumulated poison can exceed available rod
worth. The community reports exactly this in Nucleares: a player with rods
withdrawn to 0% who still could not recover and had to shut down. Recovery from
severe xenon poisoning is close to impossible; only prevention works.

Community-reported working numbers for Nucleares: keep iodine generation
**below 2 at all times**, 1.5 to 1.8 while raising power, and both concentration
gauges mid-green. The corresponding API variables are `CORE_IODINE_GENERATION`,
`CORE_IODINE_CUMULATIVE`, `CORE_XENON_GENERATION`, `CORE_XENON_CUMULATIVE`.

## The unifying pattern: fast signals lie during transients

Three independent systems in this manual share one structure, and it is the most
transferable idea here.

| System | The fast signal | How it lies |
|---|---|---|
| Steam generator level | indicated level | **shrinks** on load decrease, **swells** on load increase, opposite to inventory |
| Pressurizer level | indicated level | it is a differential pressure, so it tracks water **density** and therefore temperature, not volume alone |
| Xenon | concentration | **falls** when power rises, **rises** when power falls, opposite to production |

In every case the real plant's answer is the same shape:

1. **Do not act on the fast reading during a transient.** Lag it, or subordinate
   it to something slower.
2. **Act on a balance instead.** Steam flow against feed flow. Charging against
   letdown. Production against removal.
3. **Let the slow signal become authoritative once things settle**, via an
   integral term with a deliberately long time constant (two minutes on the
   feedwater level controller).

This is the same conclusion this repository reached empirically, from a stepped
sawtooth tank gauge and a drift measurement that turned out to be plant-state
dependent: **guard the integral, not the derivative.** It is reassuring to find
it stated as design practice rather than discovered as a bug.

The practical rule for a Nucleares client: when a reading moves sharply, the
first question is not "what is wrong" but "is this the artefact or the thing".
Check the balance before believing the level.

## Characterizing the plant before controlling it

A human operator builds an intuitive model of plant response from experience:
raise the primary pump 10 points, core temperature comes down over the next
minute or so, roughly this much. An automated client has no such prior. Every
response curve it acts on has to be measured deliberately first. In
engineering this is called characterization, and it is a precondition for
control, not an optional refinement.

**The standard artefact is a step response.** Change one input by a known
amount, hold everything else fixed, and watch the output settle. Three
numbers come out of it:

| Term | Meaning |
|---|---|
| Gain | Change in output divided by change in input |
| Dead time | Delay before the output moves at all |
| Time constant | Time to reach 63.2 percent of the total change |

Together these are a first-order-plus-dead-time model, and they are what let
a controller be tuned rather than guessed at.

**One variable at a time, or the result is a correlation, not a
characterization.** Two cautionary cases from this session illustrate the
failure mode directly, both discarded rather than published as data.

An MSCV step from 5 to 10 was run while the operator simultaneously raised
primary flow from 15 to 25. Both changes push core temperature the same
direction. The resulting data cannot yield a gain for either input on its
own, the two effects are confounded, and it had to be discarded as
unattributed.

Second, MSCV at 5 produced about 26.1 MW at one point in the session and
about 29.9 MW at another, because primary flow and grid demand had both
changed in between. The same valve position did not imply the same output.

**This project's plan to split control into a fast deterministic loop and a
slow supervisory loop** (see [protection-system.md](protection-system.md),
"Implications for an automated client") depends on knowing the time
constants involved. Those are currently unmeasured. The split is a sound
architectural instinct, but until a real step response exists for at least
the primary loop and MSCV, it is an assumption, not a design backed by data.

This document was chosen over [operations.md](operations.md) for this
section because it is a control-theory methodology note, not a procedure or
setpoint, and it sits alongside this file's other control-law material
rather than the startup and shutdown checklists.

## Mapping the manual to Nucleares systems

Sections worth reading, ordered by relevance to what this repository documents.

| WTSM section | ADAMS | Nucleares relevance |
|---|---|---|
| 11.1 SG Water Level Control | `ML11223A293` | The draining-secondary failure. Three-element control, shrink/swell |
| 10.3 Pressurizer Level Control | `ML11223A290` | The empty-pressurizer failure. `PRESSURIZER_FILL_LEVEL` is read-only in game |
| 10.2 Pressurizer Pressure Control | `ML11223A287` | Heater and spray logic. Not commandable in game |
| 11.2 Steam Dump Control | `ML11223A294` | Bypass and MSCV behaviour, `C-7`/`C-9` interlocks |
| 12.2 RPS Reactor Trip Signals | `ML11223A301` | 21 trips, 14 permissives. See [protection-system.md](protection-system.md) |
| 12.1 Reactor Protection System | `ML11223A300` | RPS architecture and coincidence logic |
| 7.2 Condensate and Feedwater | `ML11223A246` | The freight/feedwater pumps and makeup path |
| 7.1 Main and Auxiliary Steam | `ML11223A244` | Main steam header, MSCV context |
| 8.1 Rod Control System | `ML11223A252` | `RODS_ALL_POS_ORDERED` and bank sequencing |
| 8.4 Rod Insertion Limits | `ML11223A256` | Why 93% is a sensible rod position |
| 2.1 Reactor Physics Review | `ML11223A207` | Xenon and iodine, temperature coefficients |
| 3.2 Reactor Coolant System | `ML11223A213` | Primary loop, pressurizer surge line |
| 11.3 Westinghouse EHC | `ML11223A295` | Turbine control and the trip header |
| 5.7 / 5.8 Auxiliary Feedwater | `ML11223A229` / `ML11223A232` | The backup heat sink Nucleares does not model |

Retrieve any of these from NRC ADAMS by accession number. They are US government
works in the public domain, and are not mirrored here.

## Caveat on transferring numbers

**Do not port setpoints directly.** A real Westinghouse plant runs the RCS at
2235 psig and 584.7 F; Nucleares runs its core around 160 bar and 300 to 330 C,
with a different geometry and no containment model. The *architecture* transfers
(three-element control, flow error before level error, permissives gating trips
by regime, graduated response before trip). The *numbers* do not.

Where this repository quotes a Nucleares setpoint, it is measured `live-probe` or
taken from the game's own checklist. Where it quotes a real-plant number, it is
labelled as such and used only to explain a principle.
