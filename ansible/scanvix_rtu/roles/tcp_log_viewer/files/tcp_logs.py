"""
app/api/tcp_logs.py — read-only Scanvix TCP troubleshooting viewer.
==================================================================

Purpose: let Scanvix engineers see exactly what their RTU sent to :9000, using
ONLY the packets the existing application already received and stored. This adds
NO TCP listener, NO capture layer, and NO parser changes. It issues SELECT-only
queries against dbo.TCPMessages / dbo.RawMessages / dbo.Devices, reusing the
application's existing SQLAlchemy engine.

Routes (registered from main.py with the app's normal convention):
    GET /api/tcp-logs   ?limit=50&status=&device_id=
    GET /tcp-logs        (auto-refreshing HTML page)

The stored payload is shown EXACTLY as stored — never json.dumps'd, reformatted,
normalized, or reconstructed. Because the payload is read back from a stored
column (not the socket), it is labelled "stored payload", not byte-exact socket
capture.
"""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

# Reuse the application's existing engine (no second connection implementation).
from app.database.database import engine

router = APIRouter(tags=["tcp-logs"])

# --- timezone: DD-MMM-YYYY HH:mm:ss IST ------------------------------------
# BUG FIX (verified against app/timezone.py, the single source of truth for
# this project's timestamp policy): every ReceivedAt/CreatedAt column in
# app/database/models.py defaults to app.timezone.now_ist(), which returns a
# NAIVE datetime whose wall-clock numbers ALREADY represent Asia/Kolkata time
# (see now_ist()'s own docstring: "a naive datetime whose wall-clock numbers
# represent IST"). It is NOT naive UTC. RECEIVED_AT_STORED_AS was left at
# "utc" (the default placeholder this file's own comment warned to verify),
# which made _format_ist() treat an already-IST value as UTC and convert it
# +5:30 a second time -- the exact root cause of the TCP Test Log showing
# times ~5h30m ahead of actual IST. Do not change this back to "utc" unless
# app/timezone.py's storage policy changes (it would then also require a
# matching change to every model default, which is out of scope here).
RECEIVED_AT_STORED_AS = "ist"
_IST = timezone(timedelta(hours=5, minutes=30))
_MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _format_ist(dt) -> str:
    if dt is None:
        return ""
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except Exception:
            return dt
    if RECEIVED_AT_STORED_AS == "utc":
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(_IST)
    elif dt.tzinfo is not None:
        dt = dt.astimezone(_IST)
    return "%02d-%s-%04d %02d:%02d:%02d IST" % (
        dt.day, _MONTHS[dt.month], dt.year, dt.hour, dt.minute, dt.second)


# --- payload rendering (exact value preserved; extra views are additive) ----
def _escape(s: str) -> str:
    out = []
    for ch in s:
        o = ord(ch)
        if ch in ("\n", "\r", "\t"):
            out.append(ch)
        elif o < 32 or o == 127:
            out.append("\\x%02x" % o)
        else:
            out.append(ch)
    return "".join(out)


def _has_nonprintable(s: str) -> bool:
    return any((ord(c) < 32 and c not in "\r\n\t") or ord(c) == 127 for c in s)


def _hex(s: str) -> str:
    return " ".join("%02X" % b for b in s.encode("utf-8", "surrogatepass"))


def _preview(s: str, n: int = 80) -> str:
    one = _escape(s).replace("\n", " ").replace("\r", " ").replace("\t", " ")
    return one[:n] + ("…" if len(one) > n else "")


def _parse_status(status, is_valid):
    s = (status or "").upper()
    if s in ("PROCESSED", "OK", "SUCCESS", "VALID"):
        return "VALID"
    if s in ("INVALID", "FAILED", "ERROR"):
        return "INVALID"
    if is_valid is True:
        return "VALID"
    if is_valid is False:
        return "INVALID"
    return s or "UNKNOWN"


_SQL = """
    SELECT TOP (:limit)
        t.Id AS Id, t.ReceivedAt AS ReceivedAt, t.DeviceId AS DeviceId,
        t.SourceIP AS SourceIP, t.Payload AS Payload,
        t.Acknowledgement AS Acknowledgement, t.Status AS Status,
        t.RawMessageId AS RawMessageId,
        r.Protocol AS RawProtocol, r.Payload AS RawPayload,
        r.IsValid AS IsValid, r.ErrorMessage AS ErrorMessage,
        d.IMEI AS DevIMEI, d.SiteId AS DevSiteId
    FROM dbo.TCPMessages t
    LEFT JOIN dbo.RawMessages r ON r.Id = t.RawMessageId
    LEFT JOIN dbo.Devices     d ON d.DeviceId = t.DeviceId
    {where}
    ORDER BY t.Id DESC
"""


@router.get("/api/tcp-logs")
def api_tcp_logs(
    limit: int = Query(50, ge=1, le=200),
    status: str = Query(None),
    device_id: str = Query(None),
):
    where = []
    params = {"limit": limit}
    if status:
        where.append("t.Status = :status")
        params["status"] = status
    if device_id:
        where.append("t.DeviceId = :device_id")
        params["device_id"] = device_id
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    sql = text(_SQL.format(where=clause))

    messages = []
    last_at = None
    with Session(engine) as db:               # read-only, short-lived session
        rows = db.execute(sql, params).mappings().all()
    for r in rows:
        payload = r["Payload"] if r["Payload"] is not None else ""
        if not isinstance(payload, str):
            payload = bytes(payload).decode("latin-1")  # binary column -> lossless
        raw_payload = r["RawPayload"]
        if raw_payload is not None and not isinstance(raw_payload, str):
            raw_payload = bytes(raw_payload).decode("latin-1")
        if last_at is None and r["ReceivedAt"] is not None:
            last_at = r["ReceivedAt"]
        messages.append({
            "id": r["Id"],
            "receivedAt": _format_ist(r["ReceivedAt"]),
            "deviceId": r["DeviceId"] or "UNKNOWN",
            "imei": r["DevIMEI"],
            "siteId": r["DevSiteId"],
            "sourceIp": r["SourceIP"] or "",
            "protocol": "TCP / ASCII",
            "rawProtocol": r["RawProtocol"],
            "status": r["Status"],
            "tcpReceived": "YES",
            "parseStatus": _parse_status(r["Status"], r["IsValid"]),
            "databaseStatus": "STORED",
            "acknowledgement": r["Acknowledgement"],
            "rawMessageId": r["RawMessageId"],
            "errorMessage": r["ErrorMessage"],
            "payload": payload,                 # EXACT stored payload
            "payloadPreview": _preview(payload),
            "payloadEscaped": _escape(payload),
            "payloadHex": _hex(payload),
            "hasNonPrintable": _has_nonprintable(payload),
            "byteLength": len(payload.encode("utf-8", "surrogatepass")),
            "rawPayload": raw_payload,
        })

    return JSONResponse({
        "status": "ok",
        "count": len(messages),
        "lastMessageAt": _format_ist(last_at) if last_at else None,
        "messages": messages,
    })


@router.get("/tcp-logs", response_class=HTMLResponse)
def tcp_logs_page():
    return HTMLResponse(_PAGE_HTML)


_PAGE_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>STORM ENERGY RTU — TCP TEST LOG</title>
<style>
 :root{color-scheme:light dark}
 body{font-family:ui-monospace,Menlo,Consolas,monospace;margin:0;background:#0f1115;color:#d7dbe0}
 header{padding:16px 20px;border-bottom:1px solid #2a2f3a}
 h1{font-size:16px;letter-spacing:1px;margin:0}
 .sub{font-size:12px;color:#8b93a1;margin-top:2px}
 .status{padding:12px 20px;border-bottom:1px solid #2a2f3a;font-size:13px;display:flex;gap:24px;flex-wrap:wrap}
 .dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px}
 .wait{background:#e0b23c}
 table{width:100%;border-collapse:collapse;font-size:12.5px}
 th,td{text-align:left;padding:7px 12px;border-bottom:1px solid #20242e;vertical-align:top}
 th{color:#8b93a1;position:sticky;top:0;background:#0f1115}
 tr.row{cursor:pointer} tr.row:hover{background:#161a22}
 td.pl{color:#9fb0c3;max-width:380px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .badge{font-size:11px;padding:2px 7px;border-radius:3px;font-weight:600}
 .b-ok{background:#123a25;color:#5fe0a0}.b-bad{background:#3a1717;color:#f08a7a}.b-other{background:#33321a;color:#e0cf7a}
 .detail td{background:#12151c;padding:0}.detail-inner{padding:14px 20px}
 .sec{color:#8b93a1;font-size:11px;letter-spacing:1px;margin:14px 0 4px}
 pre{margin:0;padding:10px 12px;background:#0a0c10;border:1px solid #232833;border-radius:4px;white-space:pre-wrap;word-break:break-all;font-size:12.5px;color:#e6ebf1}
 .kv{display:grid;grid-template-columns:150px 1fr;gap:2px 12px;font-size:12.5px}
 .kv div:nth-child(odd){color:#8b93a1}
 .err{color:#f08a7a}.foot{padding:10px 20px;font-size:11px;color:#6b7280}
</style></head>
<body>
<header><h1>STORM ENERGY RTU &nbsp;—&nbsp; TCP TEST LOG</h1>
<div class="sub">Read-only viewer · newest first · auto-refresh 5s · shows valid AND invalid packets</div></header>
<div class="status" id="status">Loading…</div>
<table><thead><tr>
 <th>Received Time</th><th>Device</th><th>IMEI</th><th>Site ID</th>
 <th>Source IP</th><th>Protocol</th><th>Status</th><th>Payload</th>
</tr></thead><tbody id="rows"></tbody></table>
<div class="foot" id="foot"></div>
<script>
const expanded=new Set();
function badge(p){if(p==='VALID')return['b-ok',p];if(p==='INVALID'||p==='FAILED')return['b-bad',p];return['b-other',p||'UNKNOWN'];}
function td(t,c){const e=document.createElement('td');if(c)e.className=c;e.textContent=(t==null?'':String(t));return e;}
function pre(t){const p=document.createElement('pre');p.textContent=(t==null?'':String(t));return p;}
function sec(t){const d=document.createElement('div');d.className='sec';d.textContent=t;return d;}
function renderStatus(d){const s=document.getElementById('status');s.innerHTML='';
 const last=document.createElement('div');
 if(!d.count){last.innerHTML='<span class="dot wait"></span>WAITING FOR TCP DATA';}
 else if(d.lastMessageAt){last.textContent='LAST TCP MESSAGE: '+d.lastMessageAt;}
 else{last.innerHTML='<span class="dot wait"></span>WAITING FOR RTU DATA';}
 const c=document.createElement('div');c.textContent='RECORDS: '+d.count;
 s.append(last,c);}
function detail(m){const tr=document.createElement('tr');tr.className='detail';
 const cell=document.createElement('td');cell.colSpan=8;const box=document.createElement('div');box.className='detail-inner';
 const kv=document.createElement('div');kv.className='kv';
 [['RECEIVED TIME',m.receivedAt],['SOURCE IP',m.sourceIp],['DEVICE ID',m.deviceId],
  ['IMEI (registry)',m.imei],['SITE ID (registry)',m.siteId],['PROTOCOL',m.protocol],
  ['STATUS',m.status],['TCP RECEIVED',m.tcpReceived],['PARSE STATUS',m.parseStatus],
  ['DATABASE STATUS',m.databaseStatus],['ACKNOWLEDGEMENT',m.acknowledgement],
  ['RAW MESSAGE ID',m.rawMessageId]].forEach(([k,v])=>{const a=document.createElement('div');a.textContent=k;
   const b=document.createElement('div');b.textContent=(v==null?'—':String(v));kv.append(a,b);});
 box.append(kv);
 if(m.errorMessage){box.append(sec('ERROR MESSAGE'));const e=pre(m.errorMessage);e.classList.add('err');box.append(e);}
 box.append(sec('EXACT STORED PAYLOAD  (dbo.TCPMessages.Payload · '+(m.byteLength||0)+' bytes · not byte-exact socket capture)'));
 box.append(pre(m.payload));
 if(m.hasNonPrintable){box.append(sec('SAFE ESCAPED VIEW  (control bytes as \\xNN)'));box.append(pre(m.payloadEscaped));}
 box.append(sec('RAW HEX  (of stored payload)'));box.append(pre(m.payloadHex));
 if(m.rawPayload!=null){box.append(sec('RAW-INGESTION PAYLOAD  (dbo.RawMessages.Payload)'));box.append(pre(m.rawPayload));}
 box.append(sec('PARSED TELEMETRY'));
 const note=document.createElement('div');note.className='sub';
 note.textContent='Not stored by the existing parser for this record — the exact stored payload above is authoritative.';
 box.append(note);
 cell.append(box);tr.append(cell);return tr;}
function render(d){renderStatus(d);const body=document.getElementById('rows');body.innerHTML='';
 d.messages.forEach(m=>{const tr=document.createElement('tr');tr.className='row';
  tr.append(td(m.receivedAt),td(m.deviceId),td(m.imei==null?'—':m.imei),td(m.siteId==null?'—':m.siteId),td(m.sourceIp),td(m.protocol));
  const st=document.createElement('td');const[c,l]=badge(m.parseStatus);const sp=document.createElement('span');sp.className='badge '+c;sp.textContent=l;st.append(sp);tr.append(st);
  tr.append(td(m.payloadPreview,'pl'));
  tr.onclick=()=>{if(expanded.has(m.id))expanded.delete(m.id);else expanded.add(m.id);refresh();};
  body.append(tr);if(expanded.has(m.id))body.append(detail(m));});
 document.getElementById('foot').textContent='Showing '+d.messages.length+' most-recent TCP messages · read-only';}
async function refresh(){try{const r=await fetch('/api/tcp-logs?limit=50',{cache:'no-store'});render(await r.json());}
 catch(e){document.getElementById('status').innerHTML='<span class="dot wait"></span>VIEWER CANNOT REACH API';}}
refresh();setInterval(refresh,5000);
</script></body></html>"""
