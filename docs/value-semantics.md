# Value semantics: what the API does with what you send it

Measured `live-probe` at build V 2.2.25.220 on a cold-shutdown plant, sweeping
every variable previously marked "range unconfirmed" with in-range,
out-of-range, negative, fractional and non-numeric values.

The short version: **there is no API-side range validation, and the
`_ORDERED`/`_ACTUAL` pair does not mean what it looks like.**

## 1. `_ORDERED` stores raw. Nothing is clamped on the way in

| Posted | `CHEM_BORON_DOSAGE_ORDERED` reads back |
|---|---|
| `-1` | `-1` |
| `0` | `0` |
| `100` | `100` |
| `101` | `101` |
| `150` | `150` |
| `1000` | `1000` |

Same for `STEAM_EJECTOR_STARTUP_MOTIVE_VALVE_ORDERED` and
`ROD_BANK_POS_0_ORDERED`, which happily stored `1000`.

So "what is the valid range" is the wrong question to ask the API. It will
accept and store nonsense. The range is enforced downstream, if at all.

**Do not treat a successful `_ORDERED` read-back as proof the value was
sensible.** It only proves it was received.

## 2. Clamping happens at the actuator

`ROD_BANK_POS_0_ORDERED` was driven to `101`, `150` and `1000`.
`ROD_BANK_POS_0_ACTUAL` stayed at `100` throughout.

So the physical limit is real, it is just applied by the equipment rather than
by the endpoint. `_ACTUAL` is where the constraint lives.

## 3. `_ACTUAL` slews. It is not a read-back

This is the one most likely to produce a wrong conclusion.

`_ACTUAL` ramps toward `_ORDERED` at a rate limit rather than jumping. Observed
on `STEAM_EJECTOR_STARTUP_MOTIVE_VALVE` at roughly 10 units per 2 s, with
`_ORDERED` set to `-1`:

```
ACTUAL: 100 -> 90 -> 80 -> 70 ...
```

and on the global rod command:

```
RODS_ALL_POS_ORDERED <- 95    RODS_POS_ACTUAL: 100 -> 96.67
RODS_ALL_POS_ORDERED <- 100   RODS_POS_ACTUAL: 96.67 -> 99.17 -> 100
```

**Consequences for a client:**

- To confirm a write was **accepted**, read `_ORDERED`.
- To learn where the equipment **is**, read `_ACTUAL`.
- Sampling `_ACTUAL` immediately after a write measures the slew, not the
  outcome. A probe with a short settle window will report a partial value and,
  worse, will report a *different* partial value each run.

This retires a plausible-sounding but wrong rule of thumb: "read back the
`_ACTUAL` twin to confirm the write." That confirms nothing on any rate-limited
actuator.

## 4. `null` means that fuel position is empty

`ROD_BANK_POS_{n}_ACTUAL` across all nine banks on a fresh save:

| Bank (API) | `_ORDERED` | `_ACTUAL` |
|---|---|---|
| 0 | 100 | **100** |
| 1-8 | 100 | **`null`** |

The reason is the reactor layout, not missing hardware. The core has **9 fuel
positions with 8 control rods each**. `RODS_QUANTITY` reads `8`, which is rods
*per position*, not a count of banks.

A bank reports a rod position only if its fuel position is loaded. Cross-checked
directly:

```
CORE_BAY_1_STATE = INTERIOR   (fuelled)  ->  ROD_BANK_POS_0_ACTUAL = 100
CORE_BAY_2..9    = VACIO      (empty)    ->  ROD_BANK_POS_1..8     = null
```

**The two families are offset by one.** The fuel bay variables are 1-indexed and
the rod bank variables are 0-indexed:

```
CORE_BAY_{n}  <->  ROD_BANK_POS_{n-1}
```

The in-game panel labels the banks `BANK 1` through `BANK 9`, so **UI `BANK 1`
is API `ROD_BANK_POS_0`**. This is the same off-by-one that applies elsewhere in
this API: the UI is 1-indexed, the API is 0-indexed.

Verified against the reactor core panel, which draws each of the 9 bank
positions as a hub with 8 petals, and lights only `BANK 1` with a digital
readout of `100` while `BANK 2` through `BANK 9` read `000`.

### Why this matters

`null` is a **distinct read state**, alongside a value, an empty string, and the
does-not-exist sentence. Treat it as "not applicable", never as zero. A client
that coerces it to `0` will read an empty fuel position as a fully withdrawn
rod bank, which is the most dangerous possible misreading of that variable.

Note the asymmetry it creates on the write side: a write to bank 3 on an empty
bay is indistinguishable from a successful write by every signal the API gives
you. HTTP 200, `_ORDERED` stores and reads back, no error anywhere. Only
`_ACTUAL` being `null`, or `CORE_BAY_4_STATE` being `VACIO`, reveals that the
command drove nothing.

`CORE_BAY_{n}_STATE` is also the read-back twin for the write-only
`CORE_BAY_{n}_FUEL_LOADING`. Observed values: `INTERIOR` (fuelled), `VACIO`
(empty).

## 5. Fractional handling is inconsistent between variables

| Variable | Posted | Stored |
|---|---|---|
| `STEAM_EJECTOR_STARTUP_MOTIVE_VALVE` | `12.5` | `12` (truncated) |
| `STEAM_EJECTOR_CONDENSER_RETURN_VALVE` | `33.7` | `34` |
| `ROD_BANK_POS_0_ORDERED` | `100.7` | `100.7` (preserved) |

So some variables are integer-backed and some are float-backed, and you cannot
tell which from the manifest. If precision matters, verify per variable.

## 6. Type errors are inconsistently signalled

Posting a non-numeric string to a numeric variable:

| Variable | Result |
|---|---|
| `CHEM_BORON_DOSAGE_ORDERED_RATE` | **HTTP 500** |
| `CHEM_BORON_FILTER_ORDERED_SPEED` | **HTTP 500** |
| `STEAM_EJECTOR_*_VALVE` | **HTTP 500** |
| `STEAM_TURBINE_2_BYPASS_ORDERED` | **HTTP 500** |
| `ROD_BANK_POS_{n}_ORDERED` | **HTTP 200**, value silently unchanged |

**HTTP 500 is therefore a real status in the taxonomy**: a type error, and one
of the few honest error signals this API produces. But it is not universal, so a
client cannot rely on it. Rod banks discard bad input silently with a 200.

Full status taxonomy is in [wire-format.md](wire-format.md).

## 7. Variables that accept writes and do nothing

Two found so far, both returning HTTP 200 with no state change under a
verified-working harness and a matched null:

- `CHEM_BORON_FILTER_ORDERED_SPEED`: `_ORDERED` never moved off `0` for any
  value tried.
- `EMERGENCY_BATTERIES_MODE`: see
  [emergency-controls.md](emergency-controls.md).

Both may require a precondition not present on the test plant (equipment
installed, plant mode, or a running system). Recorded as observations, not as
defects.

## Method note

The ambiguous cases were resolved with [`../tools/probe.py`](../tools/probe.py),
which measures a multi-sample matched null before each write and requires a
drifting variable to exceed its own observed spread before counting as an
effect. `STEAM_TURBINE_2_BYPASS_ORDERED` looked like noise by eye and returned a
clean `EFFECT` verdict with an empty drift set once measured properly.

## 8. Indexing: API index = physical unit minus one (mostly)

Confirmed across three families at build V 2.2.25.220. Getting this wrong puts a
client one unit off from the panel the operator is looking at.

| Family | API | Physical / UI label |
|---|---|---|
| `CORE_BAY_{n}_*` | **1**-indexed, 1-9 | Bay 1-9 |
| `ROD_BANK_POS_{n}_*` | **0**-indexed, 0-8 | `BANK 1`-`BANK 9` |
| `STEAM_TURBINE_{n}_*` | **0**-indexed, 0-2 | Turbine 1-3 |

So `STEAM_TURBINE_2_RPM` is the **third** turbine, and `ROD_BANK_POS_0_ORDERED`
is the panel's `BANK 1`. The fuel bays are the exception that breaks the rule:
they are 1-indexed and line up directly.

The same split appears *inside a single record* in
`maintenance_summary.attention_items`, where the display name is 1-indexed and
the `object_id` beside it is 0-indexed:

```json
{"label": "GENERATOR (GE_Generador03)", "object_id": 2}
{"label": "TURBINE (TG_2)",             "object_id": 2}
```

`GE_Generador03` and `object_id: 2` are the same unit. Turbine labels use the
raw index, generator labels use the physical number, in the same payload.

**Do not infer the convention from a name.** Check `_INSTALLED`, or match
against `attention_items`, or confirm against the in-game panel.
