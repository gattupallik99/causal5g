"""
api/control.py  — Causal5G Container Control Panel
Add to your main FastAPI app:
    from api.control import router as control_router
    app.include_router(control_router)
"""

import asyncio
import json
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter()

# Free5GC NF container name prefixes — adjust if yours differ
NF_NAMES = ["amf", "smf", "upf", "pcf", "nrf", "ausf", "udm", "udr", "nssf"]

# Path to your free5gc docker-compose directory
COMPOSE_DIR = "/Users/krishnakumargattupalli/causal5g/infra/free5gc"  # ← UPDATE THIS


async def run_cmd(*args) -> tuple[int, str, str]:
    """Run a command async, return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode().strip(), stderr.decode().strip()


async def get_container_statuses() -> list[dict]:
    """Return list of {name, id, status, running} for all containers."""
    rc, out, _ = await run_cmd(
        "docker", "ps", "-a",
        "--format", '{"id":"{{.ID}}","name":"{{.Names}}","status":"{{.Status}}","state":"{{.State}}"}'
    )
    containers = []
    if rc != 0 or not out:
        return containers
    for line in out.splitlines():
        try:
            c = json.loads(line)
            c["running"] = c.get("state", "").lower() == "running"
            # tag which NF this is (if any)
            c["nf"] = next((nf for nf in NF_NAMES if nf in c["name"].lower()), None)
            containers.append(c)
        except json.JSONDecodeError:
            continue
    return containers


# ── API endpoints ──────────────────────────────────────────────────────────────

@router.get("/control/status")
async def container_status():
    containers = await get_container_statuses()
    return JSONResponse({"containers": containers})


@router.post("/control/start-all")
async def start_all():
    rc, out, err = await run_cmd("docker", "compose", "-f", f"{COMPOSE_DIR}/docker-compose.yml", "up", "-d")
    return {"ok": rc == 0, "out": out, "err": err}


@router.post("/control/stop-all")
async def stop_all():
    rc, out, err = await run_cmd("docker", "compose", "-f", f"{COMPOSE_DIR}/docker-compose.yml", "down")
    return {"ok": rc == 0, "out": out, "err": err}


@router.post("/control/start/{container_name}")
async def start_container(container_name: str):
    rc, out, err = await run_cmd("docker", "start", container_name)
    return {"ok": rc == 0, "container": container_name, "out": out, "err": err}


@router.post("/control/stop/{container_name}")
async def stop_container(container_name: str):
    rc, out, err = await run_cmd("docker", "stop", container_name)
    return {"ok": rc == 0, "container": container_name, "out": out, "err": err}


# ── Control Panel HTML page ────────────────────────────────────────────────────

@router.get("/control", response_class=HTMLResponse)
async def control_panel():
    return HTMLResponse(CONTROL_PANEL_HTML)


CONTROL_PANEL_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Causal5G — Control Panel</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Syne:wght@700;800&display=swap" rel="stylesheet"/>
<style>
  :root {
    --bg:       #080c14;
    --surface:  #0d1320;
    --border:   #1a2540;
    --accent:   #00e5ff;
    --green:    #00ff88;
    --red:      #ff3860;
    --yellow:   #ffdd57;
    --muted:    #4a5878;
    --text:     #cdd6f4;
    --text-dim: #6b7a99;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'JetBrains Mono', monospace;
    min-height: 100vh;
    overflow-x: hidden;
  }

  /* grid noise overlay */
  body::before {
    content: '';
    position: fixed; inset: 0;
    background-image:
      linear-gradient(rgba(0,229,255,0.03) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0,229,255,0.03) 1px, transparent 1px);
    background-size: 40px 40px;
    pointer-events: none;
    z-index: 0;
  }

  .wrap { position: relative; z-index: 1; max-width: 1100px; margin: 0 auto; padding: 2rem 1.5rem; }

  /* ── Header ── */
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 2.5rem;
    padding-bottom: 1.5rem;
    border-bottom: 1px solid var(--border);
  }

  .logo { display: flex; align-items: center; gap: 0.75rem; }

  .logo-mark {
    width: 38px; height: 38px;
    background: linear-gradient(135deg, var(--accent), #7b61ff);
    border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    font-family: 'Syne', sans-serif;
    font-weight: 800; font-size: 1rem; color: #000;
  }

  h1 {
    font-family: 'Syne', sans-serif;
    font-weight: 800; font-size: 1.25rem;
    letter-spacing: -0.02em;
  }

  h1 span { color: var(--accent); }

  .subtitle { font-size: 0.7rem; color: var(--text-dim); margin-top: 0.1rem; }

  .header-nav { display: flex; gap: 0.75rem; }

  .nav-link {
    font-size: 0.72rem; color: var(--text-dim);
    text-decoration: none; padding: 0.4rem 0.85rem;
    border: 1px solid var(--border); border-radius: 6px;
    transition: all 0.2s;
  }
  .nav-link:hover, .nav-link.active {
    color: var(--accent); border-color: var(--accent);
    background: rgba(0,229,255,0.06);
  }

  /* ── Status bar ── */
  .status-bar {
    display: flex; align-items: center; gap: 1rem;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 0.85rem 1.25rem;
    margin-bottom: 1.75rem;
    font-size: 0.72rem;
  }

  .pulse {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--green);
    box-shadow: 0 0 8px var(--green);
    animation: pulse 2s infinite;
    flex-shrink: 0;
  }
  .pulse.dead { background: var(--red); box-shadow: 0 0 8px var(--red); animation: none; }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }

  #status-text { color: var(--text-dim); }
  #status-text strong { color: var(--text); }

  .last-update { margin-left: auto; color: var(--muted); font-size: 0.65rem; }

  /* ── Global controls ── */
  .global-controls {
    display: grid; grid-template-columns: 1fr 1fr;
    gap: 0.75rem; margin-bottom: 2rem;
  }

  .btn-global {
    display: flex; align-items: center; justify-content: center; gap: 0.6rem;
    padding: 0.9rem 1.5rem;
    border-radius: 10px; border: 1px solid;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.78rem; font-weight: 600;
    cursor: pointer; transition: all 0.2s;
    letter-spacing: 0.05em;
  }

  .btn-start-all {
    background: rgba(0,255,136,0.08);
    border-color: var(--green); color: var(--green);
  }
  .btn-start-all:hover {
    background: rgba(0,255,136,0.16);
    box-shadow: 0 0 20px rgba(0,255,136,0.2);
  }

  .btn-stop-all {
    background: rgba(255,56,96,0.08);
    border-color: var(--red); color: var(--red);
  }
  .btn-stop-all:hover {
    background: rgba(255,56,96,0.16);
    box-shadow: 0 0 20px rgba(255,56,96,0.2);
  }

  .btn-global:disabled {
    opacity: 0.4; cursor: not-allowed;
    box-shadow: none;
  }

  /* ── Section header ── */
  .section-header {
    display: flex; align-items: center; gap: 0.6rem;
    font-size: 0.68rem; font-weight: 600;
    color: var(--text-dim); letter-spacing: 0.1em;
    text-transform: uppercase;
    margin-bottom: 1rem;
  }
  .section-header::after {
    content: ''; flex: 1; height: 1px;
    background: var(--border);
  }

  /* ── NF Grid ── */
  #nf-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 0.85rem;
    margin-bottom: 2rem;
  }

  .nf-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.1rem 1.25rem;
    transition: border-color 0.2s, box-shadow 0.2s;
    position: relative;
    overflow: hidden;
  }

  .nf-card::before {
    content: '';
    position: absolute; top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, var(--card-color, var(--accent)), transparent);
    opacity: 0;
    transition: opacity 0.3s;
  }

  .nf-card.running { --card-color: var(--green); }
  .nf-card.running::before { opacity: 1; }
  .nf-card.stopped { --card-color: var(--red); }

  .nf-card:hover { border-color: rgba(0,229,255,0.3); }

  .nf-top {
    display: flex; align-items: center;
    justify-content: space-between;
    margin-bottom: 0.7rem;
  }

  .nf-name {
    font-family: 'Syne', sans-serif;
    font-weight: 700; font-size: 1rem;
    letter-spacing: -0.01em;
  }

  .nf-badge {
    font-size: 0.6rem; font-weight: 600;
    padding: 0.2rem 0.55rem; border-radius: 4px;
    letter-spacing: 0.08em; text-transform: uppercase;
  }
  .badge-running {
    background: rgba(0,255,136,0.12);
    color: var(--green); border: 1px solid rgba(0,255,136,0.3);
  }
  .badge-stopped {
    background: rgba(255,56,96,0.1);
    color: var(--red); border: 1px solid rgba(255,56,96,0.25);
  }
  .badge-unknown {
    background: rgba(74,88,120,0.2);
    color: var(--muted); border: 1px solid var(--border);
  }

  .nf-container-name {
    font-size: 0.62rem; color: var(--text-dim);
    margin-bottom: 0.9rem;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }

  .nf-actions { display: flex; gap: 0.5rem; }

  .btn-nf {
    flex: 1; padding: 0.45rem;
    border-radius: 7px; border: 1px solid;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.65rem; font-weight: 600;
    cursor: pointer; transition: all 0.15s;
    letter-spacing: 0.05em;
  }

  .btn-nf-start {
    background: rgba(0,255,136,0.07);
    border-color: rgba(0,255,136,0.3); color: var(--green);
  }
  .btn-nf-start:hover:not(:disabled) {
    background: rgba(0,255,136,0.15);
  }

  .btn-nf-stop {
    background: rgba(255,56,96,0.07);
    border-color: rgba(255,56,96,0.25); color: var(--red);
  }
  .btn-nf-stop:hover:not(:disabled) {
    background: rgba(255,56,96,0.15);
  }

  .btn-nf:disabled { opacity: 0.3; cursor: not-allowed; }

  /* ── Fault Injection ── */
  #fault-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 0.7rem;
    margin-bottom: 2rem;
  }

  .fault-btn {
    padding: 0.65rem 1rem;
    border-radius: 8px;
    background: rgba(255,221,87,0.06);
    border: 1px solid rgba(255,221,87,0.2);
    color: var(--yellow);
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.68rem; font-weight: 600;
    cursor: pointer; transition: all 0.15s;
    display: flex; align-items: center; gap: 0.5rem;
    letter-spacing: 0.04em;
  }
  .fault-btn:hover:not(:disabled) {
    background: rgba(255,221,87,0.12);
    box-shadow: 0 0 12px rgba(255,221,87,0.15);
  }
  .fault-btn:disabled { opacity: 0.35; cursor: not-allowed; }

  /* ── Log / toast ── */
  #log {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1rem 1.25rem;
    font-size: 0.68rem;
    color: var(--text-dim);
    min-height: 56px;
    max-height: 140px;
    overflow-y: auto;
    line-height: 1.7;
  }

  .log-entry { display: flex; gap: 0.75rem; }
  .log-time { color: var(--muted); flex-shrink: 0; }
  .log-ok { color: var(--green); }
  .log-err { color: var(--red); }
  .log-info { color: var(--accent); }

  /* ── Spinner ── */
  .spinner {
    display: inline-block;
    width: 10px; height: 10px;
    border: 2px solid rgba(255,255,255,0.2);
    border-top-color: currentColor;
    border-radius: 50%;
    animation: spin 0.6s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── Other containers section ── */
  #other-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 0.7rem;
    margin-bottom: 2rem;
  }

  .other-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 0.8rem 1rem;
    display: flex; align-items: center;
    justify-content: space-between;
    font-size: 0.7rem;
  }

  .other-name { color: var(--text); font-weight: 600; }
  .other-status { font-size: 0.62rem; color: var(--text-dim); margin-top: 0.1rem; }

  .dot {
    width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0;
    margin-right: 0.5rem;
  }
  .dot-green { background: var(--green); box-shadow: 0 0 5px var(--green); }
  .dot-red   { background: var(--red);   box-shadow: 0 0 5px var(--red); }
  .dot-gray  { background: var(--muted); }
</style>
</head>
<body>
<div class="wrap">

  <!-- Header -->
  <header>
    <div class="logo">
      <div class="logo-mark">C5</div>
      <div>
        <h1>Causal<span>5G</span></h1>
        <div class="subtitle">Container Control Panel</div>
      </div>
    </div>
    <nav class="header-nav">
      <a href="/demo" class="nav-link">Demo</a>
      <a href="/control" class="nav-link active">Control</a>
      <a href="/docs" class="nav-link">API Docs</a>
    </nav>
  </header>

  <!-- Status bar -->
  <div class="status-bar">
    <div class="pulse" id="pulse-dot"></div>
    <span id="status-text"><strong>—</strong> containers running</span>
    <span class="last-update" id="last-update">refreshing…</span>
  </div>

  <!-- Global controls -->
  <div class="global-controls">
    <button class="btn-global btn-start-all" onclick="startAll()">
      ▶ START ALL
    </button>
    <button class="btn-global btn-stop-all" onclick="stopAll()">
      ■ STOP ALL
    </button>
  </div>

  <!-- 5G NF cards -->
  <div class="section-header">5G Network Functions</div>
  <div id="nf-grid">
    <div style="color:var(--muted);font-size:0.72rem;grid-column:1/-1">Loading…</div>
  </div>

  <!-- Fault injection -->
  <div class="section-header">Fault Injection</div>
  <div id="fault-grid"></div>

  <!-- Other containers -->
  <div class="section-header">All Containers</div>
  <div id="other-grid">
    <div style="color:var(--muted);font-size:0.72rem">Loading…</div>
  </div>

  <!-- Log -->
  <div class="section-header">Activity Log</div>
  <div id="log"><span style="color:var(--muted)">No activity yet.</span></div>

</div>

<script>
const NF_LABELS = {
  amf:"AMF", smf:"SMF", upf:"UPF", pcf:"PCF",
  nrf:"NRF", ausf:"AUSF", udm:"UDM", udr:"UDR", nssf:"NSSF"
};

let lastContainers = [];

function ts() {
  return new Date().toLocaleTimeString('en-US',{hour12:false});
}

function log(msg, type='info') {
  const el = document.getElementById('log');
  const blank = el.querySelector('span');
  if(blank) blank.remove();
  const row = document.createElement('div');
  row.className = 'log-entry';
  row.innerHTML = `<span class="log-time">${ts()}</span><span class="log-${type}">${msg}</span>`;
  el.prepend(row);
  // keep max 30 lines
  while(el.children.length > 30) el.removeChild(el.lastChild);
}

async function api(method, path) {
  const res = await fetch(path, {method});
  return res.json();
}

async function startAll() {
  log('Starting all containers via docker compose up…', 'info');
  disableGlobal(true);
  const d = await api('POST', '/control/start-all');
  log(d.ok ? '✓ All containers started' : `✗ Error: ${d.err}`, d.ok ? 'ok' : 'err');
  disableGlobal(false);
  await refresh();
}

async function stopAll() {
  log('Stopping all containers via docker compose down…', 'info');
  disableGlobal(true);
  const d = await api('POST', '/control/stop-all');
  log(d.ok ? '✓ All containers stopped' : `✗ Error: ${d.err}`, d.ok ? 'ok' : 'err');
  disableGlobal(false);
  await refresh();
}

async function toggleContainer(name, action) {
  log(`${action === 'start' ? '▶' : '■'} ${action} ${name}…`, 'info');
  const d = await api('POST', `/control/${action}/${name}`);
  log(d.ok ? `✓ ${name} ${action}ed` : `✗ ${name}: ${d.err}`, d.ok ? 'ok' : 'err');
  await refresh();
}

async function injectFault(nf) {
  log(`⚡ Injecting fault into ${nf.toUpperCase()}…`, 'info');
  try {
    const d = await api('POST', `/fault/inject/${nf}`);
    log(`✓ Fault injected into ${nf.toUpperCase()}`, 'ok');
  } catch(e) {
    log(`✗ Fault injection failed: ${e.message}`, 'err');
  }
  await refresh();
}

function disableGlobal(v) {
  document.querySelectorAll('.btn-global').forEach(b => b.disabled = v);
}

async function refresh() {
  try {
    const data = await api('GET', '/control/status');
    lastContainers = data.containers || [];
    renderAll(lastContainers);
    const running = lastContainers.filter(c => c.running).length;
    const total = lastContainers.length;
    document.getElementById('status-text').innerHTML =
      `<strong>${running}/${total}</strong> containers running`;
    const dot = document.getElementById('pulse-dot');
    dot.className = running > 0 ? 'pulse' : 'pulse dead';
    document.getElementById('last-update').textContent = `Updated ${ts()}`;
  } catch(e) {
    document.getElementById('status-text').innerHTML =
      '<strong style="color:var(--red)">Docker unreachable</strong>';
  }
}

function renderAll(containers) {
  // Split into known NFs and others
  const nfs = containers.filter(c => c.nf);
  const others = containers.filter(c => !c.nf);

  // NF cards
  const nfGrid = document.getElementById('nf-grid');
  if(nfs.length === 0) {
    nfGrid.innerHTML = '<div style="color:var(--muted);font-size:0.72rem;grid-column:1/-1">No Free5GC NF containers found. Are they running?</div>';
  } else {
    nfGrid.innerHTML = nfs.map(c => {
      const label = NF_LABELS[c.nf] || c.nf.toUpperCase();
      const running = c.running;
      return `
      <div class="nf-card ${running ? 'running' : 'stopped'}">
        <div class="nf-top">
          <div class="nf-name">${label}</div>
          <span class="nf-badge ${running ? 'badge-running' : 'badge-stopped'}">
            ${running ? 'RUNNING' : 'STOPPED'}
          </span>
        </div>
        <div class="nf-container-name">${c.name}</div>
        <div class="nf-actions">
          <button class="btn-nf btn-nf-start" ${running ? 'disabled' : ''}
            onclick="toggleContainer('${c.name}','start')">▶ Start</button>
          <button class="btn-nf btn-nf-stop" ${!running ? 'disabled' : ''}
            onclick="toggleContainer('${c.name}','stop')">■ Stop</button>
        </div>
      </div>`;
    }).join('');
  }

  // Fault injection buttons (only for running NFs)
  const faultGrid = document.getElementById('fault-grid');
  const runningNFs = nfs.filter(c => c.running);
  if(runningNFs.length === 0) {
    faultGrid.innerHTML = '<div style="color:var(--muted);font-size:0.72rem">Start NF containers to enable fault injection.</div>';
  } else {
    faultGrid.innerHTML = runningNFs.map(c => {
      const label = NF_LABELS[c.nf] || c.nf.toUpperCase();
      return `<button class="fault-btn" onclick="injectFault('${c.nf}')">
        ⚡ Inject → ${label}
      </button>`;
    }).join('');
  }

  // Other containers
  const otherGrid = document.getElementById('other-grid');
  if(others.length === 0) {
    otherGrid.innerHTML = '<div style="color:var(--muted);font-size:0.72rem">No other containers detected.</div>';
  } else {
    otherGrid.innerHTML = others.map(c => `
      <div class="other-card">
        <div style="display:flex;align-items:center">
          <div class="dot ${c.running ? 'dot-green' : 'dot-red'}"></div>
          <div>
            <div class="other-name">${c.name}</div>
            <div class="other-status">${c.status}</div>
          </div>
        </div>
        <div style="display:flex;gap:0.4rem">
          <button class="btn-nf btn-nf-start" style="flex:0;padding:0.35rem 0.6rem" ${c.running?'disabled':''}
            onclick="toggleContainer('${c.name}','start')">▶</button>
          <button class="btn-nf btn-nf-stop" style="flex:0;padding:0.35rem 0.6rem" ${!c.running?'disabled':''}
            onclick="toggleContainer('${c.name}','stop')">■</button>
        </div>
      </div>`).join('');
  }
}

// Initial load + poll every 2s
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>"""
