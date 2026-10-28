# TeleTask + Home Assistant examples

Working examples for a **TeleTask** home automation system (MICROS+) in **Home Assistant**, through the
[jeletask2mqtt](https://github.com/ridiekel/jeletask) bridge. They come from a real house and are shared as
Home Assistant [packages](https://www.home-assistant.io/docs/configuration/packages/): one file per example, with a
README explaining the TeleTask (PROSOFT) and jeletask2mqtt side.

| Example | What it does |
|---|---|
| [jeletask2mqtt-addon](jeletask2mqtt-addon) | **Start here on Home Assistant OS:** run jeletask2mqtt as a local add-on next to Mosquitto, step by step, no separate Docker host needed. |
| [heating](heating) | Room thermostats: presets, setpoints, preset temperatures, week schedules per room, public holidays, vacations, heat demand and pump statistics, a 3-tab dashboard. Generated from a list of your rooms. |
| [aurus-panel-message](aurus-panel-message) | Show a Home Assistant state (e.g. "on vacation") as a message on the Aurus wall panels. |
| [sun-shading-shelly](sun-shading-shelly) | TeleTask wall buttons → flags → Shelly Plus 2PM roller shutters (move / stop / reverse), with a hardware fallback. |
| [garage-door](garage-door) | Garage door on a TeleTask MOTOR with end switches: real open/closed state, close after sunset, alarm flag. |

## Before you start

- Install jeletask2mqtt and connect it to your MQTT broker; on Home Assistant OS see
  [jeletask2mqtt-addon](jeletask2mqtt-addon). Every TeleTask function you use must be in its `config.json`.
- Enable packages in `configuration.yaml`:

  ```yaml
  homeassistant:
    packages: !include_dir_named packages
  ```

  and copy the `package.yaml` of an example to `/config/packages/<name>.yaml`.
- Entity ids follow jeletask2mqtt's pattern `<domain>.teletask_<central id>_<function>_<number>`, e.g.
  `switch.teletask_1_flag_10`. Change the numbers to yours.

## Lessons learned

- After a reconnect of the bridge all entities go `unavailable` and come back. Triggers that stand for a button
  press or a change need `from: ["on", "off"]`, or they fire on every reconnect.
- Digital inputs report `OPEN` / `CLOSED` in capitals; comparisons are case sensitive.
- The MICROS+ accepts one DoIP client at a time; after a PROSOFT download restart the bridge if states stop.
- Configure relays you only want to read as `SWITCH` and make a template `binary_sensor` in Home Assistant
  ([ridiekel/jeletask#68](https://github.com/ridiekel/jeletask/issues/68)).

## License and disclaimer

[MIT](LICENSE). Not affiliated with TeleTask. These examples switch heating, shades and a garage door: test them
on your own installation, and leave mains wiring to a qualified electrician.
