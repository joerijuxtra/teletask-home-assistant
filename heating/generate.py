"""Generate the Home Assistant heating package and dashboard from rooms.yaml.

Usage:  python generate.py [rooms.yaml] [output-dir]
Needs:  Python 3.9+ and PyYAML (pip install pyyaml)

Writes <output-dir>/heating_package.yaml (copy to /config/packages/) and
<output-dir>/heating_dashboard.yaml (paste in a dashboard's raw configuration editor).
"""
import re
import sys
import unicodedata
from pathlib import Path

import yaml

MODES = ["No schedule", "Day / Night", "Day / Eco", "On / Off", "Eco / Eco"]
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DAY_ABBR = "['mo', 'tu', 'we', 'th', 'fr', 'sa', 'su']"
TODAY_START = "{{ now().replace(hour=0, minute=0, second=0, microsecond=0) }}"
ON_OFF = ["on", "off"]


def slugify(text):
    """Entity id part the way Home Assistant derives it from a name."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


class Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def _str(dumper, value):
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


Dumper.add_representer(str, _str)


def dump(data):
    return yaml.dump(data, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=1000)


class Setup:
    def __init__(self, cfg):
        self.cfg = cfg
        self.central = cfg.get("central_id", 1)
        self.prefix = cfg.get("mqtt_prefix", "teletask2mqtt")
        self.labels = {"manual": "Manual", "day": "Day", "night": "Night", "eco": "Eco"}
        self.labels.update(cfg.get("preset_labels") or {})
        self.path = cfg.get("dashboard_path", "heating")
        self.rooms = []
        for room in cfg["rooms"]:
            slug = room.get("slug") or slugify(room["name"])
            if slug != slugify(room["name"]):
                sys.exit(f"Room '{room['name']}': slug must be '{slugify(room['name'])}' "
                         "(Home Assistant derives entity ids from the name)")
            self.rooms.append({**room, "slug": slug})
        self.pump = self.switch(cfg["pump_relay"]) if cfg.get("pump_relay") else None
        self.valves = [self.switch(r["valve_relay"]) for r in self.rooms if r.get("valve_relay")]

    def climate(self, room):
        return f"climate.teletask_{self.central}_sensor_{room['sensor']}"

    def switch(self, relay):
        return f"switch.teletask_{self.central}_relay_{relay}"

    def sensor(self, number):
        return f"sensor.teletask_{self.central}_sensor_{number}"

    def topic(self, room, suffix):
        return f"{self.prefix}/{self.central}/sensor/{room['sensor']}/{suffix}"

    def edit_link(self, room):
        return (f"/{self.path}/schedules?more-info-entity-id=schedule.heating_{room['slug']}"
                "&more-info-view=settings")

    def room_list(self):
        """Jinja list of (name, slug) tuples."""
        items = ", ".join(f"({n!r}, {s!r})" for n, s in ((r["name"], r["slug"]) for r in self.rooms))
        return f"[{items}]"

    def stand_map(self):
        """Jinja dict: word of a mode -> preset label ('off' = thermostat off)."""
        lb = self.labels
        return (f"{{'Day': {lb['day']!r}, 'On': {lb['day']!r}, 'Night': {lb['night']!r}, "
                f"'Eco': {lb['eco']!r}, 'Off': 'off'}}")

    def emoji_map(self):
        lb = self.labels
        return (f"{{{lb['day']!r}: '☀️ {lb['day']}', {lb['night']!r}: '🌙 {lb['night']}', "
                f"{lb['eco']!r}: '🍃 {lb['eco']}', {lb['manual']!r}: '✋ {lb['manual']}', 'Off': '⏻ Off'}}")

    # ------------------------------------------------------------------ package
    def package(self):
        pkg = {}
        pkg["input_select"] = {
            f"heating_mode_{r['slug']}": {
                "name": f"Heating mode {r['name']}",
                "icon": "mdi:calendar-clock",
                "options": MODES,
            }
            for r in self.rooms
        }
        pkg["input_select"]["heating_chart_room"] = {
            "name": "Heating chart room",
            "icon": "mdi:radiator",
            "options": [r["name"] for r in self.rooms],
        }
        pkg["input_boolean"] = {
            "heating_schedules_active": {"name": "Heating schedules active", "icon": "mdi:calendar-clock"},
            "heating_vacation": {"name": "Heating vacation", "icon": "mdi:airplane"},
        }
        pkg["input_datetime"] = {
            "heating_exception_start": {"name": "Heating exception start", "icon": "mdi:calendar-start",
                                        "has_date": True, "has_time": True},
            "heating_exception_end": {"name": "Heating exception end", "icon": "mdi:calendar-end",
                                      "has_date": True, "has_time": True},
        }
        pkg["input_text"] = {
            "heating_exception_description": {"name": "Heating exception description", "icon": "mdi:text",
                                              "max": 60, "initial": "Vacation"},
        }
        if self.pump:
            pkg["sensor"] = self.history_stats()
        pkg["template"] = self.templates()
        pkg["mqtt"] = {"sensor": self.mqtt_sensors(), "number": self.mqtt_numbers()}
        pkg["automation"] = self.automations()
        pkg["script"] = self.scripts()
        return pkg

    def history_stats(self):
        def stat(name, entity, kind="time", **window):
            return {"platform": "history_stats", "name": name, "unique_id": slugify(name),
                    "entity_id": entity, "state": "on", "type": kind, **window}

        today = {"start": TODAY_START, "end": "{{ now() }}"}
        stats = [
            stat("Heating pump runtime today", self.pump, **today),
            stat("Heating pump runtime 7 days", self.pump, end="{{ now() }}", duration={"days": 7}),
            stat("Heating pump starts today", self.pump, "count", **today),
        ]
        stats += [stat(f"Heating demand {r['name']} today", self.switch(r["valve_relay"]), **today)
                  for r in self.rooms if r.get("valve_relay")]
        return stats

    def templates(self):
        rooms = self.rooms
        schedules = [f"schedule.heating_{r['slug']}" for r in rooms]
        slugs = [r["slug"] for r in rooms]
        holiday = {"binary_sensor": [{
            "name": "Heating holiday",
            "unique_id": "heating_holiday",
            "icon": "mdi:party-popper",
            "state": (f"{{{{ now().weekday() < 5 and (is_state('{self.cfg['workday_sensor']}', 'off')\n"
                      "   or is_state('calendar.heating_holidays', 'on')) }}"),
        }]}
        in_block = (
            "{% set holiday = is_state('binary_sensor.heating_holiday', 'on') %}\n"
            "{% set now_t = now().strftime('%H:%M:%S') %}\n"
            "{% set ns = namespace(rooms=[]) %}\n"
            f"{{% for k in {slugs} %}}\n"
            "  {% set e = 'schedule.heating_' ~ k %}\n"
            "  {% if not holiday %}\n"
            "    {% if is_state(e, 'on') %}{% set ns.rooms = ns.rooms + [k] %}{% endif %}\n"
            "  {% else %}\n"
            "    {# public holiday on a weekday: use the Sunday blocks #}\n"
            "    {% for b in schedule.get(e, {}).get('sunday', []) %}\n"
            "      {# from/to are time objects, not strings; an end of 24:00 is 23:59:59 #}\n"
            "      {% set start = (b['from'] | string)[:8] %}\n"
            "      {% set end = (b['to'] | string)[:8] %}\n"
            "      {% set end = '24:00:00' if end in ['00:00:00', '23:59:59'] else end %}\n"
            "      {% if start <= now_t < end and k not in ns.rooms %}{% set ns.rooms = ns.rooms + [k] %}{% endif %}\n"
            "    {% endfor %}\n"
            "  {% endif %}\n"
            "{% endfor %}\n"
            "{{ ns.rooms }}"
        )
        table = (
            f"{{%- set rooms = {self.room_list()} -%}}\n"
            f"{{%- set days = {DAYS} -%}}\n"
            "{%- set ns = namespace(rows=['| Room | mo | tu | we | th | fr | sa | su |',\n"
            "                             '|:--|:-:|:-:|:-:|:-:|:-:|:-:|:-:|']) -%}\n"
            "{%- for name, k in rooms -%}\n"
            "  {%- set ns2 = namespace(cells=[]) -%}\n"
            "  {%- for d in days -%}\n"
            "    {%- set ns3 = namespace(blocks=[]) -%}\n"
            "    {%- for b in schedule.get('schedule.heating_' ~ k, {}).get(d, []) -%}\n"
            "      {%- set end = (b['to'] | string)[:5] -%}\n"
            "      {%- set ns3.blocks = ns3.blocks + [(b['from'] | string)[:5] ~ '–' ~ ('24:00' if end in ['00:00', '23:59'] else end)] -%}\n"
            "    {%- endfor -%}\n"
            "    {%- set ns2.cells = ns2.cells + [ns3.blocks | join('<br>') if ns3.blocks else '–'] -%}\n"
            "  {%- endfor -%}\n"
            f"  {{%- set link = '/{self.path}/schedules?more-info-entity-id=schedule.heating_' ~ k ~ '&more-info-view=settings' -%}}\n"
            "  {%- set ns.rows = ns.rows + ['| [' ~ name ~ '](' ~ link ~ ') | ' ~ (ns2.cells | join(' | ')) ~ ' |'] -%}\n"
            "{%- endfor -%}\n"
            "{{ ns.rows | join('\\n') }}"
        )
        schedule_block = {
            "triggers": [
                {"trigger": "time_pattern", "minutes": "/1"},
                {"trigger": "homeassistant", "event": "start"},
                {"trigger": "state", "entity_id": ["binary_sensor.heating_holiday"] + schedules},
            ],
            "actions": [
                {"action": "schedule.get_schedule", "target": {"entity_id": schedules},
                 "response_variable": "schedule"},
                {"variables": {"in_block": in_block, "table": table}},
            ],
            "sensor": [{
                "name": "Heating schedules",
                "unique_id": "heating_schedules",
                "icon": "mdi:calendar-week",
                "state": "{{ schedule | count }}",
                "attributes": {"table": "{{ table }}"},
            }],
            "binary_sensor": [{
                "name": f"Heating in block {r['name']}",
                "unique_id": f"heating_in_block_{r['slug']}",
                "icon": "mdi:calendar-clock",
                "state": f"{{{{ '{r['slug']}' in in_block }}}}",
            } for r in rooms],
        }
        result = [holiday, schedule_block]

        if self.pump:
            valves = [{
                "name": f"Heating valve {r['name']}",
                "unique_id": f"heating_valve_{r['slug']}",
                "device_class": "opening",
                "availability": f"{{{{ has_value('{self.switch(r['valve_relay'])}') }}}}",
                "state": f"{{{{ is_state('{self.switch(r['valve_relay'])}', 'on') }}}}",
            } for r in rooms if r.get("valve_relay")]
            valves.append({
                "name": "Heating pump",
                "unique_id": "heating_pump",
                "device_class": "running",
                "icon": "mdi:pump",
                "availability": f"{{{{ has_value('{self.pump}') }}}}",
                "state": f"{{{{ is_state('{self.pump}', 'on') }}}}",
            })
            valves.append({
                "name": "Heating pump without demand",
                "unique_id": "heating_pump_without_demand",
                "device_class": "problem",
                "delay_on": "00:15:00",  # ignore the pump's run-on time
                "state": (f"{{{{ is_state('{self.pump}', 'on')\n"
                          f"   and {self.valves} | select('is_state', 'on') | list | count == 0 }}}}"),
            })
            result.append({"binary_sensor": valves})
            result.append({"sensor": [{
                "name": "Heating rooms with demand",
                "unique_id": "heating_rooms_with_demand",
                "unit_of_measurement": "rooms",
                "state_class": "measurement",
                "icon": "mdi:radiator",
                "state": f"{{{{ {self.valves} | select('is_state', 'on') | list | count }}}}",
            }]})

        result.append({"sensor": [{
            "name": f"Heating temperature {r['name']}",
            "unique_id": f"heating_temperature_{r['slug']}",
            "device_class": "temperature",
            "state_class": "measurement",
            "unit_of_measurement": "°C",
            "availability": f"{{{{ state_attr('{self.climate(r)}', 'current_temperature') is number }}}}",
            "state": f"{{{{ state_attr('{self.climate(r)}', 'current_temperature') }}}}",
        } for r in rooms]})

        lb = self.labels
        presets = [lb["manual"], lb["day"], lb["night"], lb["eco"]]
        result.append({"sensor": [{
            "name": f"Heating preset {r['name']}",
            "unique_id": f"heating_preset_{r['slug']}",
            "icon": "mdi:thermostat",
            "availability": f"{{{{ states('{self.climate(r)}') not in ['unavailable', 'unknown'] }}}}",
            "state": (f"{{% set e = '{self.climate(r)}' %}}{{% set p = state_attr(e, 'preset_mode') %}}"
                      f"{{% if is_state(e, 'off') %}}Off{{% else %}}"
                      f"{{{{ p if p in {presets} else {lb['manual']!r} }}}}{{% endif %}}"),
        } for r in rooms]})

        icons = {"manual": "mdi:hand-back-right", "day": "mdi:weather-sunny",
                 "night": "mdi:weather-night", "eco": "mdi:leaf"}
        result.append({"binary_sensor": [{
            "name": f"Heating preset {r['name']} {key}",
            "unique_id": f"heating_preset_{r['slug']}_{key}",
            "icon": icons[key],
            "availability": f"{{{{ has_value('sensor.heating_preset_{r['slug']}') }}}}",
            "state": f"{{{{ is_state('sensor.heating_preset_{r['slug']}', {lb[key]!r}) }}}}",
        } for r in rooms for key in ("manual", "day", "night", "eco")]})

        result.append({"binary_sensor": [{
            "name": "Heating vacation active",
            "unique_id": "heating_vacation_active",
            "icon": "mdi:airplane",
            "state": ("{{ is_state('input_boolean.heating_vacation', 'on')\n"
                      "   or is_state('calendar.heating_exceptions', 'on') }}"),
        }]})
        return result

    def mqtt_sensors(self):
        return [{
            "name": f"Heating presets {r['name']}",
            "unique_id": f"heating_presets_{r['slug']}",
            "state_topic": self.topic(r, "state"),
            "value_template": "{{ value_json.day_preset_temperature }}",
            "unit_of_measurement": "°C",
            "device_class": "temperature",
            "json_attributes_topic": self.topic(r, "state"),
            "json_attributes_template": (
                "{{ {'day': value_json.day_preset_temperature,\n"
                "    'night': value_json.night_at_heating_preset_temperature,\n"
                "    'eco': ((value_json.day_preset_temperature | float(0))\n"
                "            - (value_json.eco_preset_offset | float(0))) | round(1),\n"
                "    'eco_offset': value_json.eco_preset_offset} | tojson }}"),
        } for r in self.rooms]

    def mqtt_numbers(self):
        numbers = []
        for r in self.rooms:
            base = {"state_topic": self.topic(r, "state"), "command_topic": self.topic(r, "set"),
                    "step": 0.5, "unit_of_measurement": "°C", "mode": "box"}
            numbers += [
                {"name": f"Heating day temperature {r['name']}",
                 "unique_id": f"heating_day_temperature_{r['slug']}", "icon": "mdi:weather-sunny",
                 **base, "value_template": "{{ value_json.day_preset_temperature }}",
                 "command_template": '{"state": "ON", "action": "DAY_PRESET", "day_preset_temperature": {{ value }}}',
                 "min": 15, "max": 25},
                {"name": f"Heating night temperature {r['name']}",
                 "unique_id": f"heating_night_temperature_{r['slug']}", "icon": "mdi:weather-night",
                 **base, "value_template": "{{ value_json.night_at_heating_preset_temperature }}",
                 "command_template": ('{"state": "ON", "action": "NIGHT_PRESET", '
                                      '"night_at_heating_preset_temperature": {{ value }}}'),
                 "min": 5, "max": 22},
                {"name": f"Heating eco temperature {r['name']}",
                 "unique_id": f"heating_eco_temperature_{r['slug']}", "icon": "mdi:leaf",
                 **base,
                 "value_template": ("{{ ((value_json.day_preset_temperature | float(0))\n"
                                    "    - (value_json.eco_preset_offset | float(0))) | round(1) }}"),
                 # the central stores eco as an offset below the day temperature
                 "command_template": (
                     '{"state": "ON", "action": "ECO_OFFSET", "eco_preset_offset": '
                     f"{{{{ [[(states('sensor.heating_presets_{r['slug']}') | float(0)) - (value | float), 0] | max, 25] | min | round(1) }}}}}}"),
                 "min": 5, "max": 25},
            ]
        return numbers

    def automations(self):
        rooms = [{"slug": r["slug"], "climate": self.climate(r)} for r in self.rooms]
        target = (
            f"{{% set stand = {self.stand_map()} %}}\n"
            "{% set parts = mode.split(' / ') %}\n"
            "{% if parts | count != 2 or parts[0] not in stand or parts[1] not in stand %}none\n"
            "{% elif is_state('input_boolean.heating_vacation', 'on') or is_state('calendar.heating_exceptions', 'on') %}"
            f"{self.labels['night']}\n"
            "{% elif is_state('binary_sensor.heating_in_block_' ~ repeat.item.slug, 'on') %}{{ stand[parts[0]] }}\n"
            "{% else %}{{ stand[parts[1]] }}{% endif %}"
        )
        presets = [self.labels[k] for k in ("day", "night", "eco")]
        control = {
            "id": "heating_schedule_control",
            "alias": "Heating: room schedules → thermostats",
            "description": (
                "Per room: inside a block of schedule.heating_<room> (Sunday blocks on a public holiday) the first part "
                "of input_select.heating_mode_<room>, outside the second part. 'No schedule' = not controlled. "
                "Vacation (input_boolean.heating_vacation or an event in calendar.heating_exceptions) = night for "
                "all scheduled rooms. Changes made on a wall panel or in an app stay until the next switch."),
            "mode": "queued",
            "max": 20,
            "triggers": [
                {"trigger": "state", "entity_id": [f"binary_sensor.heating_in_block_{r['slug']}" for r in self.rooms],
                 "from": ON_OFF, "to": ON_OFF},
                {"trigger": "state", "entity_id": "calendar.heating_exceptions", "from": ON_OFF, "to": ON_OFF},
                {"trigger": "state", "entity_id": [f"input_select.heating_mode_{r['slug']}" for r in self.rooms]},
                {"trigger": "state", "entity_id": ["input_boolean.heating_schedules_active", "input_boolean.heating_vacation"],
                 "from": ON_OFF, "to": ON_OFF},
                {"trigger": "homeassistant", "event": "start"},
            ],
            "conditions": [{"condition": "state", "entity_id": "input_boolean.heating_schedules_active", "state": "on"}],
            "actions": [
                {"variables": {
                    "rooms": rooms,
                    # a room-specific trigger only handles that room; the others handle all rooms
                    "selection": (
                        "{% set t = trigger.entity_id if trigger.entity_id is defined else '' %}\n"
                        "{% set slug = t.split('.')[-1] | replace('heating_mode_', '') | replace('heating_in_block_', '') %}\n"
                        "{% set m = rooms | selectattr('slug', 'eq', slug) | list %}\n"
                        "{{ m if m | count > 0 else rooms }}"),
                }},
                {"repeat": {
                    "for_each": "{{ selection }}",
                    "sequence": [
                        {"variables": {
                            "c": "{{ repeat.item.climate }}",
                            "mode": "{{ states('input_select.heating_mode_' ~ repeat.item.slug) }}",
                            "target": target,
                        }},
                        {"choose": [
                            {"conditions": [{"condition": "template",
                                             "value_template": "{{ target == 'off' and has_value(c) and not is_state(c, 'off') }}"}],
                             "sequence": [{"action": "climate.set_hvac_mode", "target": {"entity_id": "{{ c }}"},
                                           "data": {"hvac_mode": "off"}}]},
                            {"conditions": [{"condition": "template",
                                             "value_template": f"{{{{ target in {presets} and has_value(c) }}}}"}],
                             "sequence": [
                                 {"if": [{"condition": "template", "value_template": "{{ is_state(c, 'off') }}"}],
                                  "then": [{"action": "climate.set_hvac_mode", "target": {"entity_id": "{{ c }}"},
                                            "data": {"hvac_mode": "heat"}},
                                           {"delay": "00:00:03"}]},
                                 {"if": [{"condition": "template",
                                          "value_template": "{{ state_attr(c, 'preset_mode') != target }}"}],
                                  "then": [{"action": "climate.set_preset_mode", "target": {"entity_id": "{{ c }}"},
                                            "data": {"preset_mode": "{{ target }}"}}]},
                             ]},
                        ]},
                    ],
                }},
            ],
        }
        result = [control]
        if self.pump:
            notify = self.cfg.get("notify_service", "notify.notify")
            result.append({
                "id": "heating_pump_alert",
                "alias": "Heating: pump runs without heat demand",
                "description": "The circulation pump runs for 15 min while no valve is open.",
                "mode": "single",
                "triggers": [
                    # from: 'off' -> no alert after a reconnect (unavailable -> on)
                    {"trigger": "state", "entity_id": "binary_sensor.heating_pump_without_demand",
                     "from": "off", "to": "on", "id": "problem"},
                    {"trigger": "state", "entity_id": "binary_sensor.heating_pump_without_demand",
                     "from": "on", "to": "off", "id": "solved"},
                ],
                "actions": [{"choose": [
                    {"conditions": [{"condition": "trigger", "id": "problem"}],
                     "sequence": [{"action": notify, "data": {
                         "title": "🔥 Heating pump without demand",
                         "message": ("The circulation pump has been running for 15 min while no valve is open. "
                                     "Runtime today: {{ states('sensor.heating_pump_runtime_today') }} h."),
                         "data": {"tag": "heating_pump_without_demand"}}}]},
                    {"conditions": [{"condition": "trigger", "id": "solved"}],
                     "sequence": [{"action": notify, "data": {
                         "message": "clear_notification", "data": {"tag": "heating_pump_without_demand"}}}]},
                ]}],
            })
        flag = self.cfg.get("vacation_flag")
        if flag:
            entity = f"switch.teletask_{self.central}_flag_{flag}"
            result.append({
                "id": "heating_vacation_flag",
                "alias": f"Heating: vacation → TeleTask flag {flag}",
                "description": (f"Keeps flag {flag} equal to binary_sensor.heating_vacation_active, also after a "
                                "reconnect of the flag. A PROSOFT logic function can show a message on a wall panel."),
                "mode": "restart",
                "triggers": [
                    {"trigger": "state", "entity_id": "binary_sensor.heating_vacation_active", "to": ON_OFF},
                    {"trigger": "state", "entity_id": entity, "to": ON_OFF},
                    {"trigger": "homeassistant", "event": "start"},
                ],
                "conditions": [{"condition": "template", "value_template": (
                    f"{{{{ has_value('binary_sensor.heating_vacation_active') and has_value('{entity}')\n"
                    f"   and states('{entity}') != states('binary_sensor.heating_vacation_active') }}}}")}],
                "actions": [{"action": "switch.turn_{{ states('binary_sensor.heating_vacation_active') }}",
                             "target": {"entity_id": entity}}],
            })
        return result

    def scripts(self):
        return {"heating_add_exception": {
            "alias": "Heating: add exception (vacation) to the calendar",
            "icon": "mdi:calendar-plus",
            "mode": "single",
            "sequence": [
                {"variables": {
                    "start": "{{ states('input_datetime.heating_exception_start') }}",
                    "end": "{{ states('input_datetime.heating_exception_end') }}",
                    "description": "{{ states('input_text.heating_exception_description') | default('Vacation', true) }}",
                }},
                {"if": [{"condition": "template", "value_template": (
                    "{{ as_datetime(end) is none or as_datetime(start) is none\n"
                    "   or as_datetime(end) <= as_datetime(start) }}")}],
                 "then": [
                     {"action": "persistent_notification.create", "data": {
                         "notification_id": "heating_exception", "title": "Heating exception not added",
                         "message": "The end ({{ end }}) must be after the start ({{ start }})."}},
                     {"stop": "invalid period"}]},
                {"action": "calendar.create_event", "target": {"entity_id": "calendar.heating_exceptions"},
                 "data": {"summary": "{{ description }}", "start_date_time": "{{ start }}",
                          "end_date_time": "{{ end }}"}},
                {"action": "persistent_notification.create", "data": {
                    "notification_id": "heating_exception", "title": "Heating exception added",
                    "message": "{{ description }}: {{ start }} → {{ end }}. All scheduled rooms are on night then."}},
            ],
        }}

    # ---------------------------------------------------------------- dashboard
    def dashboard(self):
        return {"title": "Heating", "views": [self.view_rooms(), self.view_charts(), self.view_schedules()]}

    def vacation_banner(self, text):
        return {"type": "conditional",
                "conditions": [{"condition": "state", "entity": "binary_sensor.heating_vacation_active", "state": "on"}],
                "card": {"type": "markdown",
                         "content": f'<ha-alert alert-type="warning" title="✈️ ON VACATION">{text}</ha-alert>'}}

    def room_stack(self, r):
        lb = self.labels
        c = self.climate(r)
        status = (
            f"{{% set e = '{c}' %}}{{% set p = state_attr(e, 'preset_mode') %}}{{% set a = state_attr(e, 'hvac_action') %}}"
            "{% if is_state(e, 'off') %}⏻ Off · 🌡 Measured {{ state_attr(e, 'current_temperature') }} °C"
            "{% else %}🎯 **Target {{ state_attr(e, 'temperature') }} °C** · 🌡 Measured {{ state_attr(e, 'current_temperature') }} °C<br>"
            f"{{{{ {{{lb['day']!r}: '☀️ {lb['day']}', {lb['night']!r}: '🌙 {lb['night']}', {lb['eco']!r}: '🍃 {lb['eco']}'}}"
            f".get(p, '✋ {lb['manual']}') }}}} · {{{{ {{'heating': '🔥 Heating', 'idle': '💤 Idle'}}.get(a, '') }}}}{{% endif %}}"
        )
        icons = {"manual": "mdi:hand-back-right", "day": "mdi:weather-sunny",
                 "night": "mdi:weather-night", "eco": "mdi:leaf"}
        buttons = [{
            "type": "button",
            "entity": f"binary_sensor.heating_preset_{r['slug']}_{key}",
            "name": lb[key],
            "icon": icons[key],
            "icon_height": "28px",
            "show_state": False,
            "state_color": True,
            "tap_action": {"action": "perform-action", "perform_action": "climate.set_preset_mode",
                           "data": {"entity_id": c, "preset_mode": lb[key]}},
            "hold_action": {"action": "none"},
        } for key in ("manual", "day", "night", "eco")]
        return {"type": "vertical-stack", "cards": [
            {"type": "thermostat", "entity": c, "name": r["name"],
             "features": [{"type": "climate-hvac-modes", "hvac_modes": ["heat", "off"]}]},
            {"type": "markdown", "content": status},
            {"type": "horizontal-stack", "cards": buttons},
        ]}

    def view_rooms(self):
        cards = [self.vacation_banner(
            f"All rooms with a schedule are on 🌙 {self.labels['night']}. Turn it off on the Schedules tab.")]
        cards += [self.room_stack(r) for r in self.rooms]
        if self.pump:
            demand = [{"entity": "sensor.heating_rooms_with_demand", "name": "Rooms with heat demand"},
                      {"entity": "binary_sensor.heating_pump", "name": "Circulation pump"}]
            if self.cfg.get("boiler_sensor"):
                demand.append({"entity": self.sensor(self.cfg["boiler_sensor"]), "name": "Boiler",
                               "icon": "mdi:water-boiler"})
            demand.append({"entity": "binary_sensor.heating_pump_without_demand", "name": "Pump without demand (>15 min)"})
            demand.append({"type": "divider"})
            demand += [{"entity": f"binary_sensor.heating_valve_{r['slug']}", "name": r["name"]}
                       for r in self.rooms if r.get("valve_relay")]
            cards.append({"type": "entities", "title": "Heat demand now", "show_header_toggle": False,
                          "entities": demand})
        temps = [{"entity": f"sensor.heating_temperature_{r['slug']}", "name": r["name"]} for r in self.rooms]
        if self.cfg.get("outside_sensor"):
            temps.append({"entity": self.sensor(self.cfg["outside_sensor"]), "name": "Outside"})
        cards.append({"type": "entities", "title": "Room temperatures", "entities": temps})
        if self.pump:
            today = [{"entity": "sensor.heating_pump_runtime_today", "name": "Pump runtime"},
                     {"entity": "sensor.heating_pump_starts_today", "name": "Pump starts"},
                     {"entity": "sensor.heating_pump_runtime_7_days", "name": "Pump runtime 7 days"},
                     {"type": "divider"}]
            today += [{"entity": f"sensor.heating_demand_{r['slug']}_today", "name": f"Heat demand {r['name']}"}
                      for r in self.rooms if r.get("valve_relay")]
            cards.append({"type": "entities", "title": "Today", "entities": today})
        return {"title": "Rooms", "path": "rooms", "icon": "mdi:radiator", "cards": cards}

    @staticmethod
    def on_off_series(entity, name, axis, color=None):
        series = {"entity": entity, "name": name, "yaxis_id": axis, "type": "area", "curve": "stepline",
                  "opacity": 0.25, "transform": "return x === 'on' ? 1 : 0;"}
        if color:
            series["color"] = color
        return series

    @staticmethod
    def temp_series(entity, name, width=2, duration="10min"):
        return {"entity": entity, "name": name, "yaxis_id": "temp", "stroke_width": width,
                "group_by": {"func": "avg", "duration": duration}}

    def view_charts(self):
        cards = [
            {"type": "history-graph", "title": "Preset per room (48 h)", "hours_to_show": 48,
             "entities": [{"entity": f"sensor.heating_preset_{r['slug']}", "name": r["name"]} for r in self.rooms]},
        ]
        if self.pump:
            cards.append({"type": "history-graph", "title": "Heat demand per room + pump (48 h)", "hours_to_show": 48,
                          "entities": [{"entity": "binary_sensor.heating_pump", "name": "Pump"}]
                          + [{"entity": f"binary_sensor.heating_valve_{r['slug']}", "name": r["name"]}
                             for r in self.rooms if r.get("valve_relay")]})
        stack = []
        if self.pump and self.cfg.get("boiler_sensor"):
            stack.append({
                "type": "custom:apexcharts-card",
                "header": {"show": True, "title": "Boiler and pump (48 h)", "show_states": False},
                "graph_span": "48h",
                "yaxis": [{"id": "temp", "decimals": 0},
                          {"id": "pump", "opposite": True, "min": 0, "max": 1, "show": False}],
                "series": [{**self.temp_series(self.sensor(self.cfg["boiler_sensor"]), "Boiler", duration="5min"),
                            "color": "#e53935"},
                           self.on_off_series(self.pump, "Pump on", "pump", "#1e88e5")],
            })
        stack.append({"type": "entities", "title": "Charts", "show_header_toggle": False,
                      "entities": [{"entity": "input_select.heating_chart_room", "name": "Room"}]})
        for r in self.rooms:
            target = [self.temp_series(f"sensor.heating_temperature_{r['slug']}", "Measured"),
                      {"entity": self.climate(r), "attribute": "temperature", "name": "Target",
                       "yaxis_id": "temp", "stroke_width": 2, "curve": "stepline"}]
            if r.get("valve_relay"):
                target.append(self.on_off_series(self.switch(r["valve_relay"]), "Valve open", "on"))
            charts = [{
                "type": "custom:apexcharts-card",
                "header": {"show": True, "title": f"{r['name']}: temperature vs target (48 h)", "show_states": False},
                "graph_span": "48h",
                "yaxis": [{"id": "temp", "decimals": 1},
                          {"id": "on", "opposite": True, "min": 0, "max": 1, "show": False}],
                "series": target,
            }]
            if self.pump:
                series = [self.temp_series(f"sensor.heating_temperature_{r['slug']}", r["name"])]
                if self.cfg.get("outside_sensor"):
                    series.append(self.temp_series(self.sensor(self.cfg["outside_sensor"]), "Outside", width=1))
                series.append(self.on_off_series(self.pump, "Pump", "pump"))
                charts.append({
                    "type": "custom:apexcharts-card",
                    "header": {"show": True, "title": f"Pump, {r['name']} and outside (48 h)", "show_states": False},
                    "graph_span": "48h",
                    "yaxis": [{"id": "temp", "decimals": 0},
                              {"id": "pump", "opposite": True, "min": 0, "max": 1, "show": False}],
                    "series": series,
                })
            stack.append({"type": "conditional",
                          "conditions": [{"condition": "state", "entity": "input_select.heating_chart_room",
                                          "state": r["name"]}],
                          "card": {"type": "vertical-stack", "cards": charts}})
        cards.append({"type": "vertical-stack", "cards": stack})
        return {"title": "Charts", "path": "charts", "icon": "mdi:chart-line", "cards": cards}

    def view_schedules(self):
        lb = self.labels
        overview = (
            f"{{% set rooms = {self.room_list()} %}}\n"
            "| Room | Mode | Schedule wants | Next switch |\n"
            "|:--|:--|:--|--:|\n"
            "{% for name, k in rooms %}{% set s = 'schedule.heating_' ~ k %}"
            "{% set m = states('input_select.heating_mode_' ~ k) %}"
            "| {{ name }} | {{ m }} | "
            "{% if m == 'No schedule' %}–"
            "{% elif is_state('input_boolean.heating_vacation', 'on') or is_state('calendar.heating_exceptions', 'on') %}"
            f"🌙 {lb['night']} (vacation)"
            "{% else %}{% set parts = m.split(' / ') %}{% set block = is_state('binary_sensor.heating_in_block_' ~ k, 'on') %}"
            "{% set w = parts[0] if block else parts[-1] %}"
            f"{{{{ {{'Day': '☀️ {lb['day']}', 'On': '☀️ {lb['day']}', 'Night': '🌙 {lb['night']}', "
            f"'Eco': '🍃 {lb['eco']}', 'Off': '⏻ Off'}}.get(w, w) }}}}"
            " ({{ 'in block' if block else 'outside block' }}){% endif %} | "
            "{% set n = state_attr(s, 'next_event') %}"
            "{% if n and m != 'No schedule' %}{% set t = (as_datetime(n) if n is string else n) | as_local %}"
            f"{{{{ {DAY_ABBR}[t.weekday()] }}}} {{{{ t.strftime('%H:%M') }}}}{{% else %}}–{{% endif %}} |\n"
            "{% endfor %}\n\n"
            "{% if is_state('binary_sensor.heating_holiday', 'on') %}🎉 **Public holiday today**: the rooms follow "
            "their Sunday blocks; \"Next switch\" shows the normal schedule.{% endif %}\n"
            "{% if is_state('input_boolean.heating_schedules_active', 'off') %}⚠️ **Schedules are off**: "
            "Home Assistant controls no room.{% endif %}"
        )
        setup = []
        for r in self.rooms:
            setup += [
                {"type": "button", "icon": "mdi:calendar-clock", "name": f"{r['name']} – time blocks",
                 "action_name": "Edit", "tap_action": {"action": "navigate", "navigation_path": self.edit_link(r)}},
                {"entity": f"input_select.heating_mode_{r['slug']}", "name": f"{r['name']} – mode",
                 "icon": "mdi:blank", "tap_action": {"action": "none"}},
                {"type": "divider"},
            ]
        setup.pop()
        presets_table = (
            f"{{% set rooms = {self.room_list()} %}}\n"
            "| Room | Thermostat | ☀️ Day °C | 🌙 Night °C | 🍃 Eco °C | Since |\n"
            "|:--|:--|--:|--:|--:|--:|\n"
            "{% for name, k in rooms %}{% set p = 'sensor.heating_presets_' ~ k %}{% set st = 'sensor.heating_preset_' ~ k %}"
            f"| {{{{ name }}}} | {{{{ {self.emoji_map()}.get(states(st), states(st)) }}}} | "
            "{{ state_attr(p, 'day') }} | {{ state_attr(p, 'night') }} | {{ state_attr(p, 'eco') }} | "
            "{% if states[st] is not none %}{% set t = states[st].last_changed | as_local %}"
            f"{{{{ {DAY_ABBR}[t.weekday()] }}}} {{{{ t.strftime('%H:%M') }}}}{{% endif %}} |\n"
            "{% endfor %}"
        )
        preset_inputs = []
        for r in self.rooms:
            preset_inputs += [
                {"type": "section", "label": r["name"]},
                {"entity": f"number.heating_day_temperature_{r['slug']}", "name": f"☀️ {lb['day']}"},
                {"entity": f"number.heating_night_temperature_{r['slug']}", "name": f"🌙 {lb['night']}"},
                {"entity": f"number.heating_eco_temperature_{r['slug']}", "name": f"🍃 {lb['eco']}"},
            ]
        how = (
            f"**How it works:** inside a time block a room is on ☀️ **{lb['day']}**. Outside the blocks it follows "
            f"its mode: *Day / Night* → 🌙 {lb['night']}, *Day / Eco* → 🍃 {lb['eco']}, *On / Off* → ⏻ Off, "
            "*Eco / Eco* = always eco. *No schedule* = Home Assistant does not control this room.\n\n"
            "**Public holidays** (Workday integration + the \"Heating holidays\" calendar, where you can add bridge "
            "days): rooms follow their **Sunday** blocks. **Vacation**: turn on the switch, or fill in start and end "
            f"under \"Add exception\". While an event runs, all scheduled rooms are on 🌙 {lb['night']}.\n\n"
            "**Edit time blocks:** click a room in the week schedule or \"Edit\" under \"Schedule setup\": drag over "
            "a day to add a block, click a block to change or delete it, then **Update**.\n\n"
            "**Manual override:** a change on a wall panel, in the TeleTask app or with the buttons on the first tab "
            "stays until the next switch (start or end of a block, vacation, other mode). Then the room follows its "
            "schedule again, also when the thermostat was turned off. Rooms on *No schedule* are never touched."
        )
        cards = [
            self.vacation_banner("Vacation has priority: all rooms with a schedule are on night, "
                                 "the time blocks are not followed."),
            {"type": "entities", "title": "Schedules", "show_header_toggle": False, "entities": [
                {"entity": "input_boolean.heating_schedules_active", "name": "Schedules active"},
                {"entity": "input_boolean.heating_vacation", "name": "Vacation now (scheduled rooms on night)"},
                {"entity": "calendar.heating_exceptions", "name": "Vacation according to calendar"},
                {"entity": "binary_sensor.heating_holiday", "name": "Public holiday today (Sunday blocks)"},
            ]},
            {"type": "calendar", "title": "Vacations and holidays", "initial_view": "listWeek",
             "entities": ["calendar.heating_exceptions", "calendar.heating_holidays"]},
            {"type": "entities", "title": "Add exception", "show_header_toggle": False, "entities": [
                {"entity": "input_datetime.heating_exception_start", "name": "Start"},
                {"entity": "input_datetime.heating_exception_end", "name": "End"},
                {"entity": "input_text.heating_exception_description", "name": "Description"},
                {"type": "button", "icon": "mdi:calendar-plus", "name": "Add to calendar", "action_name": "Add",
                 "tap_action": {"action": "perform-action", "perform_action": "script.heating_add_exception"}},
                {"type": "button", "icon": "mdi:calendar-edit", "name": "Change or delete (calendar)",
                 "action_name": "Open", "tap_action": {"action": "navigate", "navigation_path": "/calendar"}},
            ]},
            {"type": "markdown", "title": "Schedule per room", "content": overview},
            {"type": "markdown", "title": "Week schedule per room (time blocks = ☀️ inside block)",
             "content": "{{ state_attr('sensor.heating_schedules', 'table') }}\n\n"
                        "*Click a room to edit its time blocks. Public holidays follow the **su** column.*"},
            {"type": "entities", "title": "Schedule setup", "show_header_toggle": False, "entities": setup},
            {"type": "markdown", "content": how},
            {"type": "markdown", "title": "Preset temperatures per room", "content": presets_table},
            {"type": "entities", "title": "Set preset temperatures", "show_header_toggle": False,
             "entities": preset_inputs},
            {"type": "markdown", "content": (
                "The temperatures come straight from the TeleTask central; change them above or in the TeleTask app. "
                "Eco = day − eco offset (the central stores eco as an offset). ⏻ **Off** = the central's frost "
                "protection, not adjustable. *Since* = last change of preset.")},
            {"type": "history-graph", "title": "Preset per room (7 days)", "hours_to_show": 168,
             "entities": [{"entity": f"sensor.heating_preset_{r['slug']}", "name": r["name"]} for r in self.rooms]},
            {"type": "history-graph", "title": "Target temperature per room (7 days)", "hours_to_show": 168,
             "entities": [{"entity": self.climate(r), "name": r["name"]} for r in self.rooms]},
        ]
        return {"title": "Schedules", "path": "schedules", "icon": "mdi:calendar-clock", "cards": cards}


HEADER_PACKAGE = """# Heating package for TeleTask thermostats via jeletask2mqtt.
# GENERATED by generate.py from rooms.yaml: edit rooms.yaml and run the generator again.
#
# Copy to /config/packages/ and enable packages in configuration.yaml:
#   homeassistant:
#     packages: !include_dir_named packages
# Also create in the UI (see README.md): a Schedule helper per room, the local calendars
# "Heating exceptions" and "Heating holidays", and the Workday integration.
"""

HEADER_DASHBOARD = """# Heating dashboard (3 tabs). GENERATED by generate.py from rooms.yaml.
# New dashboard -> ⋮ -> Edit -> ⋮ -> Raw configuration editor -> paste.
# Needs the apexcharts-card (HACS) for the charts tab.
"""


def main():
    here = Path(__file__).parent
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else here / "rooms.yaml"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else here / "output"
    with open(source, encoding="utf-8") as f:
        setup = Setup(yaml.safe_load(f))
    out.mkdir(parents=True, exist_ok=True)
    (out / "heating_package.yaml").write_text(HEADER_PACKAGE + dump(setup.package()), encoding="utf-8")
    (out / "heating_dashboard.yaml").write_text(HEADER_DASHBOARD + dump(setup.dashboard()), encoding="utf-8")
    print(f"{len(setup.rooms)} rooms -> {out / 'heating_package.yaml'}, {out / 'heating_dashboard.yaml'}")


if __name__ == "__main__":
    main()
