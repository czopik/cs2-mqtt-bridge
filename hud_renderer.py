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
    map: str = ""
    map_mode: str = ""
    map_phase: str = ""


def _env_int(name: str, fallback: int) -> int:
    try:
        return int(os.getenv(name, str(fallback)))
    except (TypeError, ValueError):
        return fallback


class HudRenderer:
    """Compact lowercase HUD for a tiny 8x48 LED matrix.

    Base screen is stable: k/d/h, for example `k1d3h100`.
    Temporary event screens intentionally stay short and lowercase.

    Priority:
    1. planted bomb countdown: p40, p39, p38...
    2. bomb result popup:      defuse / boom
    3. kill/death popup:       kill 2 / death 4
    4. ammo popup after shot:  a13 or a13/90
    5. round/map popup:       7-5win / nuke
    6. menu/loading/base HUD:  menu / map / k1d3h100
    """

    def __init__(self) -> None:
        modules = max(1, _env_int("HUD_MATRIX_MODULES", 6))
        font_columns = max(4, _env_int("HUD_FONT_COLUMNS", 5))
        char_spacing = max(0, _env_int("HUD_CHAR_SPACING", 1))
        explicit_width = _env_int("HUD_WIDTH_CHARS", 0)
        calculated_width = max(4, (modules * 8) // (font_columns + char_spacing))
        self.width = explicit_width or calculated_width

        self._boom_until = 0.0
        self._defuse_until = 0.0
        self._round_result_until = 0.0
        self._map_popup_until = 0.0
        self._kd_popup_until = 0.0
        self._ammo_popup_until = 0.0

        self._round_result_text = ""
        self._map_popup_text = ""
        self._kd_popup_text = ""
        self._ammo_popup_text = ""

        self._last_bomb_state = ""
        self._last_round_phase = ""
        self._last_map = ""
        self._last_kills: int | None = None
        self._last_deaths: int | None = None
        self._last_ammo: int | None = None
        self._last_render = ""

    def render(self, state: HudState, now: float | None = None) -> str:
        now = time.monotonic() if now is None else now
        self._update_effects(state, now)

        bomb_state = (state.bomb_state or "").lower()
        if bomb_state in {"planted", "plant"} and state.bomb_seconds is not None:
            rendered = self._fit(f"p{self._n(state.bomb_seconds, 0):02d}")
        elif bomb_state in {"defused", "defuse"} and now < self._defuse_until:
            rendered = self._fit("defuse")
        elif bomb_state in {"exploded", "explode"} and now < self._boom_until:
            rendered = self._fit("boom")
        elif now < self._kd_popup_until and self._kd_popup_text:
            rendered = self._fit(self._kd_popup_text)
        elif now < self._ammo_popup_until and self._ammo_popup_text:
            rendered = self._fit(self._ammo_popup_text)
        elif now < self._round_result_until and self._round_result_text:
            rendered = self._fit(self._round_result_text)
        elif now < self._map_popup_until and self._map_popup_text:
            rendered = self._fit(self._map_popup_text)
        elif self._is_menu(state):
            rendered = self._fit("menu")
        elif self._is_loading_or_missing_player(state):
            rendered = self._fit(self._map_name(state.map) or "cs2")
        else:
            rendered = self._fit(self._render_default(state))

        if rendered != self._last_render:
            logger.debug("HUD render: %r", rendered)
            self._last_render = rendered
        return rendered

    def _update_effects(self, state: HudState, now: float) -> None:
        bomb_state = (state.bomb_state or "").lower()
        round_phase = (state.round_phase or "").lower()
        current_map = self._map_name(state.map)
        current_kills = state.kills
        current_deaths = state.deaths
        current_ammo = state.ammo

        if bomb_state in {"exploded", "explode"} and self._last_bomb_state != bomb_state:
            self._boom_until = now + 3.0

        if bomb_state in {"defused", "defuse"} and self._last_bomb_state != bomb_state:
            self._defuse_until = now + 3.0

        if current_map and self._last_map and current_map != self._last_map:
            self._map_popup_text = current_map
            self._map_popup_until = now + 3.0

        if round_phase in {"over", "gameover"} and self._last_round_phase != round_phase:
            result = self._round_result(state)
            if result:
                self._round_result_text = result
                self._round_result_until = now + 3.0

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

        if kill_increased:
            self._kd_popup_text = self._first_that_fits([f"kill {self._n(current_kills, 0)}", f"k{self._n(current_kills, 0)}"])
            self._kd_popup_until = now + 2.0
        elif death_increased:
            self._kd_popup_text = self._first_that_fits([f"death {self._n(current_deaths, 0)}", f"d{self._n(current_deaths, 0)}"])
            self._kd_popup_until = now + 2.0

        ammo_decreased = (
            self._last_ammo is not None
            and current_ammo is not None
            and 0 <= current_ammo < self._last_ammo
            and bomb_state not in {"planted", "plant"}
        )
        if ammo_decreased:
            self._ammo_popup_text = self._render_ammo(state)
            self._ammo_popup_until = now + 1.0

        if current_kills is not None:
            self._last_kills = current_kills
        if current_deaths is not None:
            self._last_deaths = current_deaths
        if current_ammo is not None:
            self._last_ammo = current_ammo
        self._last_bomb_state = bomb_state
        self._last_round_phase = round_phase
        if current_map:
            self._last_map = current_map

    def _render_default(self, state: HudState) -> str:
        kills = self._n(state.kills, 0)
        deaths = self._n(state.deaths, 0)
        hp = self._n(state.health, 0)
        return self._first_that_fits(
            [
                f"k{kills}d{deaths}h{hp}",
                f"k{kills}d{deaths}h{min(hp, 99)}",
                f"k{kills}d{deaths}",
                f"h{hp}",
            ]
        )

    def _render_ammo(self, state: HudState) -> str:
        ammo = self._n(state.ammo, 0)
        reserve = state.ammo_reserve
        if reserve is not None:
            return self._first_that_fits([f"a{ammo}/{self._n(reserve, 999)}", f"a{ammo}"])
        return f"a{ammo}"

    def _round_result(self, state: HudState) -> str:
        score = self._score_str(state)
        win_team = (state.round_win_team or "").upper()
        team = (state.team or "").upper()
        if score and win_team and team:
            suffix = "win" if win_team == team else "lose"
            return self._first_that_fits([f"{score}{suffix}", score, suffix])
        return score

    def _score_str(self, state: HudState) -> str:
        ct = state.ct_score
        t = state.t_score
        if ct is None or t is None:
            return ""
        team = (state.team or "").upper()
        if team == "CT":
            return f"{ct}-{t}"
        if team == "T":
            return f"{t}-{ct}"
        return f"{ct}-{t}"

    def _is_menu(self, state: HudState) -> bool:
        return (state.activity or "").lower() == "menu"

    def _is_loading_or_missing_player(self, state: HudState) -> bool:
        map_phase = (state.map_phase or "").lower()
        activity = (state.activity or "").lower()
        if activity and activity not in {"playing", "textinput"}:
            return True
        if map_phase and map_phase not in {"live", "gameover"}:
            return True
        return state.health is None and state.kills is None and bool(state.map)

    @staticmethod
    def _map_name(map_name: str) -> str:
        name = (map_name or "").lower().strip()
        if not name:
            return ""
        name = re.sub(r"^(de_|cs_)", "", name)
        name = name.replace("_night", "")
        return re.sub(r"[^a-z0-9]", "", name)

    def _first_that_fits(self, candidates: list[str]) -> str:
        for candidate in candidates:
            if len(self._clean_text(candidate)) <= self.width:
                return candidate
        return candidates[-1]

    def _fit(self, text: str) -> str:
        # Important: no padding. Some matrix firmwares scroll or animate padded text.
        return self._clean_text(text)[: self.width]

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
        # Kept for compatibility with older code, but now it never uppercases and never pads.
        return self._fit(text)

    def drawSplitStaticText(self, left: str, right: str) -> str:
        return self._fit(f"{left} {right}".strip())
