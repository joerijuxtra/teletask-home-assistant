# Messages on a TeleTask wall panel

Show something from Home Assistant (vacation mode, an open garage door, waste collection, …) on the
TeleTask Aurus wall panels. There are two ways.

## Method 1: a flag + a PROSOFT logic function

This is what runs on the author's installation (message "OP VAKANTIE" when the heating is in vacation mode).

1. **PROSOFT:** create a flag (here flag 15, "HA Vacation") and a logic function that shows the message on the
   panels while the flag is on. Download to the central.
2. **jeletask2mqtt:** add the flag to `config.json` and rebuild/restart the bridge:

   ```json
   "FLAG": [
     { "number": 15, "description": "HA Vacation flag" }
   ]
   ```

   A flag only gets a state in Home Assistant after it was downloaded to the central and the bridge was
   restarted; until then `switch.teletask_1_flag_15` stays `unknown`.
3. **Home Assistant:** [`package.yaml`](package.yaml) keeps the flag equal to a binary sensor of your own
   (`binary_sensor.vacation_active` in the example). It also corrects the flag after a reconnect of the bridge
   and when someone switches the flag in the TeleTask app.

Advantage: the message and its layout live in PROSOFT, and the panel keeps showing it even when Home Assistant
is down.

## Method 2: DISPLAYMESSAGE from Home Assistant

jeletask2mqtt can also send a text directly (send only, see
[MESSAGES.md](https://github.com/ridiekel/jeletask/blob/main/MESSAGES.md#display-message)): two lines of 16
characters, as a message or an alarm, with beeps. Add an entry with the bus and address numbers of your panels
(see PROSOFT):

```json
"DISPLAYMESSAGE": [
  { "number": 1, "description": "All panels", "bus_numbers": "1,1", "address_numbers": "5,6" }
]
```

and call the script from the package:

```yaml
action: script.panel_message_send
data:
  line1: "Waste bins"
  line2: "outside tonight"
  kind: message
  beeps: 2
```

> Method 2 follows the jeletask2mqtt documentation; it is not in use on the author's installation yet.
