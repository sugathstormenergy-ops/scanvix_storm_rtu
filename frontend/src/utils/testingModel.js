/** Testing page constants (kept out of the component file for fast refresh). */
export const REFRESH_CHOICES = [5, 10, 30];
export const DEFAULT_REFRESH_S = 5;

/** Canonical telemetry fields (backend NormalizedTelemetry) in display order. */
export const TELEMETRY_ROWS = [
  ['device_id', 'Device ID'], ['site_id', 'Site ID'], ['timestamp', 'Timestamp'], ['flow', 'Flow'],
  ['flow_unit', 'Flow Unit'], ['total_today', 'Today Total'], ['total_yesterday', 'Yesterday Total'],
  ['sensor_type', 'Sensor Type'], ['signal_dbm', 'Signal (dBm)'], ['battery', 'Battery'],
  ['fw_version', 'Firmware Version'], ['read01', 'READ01'], ['read02', 'READ02'], ['read03', 'READ03'],
  ['read04', 'READ04'], ['read05', 'READ05'], ['pressure', 'Pressure'],
];
