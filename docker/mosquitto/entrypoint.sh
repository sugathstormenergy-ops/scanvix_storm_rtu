#!/bin/sh
# Storm Energy RTU — Docker Mosquitto entrypoint.
# Builds the broker password file from environment variables (supplied from the
# git-ignored .env via compose.yml) and starts mosquitto. No credentials are
# stored in the image or in Git. Mosquitto drops privileges to the
# "mosquitto" user after start.
set -eu

: "${MQTT_USERNAME:?MQTT_USERNAME must be set in .env}"
: "${MQTT_PASSWORD:?MQTT_PASSWORD must be set in .env}"

DATA_DIR=/mosquitto/data
PW_FILE="$DATA_DIR/passwd"

mkdir -p "$DATA_DIR"
umask 077
rm -f "$PW_FILE.tmp"
mosquitto_passwd -c -b "$PW_FILE.tmp" "$MQTT_USERNAME" "$MQTT_PASSWORD"
mv -f "$PW_FILE.tmp" "$PW_FILE"
chown -R mosquitto:mosquitto "$DATA_DIR"
chmod 0700 "$DATA_DIR"
chmod 0600 "$PW_FILE"

echo "storm-mosquitto: password file prepared for service user '$MQTT_USERNAME'"
exec /usr/sbin/mosquitto -c /mosquitto/config/mosquitto.conf
