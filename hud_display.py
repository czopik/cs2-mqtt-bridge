from __future__ import annotations

import copy
import json
import logging
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
        self._bomb_countdown_start: float | None = None
        self._initial_bomb_seconds: int | None = None
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
            state = self._state

        rendered_state = state

        # Jeśli bomba jest podłożona, odliczaj czas lokalnie co sekundę
        if state.bomb_state == "planted" and state.bomb_seconds is not None:
            if self._bomb_countdown_start is None:
                self._bomb_countdown_start = time.time()
                self._initial_bomb_seconds = state.bomb_seconds

            elapsed = time.time() - self._bomb_countdown_start
            current_bomb_seconds = max(0, int(self._initial_bomb_seconds - elapsed))

            # Tworzę kopię state ze zaktualizowanym bomb_seconds
            rendered_state = copy.copy(state)
            rendered_state.bomb_seconds = current_bomb_seconds
        else:
            # Resetuj licznik jeśli bomba już nie jest aktywna
            self._bomb_countdown_start = None
            self._initial_bomb_seconds = None

        rendered = self._renderer.render(rendered_state)
        if rendered != self._last_render:
            self._client.publish(config.MQTT_TOPIC_LED, rendered, qos=1, retain=False)
            self._last_render = rendered
            logger.debug("HUD publish: %r", rendered)

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

        with self._lock:
            self._state = HudState(
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
                ammo=_to_int(payload.get("ammo")),
                kills=_to_int(payload.get("kills")),
                deaths=_to_int(payload.get("deaths")),
                score=_to_int(payload.get("score")),
                round_kills=_to_int(payload.get("round_kills")),
                ct_score=_to_int(payload.get("ct_score")),
                t_score=_to_int(payload.get("t_score")),
                name=str(payload.get("name") or ""),
            )
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