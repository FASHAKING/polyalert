"""Cross-platform interactive bootstrap.

Detects the host OS (Linux / macOS / Termux / Windows), installs deps,
walks the user through a setup wizard (token, chat id, leagues, poll
interval), saves the answers to .env, then launches the bot.

Usage:
    python run.py            # interactive wizard if .env missing/incomplete
    python run.py --reconfig # force re-prompt even if .env exists
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
REQUIREMENTS = ROOT / "requirements.txt"

DEFAULT_FILTERS = ["nfl", "nba", "mlb", "soccer", "epl", "champions-league"]


# ---------- environment detection ----------

def detect_env() -> str:
    if os.environ.get("TERMUX_VERSION") or "com.termux" in os.environ.get("PREFIX", ""):
        return "termux"
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


# ---------- pretty prompts ----------

def _input(prompt_text: str) -> str:
    try:
        return input(prompt_text)
    except EOFError:
        print()
        sys.exit(130)
    except KeyboardInterrupt:
        print("\n!! cancelled")
        sys.exit(130)


def ask(label: str, *, default: str | None = None, secret: bool = False, allow_empty: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        if secret:
            import getpass
            try:
                value = getpass.getpass(f"{label}{suffix}: ").strip()
            except Exception:
                value = _input(f"{label}{suffix}: ").strip()
        else:
            value = _input(f"{label}{suffix}: ").strip()
        if not value and default is not None:
            return default
        if value or allow_empty:
            return value
        print("   (required)")


def ask_yes_no(label: str, *, default: bool = True) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    while True:
        v = _input(f"{label}{suffix}: ").strip().lower()
        if not v:
            return default
        if v in ("y", "yes"):
            return True
        if v in ("n", "no"):
            return False
        print("   (please answer y or n)")


def ask_int(label: str, *, default: int, minimum: int = 1) -> int:
    while True:
        v = _input(f"{label} [{default}]: ").strip()
        if not v:
            return default
        try:
            i = int(v)
            if i < minimum:
                print(f"   (must be >= {minimum})")
                continue
            return i
        except ValueError:
            print("   (please enter an integer)")


def ask_filters(current: list[str] | None = None) -> list[str]:
    # Lazy import so dependency-install step in main() can run first.
    import filters as flt  # type: ignore

    keys: list[str] = []
    print()
    print("Pick the filters to watch. Enter numbers separated by commas, or")
    print("press Enter to keep the current selection (marked with *). Filters")
    print("can be added/removed live via Telegram with /add and /remove.")
    print()

    selected = set(current or DEFAULT_FILTERS)
    counter = 0
    for cat_slug, fs in flt.by_category().items():
        if not fs:
            continue
        print(f"  -- {flt.category_label(cat_slug)} --")
        for f in fs:
            counter += 1
            keys.append(f.slug)
            mark = "*" if f.slug in selected else " "
            print(f"   [{mark}] {counter}. {f.label}  ({f.slug})")
        print()

    while True:
        raw = _input("Selection (e.g. 1,2,3) [keep]: ").strip()
        if not raw:
            return sorted(selected, key=lambda s: keys.index(s) if s in keys else len(keys))
        try:
            picks = {int(x.strip()) for x in raw.split(",") if x.strip()}
            if not picks or any(p < 1 or p > len(keys) for p in picks):
                raise ValueError
            return [keys[p - 1] for p in sorted(picks)]
        except ValueError:
            print(f"   (enter comma-separated numbers between 1 and {len(keys)})")


# ---------- dependency install ----------

def install_deps() -> None:
    if not REQUIREMENTS.exists():
        print(f"!! missing {REQUIREMENTS}", file=sys.stderr)
        sys.exit(1)

    print(">> installing Python dependencies...")
    pip_cmd = [sys.executable, "-m", "pip", "install", "-q", "-r", str(REQUIREMENTS)]
    result = subprocess.run(pip_cmd)
    if result.returncode != 0:
        print(">> retrying with --break-system-packages --user")
        subprocess.run(pip_cmd + ["--break-system-packages", "--user"], check=True)


# ---------- Telegram helpers ----------

def telegram_api(token: str, method: str, params: dict | None = None, timeout: int = 15) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def validate_token(token: str) -> tuple[bool, str]:
    """Return (ok, message). On success message is the bot's @username."""
    try:
        resp = telegram_api(token, "getMe")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "token rejected (401) — check for typos"
        return False, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return False, f"network error: {e.reason}"
    except Exception as e:
        return False, f"unexpected error: {e}"
    if not resp.get("ok"):
        return False, resp.get("description", "unknown error")
    me = resp.get("result", {})
    return True, f"@{me.get('username', '?')}"


def discover_chat_ids(token: str) -> list[tuple[int, str]]:
    """Return [(chat_id, label), ...] from recent updates. Empty if none."""
    try:
        resp = telegram_api(token, "getUpdates", {"timeout": 0})
    except Exception:
        return []
    if not resp.get("ok"):
        return []
    seen: dict[int, str] = {}
    for upd in resp.get("result", []):
        msg = upd.get("message") or upd.get("channel_post") or upd.get("edited_message")
        if not msg:
            continue
        chat = msg.get("chat", {})
        cid = chat.get("id")
        if cid is None or cid in seen:
            continue
        ctype = chat.get("type", "?")
        name = (
            chat.get("title")
            or chat.get("username")
            or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
            or "(unnamed)"
        )
        seen[cid] = f"{name} [{ctype}]"
    return list(seen.items())


# ---------- wizard ----------

def parse_env_file() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    out: dict[str, str] = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def write_env(values: dict[str, str]) -> None:
    body = "\n".join(f"{k}={v}" for k, v in values.items()) + "\n"
    ENV_FILE.write_text(body)
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass
    print(f">> saved {ENV_FILE}")


def wizard(existing: dict[str, str]) -> dict[str, str]:
    print()
    print("=" * 60)
    print("  polyalert — interactive setup")
    print("=" * 60)
    print()
    print("Step 1/4 — Telegram bot token")
    print("  Get one from @BotFather on Telegram: send /newbot and follow")
    print("  the prompts. The token looks like 123456:ABC-DEF...")
    print()

    token = existing.get("TELEGRAM_BOT_TOKEN", "")
    while True:
        token_in = ask("Telegram bot token", default=token or None, secret=True)
        ok, info = validate_token(token_in)
        if ok:
            print(f"   token OK — bot identity: {info}")
            token = token_in
            break
        print(f"   ✗ {info}")
        if not ask_yes_no("   try again?", default=True):
            sys.exit(1)

    print()
    print("Step 2/4 — Telegram chat ID (where notifications get sent)")
    print("  Send any message to your bot first, then we can auto-detect it.")
    print()

    chat_id = existing.get("TELEGRAM_CHAT_ID", "")
    if ask_yes_no("Auto-detect chat ID from recent messages?", default=True):
        while True:
            chats = discover_chat_ids(token)
            if chats:
                print()
                print("   Found these chats:")
                for i, (cid, label) in enumerate(chats, 1):
                    print(f"     {i}. {cid}  —  {label}")
                print()
                pick = ask("Pick a number (or type a chat ID manually)", default="1")
                if pick.isdigit() and 1 <= int(pick) <= len(chats):
                    chat_id = str(chats[int(pick) - 1][0])
                    break
                if pick.lstrip("-").isdigit():
                    chat_id = pick
                    break
                print("   (invalid choice)")
            else:
                print("   No messages found. Open Telegram, send any message to")
                print("   your bot, then come back.")
                if not ask_yes_no("   retry?", default=True):
                    chat_id = ask("Chat ID", default=chat_id or None)
                    break
    else:
        chat_id = ask("Chat ID", default=chat_id or None)

    print(f"   chat ID set to: {chat_id}")

    print()
    print("Step 3/4 — Filters to watch")
    raw = existing.get("FILTERS") or existing.get("LEAGUES") or ",".join(DEFAULT_FILTERS)
    current_filters = [s.strip() for s in raw.split(",") if s.strip()]
    selected = ask_filters(current_filters)
    import filters as flt  # type: ignore
    print(f"   watching: {', '.join(flt.label_for(s) for s in selected)}")

    print()
    print("Step 4/4 — Poll interval")
    interval_default = int(existing.get("POLL_INTERVAL_SECONDS", "300"))
    interval = ask_int("Seconds between polls", default=interval_default, minimum=30)

    return {
        "TELEGRAM_BOT_TOKEN": token,
        "TELEGRAM_CHAT_ID": chat_id,
        "FILTERS": ",".join(selected),
        "POLL_INTERVAL_SECONDS": str(interval),
        "DB_PATH": existing.get("DB_PATH", "seen.db"),
        "LOG_LEVEL": existing.get("LOG_LEVEL", "INFO"),
    }


def send_test_message(token: str, chat_id: str) -> bool:
    try:
        resp = telegram_api(
            token,
            "sendMessage",
            {"chat_id": chat_id, "text": "polyalert is connected and watching for new sports markets."},
        )
        return bool(resp.get("ok"))
    except Exception as e:
        print(f"   test message failed: {e}")
        return False


# ---------- entry ----------

def launch_bot() -> int:
    bot = ROOT / "bot.py"
    if not bot.exists():
        print(f"!! missing {bot}", file=sys.stderr)
        return 1
    print()
    print(">> starting bot (Ctrl+C to stop)")
    print()
    return subprocess.call([sys.executable, str(bot)], cwd=str(ROOT))


def main() -> int:
    reconfig = "--reconfig" in sys.argv

    env = detect_env()
    print(f">> environment: {env}  |  python {platform.python_version()}")

    if shutil.which("git") is None:
        print("!! git not on PATH (only needed for updates)")

    install_deps()

    existing = parse_env_file()
    needs_wizard = reconfig or not existing.get("TELEGRAM_BOT_TOKEN") or not existing.get("TELEGRAM_CHAT_ID")

    if needs_wizard:
        values = wizard(existing)
        write_env(values)
        if ask_yes_no("\nSend a test message to confirm Telegram delivery?", default=True):
            if send_test_message(values["TELEGRAM_BOT_TOKEN"], values["TELEGRAM_CHAT_ID"]):
                print("   ✓ test message sent — check Telegram.")
            else:
                print("   ✗ couldn't send. Double-check the chat ID.")
    else:
        print(">> using existing .env (pass --reconfig to re-run the wizard)")

    return launch_bot()


if __name__ == "__main__":
    sys.exit(main())
