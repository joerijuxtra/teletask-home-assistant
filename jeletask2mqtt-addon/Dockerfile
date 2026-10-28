# Local Home Assistant OS add-on for jeletask2mqtt.
# Fill in the values below. This file holds your MQTT password: keep it out of shared backups/repos.
FROM ridiekel/jeletask2mqtt:latest

# Your TeleTask config (same folder) is copied into the image when the add-on is built.
COPY config.json /teletask2mqtt/config.json

# --- TeleTask central ---
ENV TELETASK_CENTRAL_HOST="<ip of your MICROS+>"
ENV TELETASK_CENTRAL_PORT="55957"
ENV TELETASK_CENTRAL_ID="1"

# --- MQTT: the Mosquitto broker add-on ---
ENV TELETASK_MQTT_HOST="core-mosquitto"
ENV TELETASK_MQTT_PORT="1883"
ENV TELETASK_MQTT_USERNAME="<mqtt user>"
ENV TELETASK_MQTT_PASSWORD="<mqtt password>"

# --- Home Assistant ---
ENV TELETASK_MQTT_RETAINED="true"
ENV TELETASK_MQTT_DISCOVERY_PREFIX="homeassistant"
