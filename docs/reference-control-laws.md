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
fully uncovered. That pressurizer carried two `deterioration_logs` entries at
the time of that `maintenance_summary` capture, one `ALTA_PRESION` and one
`ALTA_TEMPERATURA` (see [diagnostics-endpoint.md](diagnostics-endpoint.md),
"Deterioration logs name the cause", same `90.51`% integrity reading), not
three `ALTA_TEMPERATURA` entries as an earlier draft of this document stated.
`maintenance_summary` is a stale snapshot, not live telemetry (see the same
document, "The staleness trap"), so this deterioration history is as of that
capture's `analysis_timestamp`, not necessarily current.

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

## Fuel depletion, rod compensation, and which constraint actually binds first

Section 2.1, Reactor Physics Review (`ML11223A207`), same source as the
xenon material above.

### Measured rates

`CORE_FUEL_1_FISSIONABLE` fell from `94.5660` to `94.4900` over 38 game-minutes,
`0.12` fissionable per game-hour. At that rate, roughly `787` game-hours, about
`32.8` game-days, remain before the loaded bay is exhausted.

**`CORE_FUEL_AVG_POWER_FACTOR` is not an average of the per-bay power
factors, despite the name.** It equals `FISSIONABLE / 100`: it reaches zero
at the identical time the fuel does, roughly 787 game-hours out, while the
only loaded bay's `CORE_FUEL_1_POWER_FACTOR` reads about `0.60` at the same
moment. Those are different numbers describing different things, and the
`AVG` in the name is misleading on this plant, where only one bay is
loaded. Not previously documented anywhere in this repository; recorded here
so it is not assumed from the name elsewhere.

**Rod compensation rate is derived, not independently measured, and it
lands inside the operator's own observed range, which is consistency, not
convergence.** Computed from the fuel burn rate times the rod-per-fuel
ratio: rods withdrawn divided by fuel consumed, `4.0` rod units over `5.53`
fissionable gives `0.723`, and `0.723` times the `0.12`/game-hour burn rate
gives `0.0868` rod units per game-hour. Reported separately from the
operator's own observed practice, without reference to the calculation:
`0.05` to `0.10` per game-hour. The derived figure falls inside that range,
but a single point estimate landing inside a range spanning roughly a
factor of two is consistency, not independent convergence: this is one
derived number and one wide operator-reported band that happens to contain
it, not two independent methods arriving at the same answer.

### What real PWRs do instead, and why this plant cannot

Differential control rod worth peaks at roughly **40 percent withdrawn**,
and is **lowest** near fully inserted and near fully withdrawn (WTSM 2.1).
This plant's rods sit at `88.5`, and `100` is fully inserted here, so the
rods are `11.5` percent withdrawn: deep in the low-worth region, nowhere
near the peak. The consequence is that required withdrawal-per-hour is a
**curve**, not a constant, and should fall as the rods withdraw toward the
worth peak rather than staying at the `0.0868` figure derived above.

WTSM 2.1 also describes how a real Westinghouse plant actually compensates
for fuel depletion: it **dilutes soluble boron** while keeping the rods
nearly fully withdrawn, which optimises the power distribution across the
core and preserves shutdown margin. Rods are the fine control, boron is
the bulk compensation.

**This plant has no such option, and that is a fact about its
configuration, not about the operator.** The chemicals subsystem is
disabled (see [value-semantics.md](value-semantics.md), "Undocumented
readable variables"), so boron dilution is unavailable here. Rods are
structurally the only reactivity lever this plant has, which makes rod
life the genuine binding constraint of this configuration. State that
plainly: this is not an operating error, it is what running without the
chemistry subsystem means.

### Constraint ranking: fuel is last, not first

Every row below is recomputable on its own: measured rate, assumed limit,
and the arithmetic that produces the time-to-limit figure.

| Variable | Measured rate | Assumed limit | Time to limit |
|---|---|---|---|
| `CORE_WEAR` | `+0.783`/game-hour (current `29.01`) | `100` | `(100 - 29.01) / 0.783` = 90.7 game-hours = 3.8 game-days |
| `CORE_FUEL_1_POWER_FACTOR` | `-0.00586`/game-hour (measured `0.58504` to `0.58055` over 46 game-minutes; current `0.5806`) | `0` | `0.5806 / 0.00586` = 99 game-hours = 4.1 game-days |
| Rod travel (`ROD_BANK_POS_0_ACTUAL`) | **two regimes, see below** | `88.5` remaining before the travel limit | 9.4 game-days at the active-adjustment rate, or 42.5 game-days at the steady compensation rate |
| Fuel (`CORE_FUEL_1_FISSIONABLE`) | `0.12`/game-hour (current `94.49`) | `0` | `94.49 / 0.12` = 787 game-hours = 32.8 game-days |

**Rod travel has two rates, not one, and publishing a single number without
saying which regime it came from is not reproducible.** `0.391` rod units
per game-hour is the observed withdrawal rate while the operator was
**actively adjusting** rods (`89.0` to `88.7` over 46 game-minutes). `0.0868`
rod units per game-hour is the derived **steady compensation** rate for
holding station against fuel depletion (see "Fuel depletion, rod
compensation..." above). These describe two different regimes this
repository already distinguishes elsewhere, active adjustment versus holding
station, not one constant rate:

- At the observed active-adjustment rate: `88.5 / 0.391` = 226 game-hours =
  **9.4 game-days**.
- At the derived steady compensation rate: `88.5 / 0.0868` = 1019 game-hours
  = **42.5 game-days**.

**Fuel, the constraint every player-facing gauge foregrounds, still does not
bind first.** Wear binds roughly 8.6 times sooner than fuel. Where fuel
ranks second-to-last depends on which rod-travel regime applies: at the
active-adjustment rate, rod travel binds before fuel too, at 9.4 days; at
the steady compensation rate, rod travel binds after fuel, at 42.5 days.
That is not a contradiction in the ranking, it is the regime distinction
above determining the order.

Two of these figures also carry an honest caveat the ranking itself does
not show: the `CORE_WEAR` and `CORE_FUEL_1_POWER_FACTOR` figures depend on
assumed limits, `100` and `0` respectively, neither confirmed as a hard
ceiling for those specific variables, and every figure here comes from
linear extrapolation of short observation windows on a plant whose rates
are not guaranteed constant. Treat this ranking as a snapshot of the
current trajectory, not a certified schedule.

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

### A settled-gain measurement, not a full characterization: primary flow versus core temperature

The first clean data point this method has produced, put here because it
is what the section above calls for and because the earlier confounded
attempts are recorded honestly rather than quietly dropped.

**This is a settled-gain measurement, not a full step-response
characterization.** The section above defines characterization as gain plus
dead time plus time constant, three numbers. Only gain was measured in this
run. Dead time (the delay before core temperature starts moving) and time
constant (time to reach 63.2 percent of the total change) were **not
measured here and remain open.**

Primary circulation was stepped from 25 to 30 and held there for 300 real
seconds, roughly 120 game-minutes at this session's time acceleration of
approximately 24x. Real wall-clock time is the wrong clock for a rate under
time acceleration (see [value-semantics.md](value-semantics.md), section
13), which is why the game-clock figure is given here alongside the raw
real-time duration the measurement was actually taken against. The baseline
was independently verified settled going into the step, drifting at only
`-0.045` C/min. Core temperature moved from `339.55` to `336.74` C over the
hold, a raw change of `2.81` C.

**Two gain figures follow from that; use the drift-corrected one.** Over the
300 second hold, the settled `-0.045` C/min baseline drift accounts for
`0.225` C of the 2.81 C move on its own, before primary flow is credited
with any of it:

| | Change | Gain per unit of primary flow |
|---|---|---|
| Raw | `2.81` C | `-0.562` C |
| Drift-corrected (`2.81 - 0.225`) | `2.585` C | `-0.517` C |

**`-0.517` C per unit of primary flow, the drift-corrected figure, is the
one to use.** Publishing the raw gain without subtracting the settled
baseline drift attributes part of the plant's own background drift to the
step, which is exactly the matched-null discipline this repository's probe
harness enforces on every POST (see [tools/README.md](../tools/README.md),
"Multi-sample matched nulls" and "No baked-in constants"). The same
discipline applies here even though this measurement was taken by hand
rather than through `probe.py`.

**Settling evidence.** An independent check taken at the end of the 300
second hold measured temperature still moving at `-0.04` C/min, close to
the `-0.045` C/min baseline it started from and far below the rate during
the active part of the transient. That is the basis for treating the hold
as settled by t=300 rather than still actively responding to the step.

**Zero rod corrections were required.** The 2.81 C excursion stayed inside
a 3.0 C deadband for the whole run. That deadband is not a game or repo
constant: it is the tolerance configured in this session's own hold-test
harness, an operator-chosen tolerance for this run, not a documented plant
setpoint.

**Confounder check passed.** Rods, MSCV, `POWER_DEMAND_MW`, condenser
pressure and `CORE_STATE` each held exactly one distinct value for the
entire 300 seconds, which is what makes this attributable to primary flow
alone rather than another cautionary confounded case like the two above.

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
