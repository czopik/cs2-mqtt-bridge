"""
Test animacji LED Matrix 8x48 przez MQTT.
Uruchamia wszystkie sekwencje animacji po kolei z opisem.

Uzycie:
    .venv\\Scripts\\python.exe test_animations.py
    .venv\\Scripts\\python.exe test_animations.py --only bomb_planted
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from dotenv import load_dotenv
import paho.mqtt.client as mqtt

load_dotenv()

MQTT_HOST = os.getenv("MQTT_HOST", "192.168.1.249")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USERNAME", "mqtt")
MQTT_PASS = os.getenv("MQTT_PASSWORD", "mqtt")
MQTT_TOPIC = os.getenv("MQTT_TOPIC_LED", "all")

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

# Czekaj na polaczenie
for _ in range(50):
    if connected:
        break
    time.sleep(0.1)
else:
    print("[BLAD] Nie mozna polaczyc z MQTT po 5s")
    sys.exit(1)


def pub(msg: str) -> None:
    client.publish(MQTT_TOPIC, msg, qos=1)
    label = repr(msg) if msg == "" else msg
    print(f"  -> {label}")


def pause(seconds: float, label: str = "") -> None:
    if label:
        print(f"  ... czekam {seconds}s ({label})")
    time.sleep(seconds)


def sep(title: str) -> None:
    print(f"\n{'='*55}")
    print(f"  {title}")
    print(f"{'='*55}")


# ---------------------------------------------------------------------------
# Definicje testow
# ---------------------------------------------------------------------------

def test_bomb_planted():
    sep("TEST: BOMBA PODLOZONA (alarm alert)")
    pub("!! BOMBA !!")
    pause(0.25, "blysk 1")
    pub("")
    pause(0.25)
    pub("!! BOMBA !!")
    pause(0.25, "blysk 2")
    pub("")
    pause(0.25)
    pub("BOMBA PODLOZONA 40s")
    pause(2.5, "stabilny stan")
    pub("")


def test_bomb_timer_normal():
    sep("TEST: TIMER NORMALNY (40s -> 11s, co 1s)")
    for s in range(40, 10, -1):
        pub(f"BOMBA {s}s")
        pause(0.15)  # przyspieszone dla testu
    pub("")


def test_bomb_timer_warning():
    sep("TEST: TIMER OSTRZEZENIE (10s -> 5s, naprzemienne)")
    for s in range(10, 4, -1):
        bars = ">" * min(s, 5)
        pub(f"!! UWAGA {s}s !!")
        pause(0.3)
        pub(f"{bars} {s}s {bars}")
        pause(0.3)
    pub("")


def test_bomb_timer_critical():
    sep("TEST: TIMER KRYTYCZNY (4s -> 0s, szybkie miganie)")
    for s in range(4, -1, -1):
        pub(f">>> {s}s <<<")
        pause(0.15)
        pub(f"*** {s}s ***")
        pause(0.15)
        pub(f">>> {s}s <<<")
        pause(0.15)
    pub("")


def test_bomb_defused():
    sep("TEST: BOMBA ROZBROJONA")
    pub("")
    pause(0.05)
    pub("ROZBROJON!")
    pause(0.4)
    pub("** ROZBROJON **")
    pause(0.6)
    pub("CT WIN! :)")
    pause(2.5)
    pub("")


def test_bomb_exploded():
    sep("TEST: BOMBA WYBUCHLA")
    pub("WYBUCH!!!")
    pause(0.2)
    pub("")
    pause(0.1)
    pub("WYBUCH!!!")
    pause(0.2)
    pub("")
    pause(0.1)
    pub("WYBUCH!!!")
    pause(2.5)
    pub("")


def test_round_freezetime():
    sep("TEST: FAZA FREEZE")
    pub("-- FREEZE --")
    pause(2.0)
    pub("")


def test_round_live():
    sep("TEST: RUNDA LIVE")
    pub(">>> LIVE <<<")
    pause(2.0)
    pub("")


def test_round_over():
    sep("TEST: RUNDA ZAKONCZONA")
    pub("RUNDA OVER")
    pause(2.0)
    pub("")


def test_bomb_carried():
    sep("TEST: BOMBA WZIĘTA")
    pub("BOMBA WZIĘTA")
    pause(2.0)
    pub("")


def test_bomb_dropped():
    sep("TEST: BOMBA UPUSZCZONA")
    pub("BOMBA UPUSZCZON")
    pause(2.0)
    pub("")


def test_player_killed():
    sep("TEST: KILL (liczba zabójstw)")
    pub(">>> KILL <<<")
    pause(0.3)
    pub("*** 1 ***")
    pause(2.0)
    pub("KILL: 1")
    pause(0.5)
    pub("")
    pause(1.0)
    # Symuluj drugi kill
    pub(">>> KILL <<<")
    pause(0.3)
    pub("*** 2 ***")
    pause(2.0)
    pub("KILL: 2")
    pause(0.5)
    pub("")


def test_full_round_simulation():
    sep("TEST: PELNA SYMULACJA RUNDY")

    print("\n[FAZA 1] Freeze time")
    pub("-- FREEZE --")
    pause(1.5)
    pub("")
    pause(0.5)

    print("\n[FAZA 2] Runda live")
    pub(">>> LIVE <<<")
    pause(1.5)
    pub("")
    pause(1.0)

    print("\n[FAZA 3] Bomba podlozona (40s)")
    pub("!! BOMBA !!")
    pause(0.25)
    pub("")
    pause(0.25)
    pub("!! BOMBA !!")
    pause(0.25)
    pub("")
    pause(0.25)
    pub("BOMBA PODLOZONA 40s")
    pause(0.8)

    print("\n[FAZA 4] Odliczanie 40s..11s (przyspieszone)")
    for s in range(40, 10, -1):
        pub(f"BOMBA {s}s")
        pause(0.08)

    print("\n[FAZA 5] Odliczanie ostrzezenie 10s..5s")
    for s in range(10, 4, -1):
        bars = ">" * min(s, 5)
        pub(f"!! UWAGA {s}s !!")
        pause(0.25)
        pub(f"{bars} {s}s {bars}")
        pause(0.25)

    print("\n[FAZA 6] Odliczanie krytyczne 4s..0s")
    for s in range(4, -1, -1):
        pub(f">>> {s}s <<<")
        pause(0.12)
        pub(f"*** {s}s ***")
        pause(0.12)
        pub(f">>> {s}s <<<")
        pause(0.12)

    print("\n[FAZA 7] Wybuch!")
    pub("WYBUCH!!!")
    pause(0.2)
    pub("")
    pause(0.1)
    pub("WYBUCH!!!")
    pause(0.2)
    pub("")
    pause(0.1)
    pub("WYBUCH!!!")
    pause(2.0)
    pub("")
    pause(0.5)

    print("\n[ALTERNATYWA 7b] Rozbrojenie")
    pub("")
    pause(0.05)
    pub("ROZBROJON!")
    pause(0.4)
    pub("** ROZBROJON **")
    pause(0.6)
    pub("CT WIN! :)")
    pause(2.0)
    pub("")


# ---------------------------------------------------------------------------
# Rejestr testow
# ---------------------------------------------------------------------------

ALL_TESTS: dict[str, tuple[str, object]] = {
    "bomb_planted":       ("Bomba podlozona - alert",                test_bomb_planted),
    "bomb_timer_normal":  ("Timer normalny 40->11s",                 test_bomb_timer_normal),
    "bomb_timer_warning": ("Timer ostrzezenie 10->5s",              test_bomb_timer_warning),
    "bomb_timer_critical":("Timer krytyczny 4->0s",                 test_bomb_timer_critical),
    "bomb_defused":       ("Bomba rozbrojona",                      test_bomb_defused),
    "bomb_exploded":      ("Bomba wybuchla",                        test_bomb_exploded),
    "round_freezetime":   ("Faza freeze",                           test_round_freezetime),
    "round_live":         ("Runda live",                            test_round_live),
    "round_over":         ("Runda zakonczona",                      test_round_over),
    "bomb_carried":       ("Bomba wzięta",                          test_bomb_carried),
    "bomb_dropped":       ("Bomba upuszczona",                      test_bomb_dropped),
    "player_killed":      ("Kill (liczba zabójstw)",               test_player_killed),
    "full_simulation":    ("Pelna symulacja rundy (wbudowana)",     test_full_round_simulation),
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test animacji LED Matrix 8x48")
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
            print(f"  {key:<25} {desc}")
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
        print("\nUruchamiam WSZYSTKIE testy animacji...")
        for key, (desc, fn) in ALL_TESTS.items():
            print(f"\n>>> {desc}")
            fn()
            pause(1.0, "przerwa miedzy testami")

    pub("")
    print("\n[KONIEC] Wszystkie testy zakonczone. Ekran wyczyszczony.")
    client.loop_stop()
