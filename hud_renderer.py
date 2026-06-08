from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import re
import time

logger = logging.getLogger("cs2_mqtt_hud")


@dataclass(slots=True)
class HudState:
    activity: str = ""
    round_phase: str = ""
    bomb_state: str = ""
    bomb_seconds: int | None = None
    countdown_seconds: int | None = None
    countdown_phase: str = ""
    round_number: int | None = None
    round_win_team: str = ""
    team: str = ""
    health: int | None = None
    armor: int | None = None
    weapon: str = ""
    weapon_raw: str = ""
    weapon_type: str = ""
    ammo: int | None = None
    ammo_reserve: int | None = None
    ammo_clip_max: int | None = None
    kills: int | None = None
    deaths: int | None = None
    score: int | None = None
    round_kills: int | None = None
    ct_score: int | None = None
    t_score: int | None = None
    name: str = ""


def _env_int(name: str, fallback: int) -> int:
    try:
        return int(os.getenv(name, str(fallback)))
    except (TypeError, ValueError):
        return fallback


class HudRenderer:
    """Simple lowercase HUD for a tiny 8x48 LED matrix.

    Priority:
    1. bomb timer / bomb result
    2. kill or death popup with kills/deaths
    3. constant hp + kills display
    """

    def __init__(self) -> None:
        modules = max(1, _env_int("HUD_MATRIX_MODULES", 6))
        font_columns = max(4, _env_int("HUD_FONT_COLUMNS", 5))
        char_spacing = max(0, _env_int("HUD_CHAR_SPACING", 1))
        explicit_width = _env_int("HUD_WIDTH_CHARS", 0)
        calculated_width = max(4, (modules * 8) // (font_columns + char_spacing))
        self.width = explicit_width or calculated_width

        self._boom_started_at = 0.0
        self._boom_until = 0.0
        self._defuse_until = 0.0
        self._kd_popup_until = 0.0
        self._kd_popup_text = ""
        self._last_bomb_state = ""
        self._last_kills: int | None = None
        self._last_deaths: int | None = None
        self._last_mode = ""

    def render(self, state: HudState, now: float | None = None) -> str:
        now = time.monotonic() if now is None else now
        self._update_effects(state, now)
        mode = self._resolve_mode(state, now)

        if mode != self._last_mode:
            logger.debug(
                "HUD mode=%s hp=%s kills=%s deaths=%s bomb_state=%s bomb_seconds=%s",
                mode,
                state.health,
                state.kills,
                state.deaths,
                state.bomb_state or "-",
                state.bomb_seconds,
            )
            self._last_mode = mode

        if mode == "boom":
            return self.drawStaticText("boom")
        if mode == "defuse":
            return self.drawStaticText("defuse")
        if mode == "bomb":
            return self._render_bomb(state, now)
        if mode == "kd":
            return self.drawStaticText(self._kd_popup_text or self._render_kd(state))
        if mode == "ready":
            return self.drawStaticText("cs2")
        return self.drawStaticText(self._render_hp_kills(state))

    def _resolve_mode(self, state: HudState, now: float) -> str:
        bomb_state = (state.bomb_state or "").lower()
        activity = (state.activity or "").lower()

        if bomb_state in {"exploded", "explode"} and now < self._boom_until:
            return "boom"

        if bomb_state in {"defused", "defuse"} and now < self._defuse_until:
            return "defuse"

        if bomb_state in {"planted", "plant"} and state.bomb_seconds is not None:
            return "bomb"

        if now < self._kd_popup_until and self._kd_popup_text:
            return "kd"

        # If player is dead and CS2 still reports health 0, keep showing K/D.
        if state.health == 0:
            return "kd"

        if activity == "menu" or (state.health is None and state.kills is None and state.deaths is None):
            return "ready"

        return "normal"

    def _update_effects(self, state: HudState, now: float) -> None:
        bomb_state = (state.bomb_state or "").lower()
        current_kills = state.kills
        current_deaths = state.deaths

        if bomb_state in {"exploded", "explode"} and self._last_bomb_state != bomb_state:
            self._boom_started_at = now
            self._boom_until = now + 3.0

        if bomb_state in {"defused", "defuse"} and self._last_bomb_state != bomb_state:
            self._defuse_until = now + 3.0

        kill_increased = (
            self._last_kills is not None
            and current_kills is not None
            and current_kills > self._last_kills
        )
        death_increased = (
            self._last_deaths is not None
            and current_deaths is not None
            and current_deaths > self._last_deaths
        )

        if kill_increased or death_increased:
            self._kd_popup_text = self._render_kd(state)
            self._kd_popup_until = now + 3.0

        if current_kills is not None:
            self._last_kills = current_kills
        if current_deaths is not None:
            self._last_deaths = current_deaths
        self._last_bomb_state = bomb_state

    def _render_hp_kills(self, state: HudState) -> str:
        hp = self._n(state.health, 0)
        kills = self._n(state.kills, 0)

        # Prefer requested format. For width=8, hp100 k12 is too long, so remove space.
        candidates = [
            f"hp{hp} k{kills}",
            f"hp{hp}k{kills}",
            f"h{hp} k{kills}",
            f"h{hp}k{kills}",
        ]
        return self._first_that_fits(candidates)

    def _render_kd(self, state: HudState) -> str:
        kills = self._n(state.kills, 0)
        deaths = self._n(state.deaths, 0)
        candidates = [
            f"k{kills} d{deaths}",
            f"k{kills}d{deaths}",
        ]
        return self._first_that_fits(candidates)

    def _render_bomb(self, state: HudState, now: float) -> str:
        secs = self._n(state.bomb_seconds, 0)
        text = self.drawStaticText(f"bomb {secs:02d}")
        if secs <= 10:
            return text if int(now / 0.25) % 2 == 0 else self.drawStaticText("")
        return text

    def _first_that_fits(self, candidates: list[str]) -> str:
        for candidate in candidates:
            if len(self._clean_text(candidate)) <= self.width:
                return candidate
        return candidates[-1]

    def _n(self, value: int | None, fallback: int) -> int:
        if value is None:
            return fallback
        return max(0, min(999, value))

    @staticmethod
    def _clean_text(text: str) -> str:
        text = (text or "").lower()
        replacements = str.maketrans(
            {
                "ą": "a",
                "ć": "c",
                "ę": "e",
                "ł": "l",
                "ń": "n",
                "ó": "o",
                "ś": "s",
                "ź": "z",
                "ż": "z",
            }
        )
        text = text.translate(replacements)
        text = re.sub(r"[^a-z0-9 +\-/]", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def drawStaticText(self, text: str, align: str = "left") -> str:
        cleaned = self._clean_text(text)
        clipped = cleaned[: self.width]
        if align == "right":
            return clipped.rjust(self.width)
        return clipped.ljust(self.width)

    def drawSplitStaticText(self, left: str, right: str) -> str:
        combined = f"{left} {right}".strip()
        return self.drawStaticText(combined)
