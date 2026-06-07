# CS2 MQTT LED Bridge

This project receives Counter-Strike 2 Game State Integration (GSI) updates over HTTP and publishes:
- raw snapshots to MQTT,
- normalized game state to MQTT,
- short LED-ready messages to your LED matrix topic.

It is tuned for a small LED matrix made from 6 x MAX7219-style 8x8 modules: **8x48 px**.

## 1) Requirements

- Windows PC with CS2
- Python 3.11+ or Docker/Unraid
- MQTT broker (for example Mosquitto)
- LED matrix already listening on an MQTT topic (default `all`)

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
- `MQTT_TOPIC_LED` (use your matrix topic, now default `all`)

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

Copy file:
- from `gsi\gamestate_integration_ledmatrix.cfg`
- to `Counter-Strike\game\csgo\cfg\gamestate_integration_ledmatrix.cfg`

Typical Steam path:
- `C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\csgo\cfg\`

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

Server starts on `http://127.0.0.1:3010/gsi` by default from the provided `.env.example`, or on `http://192.168.1.249:3010/gsi` when running on Unraid with the provided Docker configuration.

## 6) MQTT topics

From `.env`:
- `MQTT_TOPIC_RAW` default `cs2/raw`
- `MQTT_TOPIC_STATE` default `cs2/state`
- `MQTT_TOPIC_LED` default `all`

`main.py` publishes normalized state to `cs2/state`. `hud_display.py` reads `cs2/state`, renders short HUD pages, and publishes text to the LED topic.

## 7) HUD behavior for 8x48 matrix

The HUD avoids long Polish messages because they are not readable on 8x48 px. It shows short ASCII panels:

- Normal game, page 1: `HP84 K18`
- Normal game, page 2: `A91 AM23`
- Normal game, page 3: `7-5`
- Buy/freezetime: `BUY 12`
- Bomb planted: `BOMB 34`
