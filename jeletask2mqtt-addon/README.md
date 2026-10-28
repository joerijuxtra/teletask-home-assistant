# jeletask2mqtt as a Home Assistant OS add-on (no Docker setup needed)

On **Home Assistant OS** you don't need a separate Docker host for
[jeletask2mqtt](https://github.com/ridiekel/jeletask): run it as a *local add-on* next to the Mosquitto broker.
Home Assistant builds and starts it for you, and the TeleTask entities appear automatically via MQTT discovery.
This is how the author's installation (MICROS+) runs.

```
TeleTask MICROS+  ⇄  jeletask2mqtt (local add-on)  ⇄  Mosquitto (add-on)  ⇄  Home Assistant (MQTT integration)
```

## Steps

1. **MQTT broker:** install the **Mosquitto broker** add-on and the **MQTT** integration (Home Assistant offers it
   after the broker starts). Create a Home Assistant user for MQTT, e.g. `mqtt_user` (Settings → People → Users,
   advanced mode), and use it in the Dockerfile.
2. **Access to `/addons`:** install the **Samba share** (or *Studio Code Server* / *SSH*) add-on, so you can put
   files in the `addons` folder of Home Assistant.
3. **Create the add-on folder** `addons/jeletask2mqtt/` with the three files from this folder:
   - [`config.yaml`](config.yaml): the add-on definition (use `aarch64` instead of `amd64` on a Raspberry Pi,
     if the image you use supports it);
   - [`Dockerfile`](Dockerfile): fill in the IP of your central and the MQTT user/password;
   - [`config.json`](config.json): your TeleTask components (see the
     [jeletask README](https://github.com/ridiekel/jeletask#configuring) and
     [MESSAGES.md](https://github.com/ridiekel/jeletask/blob/main/MESSAGES.md)).
4. **Install:** Settings → Apps (Add-ons in older versions) → store → ⋮ → **Check for updates**. The add-on appears
   under **Local**. Open it → **Install** → **Start**, and turn on *Start on boot*.
5. **Check:** the add-on's **Log** shows the connection to the central and MQTT. The entities appear under the MQTT
   integration, e.g. `light.teletask_1_relay_1`, `switch.teletask_1_flag_10`.

## Changing the config

`config.json` (and the Dockerfile) are copied into the image when the add-on is **built**. After a change use
**Rebuild** on the add-on page: a restart keeps running the old configuration.

## Tips

- Give relays an explicit `"type": "LIGHT"` or `"SWITCH"`; read-only relays as `SWITCH` (as `binary_sensor`
  they stay `unknown`, [ridiekel/jeletask#68](https://github.com/ridiekel/jeletask/issues/68)).
- The MICROS+ accepts one DoIP client at a time; stop other tools that connect to it.
- After a PROSOFT download, restart the add-on if states stop updating. A function you just added in PROSOFT
  stays `unknown` until it was downloaded and the add-on was restarted.
- When the bridge reconnects, entities go `unavailable` and come back: use `from: ["on", "off"]` in automation
  triggers that react to flags or inputs.
- To control which jeletask version you run, put a version tag instead of `latest` in the `FROM` line (see the
  tags on [Docker Hub](https://hub.docker.com/r/ridiekel/jeletask2mqtt)) and **Rebuild** after changing it.
