"""Cross-platform bootstrap: install deps, collect creds, launch the bot.

Works on Linux, macOS, Termux (Android), and Windows PowerShell. Detects the
host environment and adapts (pip flags, python binary, paths).

Usage:
    python run.py
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
REQUIREMENTS = ROOT / "requirements.txt"


def detect_env() -> str:
    """Return one of: 'termux', 'windows', 'macos', 'linux'."""
    if os.environ.get("TERMUX_VERSION") or "com.termux" in os.environ.get("PREFIX", ""):
        return "termux"
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, check=check)


def install_deps(env: str) -> None:
    if not REQUIREMENTS.exists():
        print(f"!! missing {REQUIREMENTS}", file=sys.stderr)
        sys.exit(1)

    pip_cmd = [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS)]

    # On modern Debian/Ubuntu (PEP 668) and Termux, pip refuses to install into
    # the system Python without a flag. Try plain first, fall back on failure.
    result = subprocess.run(pip_cmd)
    if result.returncode != 0:
        print(">> retrying with --break-system-packages")
        run(pip_cmd + ["--break-system-packages", "--user"], check=True)


def prompt(label: str, *, secret: bool = False) -> str:
    if secret:
        try:
            import getpass

            return getpass.getpass(f"{label}: ").strip()
        except Exception:
            pass
    return input(f"{label}: ").strip()


def ensure_env_file() -> None:
    """Make sure .env exists and contains the two required vars."""
    existing: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            existing[k.strip()] = v.strip()

    required = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    missing = [k for k in required if not existing.get(k) and not os.environ.get(k)]

    if not missing:
        return

    print()
    print("== First-time setup ==")
    print("Need your Telegram bot credentials. From @BotFather you get the")
    print("token; your chat id comes from https://api.telegram.org/bot<TOKEN>/getUpdates")
    print()
    for key in missing:
        existing[key] = prompt(key, secret=(key == "TELEGRAM_BOT_TOKEN"))
        if not existing[key]:
            print(f"!! {key} is required, aborting.", file=sys.stderr)
            sys.exit(1)

    # Sensible defaults for the rest if the file didn't exist.
    existing.setdefault("POLL_INTERVAL_SECONDS", "300")
    existing.setdefault("LEAGUES", "nfl,nba,mlb,soccer,epl,champions-league")
    existing.setdefault("DB_PATH", "seen.db")
    existing.setdefault("LOG_LEVEL", "INFO")

    ENV_FILE.write_text("\n".join(f"{k}={v}" for k, v in existing.items()) + "\n")
    # Lock down on Unix-like systems; Windows ignores chmod.
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass
    print(f">> wrote {ENV_FILE}")


def launch_bot() -> int:
    bot = ROOT / "bot.py"
    if not bot.exists():
        print(f"!! missing {bot}", file=sys.stderr)
        return 1
    print()
    print(">> starting bot (Ctrl+C to stop)")
    return subprocess.call([sys.executable, str(bot)], cwd=str(ROOT))


def main() -> int:
    env = detect_env()
    print(f">> detected environment: {env}")
    print(f">> python: {sys.executable} ({platform.python_version()})")

    if shutil.which("git") is None:
        print("!! git not found on PATH (only needed if you plan to update)", file=sys.stderr)

    install_deps(env)
    ensure_env_file()
    return launch_bot()


if __name__ == "__main__":
    sys.exit(main())
