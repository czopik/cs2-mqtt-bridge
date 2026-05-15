# CS2 MQTT LED Bridge

This project receives Counter-Strike 2 Game State Integration (GSI) updates over HTTP and publishes:
- raw snapshots to MQTT,
- normalized game state to MQTT,
- short LED-ready messages to your LED matrix topic.

It is tuned for a small LED matrix made from 6 x MAX7219-style 8x8 modules: **8x48 px**.

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

For the 6-module display keep:

```env
LED_MODE=hud
HUD_MATRIX_MODULES=6
HUD_FONT_COLUMNS=5
HUD_CHAR_SPACING=1
HUD_WIDTH_CHARS=0
```

`HUD_WIDTH_CHARS=0` means auto width. For a 48px-wide matrix with a 5x7 font and 1px spacing, the HUD uses 8 readable characters. Do not force long 12+ character messages unless your firmware scrolls them nicely.

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

Server starts on `http://127.0.0.1:3000/gsi` by default.

## 5) MQTT topics

From `.env`:
- `MQTT_TOPIC_RAW` default `cs2/raw`
- `MQTT_TOPIC_STATE` default `cs2/state`
- `MQTT_TOPIC_LED` default `all`

`main.py` publishes normalized state to `cs2/state`. `hud_display.py` reads `cs2/state`, renders short HUD pages, and publishes text to the LED topic.

## 6) HUD behavior for 8x48 matrix

The HUD avoids long Polish messages because they are not readable on 8x48 px. It shows short ASCII panels:

- Normal game, page 1: `HP84 K18`
- Normal game, page 2: `A91 AM23`
- Normal game, page 3: `7-5`
- Buy/freezetime: `BUY 12`
- Bomb planted: `BOMB 34`
- Last 10 bomb seconds: blinking `BOMB 09`
- Low HP: blinking `LOW HP` / `HP09`
- Death: `DEAD 12`
- Kill popup: `K+18`
- Defuse: `DEFUSE`
- Explosion: blinking `BOOM`, then `T WIN`
- Round result: `WIN` or `LOSE`

## 7) Quick test without CS2

Start `main.py` and `hud_display.py`, then run this in PowerShell:

```powershell
$body = @'
{
  "auth": {"token": "CHANGE_ME"},
  "provider": {"timestamp": 1710000000},
  "map": {
    "name": "de_mirage",
    "phase": "live",
    "round": 12,
    "team_ct": {"score": 7},
    "team_t": {"score": 5}
  },
  "round": {"phase": "live"},
  "player": {
    "activity": "playing",
    "team": "CT",
    "name": "czopik",
    "state": {"health": 84, "armor": 91, "round_kills": 1},
    "match_stats": {"kills": 18, "deaths": 12, "score": 40},
    "weapons": {
      "weapon_0": {"name": "weapon_ak47", "state": "active", "ammo_clip": 23}
    }
  }
}
'@
Invoke-RestMethod -Uri http://127.0.0.1:3000/gsi -Method Post -ContentType "application/json" -Body $body
```

Bomb test:

```powershell
$body = @'
{
  "auth": {"token": "CHANGE_ME"},
  "provider": {"timestamp": 1710000000},
  "map": {"name": "de_mirage", "phase": "live", "team_ct": {"score": 7}, "team_t": {"score": 5}},
  "round": {"phase": "live", "bomb": "planted"},
  "bomb": {"state": "planted"},
  "phase_countdowns": {"phase": "bomb", "phase_ends_in": "34.2"},
  "player": {"activity": "playing", "team": "CT", "state": {"health": 84, "armor": 91}, "match_stats": {"kills": 18, "deaths": 12}}
}
'@
Invoke-RestMethod -Uri http://127.0.0.1:3000/gsi -Method Post -ContentType "application/json" -Body $body
```

If your `.env` token is not `CHANGE_ME`, set it in these test JSON bodies too.

## 8) Notes

- Use `LED_MODE=hud` for the clean 8x48 HUD.
- `LED_MODE=event` still exists, but it can spam/overwrite the display with longer animation texts.
- If CS2 changes payload fields, parsing may need adjustment in `main.py`.
- If your matrix needs a different payload format than plain text, change `publish_led()` in `main.py` or the publish call in `hud_display.py`.
