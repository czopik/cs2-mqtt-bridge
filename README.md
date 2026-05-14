# CS2 MQTT LED Bridge

This project receives Counter-Strike 2 Game State Integration (GSI) updates over HTTP and publishes:
- raw snapshots to MQTT,
- normalized game state to MQTT,
- short LED-ready messages (bomb/time/round) to your LED matrix topic.

## 1) Requirements

- Windows PC with CS2
- Python 3.11+
- MQTT broker (for example Mosquitto)
- LED matrix already listening on an MQTT topic (default `all`)

## 2) Install

```powershell
cd C:\Users\chemi\cs2-mqtt-bridge
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` and set at least:
- `GSI_TOKEN`
- `MQTT_HOST`
- `MQTT_PORT`
- `MQTT_TOPIC_LED` (use your matrix topic, now default `all`)

## 3) Configure CS2 GSI

Copy file:
- from `gsi\gamestate_integration_ledmatrix.cfg`
- to `Counter-Strike\game\csgo\cfg\gamestate_integration_ledmatrix.cfg`

Typical Steam path:
- `C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\csgo\cfg\`

Important:
- Set the same token in both places:
  - `.env` -> `GSI_TOKEN`
  - `gamestate_integration_ledmatrix.cfg` -> `auth` -> `token`

## 4) Run

```powershell
cd C:\Users\chemi\cs2-mqtt-bridge
.\.venv\Scripts\Activate.ps1
python main.py
```

Server starts on `http://127.0.0.1:3000/gsi` by default.

## 5) MQTT topics

From `.env`:
- `MQTT_TOPIC_RAW` default `cs2/raw`
- `MQTT_TOPIC_STATE` default `cs2/state`
- `MQTT_TOPIC_LED` default `all`

## 6) LED behavior

- Bomb planted -> `BOMBA PODLOZONA`
- Bomb timer while planted -> updates every 1s, e.g. `BOMBA 34s`
- Last seconds warning -> `UWAGA 10s` (threshold from `LED_WARN_AT_SECONDS`)
- Bomb defused/exploded -> final message and optional clear
- Round phase changes -> short status messages

Options:
- `LED_CLEAR_BEFORE=true`
- `LED_CLEAR_AFTER=true`
- `LED_HOLD_SECONDS=8`

## 7) Quick test (without CS2)

```powershell
$body = @'
{
  "auth": {"token": "CHANGE_ME"},
  "provider": {"timestamp": 1710000000},
  "map": {"name": "de_mirage", "phase": "live"},
  "round": {"phase": "live"},
  "bomb": {"state": "planted"},
  "phase_countdowns": {"phase": "live", "phase_ends_in": "34.2"}
}
'@
Invoke-RestMethod -Uri http://127.0.0.1:3000/gsi -Method Post -ContentType "application/json" -Body $body
```

If your `.env` token is not `CHANGE_ME`, set it in this test JSON too.

## 8) Notes

- This bridge is stateless enough for daily use, but if CS2 changes payload fields you may need to adapt parsing in `main.py`.
- If your matrix needs a different payload format than plain text, change `publish_led_message()`.
