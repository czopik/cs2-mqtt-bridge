"""
Test LED Matrix 8x48 przez MQTT.

Uzycie:
    .venv\\Scripts\\python.exe test_animations.py
    .venv\\Scripts\\python.exe test_animations.py --only hud_normal
    .venv\\Scripts\\python.exe test_animations.py --list
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable

from dotenv import load_dotenv
import paho.mqtt.client as mqtt

load_dotenv()

MQTT_HOST = os.getenv("MQTT_HOST", "192.168.1.249")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USERNAME", "mqtt")
MQTT_PASS = os.getenv("MQTT_PASSWORD", "mqtt")
MQTT_TOPIC = os.getenv("MQTT_TOPIC_LED", "all")
HUD_WIDTH = int(os.getenv("HUD_WIDTH_CHARS", "8") or "8")
if HUD_WIDTH <= 0:
    HUD_WIDTH = 8

connected = False


def _on_connect(client, userdata, flags, reason_code, properties):
    global connected
    if reason_code == 0:
        connected = True
        print(f"[MQTT] Polaczono z {MQTT_HOST}:{MQTT_PORT}  topic={MQTT_TOPIC}")
    else:
        print(f"[MQTT] Blad polaczenia: {reason_code}")
        sys.exit(1)


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="cs2-led-test")
client.on_connect = _on_connect
if MQTT_USER:
    client.username_pw_set(MQTT_USER, MQTT_PASS)
client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
client.loop_start()

for _ in range(50):
    if connected:
        break
    time.sleep(0.1)
else:
    print("[BLAD] Nie mozna polaczyc z MQTT po 5s")
    sys.exit(1)


def fit(msg: str) -> str:
    return (msg or "")[:HUD_WIDTH].ljust(HUD_WIDTH)


def pub(msg: str) -> None:
    payload = fit(msg)
    client.publish(MQTT_TOPIC, payload, qos=1)
    label = repr(payload) if payload.strip() == "" else payload
    print(f"  -> {label}")


def pause(seconds: float, label: str = "") -> None:
    if label:
        print(f"  ... czekam {seconds}s ({label})")
    time.sleep(seconds)


def sep(title: str) -> None:
    print(f"\n{'='*55}")
    print(f"  {title}")
    print(f"{'='*55}")


def blink(text: str, times: int = 4, on: float = 0.2, off: float = 0.15) -> None:
    for _ in range(times):
        pub(text)
        pause(on)
        pub("")
        pause(off)


# ---------------------------------------------------------------------------
# Compact HUD tests for 6 x 8x8 modules = 8x48 px
# ---------------------------------------------------------------------------

def test_hud_normal() -> None:
    sep("HUD: normalne strony")
    for msg in ("HP84 K18", "A91 AM23", "7-5"):
        pub(msg)
        pause(2.0)
    pub("")


def test_hud_low_hp() -> None:
    sep("HUD: LOW HP")
    for _ in range(6):
        pub("LOW HP")
        pause(0.35)
        pub("HP09")
        pause(0.35)
    pub("")


def test_hud_bomb() -> None:
    sep("HUD: bomba 34s -> 0s")
    for s in range(34, 10, -1):
        pub(f"BOMB {s:02d}")
        pause(0.1)
    for s in range(10, -1, -1):
        pub(f"BOMB {s:02d}")
        pause(0.18)
        pub("")
        pause(0.12)
    pub("")


def test_hud_freeze() -> None:
    sep("HUD: buy/freezetime")
    for s in range(15, 0, -1):
        pub(f"BUY {s:02d}")
        pause(0.12)
    pub("LIVE")
    pause(1.0)
    pub("")


def test_hud_events() -> None:
    sep("HUD: eventy")
    for msg in ("K+18", "DEAD 12", "DEFUSE", "WIN", "LOSE"):
        pub(msg)
        pause(1.0)
    blink("BOOM", times=6, on=0.15, off=0.1)
    pub("T WIN")
    pause(1.0)
    pub("")


def test_full_round_simulation() -> None:
    sep("HUD: pelna symulacja rundy")
    for s in range(5, 0, -1):
        pub(f"BUY {s:02d}")
        pause(0.35)
    pub("LIVE")
    pause(0.8)
    pub("HP100K00")
    pause(1.0)
    pub("HP84 K01")
    pause(1.0)
    pub("A91 AM23")
    pause(1.0)
    pub("7-5")
    pause(1.0)
    for s in range(12, -1, -1):
        if s <= 10:
            pub(f"BOMB {s:02d}")
            pause(0.18)
            pub("")
            pause(0.12)
        else:
            pub(f"BOMB {s:02d}")
            pause(0.35)
    blink("BOOM", times=5, on=0.15, off=0.1)
    pub("T WIN")
    pause(1.5)
    pub("")


ALL_TESTS: dict[str, tuple[str, Callable[[], None]]] = {
    "hud_normal": ("Normalne strony: HP/kille, armor/ammo, wynik", test_hud_normal),
    "hud_low_hp": ("Miganie LOW HP", test_hud_low_hp),
    "hud_bomb": ("Timer bomby", test_hud_bomb),
    "hud_freeze": ("Buy/freezetime", test_hud_freeze),
    "hud_events": ("Kille, death, defuse, win/lose, boom", test_hud_events),
    "full_simulation": ("Pelna symulacja rundy", test_full_round_simulation),
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test LED Matrix 8x48")
    parser.add_argument(
        "--only",
        metavar="TEST",
        help=f"Uruchom tylko jeden test. Dostepne: {', '.join(ALL_TESTS)}",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Wyswietl liste testow i wyjdz",
    )
    args = parser.parse_args()

    if args.list:
        print("Dostepne testy:")
        for key, (desc, _) in ALL_TESTS.items():
            print(f"  {key:<20} {desc}")
        sys.exit(0)

    if args.only:
        if args.only not in ALL_TESTS:
            print(f"[BLAD] Nieznany test: {args.only}")
            print(f"Dostepne: {', '.join(ALL_TESTS)}")
            sys.exit(1)
        desc, fn = ALL_TESTS[args.only]
        print(f"\nUruchamiam: {desc}")
        fn()
    else:
        print("\nUruchamiam wszystkie testy HUD 8x48...")
        for key, (desc, fn) in ALL_TESTS.items():
            print(f"\n>>> {desc}")
            fn()
            pause(0.8, "przerwa miedzy testami")

    pub("")
    print("\n[KONIEC] Test zakonczony. Ekran wyczyszczony.")
    client.loop_stop()
