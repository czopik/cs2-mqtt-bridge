from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

from dotenv import load_dotenv
from flask import Flask, jsonify, Response
import paho.mqtt.client as mqtt


load_dotenv()


class Config:
    MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
    MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
    MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
    MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
    MQTT_KEEPALIVE = int(os.getenv("MQTT_KEEPALIVE", "60"))
    MQTT_TOPIC_STATE = os.getenv("MQTT_TOPIC_STATE", "cs2/state")

    DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "127.0.0.1")
    DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "4000"))
    DASHBOARD_CLIENT_ID = os.getenv("DASHBOARD_CLIENT_ID", "cs2-dashboard")


config = Config()

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("cs2_dashboard")

app = Flask(__name__)

state_lock = threading.Lock()
latest_state: dict[str, Any] = {}
latest_state_at = 0.0
mqtt_connected = False


DASHBOARD_HTML = r"""
<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>CS2 Live Dashboard</title>
  <style>
    :root {
      --bg: #070b12;
      --panel: rgba(255, 255, 255, 0.075);
      --panel2: rgba(255, 255, 255, 0.11);
      --text: #eef5ff;
      --muted: #8fa2ba;
      --green: #3df58a;
      --yellow: #ffd34d;
      --red: #ff4d67;
      --blue: #4da3ff;
      --purple: #b46cff;
      --line: rgba(255, 255, 255, 0.12);
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-height: 100vh;
      color: var(--text);
      font-family: Inter, Segoe UI, Roboto, Arial, sans-serif;
      background:
        radial-gradient(circle at 20% 10%, rgba(77, 163, 255, 0.22), transparent 28%),
        radial-gradient(circle at 80% 30%, rgba(180, 108, 255, 0.18), transparent 30%),
        linear-gradient(135deg, #070b12, #0d1420 55%, #090b10);
      overflow: hidden;
    }

    .app {
      height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
      gap: 18px;
      padding: 22px;
    }

    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }

    .title {
      display: flex;
      align-items: center;
      gap: 14px;
    }

    .logo {
      width: 48px;
      height: 48px;
      border-radius: 14px;
      display: grid;
      place-items: center;
      background: linear-gradient(135deg, rgba(77, 163, 255, 0.9), rgba(180, 108, 255, 0.85));
      box-shadow: 0 16px 40px rgba(77, 163, 255, 0.18);
      font-weight: 900;
      letter-spacing: -1px;
    }

    h1 {
      margin: 0;
      font-size: clamp(28px, 3vw, 46px);
      line-height: 1;
      letter-spacing: -1.3px;
    }

    .sub {
      margin-top: 6px;
      color: var(--muted);
      font-size: 14px;
    }

    .statusbar {
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
      justify-content: flex-end;
    }

    .pill {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 999px;
      padding: 10px 14px;
      font-weight: 700;
      color: var(--muted);
    }

    .dot {
      display: inline-block;
      width: 9px;
      height: 9px;
      border-radius: 50%;
      margin-right: 8px;
      background: var(--red);
      box-shadow: 0 0 18px var(--red);
    }

    .dot.ok { background: var(--green); box-shadow: 0 0 18px var(--green); }
    .dot.warn { background: var(--yellow); box-shadow: 0 0 18px var(--yellow); }

    .grid {
      min-height: 0;
      display: grid;
      grid-template-columns: 1.15fr 0.85fr;
      gap: 18px;
    }

    .left, .right {
      min-height: 0;
      display: grid;
      gap: 18px;
    }

    .left { grid-template-rows: 1fr 0.72fr; }
    .right { grid-template-rows: 0.85fr 1fr; }

    .card {
      border: 1px solid var(--line);
      border-radius: 28px;
      background: linear-gradient(180deg, var(--panel2), rgba(255,255,255,0.055));
      box-shadow: 0 22px 80px rgba(0, 0, 0, 0.27);
      backdrop-filter: blur(12px);
      padding: 22px;
      overflow: hidden;
    }

    .hero {
      display: grid;
      grid-template-columns: 1fr auto;
      align-items: center;
      gap: 16px;
    }

    .map {
      font-size: clamp(44px, 6vw, 90px);
      font-weight: 900;
      letter-spacing: -3px;
      text-transform: uppercase;
      line-height: 0.95;
    }

    .phase {
      margin-top: 12px;
      font-size: clamp(22px, 2.5vw, 38px);
      color: var(--blue);
      font-weight: 900;
      text-transform: uppercase;
    }

    .scoreBox {
      text-align: center;
      min-width: 260px;
      padding: 22px;
      border-radius: 24px;
      background: rgba(0,0,0,0.22);
      border: 1px solid var(--line);
    }

    .score {
      font-size: clamp(56px, 7vw, 112px);
      line-height: 0.9;
      font-weight: 1000;
      letter-spacing: -4px;
    }

    .team {
      margin-top: 12px;
      font-size: 20px;
      color: var(--muted);
      font-weight: 800;
      text-transform: uppercase;
    }

    .stats {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 14px;
      margin-top: 22px;
    }

    .stat {
      min-height: 134px;
      border-radius: 22px;
      border: 1px solid var(--line);
      background: rgba(0,0,0,0.18);
      padding: 18px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }

    .label {
      color: var(--muted);
      font-weight: 800;
      letter-spacing: 0.5px;
      text-transform: uppercase;
      font-size: 13px;
    }

    .value {
      font-size: clamp(34px, 4vw, 64px);
      font-weight: 1000;
      line-height: 0.95;
      letter-spacing: -2px;
    }

    .barWrap {
      height: 16px;
      border-radius: 999px;
      overflow: hidden;
      background: rgba(255,255,255,0.12);
      margin-top: 12px;
    }

    .bar {
      height: 100%;
      width: 0%;
      border-radius: 999px;
      background: var(--green);
      transition: width 0.18s ease, background 0.18s ease;
    }

    .bombCard {
      display: grid;
      place-items: center;
      text-align: center;
      position: relative;
    }

    .bombState {
      color: var(--muted);
      font-weight: 900;
      text-transform: uppercase;
      letter-spacing: 1px;
      font-size: 16px;
    }

    .bombTime {
      margin-top: 12px;
      font-size: clamp(70px, 8vw, 140px);
      font-weight: 1000;
      line-height: 0.9;
      letter-spacing: -5px;
    }

    .bombActive .bombTime { color: var(--red); text-shadow: 0 0 35px rgba(255, 77, 103, 0.38); }
    .bombCritical { animation: pulse 0.35s infinite alternate; }

    @keyframes pulse {
      from { filter: brightness(0.85); transform: scale(0.99); }
      to { filter: brightness(1.55); transform: scale(1.015); }
    }

    .miniGrid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 14px;
    }

    .raw {
      height: 100%;
      min-height: 0;
      display: flex;
      flex-direction: column;
    }

    pre {
      margin: 14px 0 0;
      flex: 1;
      min-height: 0;
      overflow: auto;
      padding: 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(0,0,0,0.26);
      color: #d7e7ff;
      font-size: 13px;
      line-height: 1.45;
    }

    .empty {
      color: var(--muted);
      font-size: clamp(22px, 2.2vw, 34px);
      font-weight: 800;
      text-align: center;
      padding: 50px 20px;
    }

    @media (max-width: 1100px) {
      body { overflow: auto; }
      .app { height: auto; min-height: 100vh; }
      .grid, .hero { grid-template-columns: 1fr; }
      .stats { grid-template-columns: repeat(2, 1fr); }
      .scoreBox { min-width: 0; }
    }
  </style>
</head>
<body>
  <main class="app">
    <header>
      <div class="title">
        <div class="logo">CS2</div>
        <div>
          <h1>Live Dashboard</h1>
          <div class="sub">Drugi monitor — dane z CS2 GSI przez MQTT</div>
        </div>
      </div>
      <div class="statusbar">
        <div class="pill"><span id="connDot" class="dot"></span><span id="connText">Brak danych</span></div>
        <div class="pill">MQTT: <span id="mqttText">?</span></div>
        <div class="pill">Age: <span id="ageText">-</span></div>
      </div>
    </header>

    <section id="content" class="grid">
      <div class="left">
        <div class="card">
          <div class="hero">
            <div>
              <div id="map" class="map">WAITING</div>
              <div id="phase" class="phase">odpal CS2 albo test JSON</div>
            </div>
            <div class="scoreBox">
              <div id="score" class="score">0-0</div>
              <div id="team" class="team">TEAM -</div>
            </div>
          </div>
          <div class="stats">
            <div class="stat">
              <div class="label">Health</div>
              <div id="health" class="value">-</div>
              <div class="barWrap"><div id="healthBar" class="bar"></div></div>
            </div>
            <div class="stat">
              <div class="label">Armor</div>
              <div id="armor" class="value">-</div>
              <div class="barWrap"><div id="armorBar" class="bar"></div></div>
            </div>
            <div class="stat">
              <div class="label">Ammo</div>
              <div id="ammo" class="value">-</div>
            </div>
            <div class="stat">
              <div class="label">Round</div>
              <div id="round" class="value">-</div>
            </div>
          </div>
        </div>

        <div class="card miniGrid">
          <div class="stat"><div class="label">Kills</div><div id="kills" class="value">-</div></div>
          <div class="stat"><div class="label">Deaths</div><div id="deaths" class="value">-</div></div>
          <div class="stat"><div class="label">Score</div><div id="playerScore" class="value">-</div></div>
          <div class="stat"><div class="label">Round kills</div><div id="roundKills" class="value">-</div></div>
        </div>
      </div>

      <div class="right">
        <div id="bombCard" class="card bombCard">
          <div>
            <div id="bombState" class="bombState">Bomb</div>
            <div id="bombTime" class="bombTime">--</div>
          </div>
        </div>
        <div class="card raw">
          <div class="label">Raw normalized state</div>
          <pre id="raw">{}</pre>
        </div>
      </div>
    </section>
  </main>

  <script>
    const $ = (id) => document.getElementById(id);

    function val(v, fallback = '-') {
      return v === null || v === undefined || v === '' ? fallback : v;
    }

    function mapName(name) {
      if (!name) return 'WAITING';
      return String(name).replace(/^de_/, '').replace(/^cs_/, '').toUpperCase();
    }

    function setBar(id, value) {
      const n = Math.max(0, Math.min(100, Number(value || 0)));
      const el = $(id);
      el.style.width = n + '%';
      if (n <= 20) el.style.background = 'var(--red)';
      else if (n <= 50) el.style.background = 'var(--yellow)';
      else el.style.background = 'var(--green)';
    }

    function scoreText(s) {
      const ct = Number(s.ct_score ?? 0);
      const t = Number(s.t_score ?? 0);
      if ((s.team || '').toUpperCase() === 'T') return `${t}-${ct}`;
      return `${ct}-${t}`;
    }

    function update(data) {
      const s = data.state || {};
      const age = Number(data.age_seconds ?? 999);
      const fresh = Object.keys(s).length > 0 && age < 3;
      const stale = Object.keys(s).length > 0 && age >= 3;

      $('connDot').className = 'dot ' + (fresh ? 'ok' : stale ? 'warn' : '');
      $('connText').textContent = fresh ? 'LIVE' : stale ? 'Stare dane' : 'Brak danych';
      $('mqttText').textContent = data.mqtt_connected ? 'OK' : 'OFF';
      $('ageText').textContent = Number.isFinite(age) && age < 999 ? age.toFixed(1) + 's' : '-';

      $('map').textContent = mapName(s.map);
      $('phase').textContent = val(s.round_phase || s.activity, 'waiting');
      $('score').textContent = scoreText(s);
      $('team').textContent = 'TEAM ' + val(s.team);

      $('health').textContent = val(s.health);
      $('armor').textContent = val(s.armor);
      $('ammo').textContent = val(s.ammo);
      $('round').textContent = val(s.round);
      $('kills').textContent = val(s.kills);
      $('deaths').textContent = val(s.deaths);
      $('playerScore').textContent = val(s.score);
      $('roundKills').textContent = val(s.round_kills);
      setBar('healthBar', s.health);
      setBar('armorBar', s.armor);

      const bombState = val(s.bomb_state, 'none');
      const bombSeconds = s.bomb_seconds;
      $('bombState').textContent = bombState;
      $('bombTime').textContent = bombSeconds === null || bombSeconds === undefined ? '--' : String(bombSeconds).padStart(2, '0');
      const bombCard = $('bombCard');
      bombCard.classList.toggle('bombActive', bombState === 'planted' || bombState === 'plant');
      bombCard.classList.toggle('bombCritical', Number(bombSeconds) <= 10 && (bombState === 'planted' || bombState === 'plant'));

      $('raw').textContent = JSON.stringify(s, null, 2);
    }

    async function poll() {
      try {
        const res = await fetch('/api/state', { cache: 'no-store' });
        update(await res.json());
      } catch (err) {
        $('connDot').className = 'dot';
        $('connText').textContent = 'Dashboard offline';
        $('raw').textContent = String(err);
      }
    }

    poll();
    setInterval(poll, 250);
  </script>
</body>
</html>
"""


@app.get("/")
def dashboard() -> Response:
    return Response(DASHBOARD_HTML, mimetype="text/html")


@app.get("/api/state")
def api_state():
    with state_lock:
        snapshot = dict(latest_state)
        state_at = latest_state_at
        connected = mqtt_connected
    age = time.time() - state_at if state_at else 999999
    return jsonify(
        {
            "ok": True,
            "mqtt_connected": connected,
            "age_seconds": round(age, 3),
            "state": snapshot,
        }
    )


def on_connect(client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
    global mqtt_connected
    if reason_code == 0:
        mqtt_connected = True
        logger.info("Connected to MQTT %s:%s, subscribing to %s", config.MQTT_HOST, config.MQTT_PORT, config.MQTT_TOPIC_STATE)
        client.subscribe(config.MQTT_TOPIC_STATE, qos=1)
    else:
        mqtt_connected = False
        logger.error("MQTT connect failed. reason_code=%s", reason_code)


def on_disconnect(client: mqtt.Client, userdata: Any, disconnect_flags: Any, reason_code: Any, properties: Any) -> None:
    global mqtt_connected
    mqtt_connected = False
    logger.warning("MQTT disconnected. reason_code=%s", reason_code)


def on_message(client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
    global latest_state, latest_state_at
    try:
        payload = json.loads(message.payload.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("state payload is not a JSON object")
    except Exception as exc:
        logger.warning("Invalid state payload on %s: %s", message.topic, exc)
        return

    with state_lock:
        latest_state = payload
        latest_state_at = time.time()


def start_mqtt() -> mqtt.Client:
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=config.DASHBOARD_CLIENT_ID,
        protocol=mqtt.MQTTv311,
        clean_session=True,
    )
    if config.MQTT_USERNAME:
        client.username_pw_set(config.MQTT_USERNAME, config.MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=3, max_delay=30)
    client.connect(config.MQTT_HOST, config.MQTT_PORT, keepalive=config.MQTT_KEEPALIVE)
    client.loop_start()
    return client


if __name__ == "__main__":
    mqtt_client = start_mqtt()
    try:
        logger.info("Dashboard: http://%s:%s", config.DASHBOARD_HOST, config.DASHBOARD_PORT)
        app.run(host=config.DASHBOARD_HOST, port=config.DASHBOARD_PORT, use_reloader=False, threaded=True)
    finally:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
