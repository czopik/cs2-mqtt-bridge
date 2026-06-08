from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


CFG_NAME = "gamestate_integration_ledmatrix.cfg"


CFG_TEMPLATE = '''"CS2 LED Matrix Bridge"
{{
  "uri"           "{uri}"
  "timeout"       "1.1"
  "buffer"        "0.1"
  "throttle"      "0.2"
  "heartbeat"     "30.0"

  "auth"
  {{
    "token"       "{token}"
  }}

  "data"
  {{
    "provider"               "1"
    "map"                    "1"
    "map_round_wins"         "1"
    "round"                  "1"
    "player_id"              "1"
    "player_position"        "1"
    "bomb"                   "1"
    "phase_countdowns"       "1"
    "player_state"           "1"
    "player_match_stats"     "1"
    "player_weapons"         "1"
    "allplayers_id"          "1"
    "allplayers_state"       "1"
    "allplayers_match_stats" "1"
    "allplayers_weapons"     "1"
    "allplayers_position"    "1"
    "allgrenades"            "1"
  }}
}}
'''


def main() -> None:
    args = parse_args()
    token = get_required_token()
    uri = build_uri()

    if args.output:
        target = Path(args.output).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
    else:
        cfg_dir = find_cs2_cfg_dir()
        if cfg_dir is None:
            raise SystemExit(
                "Nie znalazlem katalogu CS2 cfg. Podaj sciezke przez --output albo ustaw CS2_CFG_DIR w .env."
            )
        target = cfg_dir / CFG_NAME

    target.write_text(CFG_TEMPLATE.format(uri=uri, token=token), encoding="utf-8")

    print("Zapisano CS2 GSI config:")
    print(target)
    print()
    print("URI:", uri)
    print("Token:", mask_token(token))
    print()
    print("Po zmianie zrestartuj CS2.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate CS2 Game State Integration config from local .env")
    parser.add_argument(
        "--output",
        help="Manual output path for gamestate_integration_ledmatrix.cfg. Useful when CS2 is in a custom location.",
    )
    return parser.parse_args()


def get_required_token() -> str:
    token = os.getenv("GSI_TOKEN", "").strip()
    if not token or token == "CHANGE_ME":
        raise SystemExit(
            "GSI_TOKEN w .env nie jest ustawiony. Wpisz swoj token w .env, np. GSI_TOKEN=twoj-token, "
            "a potem uruchom ponownie: python install_gsi.py"
        )
    return token


def build_uri() -> str:
    host = os.getenv("PUBLIC_GSI_HOST") or os.getenv("GSI_PUBLIC_HOST") or local_host_for_gsi()
    port = int(os.getenv("GSI_PORT", "3010"))
    path = os.getenv("GSI_PATH", "/gsi")
    return f"http://{host}:{port}{path}"


def find_cs2_cfg_dir() -> Path | None:
    manual = os.getenv("CS2_CFG_DIR", "").strip()
    if manual:
        path = Path(manual).expanduser()
        if path.exists():
            return path

    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Steam"
        / "steamapps"
        / "common"
        / "Counter-Strike Global Offensive"
        / "game"
        / "csgo"
        / "cfg",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Steam"
        / "steamapps"
        / "common"
        / "Counter-Strike Global Offensive"
        / "game"
        / "csgo"
        / "cfg",
    ]

    for steam_library in read_steam_libraries():
        candidates.append(
            steam_library
            / "steamapps"
            / "common"
            / "Counter-Strike Global Offensive"
            / "game"
            / "csgo"
            / "cfg"
        )

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def read_steam_libraries() -> list[Path]:
    library_file = (
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Steam"
        / "steamapps"
        / "libraryfolders.vdf"
    )
    if not library_file.exists():
        return []

    libraries: list[Path] = []
    for line in library_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if '"path"' not in line:
            continue
        parts = line.split('"')
        if len(parts) >= 4:
            libraries.append(Path(parts[3].replace("\\\\", "\\")))
    return libraries


def local_host_for_gsi() -> str:
    host = os.getenv("GSI_HOST", "127.0.0.1")
    if host in {"0.0.0.0", "::"}:
        return os.getenv("UNRAID_HOST", "192.168.1.249")
    return host


def mask_token(token: str) -> str:
    if len(token) <= 8:
        return "***"
    return f"{token[:4]}...{token[-4:]}"


if __name__ == "__main__":
    main()
