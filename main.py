import json
import logging
import os
import sys
import threading
import time
from typing import Any

import psutil

from dotenv import load_dotenv
from flask import Flask, jsonify, request
import paho.mqtt.client as mqtt

from animations import AnimationEngine
from events import EventDetector


load_dotenv()


class Config:
    GSI_HOST = os.getenv("GSI_HOST", "127.0.0.1")
    GSI_PORT = int(os.getenv("GSI_PORT", "3000"))
    GSI_PATH = os.getenv("GSI_PATH", "/gsi")
    GSI_TOKEN = os.getenv("GSI_TOKEN", "CHANGE_ME")

    MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
    MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
    MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
    MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
    MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "cs2-led-bridge")
    MQTT_KEEPALIVE = int(os.getenv("MQTT_KEEPALIVE", "60"))

    MQTT_TOPIC_RAW = os.getenv("MQTT_TOPIC_RAW", "cs2/raw")
    MQTT_TOPIC_STATE = os.getenv("MQTT_TOPIC_STATE", "cs2/state")
    MQTT_TOPIC_EVENT = os.getenv("MQTT_TOPIC_EVENT", "cs2/event")
    MQTT_TOPIC_STATUS = os.getenv("MQTT_TOPIC_STATUS", "cs2/status")
    MQTT_TOPIC_LED = os.getenv("MQTT_TOPIC_LED", "all")
    LED_MODE = os.getenv("LED_MODE", "hud").lower()

    PUBLISH_RAW = os.getenv("PUBLISH_RAW", "true").lower() == "true"
    PUBLISH_STATE = os.getenv("PUBLISH_STATE", "true").lower() == "true"
    PUBLISH_EVENTS = os.getenv("PUBLISH_EVENTS", "true").lower() == "true"
    PUBLISH_STATUS = os.getenv("PUBLISH_STATUS", "true").lower() == "true"
    STATUS_OFFLINE_AFTER_SECONDS = int(os.getenv("STATUS_OFFLINE_AFTER_SECONDS", "45"))

    LED_CLEAR_BEFORE = os.getenv("LED_CLEAR_BEFORE", "true").lower() == "true"
    LED_CLEAR_AFTER = os.getenv("LED_CLEAR_AFTER", "true").lower() == "true"
    LED_HOLD_SECONDS = int(os.getenv("LED_HOLD_SECONDS", "8"))
    LED_TIMER_PREFIX = os.getenv("LED_TIMER_PREFIX", "BOMBA")
    LED_WARN_AT_SECONDS = int(os.getenv("LED_WARN_AT_SECONDS", "10"))
    BOMB_DURATION_SECONDS = int(os.getenv("BOMB_DURATION_SECONDS", "40"))


config = Config()

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("cs2_mqtt_bridge")

app = Flask(__name__)


class BridgeState:
    def __init__(self) -> None:
        self.last_raw_hash = ""
        self.last_published_state = ""
        self.last_bomb_state = ""
        self.last_round_phase = ""
        self.last_timer_second = -1
        self.last_kills = -1
        self.mqtt_connected = False
        self.bomb_planted_at: int | None = None
        self.last_gsi_seen_monotonic = 0.0
        self.last_status = "offline"
        self.last_status_payload = ""


state = BridgeState()
event_detector = EventDetector()

mqtt_client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id=config.MQTT_CLIENT_ID,
    protocol=mqtt.MQTTv311,
    clean_session=True,
)
if config.MQTT_USERNAME:
    mqtt_client.username_pw_set(config.MQTT_USERNAME, config.MQTT_PASSWORD)
mqtt_client.reconnect_delay_set(min_delay=3, max_delay=60)


def on_connect(client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
    if reason_code == 0:
        state.mqtt_connected = True
        logger.info("Connected to MQTT %s:%s", config.MQTT_HOST, config.MQTT_PORT)
        publish_status("bridge_online")
    else:
        state.mqtt_connected = False
        logger.error("MQTT connect failed. reason_code=%s", reason_code)


def on_disconnect(client: mqtt.Client, userdata: Any, disconnect_flags: Any, reason_code: Any, properties: Any) -> None:
    state.mqtt_connected = False
    from_broker = getattr(disconnect_flags, "is_disconnect_packet_from_broker", None)
    source = "BROKER" if from_broker else "NETWORK"
    logger.warning("MQTT disconnected [%s] reason_code=%s", source, reason_code)


mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect


def _to_int_seconds(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _clean_string(value: Any) -> str:
    return str(value or "").strip()


def _get_bomb_state(payload: dict[str, Any]) -> str:
    bomb = payload.get("bomb", {})
    if isinstance(bomb, dict):
        for key in ("state", "phase", "status"):
            value = bomb.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().lower()

    round_block = payload.get("round", {})
    if isinstance(round_block, dict):
        round_bomb = round_block.get("bomb")
        if isinstance(round_bomb, str) and round_bomb.strip():
            return round_bomb.strip().lower()

    return ""


def _normalize_round_phase(payload: dict[str, Any]) -> str:
    round_block = payload.get("round", {})
    if isinstance(round_block, dict):
        phase = round_block.get("phase")
        if isinstance(phase, str) and phase.strip():
            return phase.strip().lower()

    phase_countdowns = payload.get("phase_countdowns", {})
    if isinstance(phase_countdowns, dict):
        phase = phase_countdowns.get("phase")
        if isinstance(phase, str) and phase.strip():
            return phase.strip().lower()

    return ""


def _bomb_remaining_seconds(payload: dict[str, Any]) -> int | None:
    remaining = _get_phase_countdown_seconds(payload)
    if remaining is not None:
        return remaining

    bomb_state = _get_bomb_state(payload)
    if bomb_state not in ("planted", "plant"):
        return None

    provider = payload.get("provider", {})
    timestamp = provider.get("timestamp") if isinstance(provider, dict) else None
    now_seconds = _to_int_seconds(timestamp)
    if now_seconds is None:
        now_seconds = int(time.time())

    if state.bomb_planted_at is None:
        state.bomb_planted_at = now_seconds

    elapsed = max(0, now_seconds - state.bomb_planted_at)
    return max(0, config.BOMB_DURATION_SECONDS - elapsed)


def _get_player_block(payload: dict[str, Any]) -> dict[str, Any]:
    player = payload.get("player", {})
    if isinstance(player, dict):
        return player
    return {}


def _get_player_state_block(payload: dict[str, Any]) -> dict[str, Any]:
    player = _get_player_block(payload)
    state_block = player.get("state", {})
    if isinstance(state_block, dict):
        return state_block

    player_state = payload.get("player_state", {})
    if isinstance(player_state, dict):
        return player_state
    return {}


def _get_player_activity(payload: dict[str, Any]) -> str:
    player = _get_player_block(payload)
    activity = player.get("activity")
    if isinstance(activity, str) and activity.strip():
        return activity.strip().lower()
    return ""


def _get_player_team(payload: dict[str, Any]) -> str:
    player = _get_player_block(payload)
    team = player.get("team")
    if isinstance(team, str) and team.strip():
        return team.strip().upper()
    return ""


def _get_player_name(payload: dict[str, Any]) -> str:
    player = _get_player_block(payload)
    name = player.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return ""


def _get_round_number(payload: dict[str, Any]) -> int | None:
    map_block = payload.get("map", {})
    if not isinstance(map_block, dict):
        return None
    return _to_int_seconds(map_block.get("round"))


def _get_round_win_team(payload: dict[str, Any]) -> str:
    round_block = payload.get("round", {})
    if not isinstance(round_block, dict):
        return ""

    win_team = round_block.get("win_team")
    if isinstance(win_team, str) and win_team.strip():
        return win_team.strip().upper()
    return ""


def _get_phase_countdown_seconds(payload: dict[str, Any]) -> int | None:
    phase_countdowns = payload.get("phase_countdowns", {})
    if not isinstance(phase_countdowns, dict):
        return None
    return _to_int_seconds(phase_countdowns.get("phase_ends_in"))


def _get_phase_countdown_phase(payload: dict[str, Any]) -> str:
    phase_countdowns = payload.get("phase_countdowns", {})
    if not isinstance(phase_countdowns, dict):
        return ""

    phase = phase_countdowns.get("phase")
    if isinstance(phase, str) and phase.strip():
        return phase.strip().lower()
    return ""


def _get_player_health(payload: dict[str, Any]) -> int | None:
    return _to_int_seconds(_get_player_state_block(payload).get("health"))


def _get_player_armor(payload: dict[str, Any]) -> int | None:
    return _to_int_seconds(_get_player_state_block(payload).get("armor"))


def _get_player_round_kills(payload: dict[str, Any]) -> int | None:
    return _to_int_seconds(_get_player_state_block(payload).get("round_kills"))


def _get_player_match_stats(payload: dict[str, Any]) -> dict[str, Any]:
    player = _get_player_block(payload)
    match_stats = player.get("match_stats", {})
    if isinstance(match_stats, dict):
        return match_stats

    top_level = payload.get("player_match_stats", {})
    if isinstance(top_level, dict):
        return top_level
    return {}


def _get_player_deaths(payload: dict[str, Any]) -> int | None:
    return _to_int_seconds(_get_player_match_stats(payload).get("deaths"))


def _get_player_score(payload: dict[str, Any]) -> int | None:
    return _to_int_seconds(_get_player_match_stats(payload).get("score"))


def _short_weapon_name(name: str) -> str:
    name = name.replace("weapon_", "")
    aliases = {
        "ak47": "AK",
        "m4a1": "M4",
        "m4a1_silencer": "M4S",
        "usp_silencer": "USP",
        "hkp2000": "P2K",
        "deagle": "DEAG",
        "galilar": "GALIL",
        "aug": "AUG",
        "sg556": "SG",
        "famas": "FAMAS",
        "awp": "AWP",
        "ssg08": "SSG",
        "glock": "GLOCK",
        "p250": "P250",
        "elite": "DUAL",
        "fiveseven": "57",
        "tec9": "TEC9",
        "cz75a": "CZ",
        "mac10": "MAC",
        "mp9": "MP9",
        "mp7": "MP7",
        "mp5sd": "MP5",
        "ump45": "UMP",
        "p90": "P90",
        "bizon": "BIZON",
        "xm1014": "XM",
        "mag7": "MAG7",
        "nova": "NOVA",
        "sawedoff": "SAW",
        "negev": "NEGEV",
        "m249": "M249",
        "knife": "KNIFE",
        "c4": "C4",
        "hegrenade": "HE",
        "flashbang": "FLASH",
        "smokegrenade": "SMOKE",
        "molotov": "MOLO",
        "incgrenade": "FIRE",
        "decoy": "DECOY",
    }
    return aliases.get(name.lower(), name.upper()[:8])


def _extract_weapon_info(weapon: Any, fallback_key: str = "") -> dict[str, Any] | None:
    if not isinstance(weapon, dict):
        return None

    raw_name = _clean_string(weapon.get("name") or fallback_key)
    ammo_clip = None
    for key in ("ammo_clip", "clip_ammo", "ammo_in_clip", "current_ammo", "ammo", "clip", "magazine", "bullets"):
        ammo_clip = _to_int_seconds(weapon.get(key))
        if ammo_clip is not None:
            break

    ammo_reserve = None
    for key in ("ammo_reserve", "reserve_ammo", "ammo_clip_reserve"):
        ammo_reserve = _to_int_seconds(weapon.get(key))
        if ammo_reserve is not None:
            break

    ammo_clip_max = None
    for key in ("ammo_clip_max", "clip_max", "max_clip"):
        ammo_clip_max = _to_int_seconds(weapon.get(key))
        if ammo_clip_max is not None:
            break

    weapon_type = _clean_string(weapon.get("type"))
    weapon_state = _clean_string(weapon.get("state")).lower()
    is_active = bool(weapon.get("active")) or weapon_state in {"active", "equipped", "selected"}

    nested = weapon.get("state")
    if isinstance(nested, dict):
        nested_info = _extract_weapon_info(nested, fallback_key=raw_name)
        if nested_info:
            raw_name = raw_name or nested_info.get("weapon_raw", "")
            ammo_clip = ammo_clip if ammo_clip is not None else nested_info.get("ammo")
            ammo_reserve = ammo_reserve if ammo_reserve is not None else nested_info.get("ammo_reserve")
            ammo_clip_max = ammo_clip_max if ammo_clip_max is not None else nested_info.get("ammo_clip_max")
            weapon_type = weapon_type or nested_info.get("weapon_type", "")

    if not raw_name and ammo_clip is None:
        return None

    return {
        "weapon_raw": raw_name,
        "weapon": _short_weapon_name(raw_name) if raw_name else "",
        "weapon_type": weapon_type,
        "ammo": ammo_clip,
        "ammo_reserve": ammo_reserve,
        "ammo_clip_max": ammo_clip_max,
        "active": is_active,
    }


def _extract_weapon_from_container(container: Any) -> dict[str, Any] | None:
    if not isinstance(container, dict) or not container:
        return None

    fallback: dict[str, Any] | None = None
    for weapon_key, weapon in container.items():
        info = _extract_weapon_info(weapon, fallback_key=str(weapon_key))
        if not info:
            continue
        if info.get("active"):
            return info
        if fallback is None:
            fallback = info
    return fallback


def _get_active_weapon(payload: dict[str, Any]) -> dict[str, Any]:
    player = _get_player_block(payload)
    state_block = _get_player_state_block(payload)

    candidates = (
        player.get("active_weapon"),
        player.get("weapon"),
        player.get("weapons"),
        state_block.get("active_weapon"),
        payload.get("active_weapon"),
        payload.get("weapon"),
        payload.get("player_weapon"),
        payload.get("player_weapons"),
    )

    for candidate in candidates:
        info = _extract_weapon_info(candidate)
        if info is None:
            info = _extract_weapon_from_container(candidate)
        if info is not None:
            return info

    info = _extract_weapon_from_container(player.get("weapons"))
    if info is not None:
        return info

    for key in ("ammo", "ammo_clip", "clip_ammo", "current_ammo"):
        ammo = _to_int_seconds(state_block.get(key))
        if ammo is not None:
            return {"weapon_raw": "", "weapon": "", "weapon_type": "", "ammo": ammo, "ammo_reserve": None, "ammo_clip_max": None, "active": True}

    return {"weapon_raw": "", "weapon": "", "weapon_type": "", "ammo": None, "ammo_reserve": None, "ammo_clip_max": None, "active": False}


def _get_player_kills(payload: dict[str, Any]) -> int | None:
    player_state = payload.get("player_state", {})
    if not isinstance(player_state, dict):
        player_state = {}
    player = payload.get("player", {})
    if not isinstance(player, dict):
        player = {}

    player_match_stats_nested = player.get("match_stats", {})
    if isinstance(player_match_stats_nested, dict) and player_match_stats_nested:
        kills = player_match_stats_nested.get("kills")
        if kills is not None:
            return _to_int_seconds(kills)

    player_match_stats = payload.get("player_match_stats", {})
    if isinstance(player_match_stats, dict) and player_match_stats:
        kills = player_match_stats.get("kills")
        if kills is not None:
            return _to_int_seconds(kills)

    round_kills = player_state.get("round_kills")
    if round_kills is not None:
        return _to_int_seconds(round_kills)

    player_inner_state = player.get("state", {})
    if isinstance(player_inner_state, dict):
        round_kills = player_inner_state.get("round_kills")
        if round_kills is not None:
            return _to_int_seconds(round_kills)

    match_stats = player_state.get("match_stats", {})
    if isinstance(match_stats, dict) and match_stats:
        kills = match_stats.get("kills")
        if kills is not None:
            return _to_int_seconds(kills)

    all_players = payload.get("allplayers_state", {})
    if isinstance(all_players, dict) and all_players:
        provider = payload.get("provider", {})
        player_id = provider.get("steamid") or player.get("steamid")
        if player_id and player_id in all_players:
            player_info = all_players[player_id]
            if isinstance(player_info, dict):
                for field in ("match_stats", "stats"):
                    stats = player_info.get(field, {})
                    if isinstance(stats, dict):
                        kills = stats.get("kills")
                        if kills is not None:
                            return _to_int_seconds(kills)

    return None


def publish(topic: str, payload: str, qos: int = 1, retain: bool = False) -> None:
    if not state.mqtt_connected:
        logger.debug("Skipping publish while MQTT is disconnected. topic=%s", topic)
        return

    info = mqtt_client.publish(topic=topic, payload=payload, qos=qos, retain=retain)
    if info.rc != mqtt.MQTT_ERR_SUCCESS:
        logger.error("Publish failed topic=%s rc=%s", topic, info.rc)


def publish_json(topic: str, payload: dict[str, Any], qos: int = 1, retain: bool = False) -> None:
    publish(topic, json.dumps(payload, separators=(",", ":"), sort_keys=True), qos=qos, retain=retain)


def publish_status(status: str, extra: dict[str, Any] | None = None) -> None:
    if not config.PUBLISH_STATUS:
        return
    payload = {
        "status": status,
        "bridge": "online",
        "last_gsi_seen_seconds_ago": _last_gsi_age_seconds(),
        "timestamp": int(time.time()),
    }
    if extra:
        payload.update(extra)

    compact = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    if compact == state.last_status_payload:
        return
    publish(config.MQTT_TOPIC_STATUS, compact, retain=True)
    state.last_status_payload = compact
    state.last_status = status


def _last_gsi_age_seconds() -> int | None:
    if state.last_gsi_seen_monotonic <= 0:
        return None
    return max(0, int(time.monotonic() - state.last_gsi_seen_monotonic))


def publish_led(message: str) -> None:
    msg = (message or "").replace("\n", " ").replace("\r", " ").strip()
    if len(msg) > 120:
        msg = msg[:120]
    publish(config.MQTT_TOPIC_LED, msg)


anim = AnimationEngine(publish_led)


def build_state(payload: dict[str, Any]) -> dict[str, Any]:
    provider = payload.get("provider", {})
    map_block = payload.get("map", {})

    bomb_state = _get_bomb_state(payload)
    round_phase = _normalize_round_phase(payload)
    bomb_seconds = _bomb_remaining_seconds(payload)
    if bomb_state not in ("planted", "plant"):
        state.bomb_planted_at = None

    kills = _get_player_kills(payload)
    health = _get_player_health(payload)
    armor = _get_player_armor(payload)
    activity = _get_player_activity(payload)
    team = _get_player_team(payload)
    deaths = _get_player_deaths(payload)
    score = _get_player_score(payload)
    weapon = _get_active_weapon(payload)
    round_kills = _get_player_round_kills(payload)
    round_number = _get_round_number(payload)
    round_win_team = _get_round_win_team(payload)
    countdown_seconds = _get_phase_countdown_seconds(payload)
    countdown_phase = _get_phase_countdown_phase(payload)
    ct_score = int(map_block.get("team_ct", {}).get("score") or 0) if isinstance(map_block, dict) else 0
    t_score = int(map_block.get("team_t", {}).get("score") or 0) if isinstance(map_block, dict) else 0
    name = _get_player_name(payload)

    return {
        "timestamp": provider.get("timestamp") if isinstance(provider, dict) else None,
        "map": map_block.get("name") if isinstance(map_block, dict) else None,
        "map_mode": map_block.get("mode") if isinstance(map_block, dict) else None,
        "map_phase": map_block.get("phase") if isinstance(map_block, dict) else None,
        "round_phase": round_phase,
        "round": round_number,
        "round_win_team": round_win_team,
        "bomb_state": bomb_state,
        "bomb_seconds": bomb_seconds,
        "countdown_seconds": countdown_seconds,
        "countdown_phase": countdown_phase,
        "activity": activity,
        "team": team,
        "health": health,
        "armor": armor,
        "weapon": weapon.get("weapon") or "",
        "weapon_raw": weapon.get("weapon_raw") or "",
        "weapon_type": weapon.get("weapon_type") or "",
        "ammo": weapon.get("ammo"),
        "ammo_reserve": weapon.get("ammo_reserve"),
        "ammo_clip_max": weapon.get("ammo_clip_max"),
        "kills": kills,
        "deaths": deaths,
        "score": score,
        "round_kills": round_kills,
        "ct_score": ct_score,
        "t_score": t_score,
        "name": name,
    }


def handle_led_logic(cs2_state: dict[str, Any]) -> None:
    bomb_state = (cs2_state.get("bomb_state") or "").lower()
    round_phase = (cs2_state.get("round_phase") or "").lower()
    bomb_seconds = cs2_state.get("bomb_seconds")
    kills = cs2_state.get("kills")

    if bomb_state or round_phase or kills:
        logger.debug(
            "LED Event: bomb_state=%s, round_phase=%s, bomb_seconds=%s, kills=%s",
            bomb_state or "-",
            round_phase or "-",
            bomb_seconds,
            kills,
        )

    if bomb_state != state.last_bomb_state:
        if bomb_state in ("planted", "plant"):
            anim.play_bomb_planted(bomb_seconds)
            state.last_timer_second = -1
        elif bomb_state in ("defused", "defuse"):
            anim.play_bomb_defused()
            state.last_timer_second = -1
        elif bomb_state in ("exploded", "explode"):
            anim.play_bomb_exploded()
            state.last_timer_second = -1
        elif bomb_state in ("carried",):
            anim.play_bomb_carried()
            state.last_timer_second = -1
        elif bomb_state in ("dropped",):
            anim.play_bomb_dropped()
            state.last_timer_second = -1

        state.last_bomb_state = bomb_state

    if bomb_state in ("planted", "plant") and bomb_seconds is not None:
        if bomb_seconds != state.last_timer_second:
            anim.play_bomb_timer(bomb_seconds)
            state.last_timer_second = bomb_seconds

    if kills is not None and state.last_kills >= 0 and kills > state.last_kills:
        anim.play_player_killed(kills)
        state.last_kills = kills
    elif kills is not None:
        state.last_kills = kills

    if kills is not None and kills >= 0:
        if bomb_state not in ("planted", "plant"):
            anim.show_kill_counter(kills)
    elif kills is None and round_phase in ("live",):
        anim.show_kill_counter(0)

    if round_phase and round_phase != state.last_round_phase:
        if round_phase in ("freezetime", "freeze", "warmup"):
            anim.play_round_freezetime()
            state.last_kills = -1
        elif round_phase in ("live",):
            anim.play_round_live()
        elif round_phase in ("over", "gameover"):
            anim.play_round_over()
            state.last_timer_second = -1

        state.last_round_phase = round_phase


def publish_events(cs2_state: dict[str, Any]) -> None:
    if not config.PUBLISH_EVENTS:
        return

    for event in event_detector.detect(cs2_state):
        publish_json(config.MQTT_TOPIC_EVENT, event.payload, retain=False)
        publish_json(f"{config.MQTT_TOPIC_EVENT}/{event.type}", event.payload, retain=False)
        logger.info("CS2 event: %s %s", event.type, event.text)


@app.get("/health")
def health_handler():
    return jsonify(
        {
            "ok": True,
            "mqtt_connected": state.mqtt_connected,
            "last_gsi_seen_seconds_ago": _last_gsi_age_seconds(),
            "status": state.last_status,
        }
    )


@app.post(config.GSI_PATH)
def gsi_handler():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "invalid_json"}), 400

    auth = payload.get("auth", {})
    provided_token = auth.get("token") if isinstance(auth, dict) else None
    if config.GSI_TOKEN and config.GSI_TOKEN != "CHANGE_ME":
        if provided_token != config.GSI_TOKEN:
            return jsonify({"ok": False, "error": "unauthorized"}), 401

    state.last_gsi_seen_monotonic = time.monotonic()
    publish_status("online")

    bomb_data = payload.get("bomb", {})
    round_data = payload.get("round", {})
    phase_data = payload.get("phase_countdowns", {})
    player_block = payload.get("player", {})
    player_data = payload.get("player_state", {})
    logger.debug(
        "Payload sections - bomb: %s, round: %s, phase: %s, player: %s, player_state: %s",
        bool(bomb_data) or bool(round_data.get("bomb") if isinstance(round_data, dict) else None),
        bool(round_data),
        bool(phase_data),
        bool(player_block),
        bool(player_data),
    )
    logger.debug("Payload top-level keys: %s", list(payload.keys()))
    if player_block:
        logger.debug("Player block content: %s", player_block)
    if player_data:
        logger.debug("Player state content: %s", player_data)
    for wkey in ("player_weapons", "allplayers_weapons", "weapons"):
        wdata = payload.get(wkey)
        if wdata:
            logger.debug("Weapons key '%s': %s", wkey, wdata)

    payload_compact = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    payload_hash = str(hash(payload_compact))

    if config.PUBLISH_RAW and payload_hash != state.last_raw_hash:
        publish(config.MQTT_TOPIC_RAW, payload_compact)
        state.last_raw_hash = payload_hash

    cs2_state = build_state(payload)
    publish_events(cs2_state)

    if config.PUBLISH_STATE:
        compact_state = json.dumps(cs2_state, separators=(",", ":"), sort_keys=True)
        if compact_state != state.last_published_state:
            publish(config.MQTT_TOPIC_STATE, compact_state, retain=False)
            state.last_published_state = compact_state

    if config.LED_MODE in {"event", "mixed"}:
        handle_led_logic(cs2_state)
    return jsonify({"ok": True})


def ensure_mqtt_connection() -> None:
    while True:
        try:
            logger.info("Connecting to MQTT %s:%s", config.MQTT_HOST, config.MQTT_PORT)
            mqtt_client.connect(config.MQTT_HOST, config.MQTT_PORT, keepalive=config.MQTT_KEEPALIVE)
            return
        except Exception as exc:
            logger.warning("MQTT connect failed: %s. Retrying in 5s...", exc)
            time.sleep(5)


def status_watchdog() -> None:
    while True:
        time.sleep(5)
        if state.last_gsi_seen_monotonic <= 0:
            publish_status("waiting_for_cs2")
            continue
        age = time.monotonic() - state.last_gsi_seen_monotonic
        if age > config.STATUS_OFFLINE_AFTER_SECONDS:
            publish_status("offline")
            event_detector.reset()


def run() -> None:
    logger.info("Starting bridge on http://%s:%s%s", config.GSI_HOST, config.GSI_PORT, config.GSI_PATH)
    ensure_mqtt_connection()

    watchdog_thread = threading.Thread(target=status_watchdog, daemon=True)
    watchdog_thread.start()

    flask_thread = threading.Thread(
        target=lambda: app.run(
            host=config.GSI_HOST,
            port=config.GSI_PORT,
            use_reloader=False,
            threaded=True,
        ),
        daemon=True,
    )
    flask_thread.start()

    mqtt_client.loop_forever(retry_first_connection=True)


def kill_existing_instances() -> None:
    current_pid = os.getpid()
    current_script = os.path.abspath(__file__)
    script_name = os.path.basename(current_script)
    script_dir = os.path.dirname(current_script)
    killed = 0
    for proc in psutil.process_iter(["pid", "name", "cmdline", "cwd"]):
        try:
            if proc.pid == current_pid:
                continue
            cmdline = proc.info.get("cmdline") or []
            abs_match = any(os.path.abspath(arg) == current_script for arg in cmdline)
            cwd = ""
            try:
                cwd = proc.cwd()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            rel_match = script_name in cmdline and os.path.normcase(cwd) == os.path.normcase(script_dir)
            if abs_match or rel_match:
                proc.kill()
                proc.wait(timeout=3)
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
            pass
    if killed:
        logger.info("Killed %d existing instance(s) of this script.", killed)


if __name__ == "__main__":
    kill_existing_instances()
    run()
