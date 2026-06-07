from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Cs2Event:
    type: str
    text: str
    payload: dict[str, Any]


class EventDetector:
    """Detects high-level CS2 events from normalized state snapshots.

    This keeps `main.py` focused on transport: HTTP GSI in, MQTT out.
    The detector compares the previous normalized state with the current one,
    similar in spirit to CounterStrike2GSI's event callbacks.
    """

    def __init__(self) -> None:
        self._previous: dict[str, Any] | None = None

    def reset(self) -> None:
        self._previous = None

    def detect(self, current: dict[str, Any]) -> list[Cs2Event]:
        previous = self._previous
        self._previous = dict(current)

        if previous is None:
            return []

        events: list[Cs2Event] = []
        self._detect_bomb(previous, current, events)
        self._detect_round(previous, current, events)
        self._detect_player(previous, current, events)
        self._detect_weapon(previous, current, events)
        return events

    def _detect_bomb(self, previous: dict[str, Any], current: dict[str, Any], events: list[Cs2Event]) -> None:
        old_state = _clean(previous.get("bomb_state"))
        new_state = _clean(current.get("bomb_state"))
        if old_state == new_state:
            return

        seconds = current.get("bomb_seconds")
        if new_state in {"planted", "plant"}:
            events.append(_event("bomb_planted", "BOMB", current, bomb_seconds=seconds))
        elif new_state in {"defused", "defuse"}:
            events.append(_event("bomb_defused", "DEFUSE", current))
        elif new_state in {"exploded", "explode"}:
            events.append(_event("bomb_exploded", "BOOM", current))
        elif new_state == "dropped":
            events.append(_event("bomb_dropped", "B DROP", current))
        elif new_state == "carried":
            events.append(_event("bomb_carried", "B TAKE", current))

    def _detect_round(self, previous: dict[str, Any], current: dict[str, Any], events: list[Cs2Event]) -> None:
        old_phase = _clean(previous.get("round_phase"))
        new_phase = _clean(current.get("round_phase"))
        if old_phase == new_phase:
            return

        if new_phase in {"freezetime", "freeze", "warmup"}:
            events.append(_event("round_freezetime", "BUY", current))
        elif new_phase == "live":
            events.append(_event("round_live", "LIVE", current))
        elif new_phase in {"over", "gameover"}:
            winner = _clean(current.get("round_win_team")).upper()
            team = _clean(current.get("team")).upper()
            if winner and team:
                text = "WIN" if winner == team else "LOSE"
            else:
                text = "ROUND END"
            events.append(_event("round_over", text, current))

    def _detect_player(self, previous: dict[str, Any], current: dict[str, Any], events: list[Cs2Event]) -> None:
        old_kills = _to_int(previous.get("kills"))
        new_kills = _to_int(current.get("kills"))
        if old_kills is not None and new_kills is not None and new_kills > old_kills:
            events.append(_event("player_kill", f"K+{new_kills:02d}", current, kills=new_kills, delta=new_kills - old_kills))

        old_hp = _to_int(previous.get("health"))
        new_hp = _to_int(current.get("health"))
        if old_hp is None or new_hp is None:
            return

        if old_hp > 20 >= new_hp > 0:
            events.append(_event("player_low_health", "LOW HP", current, health=new_hp))
        if old_hp > 0 and new_hp == 0:
            events.append(_event("player_dead", "DEAD", current))
        elif new_hp < old_hp:
            events.append(_event("player_damage", f"HP{new_hp:02d}", current, damage=old_hp - new_hp, health=new_hp))

    def _detect_weapon(self, previous: dict[str, Any], current: dict[str, Any], events: list[Cs2Event]) -> None:
        old_weapon = _clean(previous.get("weapon"))
        new_weapon = _clean(current.get("weapon"))
        if new_weapon and old_weapon and new_weapon != old_weapon:
            events.append(_event("weapon_changed", new_weapon[:8], current, weapon=new_weapon))


def _event(event_type: str, text: str, state: dict[str, Any], **extra: Any) -> Cs2Event:
    payload: dict[str, Any] = {
        "type": event_type,
        "text": text,
        "timestamp": state.get("timestamp"),
        "map": state.get("map"),
        "round": state.get("round"),
        "round_phase": state.get("round_phase"),
        "team": state.get("team"),
    }
    payload.update(extra)
    return Cs2Event(type=event_type, text=text, payload=payload)


def _clean(value: Any) -> str:
    return str(value or "").strip().lower()


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
