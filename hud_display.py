from __future__ import annotations

import copy
import json
import logging
import math
import os
import threading
import time
from typing import Any

from dotenv import load_dotenv
import paho.mqtt.client as mqtt

from hud_renderer import HudRenderer, HudState


load_dotenv()


class Config:
    MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
    MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
    MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
    MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
    MQTT_KEEPALIVE = int(os.getenv("MQTT_KEEPALIVE", "60"))
    MQTT_TOPIC_STATE = os.getenv("MQTT_TOPIC_STATE", "cs2/state")
    MQTT_TOPIC_LED = os.getenv("MQTT_TOPIC_LED", "all")
    MQTT_TOPIC_MATRIX_CMD = os.getenv("MQTT_TOPIC_MATRIX_CMD", "matrix/cmd")
    PUBLISH_MATRIX_CMD = os.getenv("PUBLISH_MATRIX_CMD", "true").lower() == "true"
    HUD_CLIENT_ID = os.getenv("HUD_CLIENT_ID", "cs2-led-hud")
    HUD_REFRESH_MS = int(os.getenv("HUD_REFRESH_MS", "100"))


config = Config()

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("cs2_mqtt_hud")


class MatrixCommandRenderer:
    """Builds a 6 x 8x8 tile command payload for a smarter ESP renderer.

    The old text topic remains as fallback. This JSON topic lets the ESP treat
    every 8x8 module as a separate tile with one clear value:

    tile 0 = armor bar
    tile 1 = health bar
    tile 2 = ammo-in-magazine bar
    tile 3 = reserve-ammo bar
    tile 4 = kills number/icon
    tile 5 = deaths number/icon

    Bomb/defuse/boom are full-width modes because those events are more
    important than the normal six-tile HUD.
    """

    def __init__(self) -> None:
        self._last_bomb_state = ""
        self._last_kills: int | None = None
        self._last_deaths: int | None = None
        self._kill_popup_until = 0.0
        self._death_popup_until = 0.0
        self._damage_popup_until = 0.0
        self._ammo_popup_until = 0.0
        self._last_health: int | None = None
        self._last_armor: int | None = None
        self._last_ammo: int | None = None

    def render(self, state: HudState, now: float | None = None) -> dict[str, Any]:
        now = time.monotonic() if now is None else now
        self._update_effects(state, now)

        bomb_state = (state.bomb_state or "").lower()
        if bomb_state in {"planted", "plant"} and state.bomb_seconds is not None:
            seconds = self._n(state.bomb_seconds, 0)
            return {
                "m": "bomb",
                "t": seconds,
                "max": 40,
                "blink": seconds <= 10,
                "tiles": [
                    {"i": 0, "type": "icon", "v": "bomb"},
                    {"i": 1, "type": "num", "v": seconds},
                    {"i": 2, "type": "bar", "v": seconds, "max": 40},
                    {"i": 3, "type": "bar", "v": seconds, "max": 40},
                    {"i": 4, "type": "bar", "v": seconds, "max": 40},
                    {"i": 5, "type": "bar", "v": seconds, "max": 40},
                ],
            }

        if bomb_state in {"defused", "defuse"}:
            return {"m": "defuse", "flash": True}

        if bomb_state in {"exploded", "explode"}:
            return {"m": "boom", "flash": True}

        if now < self._kill_popup_until:
            return {"m": "kill", "k": self._n(state.kills, 0), "tiles": self._normal_tiles(state)}

        if now < self._death_popup_until:
            return {"m": "death", "d": self._n(state.deaths, 0), "tiles": self._normal_tiles(state)}

        if now < self._damage_popup_until:
            return {
                "m": "damage",
                "h": self._n(state.health, 0),
                "a": self._n(state.armor, 0),
                "tiles": self._normal_tiles(state),
            }

        if now < self._ammo_popup_until:
            return {
                "m": "ammo",
                "am": self._n(state.ammo, 0),
                "max": self._ammo_max(state),
                "tiles": self._normal_tiles(state),
            }

        activity = (state.activity or "").lower()
        if activity == "menu":
            return {"m": "menu"}

        return {
            "m": "tiles",
            "tiles": self._normal_tiles(state),
        }

    def _normal_tiles(self, state: HudState) -> list[dict[str, Any]]:
        ammo_max = self._ammo_max(state)
        reserve_max = max(1, self._reserve_max(state))
        return [
            {"i": 0, "name": "armor", "type": "vbar", "v": self._n(state.armor, 0), "max": 100},
            {"i": 1, "name": "hp", "type": "vbar", "v": self._n(state.health, 0), "max": 100},
            {"i": 2, "name": "ammo", "type": "vbar", "v": self._n(state.ammo, 0), "max": ammo_max},
            {"i": 3, "name": "reserve", "type": "vbar", "v": self._n(state.ammo_reserve, 0), "max": reserve_max},
            {"i": 4, "name": "kills", "type": "num", "v": self._n(state.kills, 0), "icon": "crosshair"},
            {"i": 5, "name": "deaths", "type": "num", "v": self._n(state.deaths, 0), "icon": "skull"},
        ]

    def _update_effects(self, state: HudState, now: float) -> None:
        kills = state.kills
        deaths = state.deaths
        health = state.health
        armor = state.armor
        ammo = state.ammo

        if self._last_kills is not None and kills is not None and kills > self._last_kills:
            self._kill_popup_until = now + 1.5
        if self._last_deaths is not None and deaths is not None and deaths > self._last_deaths:
            self._death_popup_until = now + 1.8

        if self._last_health is not None and health is not None and health < self._last_health:
            self._damage_popup_until = now + 1.0
        if self._last_armor is not None and armor is not None and armor < self._last_armor:
            self._damage_popup_until = now + 1.0

        if self._last_ammo is not None and ammo is not None and 0 <= ammo < self._last_ammo:
            self._ammo_popup_until = now + 1.0

        if kills is not None:
            self._last_kills = kills
        if deaths is not None:
            self._last_deaths = deaths
        if health is not None:
            self._last_health = health
        if armor is not None:
            self._last_armor = armor
        if ammo is not None:
            self._last_ammo = ammo

    def _ammo_max(self, state: HudState) -> int:
        if state.ammo_clip_max is not None and state.ammo_clip_max > 0:
            return max(1, self._n(state.ammo_clip_max, 30))
        # 30 is a safe fallback for common rifles. Pistols/shotguns still work as relative bars.
        return 30

    def _reserve_max(self, state: HudState) -> int:
        if state.ammo_reserve is None:
            return 90
        # Use common CS reserve chunks so the reserve bar is not constantly rescaled.
        reserve = self._n(state.ammo_reserve, 0)
        if reserve <= 24:
            return 24
        if reserve <= 60:
            return 60
        if reserve <= 90:
            return 90
        return 120

    def _n(self, value: int | None, fallback: int) -> int:
        if value is None:
            return fallback
        return max(0, min(999, int(value)))


class HudDisplayClient:
    def __init__(self) -> None:
        self._renderer = HudRenderer()
        self._cmd_renderer = MatrixCommandRenderer()
        self._state = HudState(activity="menu")
        self._last_render = None
        self._last_cmd = None
        self._lock = threading.Lock()

        # CS2 GSI sometimes sends bomb time in larger jumps. The display uses the
        # newest GSI value as a sync point and counts down locally between updates.
        # floor() avoids keeping e.g. boom:40 visible for one second too long.
        self._bomb_started_monotonic: float | None = None
        self._bomb_initial_seconds: int | None = None
        self._last_bomb_state = ""

        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=config.HUD_CLIENT_ID,
            protocol=mqtt.MQTTv311,
            clean_session=True,
        )
        if config.MQTT_USERNAME:
            self._client.username_pw_set(config.MQTT_USERNAME, config.MQTT_PASSWORD)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(min_delay=3, max_delay=30)

    def run(self) -> None:
        self._client.connect(config.MQTT_HOST, config.MQTT_PORT, keepalive=config.MQTT_KEEPALIVE)
        self._client.loop_start()
        try:
            while True:
                self._tick()
                time.sleep(config.HUD_REFRESH_MS / 1000.0)
        finally:
            self._client.loop_stop()

    def _tick(self) -> None:
        with self._lock:
            state = copy.copy(self._state)
            bomb_seconds = self._current_bomb_seconds_locked()
            if bomb_seconds is not None:
                state.bomb_seconds = bomb_seconds

        rendered = self._renderer.render(state)
        self._publish_if_changed(rendered)

        if config.PUBLISH_MATRIX_CMD:
            command = self._cmd_renderer.render(state)
            self._publish_cmd_if_changed(command)

    def _current_bomb_seconds_locked(self) -> int | None:
        bomb_state = (self._state.bomb_state or "").lower()
        if bomb_state not in {"planted", "plant"}:
            return None
        if self._bomb_started_monotonic is None or self._bomb_initial_seconds is None:
            return self._state.bomb_seconds

        elapsed = time.monotonic() - self._bomb_started_monotonic
        return max(0, int(math.floor(self._bomb_initial_seconds - elapsed)))

    def _sync_bomb_countdown_locked(self, new_state: HudState) -> None:
        bomb_state = (new_state.bomb_state or "").lower()
        incoming_seconds = new_state.bomb_seconds

        if bomb_state not in {"planted", "plant"} or incoming_seconds is None:
            self._bomb_started_monotonic = None
            self._bomb_initial_seconds = None
            self._last_bomb_state = bomb_state
            return

        now = time.monotonic()
        should_start = (
            self._bomb_started_monotonic is None
            or self._bomb_initial_seconds is None
            or self._last_bomb_state not in {"planted", "plant"}
        )

        if should_start:
            self._bomb_started_monotonic = now
            self._bomb_initial_seconds = incoming_seconds
            self._last_bomb_state = bomb_state
            return

        predicted = self._current_bomb_seconds_locked()
        if predicted is None or abs(predicted - incoming_seconds) > 1:
            # Resync only when GSI disagrees noticeably. Small differences are
            # ignored to avoid visible jitter on the LED.
            self._bomb_started_monotonic = now
            self._bomb_initial_seconds = incoming_seconds

        self._last_bomb_state = bomb_state

    def _publish_if_changed(self, rendered: str) -> None:
        if rendered != self._last_render:
            self._client.publish(config.MQTT_TOPIC_LED, rendered, qos=1, retain=False)
            self._last_render = rendered
            logger.info("HUD publish: %r", rendered)

    def _publish_cmd_if_changed(self, command: dict[str, Any]) -> None:
        payload = json.dumps(command, separators=(",", ":"), ensure_ascii=False)
        if payload != self._last_cmd:
            self._client.publish(config.MQTT_TOPIC_MATRIX_CMD, payload, qos=1, retain=False)
            self._last_cmd = payload
            logger.info("MATRIX cmd publish: %s", payload)

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
        if reason_code == 0:
            logger.info("HUD connected to MQTT %s:%s", config.MQTT_HOST, config.MQTT_PORT)
            client.subscribe(config.MQTT_TOPIC_STATE, qos=1)
        else:
            logger.error("HUD MQTT connect failed. reason_code=%s", reason_code)

    def _on_message(self, client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except Exception as exc:
            logger.warning("Invalid HUD state payload: %s", exc)
            return

        new_state = HudState(
            activity=str(payload.get("activity") or ""),
            round_phase=str(payload.get("round_phase") or ""),
            bomb_state=str(payload.get("bomb_state") or ""),
            bomb_seconds=_to_int(payload.get("bomb_seconds")),
            countdown_seconds=_to_int(payload.get("countdown_seconds")),
            countdown_phase=str(payload.get("countdown_phase") or ""),
            round_number=_to_int(payload.get("round")),
            round_win_team=str(payload.get("round_win_team") or ""),
            team=str(payload.get("team") or ""),
            health=_to_int(payload.get("health")),
            armor=_to_int(payload.get("armor")),
            weapon=str(payload.get("weapon") or ""),
            weapon_raw=str(payload.get("weapon_raw") or ""),
            weapon_type=str(payload.get("weapon_type") or ""),
            ammo=_to_int(payload.get("ammo")),
            ammo_reserve=_to_int(payload.get("ammo_reserve")),
            ammo_clip_max=_to_int(payload.get("ammo_clip_max")),
            kills=_to_int(payload.get("kills")),
            deaths=_to_int(payload.get("deaths")),
            score=_to_int(payload.get("score")),
            round_kills=_to_int(payload.get("round_kills")),
            ct_score=_to_int(payload.get("ct_score")),
            t_score=_to_int(payload.get("t_score")),
            name=str(payload.get("name") or ""),
            map=str(payload.get("map") or ""),
            map_mode=str(payload.get("map_mode") or ""),
            map_phase=str(payload.get("map_phase") or ""),
        )

        with self._lock:
            self._state = new_state
            self._sync_bomb_countdown_locked(new_state)
        logger.debug("HUD state update: %s", self._state)


def _to_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    HudDisplayClient().run()
