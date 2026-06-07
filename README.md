# CS2 MQTT LED Bridge

This project receives Counter-Strike 2 Game State Integration (GSI) updates over HTTP and publishes:

- raw snapshots to MQTT,
- normalized game state to MQTT,
- high-level CS2 events to MQTT,
- online/offline bridge status to MQTT,
- short LED-ready messages to your LED matrix topic.

It is tuned for a small LED matrix made from 6 x MAX7219-style 8x8 modules: **8x48 px**.

## 1) Requirements

- Windows PC with CS2
- Python 3.11+ or Docker/Unraid
- MQTT broker, for example Mosquitto
- LED matrix already listening on an MQTT topic, default `all`

## 2) Install on Windows

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
- `MQTT_TOPIC_LED`, default `all`

For the 6-module display keep:

```env
LED_MODE=hud
HUD_MATRIX_MODULES=6
HUD_FONT_COLUMNS=5
HUD_CHAR_SPACING=1
HUD_WIDTH_CHARS=0
```

`HUD_WIDTH_CHARS=0` means auto width. For a 48px-wide matrix with a 5x7 font and 1px spacing, the HUD uses 8 readable characters. Do not force long 12+ character messages unless your firmware scrolls them nicely.

## 3) Install on Unraid / Docker

Clone or copy this project to Unraid, for example:

```bash
cd /mnt/user/appdata
git clone https://github.com/czopik/cs2-mqtt-bridge.git
cd cs2-mqtt-bridge
cp .env.example .env
nano .env
```

For Unraid keep:

```env
GSI_HOST=0.0.0.0
GSI_PORT=3010
UNRAID_HOST=192.168.1.249
MQTT_HOST=192.168.1.249
MQTT_PORT=1883
MQTT_USERNAME=mqtt
MQTT_PASSWORD=mqtt
MQTT_TOPIC_LED=all
```

Start it:

```bash
docker compose up -d --build
docker logs -f cs2-mqtt-bridge
```

The container exposes:

```text
http://192.168.1.249:3010/gsi
```

If port `3010` is already used on Unraid, change `GSI_PORT` in `.env`, rebuild the container, and use the same port in the CS2 GSI config file.

## 4) Configure CS2 GSI

### Option A: manual copy

Copy file:

- from `gsi\gamestate_integration_ledmatrix.cfg`
- to `Counter-Strike\game\csgo\cfg\gamestate_integration_ledmatrix.cfg`

Typical Steam path:

```text
C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\csgo\cfg\
```

For Unraid the important line in the GSI file is:

```text
"uri" "http://192.168.1.249:3010/gsi"
```

Important:

- Set the same token in both places:
  - `.env` -> `GSI_TOKEN`
  - `gamestate_integration_ledmatrix.cfg` -> `auth` -> `token`
- Restart CS2 after changing the GSI file.

### Option B: automatic Windows installer

Run this on the Windows PC where CS2 is installed:

```powershell
python install_gsi.py
```

The script tries to find your CS2 `cfg` folder and writes `gamestate_integration_ledmatrix.cfg` automatically.

If Steam is installed in a custom place, set:

```env
CS2_CFG_DIR=C:\Your\SteamLibrary\steamapps\common\Counter-Strike Global Offensive\game\csgo\cfg
```

## 5) Run on Windows

Run the bridge first:

```powershell
cd C:\Users\chemi\cs2-mqtt-bridge
.\.venv\Scripts\Activate.ps1
python main.py
```

In a second PowerShell window run the HUD publisher:

```powershell
cd C:\Users\chemi\cs2-mqtt-bridge
.\.venv\Scripts\Activate.ps1
python hud_display.py
```

Server starts on `http://127.0.0.1:3010/gsi` when configured for local Windows, or on `http://192.168.1.249:3010/gsi` when running on Unraid with the provided Docker configuration.

## 6) MQTT topics

From `.env`:

- `MQTT_TOPIC_RAW` default `cs2/raw`
- `MQTT_TOPIC_STATE` default `cs2/state`
- `MQTT_TOPIC_EVENT` default `cs2/event`
- `MQTT_TOPIC_STATUS` default `cs2/status`
- `MQTT_TOPIC_LED` default `all`

`main.py` publishes normalized state to `cs2/state`. `hud_display.py` reads `cs2/state`, renders short HUD pages, and publishes text to the LED topic.

### Normalized state example

```json
{
  "health": 84,
  "armor": 91,
  "weapon": "AK",
  "weapon_raw": "weapon_ak47",
  "ammo": 18,
  "ammo_reserve": 90,
  "kills": 12,
  "ct_score": 7,
  "t_score": 5,
  "bomb_state": "planted",
  "bomb_seconds": 34
}
```

### Event example

`cs2/event` and `cs2/event/player_kill`:

```json
{
  "type": "player_kill",
  "text": "K+12",
  "kills": 12,
  "delta": 1
}
```

Other useful events include:

- `bomb_planted`
- `bomb_defused`
- `bomb_exploded`
- `bomb_dropped`
- `bomb_carried`
- `round_freezetime`
- `round_live`
- `round_over`
- `player_kill`
- `player_low_health`
- `player_dead`
- `player_damage`
- `weapon_changed`

### Status example

`cs2/status`:

```json
{
  "status": "online",
  "bridge": "online",
  "last_gsi_seen_seconds_ago": 0
}
```

If CS2 stops sending GSI updates for `STATUS_OFFLINE_AFTER_SECONDS`, the status changes to `offline`. By default `hud_display.py` clears the LED matrix when CS2 goes offline.

## 7) HUD behavior for 8x48 matrix

The HUD avoids long Polish messages because they are not readable on 8x48 px. It shows short ASCII panels:

- Normal game, page 1: `HP84 K18`
- Normal game, page 2: `AK18/90`
- Fallback page 2 without weapon: `A91 AM23`
- Normal game, page 3: `7-5`
- Buy/freezetime: `BUY 12`
- Bomb planted: `BOMB 34`
- Low health: `LOW HP`
- Kill popup: `K+02`

## 8) Quick MQTT test

```bash
mosquitto_sub -h 192.168.1.249 -u mqtt -P mqtt -t 'cs2/#' -v
mosquitto_sub -h 192.168.1.249 -u mqtt -P mqtt -t 'all' -v
```

## 9) Notes

CS2 GSI does not provide reliable FPS. Keep FPS as a separate module, for example PresentMon -> MQTT, and let the matrix subscribe/render it separately if needed.
