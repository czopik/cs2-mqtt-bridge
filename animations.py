"""
Animacje dla wyswietlacza LED Matrix 8x48.

Wyswietlacz ma 8 wierszy pikseli i 48 kolumn pikseli.
Przy typowej czcionce 6x8: ~8 znakow widocznych jednoczesnie, tekst scrolluje.
Przy czcionce 8x8: ~6 znakow widocznych jednoczesnie.

Protokol MQTT:
  - "" (pusty) = wyczysc ekran
  - "tekst"    = pokaz/scrolluj tekst

Sekwencja animacji: lista krotek (opoznienie_sekundy, wiadomosc_lub_None).
  None = wyczysc ekran.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

logger = logging.getLogger("cs2_mqtt_bridge.animations")

# Typ sekwencji: lista (opoznienie_s, tekst lub None)
Frame = tuple[float, str | None]
Sequence = list[Frame]

# ---------------------------------------------------------------------------
# Definicje sekwencji animacji (dostosowane do 8x48, scrollujacy tekst)
# ---------------------------------------------------------------------------

def _bomb_planted_alert(seconds: int | None) -> Sequence:
    """Alarm podlozenia bomby - trojkrotne blyskniecie, potem stan z czasem."""
    s = f" {seconds}s" if seconds is not None else ""
    return [
        (0.0,  "!! BOMBA !!"),
        (0.25, None),
        (0.25, "!! BOMBA !!"),
        (0.25, None),
        (0.25, f"BOMBA PODLOZONA{s}"),
    ]


def _bomb_timer_normal(seconds: int) -> Sequence:
    """Odliczanie w strefie bezpiecznej (>10s): jedno krotkie wyswietlenie."""
    return [
        (0.0, f"BOMBA {seconds}s"),
    ]


def _bomb_timer_warning(seconds: int) -> Sequence:
    """Odliczanie ostrzegawcze (5-10s): miganie naprzemienne."""
    bars = ">" * min(seconds, 5)
    return [
        (0.0,  f"!! UWAGA {seconds}s !!"),
        (0.3,  f"{bars} {seconds}s {bars}"),
    ]


def _bomb_timer_critical(seconds: int) -> Sequence:
    """Odliczanie krytyczne (<=4s): szybkie miganie i gwiazdki."""
    return [
        (0.0,  f">>> {seconds}s <<<"),
        (0.15, f"*** {seconds}s ***"),
        (0.15, f">>> {seconds}s <<<"),
    ]


def _bomb_defused() -> Sequence:
    """Bomba rozbrojona - celebracja."""
    return [
        (0.0,  None),
        (0.05, "ROZBROJON!"),
        (0.4,  "** ROZBROJON **"),
        (0.6,  "CT WIN! :)"),
        (2.0,  None),
    ]


def _bomb_exploded() -> Sequence:
    """Bomba wybuchla - dramatyczny efekt."""
    return [
        (0.0,  "WYBUCH!!!"),
        (0.2,  None),
        (0.1,  "WYBUCH!!!"),
        (0.2,  None),
        (0.1,  "WYBUCH!!!"),
        (2.0,  None),
    ]


def _round_freezetime() -> Sequence:
    return [
        (0.0,  "-- FREEZE --"),
        (1.5,  None),
    ]


def _round_live() -> Sequence:
    return [
        (0.0,  ">>> LIVE <<<"),
        (1.5,  None),
    ]


def _round_over() -> Sequence:
    return [
        (0.0,  "RUNDA OVER"),
        (1.5,  None),
    ]


def _bomb_carried() -> Sequence:
    return [
        (0.0,  "BOMBA WZIĘTA"),
        (2.0,  None),
    ]


def _bomb_dropped() -> Sequence:
    return [
        (0.0,  "BOMBA UPUSZCZON"),
        (2.0,  None),
    ]


def _player_killed(kill_count: int) -> Sequence:
    """Wyswietl liczbe kill'ow - alert + liczba."""
    return [
        (0.0,  ">>> KILL <<<"),
        (0.3,  f"*** {kill_count} ***"),
        (2.0,  f"KILL: {kill_count}"),
        (0.5,  None),
    ]


# ---------------------------------------------------------------------------
# Silnik animacji
# ---------------------------------------------------------------------------

class AnimationEngine:
    """
    Wykonuje sekwencje animacji na wyswietlaczu LED przez MQTT.
    Kazda nowa animacja anuluje poprzednia.
    """

    def __init__(self, publish_fn: Callable[[str], None]) -> None:
        self._publish = publish_fn
        self._cancel_event = threading.Event()
        self._lock = threading.Lock()

    # -- public API --

    def play_bomb_planted(self, seconds: int | None) -> None:
        self._run(_bomb_planted_alert(seconds), "bomb_planted")

    def play_bomb_timer(self, seconds: int) -> None:
        if seconds <= 4:
            seq = _bomb_timer_critical(seconds)
        elif seconds <= 10:
            seq = _bomb_timer_warning(seconds)
        else:
            seq = _bomb_timer_normal(seconds)
        self._run(seq, f"bomb_timer_{seconds}")

    def play_bomb_defused(self) -> None:
        self._run(_bomb_defused(), "bomb_defused")

    def play_bomb_exploded(self) -> None:
        self._run(_bomb_exploded(), "bomb_exploded")

    def play_round_freezetime(self) -> None:
        self._run(_round_freezetime(), "round_freezetime")

    def play_round_live(self) -> None:
        self._run(_round_live(), "round_live")

    def play_round_over(self) -> None:
        self._run(_round_over(), "round_over")

    def play_bomb_carried(self) -> None:
        self._run(_bomb_carried(), "bomb_carried")

    def play_bomb_dropped(self) -> None:
        self._run(_bomb_dropped(), "bomb_dropped")

    def play_player_killed(self, kill_count: int) -> None:
        self._run(_player_killed(kill_count), f"player_killed_{kill_count}")

    def show_kill_counter(self, kill_count: int) -> None:
        """Wyświetl licznik kill'i bez anulowania bieżącej animacji (overlay)."""
        # Bezpośrednio publikuj licznik bez triggering'u animacji
        msg = f"KILLS: {kill_count}"
        self._publish(msg)
        logger.debug("Kill counter overlay: %s", msg)

    def stop(self) -> None:
        """Zatrzymaj animacje i wyczysc ekran."""
        with self._lock:
            self._cancel_event.set()
        self._publish("")

    # -- internal --

    def _run(self, seq: Sequence, name: str) -> None:
        with self._lock:
            # Anuluj poprzednia animacje
            self._cancel_event.set()
            cancel = threading.Event()
            self._cancel_event = cancel

        t = threading.Thread(
            target=self._execute,
            args=(seq, name, cancel),
            daemon=True,
        )
        t.start()

    def _execute(self, seq: Sequence, name: str, cancel: threading.Event) -> None:
        logger.debug("Animation start: %s", name)
        for delay, message in seq:
            if cancel.is_set():
                logger.debug("Animation cancelled: %s", name)
                return
            if delay > 0:
                # Przerywalna pauza (sprawdzaj co 20ms)
                deadline = time.monotonic() + delay
                while time.monotonic() < deadline:
                    if cancel.is_set():
                        logger.debug("Animation cancelled mid-delay: %s", name)
                        return
                    time.sleep(0.02)
            if cancel.is_set():
                return
            if message is None:
                self._publish("")
            else:
                self._publish(message)
        logger.debug("Animation complete: %s", name)
