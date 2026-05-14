# CS2 + HUD Bridge launcher
# Uruchamia CS2, main.py i hud_display.py
# Zamyka Python gdy CS2 sie zamknie

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = "$scriptDir\.venv\Scripts\python.exe"

Write-Host "Uruchamianie CS2 HUD Bridge..."

# Wyczysc stary retained message
$envFile = Join-Path $scriptDir ".env"
& $python -c @"
import paho.mqtt.client as mqtt, time
from dotenv import load_dotenv; import os
load_dotenv(r'$envFile')
c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
c.username_pw_set(os.getenv('MQTT_USERNAME',''), os.getenv('MQTT_PASSWORD',''))
c.connect(os.getenv('MQTT_HOST','192.168.1.249'), int(os.getenv('MQTT_PORT',1883)))
c.loop_start(); time.sleep(0.3)
c.publish(os.getenv('MQTT_TOPIC_STATE','cs2/state'), None, qos=1, retain=True)
time.sleep(0.3); c.disconnect()
print('Wyczyszczono retained state')
"@

# Uruchom bridge i hud
$mainProc = Start-Process $python -ArgumentList "$scriptDir\main.py" -PassThru -WindowStyle Hidden
$hudProc  = Start-Process $python -ArgumentList "$scriptDir\hud_display.py" -PassThru -WindowStyle Hidden

Write-Host "Bridge PID=$($mainProc.Id)  HUD PID=$($hudProc.Id)"

# Uruchom CS2
Write-Host "Uruchamianie CS2..."
Start-Process "steam://rungameid/730"

# Czekaj az CS2 sie uruchomi (max 60s)
Write-Host "Czekam na uruchomienie cs2.exe..."
$waited = 0
while ($waited -lt 60) {
    $cs2 = Get-Process -Name "cs2" -ErrorAction SilentlyContinue
    if ($cs2) { Write-Host "CS2 uruchomione PID=$($cs2.Id)"; break }
    Start-Sleep 2; $waited += 2
}

if (-not $cs2) {
    Write-Host "CS2 nie uruchomilo sie w ciagu 60s - kontynuuje monitorowanie..."
}

# Monitoruj CS2 i zamknij bridge gdy CS2 sie zamknie
Write-Host "Monitoruje CS2... (zamknij CS2 zeby zatrzymac bridge)"
while ($true) {
    $cs2 = Get-Process -Name "cs2" -ErrorAction SilentlyContinue
    if (-not $cs2) {
        Write-Host "CS2 zamkniety - zatrzymuje bridge..."
        break
    }
    Start-Sleep 3
}

# Zatrzymaj Python
Stop-Process -Id $mainProc.Id -Force -ErrorAction SilentlyContinue
Stop-Process -Id $hudProc.Id  -Force -ErrorAction SilentlyContinue

# Wyczysc wyswietlacz
& $python -c @"
import paho.mqtt.client as mqtt, time
from dotenv import load_dotenv; import os
load_dotenv(r'$envFile')
c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
c.username_pw_set(os.getenv('MQTT_USERNAME',''), os.getenv('MQTT_PASSWORD',''))
c.connect(os.getenv('MQTT_HOST','192.168.1.249'), int(os.getenv('MQTT_PORT',1883)))
c.loop_start(); time.sleep(0.3)
c.publish('all', '            ', qos=1)
time.sleep(0.3); c.disconnect()
"@

Write-Host "Wszystko zatrzymane."
