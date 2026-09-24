# Storm Energy RTU Platform — Operations Guide

## Health Monitoring

```bash
# Overall platform status
GET /health

# Individual service status
GET /health/database
GET /health/mqtt
GET /health/tcp
```

Response status values: `ok` | `degraded` | `down`

## Log Files

```bash
# Application logs (structured JSON in production)
journalctl -u storm-rtu-api -f

# MQTT broker logs
tail -f /var/log/mosquitto/mosquitto.log

# Filter by device
journalctl -u storm-rtu-api | grep 864012049873321
```

## Adding Devices Without Code Changes

See `docs/device-management.md`. No restart required.

## Troubleshooting

### MQTT broker not accepting connections
```bash
systemctl status mosquitto
mosquitto_pub -h localhost -p 1883 -u <user> -P <pass> -t test -m ping
```

### Database connectivity failure
```bash
# Test from server
sqlcmd -S $SQL_SERVER -U $SQL_USERNAME -P $SQL_PASSWORD -Q "SELECT 1"
```

### RTU telemetry not appearing
1. Check `RawMessages` table — all packets are stored there
2. Check `DeviceEvents` for `INVALID_PAYLOAD` events
3. Check MQTT topic matches `storm/meters/<IMEI>/telemetry`

### Duplicate telemetry suppression
Duplicates are logged as `DUPLICATE_TELEMETRY` events and rejected with HTTP 200 (not an error).
The deduplication key is `(DeviceId, Timestamp, Protocol)`.

### Historical telemetry
Records with RTU timestamp older than `HISTORICAL_THRESHOLD_SECONDS` (default 300s)
are stored with `IsHistorical=true`. They are preserved and queryable but flagged.

## Scanvix Integration Checklist

### MQTT
- [ ] RTU connects to broker on port 1883 / 8883
- [ ] Authentication: username/password matches Mosquitto passwd file
- [ ] Topic: `storm/meters/<IMEI>/telemetry`
- [ ] Payload: valid JSON per V1.3 spec
- [ ] QoS 1 confirmed
- [ ] Reconnect tested after network outage
- [ ] Historical upload tested (buffered records sent after reconnect)

### TCP
- [ ] RTU connects to TCP_PORT (8100)
- [ ] Packet format agreed with Scanvix (currently TBD)
- [ ] ACK format agreed with Scanvix (currently TBD — NullAck active)
- [ ] Reconnect tested
- [ ] Historical upload tested

## Performance Notes

- Connection pooling: `SQL_POOL_SIZE=10`, `SQL_MAX_OVERFLOW=20`
- Deduplication check is a single indexed read — negligible overhead
- TCP connections are handled by asyncio — no thread-per-connection
- MQTT consumer is single-threaded; for very high message rates, consider a message queue
