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
