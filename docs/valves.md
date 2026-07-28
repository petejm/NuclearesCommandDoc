# Valves: the meta-command indirection

The single biggest structural finding in this repository, and the one that wasted
the most time before it was understood.

## Valves are not addressed by name

There are exactly three valve POST endpoints:

```
VALVE_OPEN
VALVE_CLOSE
VALVE_OFF
```

The **value** you post is the identifier of the valve you want to act on:

```bash
curl -s -X POST --data "" \
  "http://localhost:8785/?Variable=VALVE_OPEN&value=VALVULA_ENTRADA_NUCLEO_01"
```

Read that as an imperative with an object. `VALVE_OPEN` is the verb, the valve
identifier is the noun. It is not a variable being set to a value.

## Why probing for valve names finds nothing

None of the 55 valve identifiers appear as top-level variable names. Verified by set
intersection against the full manifest (332 GET plus 91 POST names): **0 overlap**.

The identifiers exist only as keys inside `VALVE_PANEL_JSON`, which is itself an
ordinary GET-list member. So the addressing scheme is two levels deep, and the level
that matters is not in the variable namespace at all.

There is a second reason naive probing missed them: the identifiers are Spanish
engineering names (`VALVULA_ENTRADA_NUCLEO_01`, `Valvula_Pressurizer_Vent`), and
casing is inconsistent between them. English guesses were never going to land.

Evidence: `auto_nuke:lib/auto_nuke/api/valves.ex:322,345-347`, which annotates the
payload as "value = target ActuatedValve valve_panel_key". That client had the
answer in its source the whole time.

## Reading valve state

`VALVE_PANEL_JSON` is also the read-back path. Each identifier maps to:

```json
{
  "AGUA_Valve_01": {
    "Sector": "CHEMICAL TREATMENT ROOM",
    "Actuator": "OFF",
    "Value": 0.0,
    "State": {
      "SituationReached": true,
      "OpeningTargetReached": true,
      "IsOpened": false,
      "IsClosed": true,
      "BypassMode": false,
      "Stuck": false,
      "Flooded": false
    }
  }
}
```

`Value` is 0 to 100 opening percent. `Actuator` is the commanded state
(`OFF` here, meaning no active drive). The `State` block carries the flags worth
guarding on: `Stuck`, `Flooded`, `BypassMode`, and `SituationReached`.

Note that `IsOpened` and `IsClosed` are **both false** for a partially open valve,
so they are not complements. Do not treat one as the negation of the other.

## All 55 valve identifiers

Captured live at build V 2.2.25.220. Sector grouping is the game's own.

### CHEMICAL TREATMENT ROOM (12)

| Identifier | Value | Opened | Closed | Actuator |
|---|---|---|---|---|
| `AGUA_Valve_01` | 0 | False | True | OFF |
| `Boro_Valvula_Purga` | 0 | False | True | OFF |
| `Camion_Valve_01_Boro` | 0 | False | True | OFF |
| `Camion_Valve_02_NaOH` | 0 | False | True | OFF |
| `Camion_Valve_03_Fuel` | 0 | False | True | OFF |
| `Core_Valve_01` | 0 | False | True | OFF |
| `Core_Valve_02` | 0 | False | True | OFF |
| `NAOH_Valve_01` | 0 | False | True | OFF |
| `NaOH_Valvula_Purga` | 0 | False | True | OFF |
| `Valve_Q_TANQUE_AGUA` | 0 | False | True | OFF |
| `Valve_Q_TANQUE_AGUA_CORE_EXTERNO` | 0 | False | True | OFF |
| `Valve_Q_TANQUE_AGUA_MAIN` | 0 | False | True | OFF |

### CONDENSER (13)

| Identifier | Value | Opened | Closed | Actuator |
|---|---|---|---|---|
| `VALVULA_CON_VACIO_RELIEF` | 0 | False | True | OFF |
| `VALVULA_ENTRADA_BOMBA_VACIO` | 100 | True | False | OFF |
| `VALVULA_ENTRADA_CONDENSADOR_01` | 0 | False | True | OFF |
| `VALVULA_ENTRADA_CONDENSADOR_02` | 0 | False | True | OFF |
| `VALVULA_ENTRADA_CONDENSADOR_03` | 100 | True | False | OFF |
| `VALVULA_ENTRADA_EJECTOR_EVA` | 0 | False | True | OFF |
| `VALVULA_ENTRADA_EJECTOR_TUR` | 31 | False | False | OFF |
| `VALVULA_RETORNO_CONDENSADOR` | 0 | False | True | OFF |
| `VALVULA_SALIDA_CONDENSADOR_01` | 0 | False | True | OFF |
| `VALVULA_SALIDA_CONDENSADOR_02` | 0 | False | True | OFF |
| `VALVULA_SALIDA_CONDENSADOR_03` | 100 | True | False | OFF |
| `VALVULA_VACIO_CONDENSADOR` | 100 | True | False | OFF |
| `VALVULA_VENTEO_TANQUE_RETENCION` | 0 | False | True | OFF |

### CORE (15)

| Identifier | Value | Opened | Closed | Actuator |
|---|---|---|---|---|
| `VALVULA_DRAIN_EVA01` | 0 | False | True | OFF |
| `VALVULA_DRAIN_EVA02` | 0 | False | True | OFF |
| `VALVULA_DRAIN_EVA03` | 0 | False | True | OFF |
| `VALVULA_ENTRADA_NUCLEO_01` | 0 | False | True | OFF |
| `VALVULA_ENTRADA_NUCLEO_02` | 0 | False | True | OFF |
| `VALVULA_ENTRADA_NUCLEO_03` | 100 | True | False | OFF |
| `VALVULA_SALIDA_NUCLEO_01` | 0 | False | True | OFF |
| `VALVULA_SALIDA_NUCLEO_02` | 0 | False | True | OFF |
| `VALVULA_SALIDA_NUCLEO_03` | 100 | True | False | OFF |
| `Valvula_Core_Vent` | 0 | False | True | OFF |
| `Valvula_Descargar_REF` | 0 | False | True | OFF |
| `Valvula_Pressurizer_Relief_Vent` | 0 | False | True | OFF |
| `Valvula_Pressurizer_Spray` | 100 | True | False | OPEN |
| `Valvula_Pressurizer_Vent` | 0 | False | True | OFF |
| `Valvula_Purgar_Coolant` | 0 | False | True | OFF |

### GENERATOR (13)

| Identifier | Value | Opened | Closed | Actuator |
|---|---|---|---|---|
| `VALVULA_ENTRADA_TURBINA_01` | 0 | False | True | OFF |
| `VALVULA_ENTRADA_TURBINA_02` | 0 | False | True | OFF |
| `VALVULA_ENTRADA_TURBINA_03` | 5 | False | False | OFF |
| `VALVULA_ENTRE_BC_Y_EVA_01` | 0 | False | True | OFF |
| `VALVULA_ENTRE_BC_Y_EVA_02` | 0 | False | True | OFF |
| `VALVULA_ENTRE_BC_Y_EVA_03` | 100 | True | False | OFF |
| `VALVULA_PURGA_C2_01` | 0 | False | True | OFF |
| `VALVULA_REF_BYPASS_TUR_CS_01` | 0 | False | True | OFF |
| `VALVULA_REF_BYPASS_TUR_CS_02` | 0 | False | True | OFF |
| `VALVULA_REF_BYPASS_TUR_CS_03` | 0 | False | True | OFF |
| `VALVULA_VENT_TURBINA_01` | 0 | False | True | OFF |
| `VALVULA_VENT_TURBINA_02` | 0 | False | True | OFF |
| `VALVULA_VENT_TURBINA_03` | 0 | False | True | OFF |

### DIESEL GENERATOR BUILDING (2)

| Identifier | Value | Opened | Closed | Actuator |
|---|---|---|---|---|
| `ValvulaDeCarga` | 0 | False | True | OFF |
| `ValvulaPurgadoFuel` | 0 | False | True | OFF |

Total: 12 + 13 + 15 + 13 + 2 = **55**.

## The three hand valves are not commandable

`VALVE_M01_OPEN`, `VALVE_M02_OPEN` and `VALVE_M03_OPEN` are GET-only telemetry for
the plant's manual hand valves. They are in the 332-entry GET list, absent from the
91-entry POST list, and absent from the valve panel. There is no API path to actuate
them at all. You can read their position and nothing more.

This closes a question that consumed two full sessions of probing.

