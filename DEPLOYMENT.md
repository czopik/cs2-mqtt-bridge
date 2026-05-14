# CS2 → MQTT LED Matrix - Quick Start

## Status
✅ Bridge uruchomiony na http://127.0.0.1:3000/gsi  
✅ Połączony z MQTT 192.168.1.249:1883 (mqtt/mqtt)  
✅ Testy przetwarzania bomby: PASSED  
✅ Publikacja na topic `all` (LED matrix)  

---

## Krok 1: Umieść plik GSI w CS2

**Lokalizacja pliku:** `gsi/gamestate_integration_ledmatrix.cfg`

**Docelowa ścieżka w Steam:**
```
C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\csgo\cfg\gamestate_integration_ledmatrix.cfg
```

Jeśli folder `cfg` nie istnieje, utwórz go.

---

## Krok 2: Ustaw token (opcjonalnie, ale zalecane)

W pliku `.env` jest aktualnie:
```
GSI_TOKEN=CHANGE_ME
```

**Wybierz opcję:**

### Opcja A: Token wyłączony (testowanie)
Zostaw `GSI_TOKEN=CHANGE_ME` w obu miejscach. Każdy POST będzie zaakceptowany.

### Opcja B: Token włączony (produkcja)
1. Ustaw własny token w `.env`:
   ```
   GSI_TOKEN=moj_tajny_token_123
   ```

2. Zaktualizuj plik `gsi/gamestate_integration_ledmatrix.cfg`:
   ```
   "auth"
   {
     "token"       "moj_tajny_token_123"
   }
   ```

3. Skopiuj plik do CS2.

---

## Krok 3: Uruchom Bridge

Terminal 1 - Bridge (już uruchomiony):
```powershell
cd C:\Users\chemi\cs2-mqtt-bridge
.\.venv\Scripts\Activate.ps1
python main.py
```

Powinien pokazać:
```
2026-05-09 07:05:08,509 | INFO | Connected to MQTT 192.168.1.249:1883
```

---

## Krok 4: Testuj z CS2

1. Otwórz CS2
2. Wejdź do meczu (Practice/DM/MM)
3. Obserwuj LED matrix - powinien pokazywać:
   - **Bomba podłożona:** `BOMBA PODLOZONA 40s`
   - **Odliczanie:** `BOMBA 39s`, `BOMBA 38s`, itp.
   - **W ostatnich 10s:** `UWAGA 9s`, `UWAGA 8s`, ...
   - **Rozbrojona:** `BOMBA ROZBROJONA` (automatycznie wyczyści)
   - **Wybuch:** `BOMBA WYBUCHLA` (automatycznie wyczyści)

---

## Topiki MQTT (jeśli chcesz ręcznie monitorować)

Subskrybuj do diagnostyki:
```bash
mosquitto_sub -h 192.168.1.249 -u mqtt -P mqtt -t "cs2/#"
```

Zobaczysz trzy kanały:
- `cs2/raw` - surowy JSON z CS2
- `cs2/state` - znormalizowany stan
- `all` - teksty dla LED matrix

---

## Konfiguracja zaawansowana (.env)

```bash
# Zmień topik LED jeśli potrzebujesz
MQTT_TOPIC_LED=matrix/all  # zamiast 'all'

# Zmień tekst ostrzeżenia
LED_WARN_AT_SECONDS=5  # ostrzeżenie od 5 sekund

# Zmień prefiksem timera
LED_TIMER_PREFIX=BOMB  # zamiast 'BOMBA'

# Czyszczenie ekranu
LED_CLEAR_BEFORE=true   # oczyść przed wiadomością
LED_CLEAR_AFTER=true    # oczyść po czasie
LED_HOLD_SECONDS=8      # ile sekund przytrzymaj wiadomość
```

Po zmianie: restartuj `python main.py`

---

## Troubleshooting

**1. Bridge nie łączy się z MQTT**
```
ERROR | MQTT connect failed
```
- Sprawdź IP: `192.168.1.249`
- Sprawdź login: `mqtt / mqtt`
- Sprawdź firewall/port 1883

**2. CS2 nie wysyła danych do bridga**
```
POST /gsi HTTP/1.1" brak logów
```
- Sprawdź czy plik `.cfg` jest w `csgo/cfg/`
- Sprawdź czy restart CS2 po umieszczeniu pliku
- Sprawdź czy `.cfg` ma sam kodowanie UTF-8

**3. LED nie reaguje**
- Sprawdź czy topik w LED matrix to `all`
- Testuj ręcznie: `mosquitto_pub -h 192.168.1.249 -u mqtt -P mqtt -t "all" -m "TEST"`

---

## Production Setup (opcjonalnie)

Jeśli chcesz stały start:

### Windows Service (NSSM)
```powershell
# Zainstaluj NSSM
scoop install nssm

# Utwórz service
nssm install CS2MQTTBridge C:\Users\chemi\cs2-mqtt-bridge\.venv\Scripts\python.exe main.py
nssm set CS2MQTTBridge AppDirectory C:\Users\chemi\cs2-mqtt-bridge
nssm start CS2MQTTBridge
```

### Gunicorn (dla wielu żądań)
```powershell
pip install gunicorn
gunicorn --bind 127.0.0.1:3000 --workers 2 main:app
```

---

## Support

Projekt: [CS2 MQTT LED Bridge](C:\Users\chemi\cs2-mqtt-bridge)  
Dokumentacja: [README.md](README.md)
