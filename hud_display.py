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
    HUD_CLIENT_ID = os.getenv("HUD_CLIENT_ID", "cs2-led-hud")
    HUD_REFRESH_MS = int(os.getenv("HUD_REFRESH_MS", "100"))


config = Config()

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("cs2_mqtt_hud")


class HudDisplayClient:
    def __init__(self) -> None:
        self._renderer = HudRenderer()
        self._state = HudState(activity="menu")
        self._last_render = None
        self._lock = threading.Lock()

        # CS2 GSI sometimes sends bomb time in larger jumps. The display uses the
        # newest GSI value as a sync point and counts down locally every second
        # between updates. That keeps the LED smooth: p40, p39, p38...
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

    def _current_bomb_seconds_locked(self) -> int | None:
        bomb_state = (self._state.bomb_state or "").lower()
        if bomb_state not in {"planted", "plant"}:
            return None
        if self._bomb_started_monotonic is None or self._bomb_initial_seconds is None:
            return self._state.bomb_seconds

        elapsed = time.monotonic() - self._bomb_started_monotonic
        # ceil keeps p40 visible for the first second, then p39, p38...
        return max(0, int(math.ceil(self._bomb_initial_seconds - elapsed)))

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
