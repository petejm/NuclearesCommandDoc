# tools

## `probe.py`

Measures what a POST actually does, without attributing background drift to your
command.

```bash
python3 tools/probe.py CONDENSER_VACUUM_PUMP_START_STOP START \
  --watch CONDENSER_VACUUM_PUMP_ACTIVE CONDENSER_VACUUM CONDENSER_PRESSURE \
  --readback CONDENSER_VACUUM_PUMP_ACTIVE
```

Outputs JSON with a verdict, the effects that survived drift subtraction, and
the method parameters used, so a result can be reproduced or disputed.

### Verdicts

| Verdict | Meaning |
|---|---|
| `CONFIRMED` | The read-back variable now equals the value posted. The strongest result |
| `EFFECT` | Something moved that did not move during the matched null, but the read-back did not confirm |
| `NO_EFFECT` | HTTP 200 and nothing attributable moved |
| `NOT_WRITABLE` | HTTP 404. The name is not in the writable surface |
| `GATED` | HTTP 412. Writable but behind a consent gate |

`NO_EFFECT` and `CONFIRMED` are both HTTP 200. That is the entire reason this
tool exists: see [../docs/wire-format.md](../docs/wire-format.md).

### Why it is built this way

Each rule below exists because breaking it produced a wrong published result.

**Fail closed.** Every request resolves to a value, a documented not-found, or
an `ERROR`, and `ERROR` never collapses into the other two. An earlier harness
counted connection failures as successful reads and reported "91 readable, 0
write-only" when the answer was 35 and 56. It looked complete and confident and
was inverted.

**Multi-sample matched nulls.** Before writing anything, the harness samples
every watched variable N times with no POST issued, and records which ones move
on their own and by how much. A variable that drifted during the null must then
exceed twice its observed spread to count as an effect.

A single before/after null pair is not enough. If the signal's period is
comparable to the settle window, both samples can land at the same phase of a
sawtooth and the variable looks static. That aliasing put three pressure
variables into all 10 results of an earlier emergency-control sweep as false
positives.

**No baked-in constants.** Drift rate here is plant-state dependent, not a
property of the game. A 140-sample capture found the pressure variables
completely static in conditions where an earlier session had measured them
falling steadily. Every probe therefore derives its own baseline immediately
adjacent in time, and none is reused.

**Explicit read-back name.** 56 of 91 writable variables are write-only. Pass
`--readback` with the correct twin from
[../docs/writable-variables.md](../docs/writable-variables.md), because for most
variables you cannot read the name you just wrote.

**Positive control on the listener.** Reachability is checked with `ss`, not by
attempting a connection. The API binds IPv6 loopback only, so a probe over the
wrong address family shares the broken component it is testing and cannot detect
its own fault. That produced two 15-minute false "port never bound" reports.

### Safety

Two blocklist tiers, both enforced in code rather than by convention:

- **`FUN_*` is refused unconditionally.** These are trigger writes; the act of
  writing is the action, so the usual "write the current value back" no-op
  pattern does not exist for them. See
  [../docs/fun-family.md](../docs/fun-family.md).
- **`CORE_SCRAM_BUTTON`, `CORE_EMERGENCY_STOP`, `STEAM_TURBINE_TRIP` require
  `--allow-dangerous`.** Not because they harm the game, but because the API has
  two working trip paths and no working reset, so an automated caller can abort
  and cannot recover. See
  [../docs/emergency-controls.md](../docs/emergency-controls.md).

Test writes on a throwaway save.

### Before trusting a negative result

Check `STEAM_TURBINE_{n}_INSTALLED` and the equivalent for other indexed
equipment. Uninstalled units return confident, permanently-zero values, so an
experiment aimed at one measures nothing while looking like a clean negative.

Do not run immediately after a save load. The webserver unbinds on load and
needs re-enabling, and settled values differ sharply from the first readings
back.

## `checklist.py`

Tracks the in-game startup checklist (the `[C]` key) against live telemetry.

```bash
python3 tools/checklist.py --loop 3
python3 tools/checklist.py --loop 3 --watch 5
```

The in-game checklist records what you **clicked**. This records what the plant
is **doing**. They diverge, and the gap is where the interesting failures live: a
command can be stored while the actuator is still slewing, an indexed variable
can be `null` because that fuel bay is empty, and HTTP 200 certifies nothing.

Pass `--loop` as the **in-game** loop number. The API index is one lower.

### Statuses

| Status | Meaning |
|---|---|
| `OK` | Telemetry satisfies the item |
| `DONE` | Satisfied earlier, now superseded by a later item |
| `SLEWING` | Ordered value is correct, actual is still travelling |
| `PENDING` | Not satisfied yet |
| `NO-SIGNAL` | **No API variable exists.** Not a pass |
| `NO-REF` | Observable, but the threshold is not knowable from the API |
| `ERROR` | Could not read. Never silently treated as pass or fail |

`NO-SIGNAL` is load-bearing, not padding. Activating terminals, the external
power switch, the grid startup request and the breaker close have no variable at
all, so an automated client can neither perform nor verify them. Surfacing that
is the point: it makes the hole in the commandable surface visible instead of
implicit.

`NO-REF` currently covers two items. `Retention Tank ~50%` has no capacity
variable anywhere in the manifest, so a percentage cannot be computed; the raw
volume is reported instead of a guess.

### Supersession

Several checklist items are staged: bypass goes 100 then 0, MSCV goes 0 then
`>=25`, the startup motive valve goes 100 then 0, the vacuum pump goes `STARTUP`
then `OPERATIONAL`. Once the later item is satisfied the earlier one legitimately
stops matching, and calling that `PENDING` reads as a regression. Those are
reported `DONE` with the item that superseded them.

### Two traps this tool exists to avoid

**`GENERATOR_{n}_BREAKER` carries no information.** It reads `True` on idle and
uninstalled units alike.

**`GENERATOR_{n}_KW` is not delivered power during spin-up.** Observed reading
**33702 kW at 15.14 Hz with 0 amps**, while `POWER_FROM_TURBINE_KW` read 210.6.
It appears to be a potential figure. An earlier version of this tool checked
`kw > 0` and consequently reported a successful grid sync for a generator
delivering nothing. The check now uses **amps**, cross-referenced against grid
frequency.

That bug is recorded rather than quietly fixed because it is the same failure
this repository keeps documenting: a plausible variable that reads like success.

## `monitor.py`

Steady-state monitor for a running plant. Stays quiet unless something needs an
operator.

```bash
python3 tools/monitor.py --loop 3 --interval 15
python3 tools/monitor.py --loop 1 --interval 10 --count 20 --log run.tsv
python3 tools/monitor.py --loop 3 --down-threshold 10 --poll 1
```

`--loop` selects **which** secondary loop to watch, 1, 2 or 3. It is not a
repeat count. `--count` is the repeat count, and defaults to 0, meaning run
until interrupted, not run zero times.

**Read-only.** The file contains no write method at all. That absence is the
safety guarantee, rather than a flag someone could flip.

### Severity levels

| Severity | Meaning |
|---|---|
| `ERROR` | A variable could not be read. Never collapses into a healthy reading, except for a wholesale API outage, see below, which is one fact and is reported once |
| `CRIT` | Needs operator action now |
| `WARN` | Needs attention, not yet urgent |
| `INFO` | A condition that would be WARN or CRIT at power, downgraded because `regime()` has positively established the plant is in startup. Downgraded, not suppressed, it still prints every time |

### The guards are relational

The two conditions that nearly emptied a secondary loop during testing were both
comparisons between variables, and **no single-variable limit or rate check
could express either**:

| Guard | Condition |
|---|---|
| Steam balance | `RETURN_FLOW` vs `OUTLET`. A negative balance with falling inventory is CRIT |
| Boiling | `COOLANT_SEC_{n}_TEMPERATURE` vs `STEAM_GEN_{n}_BOILING_POINT`, which **moves with pressure** |
| Grid sync | amps > 0 checked against frequency and RPM together |
| Margin | core temp and pressure against their own `_MAX` variables |
| Integrity | with the 70% continuous-bleed threshold called out explicitly |

An absolute temperature limit cannot catch "not boiling", because the boiling
point is itself a live variable that was observed moving between 215 and 321
within one session.

### Gate by regime, don't suppress on doubt

`Monitor.regime()` classifies the plant as `at_power`, `startup` or `unknown`,
the way a real RPS permissive like P-7 gates trips by plant condition: a guard
that is correct at power can be wrong during startup, when the checklist calls
for MSCV `>= 25` and the loop is deliberately unbalanced.

The direction of the gate is the load-bearing part, not its mere existence.
`unknown` gates exactly like `at_power`, never like `startup`. Only a
positively established `startup`, both `amps` and `op_mode` readable and not
consistent with carrying load at `NOMINAL`, may downgrade a guard to `INFO`.
The risky failure mode for a regime gate is suppression, not over-alerting: a
gate that fails open when it cannot read the regime would disarm protection at
exactly the moment telemetry has degraded, which is the one moment protection
matters most.

### The turbine-trip guard is a transition detector, not a latching trip

The turbine-trip guard, the Trip 18 analog covering reactor trip on turbine
trip, which Nucleares does not implement, fires by comparing current
`STEAM_TURBINE_{n}_PRESSURE` against the highest pressure this run's own
history has seen. It exists because a turbine that never started and a
turbine that tripped read identically on pressure alone, and only the history
tells them apart.

That history lives in a `deque(maxlen=30)`, so the guard has a finite, bounded
memory: once the pre-trip pressure ages out of the window, the guard stops
firing even if the turbine is still down. That is intentional. This is a
transition detector built to catch the moment of collapse, not a latching
trip that remembers a fault forever.

### The run-local inventory guard has no plant nominal to compare against

`COOLANT_SEC_{n}_LIQUID_VOLUME` has no capacity or nominal variable anywhere in
the manifest, so a percent-of-nominal guard, the actual Trip 16 form, is not
computable (see [`../docs/protection-system.md`](../docs/protection-system.md)).
The guard instead tracks a run-local high-water mark, raised only while the
loop looks healthy, `at_power` with a non-negative balance, and alerts on
percent below that mark.

The documented weakness is deliberate, not a bug: if the monitor is started
mid-drain and never observes a healthy at-power sample, no reference is ever
established, and this guard cannot fire even though the plant is genuinely
low. A silent wrong number is worse than no number, so it stays silent instead
of guessing. `tools/test_monitor.py` asserts this behavior directly rather
than treating it as an oversight.

### Guard the integral, not the derivative

Inventory alerts use level plus net balance, never a rate sampled over one
interval. Several of these signals are stepped sawtooths, so a short-window rate
is noise: a tank was observed holding a value for 10 s and then jumping.

### A deviation that is closing is not an alert

The pressurizer check suppresses its warning when the deviation is already
shrinking. A plant correcting itself does not need an operator, and alerting on
it trains people to ignore the alert. Observed converging 172.4 to 158.4 across
one run with no intervention.

### Fail closed

An unreadable variable raises `ERROR`. It never reads as healthy.

### The API outage watch

A monitor instance was once found running 2 hours after the game had
exited. It had written 5,740 lines and 370 KB, entirely per-variable
`[ERROR] unreadable <NAME>: URLError` alerts, roughly 24 of them per cycle,
one for every watched variable. It never once said the webserver was gone,
only that every individual thing it asked for had failed. That is the
defect this section closes.

**`localhost`, never `127.0.0.1`.** Liveness is checked with a plain socket
connect, `api_alive()`, to `("localhost", 8785)`. The host must resolve
through the name, not a hardcoded IPv4 literal:
[`../docs/wire-format.md`](../docs/wire-format.md) documents that this API
binds `[::1]:8785`, IPv6 loopback only. A `127.0.0.1` literal would never
reach that socket, so a client hardcoding it would report a permanent false
outage regardless of whether the game is actually running. `api_alive()`
replaces the older `ss`-based check: `ss` is Linux only, and this gets
called on every poll tick for hours at a time, so a subprocess per check is
wasted work a plain connect avoids.

**The ERROR collapse rule.** A wholesale outage and a single bad variable
are different facts and must not be conflated. If every entry in one
snapshot's error list is a transport-level failure (`URLError`, `timeout`,
`TimeoutError`, `ConnectionRefusedError`, `OSError`, `gaierror`, the names
`read()` can produce for a socket/HTTP failure) and there are more than a
handful of them, `alerts()` collapses them to a single
`API unreachable: all N variables unread (...)` `ERROR`. A single
unreadable variable, or a mix of transport and non-transport failures (for
example a name that does not exist on this build, alongside real transport
failures), is a genuine per-variable signal and is **not** collapsed, it
still gets its own `unreadable <NAME>: <reason>` line. Hiding that signal
inside a summary would be its own kind of going quiet.

**Outage duration, WARN below threshold, CRIT beyond it.**
`Monitor.note_liveness()` and `Monitor.outage_secs()` track how long the API
has been continuously unreachable, using `time.monotonic()` rather than
wall clock so a suspend/resume or NTP jump cannot corrupt the duration.
Below `--down-threshold` (default `10.0`s) the outage alert is `WARN`,
`"API unreachable for Ns. Expected briefly during a save load, the
webserver unbinds"`, because the webserver unbinds on save load and a brief
outage is benign
([`../docs/wire-format.md`](../docs/wire-format.md)). At or beyond the
threshold it escalates to `CRIT`, `"...beyond the Ns threshold. The plant
is UNOBSERVED, no guard below is running"`, because a sustained outage
means the game exited or crashed, not a save load, and every guard in this
file is silently inert while it is None all the way down. Recovery prints
once, `"API was unreachable for Ns, readings resumed"`, on the first
snapshot after the API comes back, not on every snapshot afterward.

During an outage `alerts()` can never return an empty list, that is the
whole point: it is what stops `main()` from printing `all guards clear`
while the plant is actually unobserved. `tools/test_monitor.py` asserts
this directly.

**The period-vs-threshold granularity trap.** `--interval` defaults to 15s.
A 10s `--down-threshold` checked only once per snapshot could never
actually resolve, an outage can start and fully end inside a single 15s
sleep and nobody would ever see it cross the threshold. `--poll` (default
`1.0`s) is how often liveness is checked **while sleeping between
snapshots**, independent of `--interval`, and it is what makes
`--down-threshold` observable at all: a threshold finer than the sample
period is decorative unless something polls faster than it samples. If
`--down-threshold` is set finer than `--poll`, `monitor.py` warns on
stderr at startup rather than exiting, the run is still usable, just
coarser than requested.

### Running the tests

```bash
python3 tools/test_monitor.py
python3 -m unittest discover -s tools
```

Both invocations run all 26 tests. Bare `python3 -m unittest` from the repo
root discovers 0 tests: `tools/` deliberately has no `__init__.py`, and
unittest's default recursive discovery skips directories that are not
packages.
