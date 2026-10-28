# Sun shading: TeleTask buttons → Shelly roller shutters

Motorised sun shades on **Shelly Plus 2PM** relays (cover mode), operated from the normal TeleTask wall buttons,
with a hardware fallback that works without Home Assistant or Wi-Fi.

## Normal operation (software path)

```
wall button → TeleTask FLAG toggles → jeletask2mqtt → MQTT → switch.teletask_1_flag_N
            → automation → script.shades_press → Shelly cover
```

- **PROSOFT:** link each wall button (push-button input) to *toggle* a flag. Short and long press can be two
  functions.
- **jeletask2mqtt:** add the flags to `config.json` (`"FLAG": [{ "number": 10, "description": "Shades all flag" }]`).
- **Home Assistant:** [`package.yaml`](package.yaml): a cover group, a direction helper per button, the
  `shades_press` script and one automation per flag.

Because the flag only toggles, its state means nothing: every change is one press.

| Press | Action |
|---|---|
| 1 | move (down when the direction is unknown) |
| 2 | stop |
| 3 | the opposite direction of the last movement |
| any, when fully closed | open |

### Robustness

- **Reconnects of the bridge:** the triggers use `from: ["on", "off"]`, so `unavailable → on/off` after a reconnect
  is ignored. Without it the shades moved on every reconnect. The price: a press during an outage is lost.
- **Shelly offline:** the script does nothing when the cover is `unavailable`/`unknown`.
- **Overlapping groups** (e.g. "all" and "ground floor") don't update each other's direction helper: after "all
  down", the first press on another group may be a no-op "close". The "closed → open" rule catches most cases.

## Emergency operation (hardware path)

Two TeleTask relays (UP and DOWN) are wired in parallel to the **S1** (open) resp. **S2** (close) inputs of all
Shellys and driven by a **timed function of ~1 s** in PROSOFT, with their own buttons. With the Shelly input type
set to **"Button"**, a pulse while moving stops the shade. This keeps working when Home Assistant or the Wi-Fi is
down. These relays are deliberately not used from Home Assistant.

> ⚠️ The Shelly S inputs are referenced to 230 V: only switch the same phase (L) as the Shelly supply. Work on
> mains wiring must be done by a qualified electrician.

## Installation checklist

1. Shellys online, input type "Button"; per motor check that `open_cover` really moves up (otherwise swap the
   direction in the Shelly settings).
2. Test each cover, then the groups, then the flags from Home Assistant, the wall buttons and the emergency
   buttons.
