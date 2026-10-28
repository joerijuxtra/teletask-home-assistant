# Garage door

A garage door driven by a TeleTask **MOTOR** function, with its two end switches on digital inputs.

## jeletask2mqtt config

```json
"MOTOR": [
  { "number": 1, "description": "Garage door motor" }
],
"INPUT": [
  { "number": 33, "description": "Garage door fully open (end switch)" },
  { "number": 34, "description": "Garage door fully closed (end switch)" }
],
"FLAG": [
  { "number": 9, "description": "Garage door open alarm flag" }
]
```

This gives `cover.teletask_1_motor_1`, `sensor.teletask_1_input_33/34` and `switch.teletask_1_flag_9`.

## What the package does

[`package.yaml`](package.yaml):

- **`sensor.garage_door`**: `open` / `closed` / `in between`, from the end switches. A MOTOR has no real position
  feedback, so the cover alone can't tell whether the door really closed.
- **Close after sunset:** 1 h after sunset the door is closed when the "closed" end switch is not active, with one
  retry after a minute.
- **Alarm flag (optional):** if the door is still not closed 5 minutes later, flag 9 is turned on, e.g. to show a
  message on the wall panels via a PROSOFT logic function (see [aurus-panel-message](../aurus-panel-message)). It
  turns off as soon as the door is closed. On the author's installation this part is prepared but not active yet.

> Digital inputs report `OPEN` / `CLOSED` in **capitals** and state comparisons in Home Assistant are case
> sensitive: `CLOSED`, not `closed`. For inputs, enable *Edge triggered* in PROSOFT (see the jeletask README).

Check the wiring of your end switches: on the author's installation an input is `CLOSED` when the door is at that
end position.
