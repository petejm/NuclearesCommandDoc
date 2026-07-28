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
