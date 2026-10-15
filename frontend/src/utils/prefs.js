/**
 * Per-browser display preferences (Settings page). Stored in localStorage; every access is
 * guarded so a blocked/private storage simply falls back to defaults. Nothing sensitive is
 * ever stored here.
 */
export const PREF_DEFAULTS = Object.freeze({
  refreshSeconds: 60,     // hero/overview polling interval
  basemap: 'street',      // 'street' | 'satellite'
  pageSize: 15,           // Overview table rows per page
});

export const PREF_CHOICES = Object.freeze({
  refreshSeconds: [30, 60, 120, 300],
  basemap: ['street', 'satellite'],
  pageSize: [15, 25, 50],
});

const KEY = 'storm-rtu.prefs.v1';

function readAll() {
  try {
    const raw = window.localStorage.getItem(KEY);
    const obj = raw ? JSON.parse(raw) : {};
    return obj && typeof obj === 'object' ? obj : {};
  } catch {
    return {};
  }
}

export function getPref(name) {
  const v = readAll()[name];
  const choices = PREF_CHOICES[name];
  return choices && choices.includes(v) ? v : PREF_DEFAULTS[name];
}

export function setPref(name, value) {
  const choices = PREF_CHOICES[name];
  if (choices && !choices.includes(value)) return false;
  try {
    const all = readAll();
    all[name] = value;
    window.localStorage.setItem(KEY, JSON.stringify(all));
    return true;
  } catch {
    return false;
  }
}
