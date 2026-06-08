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
GSI_TOKEN=your-private-token-here
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

The file in `gsi\gamestate_integration_ledmatrix.cfg` is only a template. Do not leave `PUT_YOUR_LOCAL_GSI_TOKEN_HERE` in the real CS2 config. The token must be the same as `GSI_TOKEN` from your local `.env`.

### Recommended: automatic Windows installer

Run this on the Windows PC where CS2 is installed:

```powershell
python install_gsi.py
```

The script reads your local `.env`, takes `GSI_TOKEN`, `UNRAID_HOST`, `GSI_PORT` and `GSI_PATH`, then writes the real file:

```text
Counter-Strike Global Offensive\game\csgo\cfg\gamestate_integration_ledmatrix.cfg
```

If `GSI_TOKEN` is empty or still set to `CHANGE_ME`, the installer stops and tells you to fix `.env` first. This prevents accidentally running CS2 with a broken token.

If Steam is installed in a custom place, set:

```env
CS2_CFG_DIR=C:\Your\SteamLibrary\steamapps\common\Counter-Strike Global Offensive\game\csgo\cfg
```

or generate to a chosen path:

```powershell
python install_gsi.py --output "C:\path\to\gamestate_integration_ledmatrix.cfg"
```

### Manual copy

Copy file:

- from `gsi\gamestate_integration_ledmatrix.cfg`
- to `Counter-Strike\game\csgo\cfg\gamestate_integration_ledmatrix.cfg`

Then edit this line manually:

```text
"token" "PUT_YOUR_LOCAL_GSI_TOKEN_HERE"
```

and replace it with the same token you have in `.env`:

```env
GSI_TOKEN=your-private-token-here
```

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
  "weapon": "ak",
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
  "text": "k+12",
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

## 7) HUD behavior for 8x48 matrix

Current simple HUD behavior:

- Normal: `hp100 k1`
- After kill/death popup: `k2 d7`
- Bomb planted: `bomb 34`
- Bomb defused: `defuse`
- Bomb exploded: `boom`

The HUD uses lowercase text and does not rotate through armor/ammo/map pages.

## 8) Quick MQTT test

```bash
mosquitto_sub -h 192.168.1.249 -u mqtt -P mqtt -t 'cs2/#' -v
mosquitto_sub -h 192.168.1.249 -u mqtt -P mqtt -t 'all' -v
```

## 9) Notes

CS2 GSI does not provide reliable FPS. Keep FPS as a separate module, for example PresentMon -> MQTT, and let the matrix subscribe/render it separately if needed.
