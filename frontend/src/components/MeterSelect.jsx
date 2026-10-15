/**
 * MeterSelect — searchable meter picker over the REGISTERED meters (Devices registry via
 * GET /api/devices/latest). Unknown/unregistered senders are never listed here.
 *
 * Search runs over the already-loaded registry snapshot (one request serves the whole
 * app); at most MAX_RESULTS matches are rendered, so hundreds of meters stay fast.
 */
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { StatusPill } from './ui/StatusPill';
import { displayName, formatAge, meterStatus } from '../utils/meterStatus';

const MAX_RESULTS = 50;

function matchesMeter(d, q) {
  if (!q) return true;
  const s = q.trim().toLowerCase();
  return [d.name, d.device_id, d.imei, d.site_id].some((v) => v && String(v).toLowerCase().includes(s));
}

export default function MeterSelect({ devices, value, onChange, serverNowMs, placeholder = 'Search by name, IMEI or site…' }) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const listId = useId();
  const box = useRef(null);
  const selected = devices.find((d) => d.device_id === value) || null;

  const matches = useMemo(() => devices
    .filter((d) => matchesMeter(d, query))
    .sort((a, b) => displayName(a).localeCompare(displayName(b)))
    .slice(0, MAX_RESULTS), [devices, query]);
  const total = useMemo(() => devices.filter((d) => matchesMeter(d, query)).length, [devices, query]);

  useEffect(() => {
    const onDoc = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  const pick = (d) => { onChange(d.device_id); setQuery(''); setOpen(false); };
  const onKey = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setActive((i) => Math.min(i + 1, matches.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)); }
    else if (e.key === 'Enter' && open && matches[active]) { e.preventDefault(); pick(matches[active]); }
    else if (e.key === 'Escape') setOpen(false);
  };

  return (
    <div className="meter-select-box" ref={box} data-testid="meter-select">
      <input
        type="search" className="meter-control meter-select-input" role="combobox" aria-label="Select meter"
        aria-expanded={open} aria-controls={listId} autoComplete="off"
        placeholder={selected ? `${displayName(selected)} — ${selected.device_id}` : placeholder}
        value={query} onFocus={() => setOpen(true)}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); setActive(0); }} onKeyDown={onKey}
      />
      {open && (
        <ul className="meter-select-list" id={listId} role="listbox" aria-label="Registered meters">
          {matches.length === 0 && <li className="meter-select-empty">{devices.length ? 'No registered meter matches.' : 'No meters are registered yet.'}</li>}
          {matches.map((d, i) => {
            const st = meterStatus(d, serverNowMs);
            return (
              <li key={d.device_id} role="option" aria-selected={d.device_id === value} data-device={d.device_id}
                className={`meter-select-option${i === active ? ' active' : ''}${d.device_id === value ? ' selected' : ''}`}
                onMouseDown={(e) => { e.preventDefault(); pick(d); }} onMouseEnter={() => setActive(i)}>
                <div className="mso-main">
                  <div className="mso-name">{displayName(d)}</div>
                  <div className="mso-sub">IMEI: {d.imei || '—'} · Site: {d.site_id || '—'} · Last seen: {formatAge(d.last_seen_at, serverNowMs)}</div>
                </div>
                <StatusPill status={st} />
              </li>
            );
          })}
          {total > matches.length && <li className="meter-select-empty">{total - matches.length} more — refine the search.</li>}
        </ul>
      )}
    </div>
  );
}
