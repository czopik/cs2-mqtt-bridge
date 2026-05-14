from __future__ import annotations

from dataclasses import dataclass
import logging
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
    ammo: int | None = None
    kills: int | None = None
    deaths: int | None = None
    score: int | None = None
    round_kills: int | None = None
    ct_score: int | None = None
    t_score: int | None = None
    name: str = ""


class HudRenderer:
    width = 12

    def __init__(self) -> None:
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
                "HUD mode=%s hp=%s ammo=%s kills=%s deaths=%s round_phase=%s bomb_state=%s bomb_seconds=%s round_result=%s",
                mode,
                state.health,
                state.ammo,
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
            return self.drawStaticText("[ DEFUSE ]")
        if mode == "bomb":
            return self._render_bomb(state, now)
        if mode == "dead":
            deaths = self._n(state.deaths, 0)
            return self.drawSplitStaticText("DEAD", f"{deaths:02d}")
        if mode == "kill":
            return self.drawStaticText(self._kill_popup_text or "KILL", align="left")
        if mode == "mvp":
            return self.drawStaticText("* MVP! *")
        if mode == "mvp_name":
            return self.drawStaticText(self._mvp_name or "* MVP! *")
        if mode == "win":
            return self.drawStaticText("* WIN *")
        if mode == "lose":
            return self.drawStaticText("X LOSE X")
        if mode == "freeze":
            return self._render_freeze(state, now)
        if mode == "ready":
            return self.drawStaticText("READY")
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

        if now < self._kill_popup_until and self._kill_popup_text:
            return "kill"

        if locked in {"win", "lose"}:
            if now < self._result_until:
                if locked == "win" and self._is_mvp:
                    return "mvp"
                return locked
            if locked == "win" and self._is_mvp and self._mvp_name and now < self._mvp_name_until:
                return "mvp_name"
            return locked

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
            self._boom_until = now + 2.5

        if bomb_state in {"defused", "defuse"} and self._last_bomb_state != bomb_state:
            self._defuse_until = now + 2.0

        if self._last_kills is not None and current_kills is not None and current_kills > self._last_kills:
            self._kill_popup_text = f"Kills: {current_kills}"
            self._kill_popup_until = now + 1.0

        round_result = self._resolve_round_result(state)
        if round_result in {"win", "lose"} and not self._locked_round_result:
            # Start MVP window after any active kill flash so MVP shows a full 2s
            mvp_start = max(self._kill_popup_until, now)
            self._result_until = mvp_start + 2.0
            self._locked_round_result = round_result  # lock first result, ignore later flickers
            if round_result == "win" and (state.round_kills or 0) > 0:
                self._is_mvp = True
                self._mvp_name = (state.name or "")[:self.width]
                self._mvp_name_until = self._result_until + 2.0
        if not round_result:
            self._is_mvp = False
            self._mvp_name = ""
            self._mvp_name_until = 0.0
            self._locked_round_result = ""  # clear when phase leaves "over"
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
        health = self._n(state.health, 0)
        armor = self._n(state.armor, 0)

        full_text = f"H{health} A{armor}"
        return self.drawStaticText(full_text, align="left")

    def _render_freeze(self, state: HudState, now: float) -> str:
        countdown = state.countdown_seconds
        round_number = state.round_number
        score_str = self._score_str(state)

        # Countdown available → always show it
        if countdown is not None:
            return self.drawStaticText(f"{countdown:02d}s", align="left")

        # No countdown → alternate RUNDA with score every 2s
        if round_number is not None:
            if score_str and int(now) % 4 >= 2:
                return self.drawStaticText(score_str)
            return self.drawStaticText(f"RUNDA {round_number:02d}", align="left")

        return self.drawStaticText("FREEZE", align="left")

    def _score_str(self, state: HudState) -> str:
        ct = state.ct_score
        t = state.t_score
        if ct is None or t is None:
            return ""
        team = (state.team or "").upper()
        if team == "CT":
            return f"{ct} - {t}"
        if team == "T":
            return f"{t} - {ct}"
        return f"{ct} - {t}"

    def _render_bomb(self, state: HudState, now: float) -> str:
        secs = self._n(state.bomb_seconds, 0)
        text = self.drawStaticText(f"BOMB {secs:02d}s", align="left")
        if state.bomb_seconds is not None and state.bomb_seconds <= 10:
            return text if int(now / 0.25) % 2 == 0 else self.drawStaticText("", align="left")
        return text

    def _render_boom(self, now: float) -> str:
        elapsed = max(0.0, now - self._boom_started_at)
        frames = (
            '    BOOM    ',
            '   B OO M   ',
            '  B  OO  M  ',
            ' B   O    M ',
            'B          M',
        )
        if elapsed < 1.6:
            index = min(len(frames) - 1, int(elapsed / 0.32))
            return frames[index]
        if elapsed >= 2.5:
            return self.drawStaticText("")
        # blink phase: all LEDs on/off at ~4Hz
        if int(elapsed / 0.12) % 2 == 0:
            return '############'
        return self.drawStaticText("")

    @staticmethod
    def _n(value: int | None, fallback: int) -> int:
        return fallback if value is None else value

    def drawStaticText(self, text: str, align: str = "center") -> str:
        clipped = (text or "")[: self.width]
        if align == "left":
            return clipped.ljust(self.width)
        if align == "right":
            return clipped.rjust(self.width)
        return clipped.center(self.width)

    def drawSplitStaticText(self, left: str, right: str) -> str:
        left = (left or "")[: self.width]
        right = (right or "")[: self.width]
        combined = f"{left} {right}".strip()
        return combined[: self.width].center(self.width)