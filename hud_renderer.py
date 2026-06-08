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
    """Static 8px-high LED matrix renderer for a tiny 8x48 display."""

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
        self._kill_popup_until = 0.0
        self._kill_popup_text = ""
        self._result_until = 0.0
        self._last_bomb_state = ""
        self._last_kills: int | None = None
        self._last_mode = ""
        self._is_mvp = False
        self._mvp_name = ""
        self._mvp_name_until = 0.0
        self._last_round_result = ""
        self._locked_round_result = ""

    def render(self, state: HudState, now: float | None = None) -> str:
        now = time.monotonic() if now is None else now
        self._update_effects(state, now)
        mode = self._resolve_mode(state, now)
        if mode != self._last_mode:
            logger.debug(
                "HUD mode=%s hp=%s weapon=%s ammo=%s/%s kills=%s deaths=%s round_phase=%s bomb_state=%s bomb_seconds=%s round_result=%s",
                mode,
                state.health,
                state.weapon or "-",
                state.ammo,
                state.ammo_reserve,
                state.kills,
                state.deaths,
                state.round_phase or "-",
                state.bomb_state or "-",
                state.bomb_seconds,
                self._resolve_round_result(state),
            )
            self._last_mode = mode

        if mode == "boom":
            return self._render_boom(now)
        if mode == "defused":
            return self.drawStaticText("DEFUSE")
        if mode == "bomb":
            return self._render_bomb(state, now)
        if mode == "dead":
            deaths = self._n(state.deaths, 0)
            return self.drawStaticText(f"DEAD {deaths:02d}")
        if mode == "kill":
            return self.drawStaticText(self._kill_popup_text or "KILL")
        if mode == "mvp":
            return self.drawStaticText("MVP")
        if mode == "mvp_name":
            return self.drawStaticText(self._mvp_name or "MVP")
        if mode == "win":
            return self.drawStaticText("WIN")
        if mode == "lose":
            return self.drawStaticText("LOSE")
        if mode == "freeze":
            return self._render_freeze(state, now)
        if mode == "ready":
            return self.drawStaticText("CS2 RDY")
        if mode == "clear":
            return self.drawStaticText("")
        return self._render_normal(state, now)

    def _resolve_mode(self, state: HudState, now: float) -> str:
        bomb_state = (state.bomb_state or "").lower()
        round_phase = (state.round_phase or "").lower()
        activity = (state.activity or "").lower()
        health = state.health
        locked = self._locked_round_result

        if bomb_state in {"exploded", "explode"}:
            if now < self._boom_until:
                return "boom"
            if locked in {"win", "lose"}:
                return locked
            return "clear"

        if bomb_state in {"defused", "defuse"}:
            if now < self._defuse_until:
                return "defused"
            if locked in {"win", "lose"}:
                return locked
            return "clear"

        if bomb_state in {"planted", "plant"} and state.bomb_seconds is not None:
            return "bomb"

        if health == 0:
            return "dead"

        if locked in {"win", "lose"}:
            if now < self._result_until:
                if locked == "win" and self._is_mvp:
                    return "mvp"
                return locked
            if locked == "win" and self._is_mvp and self._mvp_name and now < self._mvp_name_until:
                return "mvp_name"
            return locked

        if now < self._kill_popup_until and self._kill_popup_text:
            return "kill"

        if round_phase in {"freezetime", "freeze", "warmup"} or state.countdown_seconds is not None:
            return "freeze"

        if activity == "menu" or (
            not round_phase
            and state.countdown_seconds is None
            and state.round_number is None
            and not bomb_state
            and self._looks_like_menu(state)
        ):
            return "ready"

        return "normal"

    def _update_effects(self, state: HudState, now: float) -> None:
        bomb_state = (state.bomb_state or "").lower()
        current_kills = state.kills

        if bomb_state in {"exploded", "explode"} and self._last_bomb_state != bomb_state:
            self._boom_started_at = now
            self._boom_until = now + 3.0

        if bomb_state in {"defused", "defuse"} and self._last_bomb_state != bomb_state:
            self._defuse_until = now + 3.0

        if self._last_kills is not None and current_kills is not None and current_kills > self._last_kills:
            self._kill_popup_text = f"K+{current_kills:02d}"
            self._kill_popup_until = now + 0.8

        round_result = self._resolve_round_result(state)
        if round_result in {"win", "lose"} and not self._locked_round_result:
            self._result_until = now + 2.0
            self._locked_round_result = round_result
            if round_result == "win" and (state.round_kills or 0) > 0:
                self._is_mvp = True
                self._mvp_name = self._clean_text(state.name or "")[: self.width]
                self._mvp_name_until = self._result_until + 1.5
        if not round_result:
            self._is_mvp = False
            self._mvp_name = ""
            self._mvp_name_until = 0.0
            self._locked_round_result = ""
        self._last_round_result = round_result

        if current_kills is not None:
            self._last_kills = current_kills

        self._last_bomb_state = bomb_state

    def _resolve_round_result(self, state: HudState) -> str:
        win_team = (state.round_win_team or "").upper()
        team = (state.team or "").upper()
        round_phase = (state.round_phase or "").lower()
        if round_phase not in {"over", "gameover"}:
            return ""
        if not win_team or not team:
            return ""
        return "win" if win_team == team else "lose"

    @staticmethod
    def _looks_like_menu(state: HudState) -> bool:
        return (
            state.kills in {None, 0}
            and state.score in {None, 0}
            and state.health in {None, 100}
            and state.armor in {None, 0, 100}
        )

    def _render_normal(self, state: HudState, now: float) -> str:
        health = state.health
        armor = state.armor
        ammo = state.ammo
        kills = self._n(state.kills, 0)
        score_str = self._score_str(state)

        if health is None and ammo is None and state.weapon == "":
            return self.drawStaticText("CS2 RDY")

        if health is not None and 0 < health <= 20:
            if int(now / 0.4) % 2 == 0:
                return self.drawStaticText("LOW HP")
            return self.drawStaticText(f"HP{health:02d}")

        page_count = 3 if score_str else 2
        page = int(now / 2.0) % page_count
        if page == 0:
            if health is not None:
                return self.drawStaticText(f"HP{health:02d} K{kills:02d}")
            return self.drawStaticText(f"KILLS {kills:02d}")
        if page == 1:
            return self._render_weapon_page(state, armor, ammo)
        return self.drawStaticText(score_str)

    def _render_weapon_page(self, state: HudState, armor: int | None, ammo: int | None) -> str:
        weapon = self._clean_text(state.weapon or "")[:4]
        reserve = state.ammo_reserve

        if weapon and ammo is not None:
            if reserve is not None and self.width >= 8:
                return self.drawStaticText(f"{weapon}{self._n(ammo, 999):02d}/{self._n(reserve, 999):02d}")
            return self.drawStaticText(f"{weapon} {self._n(ammo, 999):02d}")

        if weapon:
            return self.drawStaticText(weapon)

        if armor is not None and ammo is not None:
            return self.drawStaticText(f"A{self._n(armor, 999):02d} AM{self._n(ammo, 999):02d}")

        if armor is not None:
            return self.drawStaticText(f"ARM {self._n(armor, 999):02d}")

        if ammo is not None:
            return self.drawStaticText(f"AMMO {self._n(ammo, 999):02d}")

        return self.drawStaticText("NO DATA")

    def _render_freeze(self, state: HudState, now: float) -> str:
        countdown = state.countdown_seconds
        round_number = state.round_number
        score_str = self._score_str(state)

        if countdown is not None:
            label = "WARM" if (state.countdown_phase or "").lower() == "warmup" else "BUY"
            return self.drawStaticText(f"{label} {countdown:02d}")

        if round_number is not None:
            if score_str and int(now / 2.0) % 2 == 1:
                return self.drawStaticText(score_str)
            return self.drawStaticText(f"R{round_number:02d}")

        return self.drawStaticText("FREEZE")

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

    def _render_bomb(self, state: HudState, now: float) -> str:
        secs = self._n(state.bomb_seconds, 0)
        text = self.drawStaticText(f"BOMB {secs:02d}")
        if secs <= 10:
            return text if int(now / 0.25) % 2 == 0 else self.drawStaticText("")
        return text

    def _render_boom(self, now: float) -> str:
        elapsed = max(0.0, now - self._boom_started_at)
        if elapsed < 2.2:
            return self.drawStaticText("BOOM") if int(elapsed / 0.18) % 2 == 0 else self.drawStaticText("")
        return self.drawStaticText("T WIN")

    def _n(self, value: int | None, fallback: int) -> int:
        if value is None:
            return fallback
        return max(0, min(999, value))

    @staticmethod
    def _clean_text(text: str) -> str:
        text = (text or "").upper()
        replacements = str.maketrans(
            {
                "Ą": "A",
                "Ć": "C",
                "Ę": "E",
                "Ł": "L",
                "Ń": "N",
                "Ó": "O",
                "Ś": "S",
                "Ź": "Z",
                "Ż": "Z",
            }
        )
        text = text.translate(replacements)
        text = re.sub(r"[^A-Z0-9 +\-/]", " ", text)
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
