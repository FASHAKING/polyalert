# polyalert

Telegram bot that notifies you when new sports markets are listed on Polymarket.

Polls the [Polymarket Gamma API](https://gamma-api.polymarket.com/events) every
5 minutes, filters to the leagues you care about (NFL, NBA, MLB, soccer/EPL/UCL
by default), and sends a Telegram message for each new event it hasn't seen
before. Seen events are tracked in a local SQLite file so restarts don't
re-spam old listings.

## One-liner quick start

`run.py` is a cross-platform interactive wizard. Pick the one-liner for
your platform — it installs every dependency (Python, git, pip packages),
clones the repo, and launches the setup wizard.

**Termux (Android):**
```sh
pkg update -y && pkg install -y python git && git clone https://github.com/FASHAKING/polyalert.git && cd polyalert && pip install -r requirements.txt && python run.py
```

**Linux (Debian/Ubuntu):**
```sh
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git && git clone https://github.com/FASHAKING/polyalert.git && cd polyalert && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt && python run.py
```

**Linux (Fedora/RHEL):**
```sh
sudo dnf install -y python3 python3-pip git && git clone https://github.com/FASHAKING/polyalert.git && cd polyalert && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt && python run.py
```

**Linux (Arch):**
```sh
sudo pacman -Sy --noconfirm python python-pip git && git clone https://github.com/FASHAKING/polyalert.git && cd polyalert && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt && python run.py
```

**Windows PowerShell:**
```powershell
winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements; winget install -e --id Git.Git --accept-source-agreements --accept-package-agreements; $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User"); git clone https://github.com/FASHAKING/polyalert.git; cd polyalert; python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt; python run.py
```

The wizard walks you through four steps:

1. **Token** — paste the token from `@BotFather` (hidden input). The
   wizard calls Telegram's `getMe` to verify it before continuing.
2. **Chat ID** — auto-detects from your recent messages to the bot. Send
   the bot any message first, then pick from the list. (Manual entry
   also accepted.)
3. **Leagues** — interactive picker. NFL, NBA, MLB, Soccer, EPL, UCL.
4. **Poll interval** — seconds between Polymarket checks (default 300).

Answers are saved to `.env` (mode `0600`), then the wizard offers to
send a test message before starting the polling loop.

Re-run the wizard at any time with `python run.py --reconfig`. Otherwise
subsequent launches reuse the saved `.env` and go straight to polling.

A `seen.db` file is created after the first poll — keep it around so
restarts don't re-notify. Stop with Ctrl+C.

## Telegram commands

Once the bot is running, message it directly to inspect and change
filters live (no restart needed):

| Command | What it does |
| --- | --- |
| `/status` | Show active leagues, poll interval, total notified count |
| `/leagues` | List every supported league with on/off state |
| `/add <slug>` | Enable a league. Multi-arg works: `/add nfl nba ufc` |
| `/remove <slug>` | Disable a league |
| `/help` | List the commands |

Available league slugs: `nfl`, `nba`, `mlb`, `nhl`, `soccer`, `epl`,
`champions-league`, `mls`, `ufc`, `tennis`, `f1`. Add more by editing
`LEAGUE_TAG_SLUGS` in `polymarket.py`.

When you `/add` a league, the bot silently marks its currently-listed
events as "seen" so you only get notified about *future* listings — no
backlog spam. Filter changes are persisted to `seen.db`, so they survive
restarts. The bot only responds to messages from the chat ID you
configured during setup; everyone else is ignored.

## Setup

### 1. Create a Telegram bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram, send `/newbot`,
   follow the prompts. Save the **bot token** it gives you.
2. Start a chat with your new bot (send it any message).
3. Get your **chat ID**: open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser, find the
   `chat.id` field in the JSON.

### 2. Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: paste TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
```

### 3. Run

```bash
python bot.py
```

On first run the bot marks all currently-listed matching events as "seen"
without notifying, so you only get pinged for *future* listings. Stop with
Ctrl+C.

## Configuration

All via env vars (or `.env`):

| Var | Default | Notes |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | *(required)* | From BotFather |
| `TELEGRAM_CHAT_ID` | *(required)* | Your personal chat ID |
| `LEAGUES` | `nfl,nba,mlb,soccer,epl,champions-league` | Comma-separated. Slugs defined in `polymarket.py` |
| `POLL_INTERVAL_SECONDS` | `300` | 5 min |
| `DB_PATH` | `seen.db` | SQLite file path |
| `LOG_LEVEL` | `INFO` | `DEBUG` for verbose |

## Running as a service (systemd)

```ini
# /etc/systemd/system/polyalert.service
[Unit]
Description=Polymarket sports market notifier
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/polyalert
EnvironmentFile=/opt/polyalert/.env
ExecStart=/opt/polyalert/.venv/bin/python bot.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now polyalert
journalctl -u polyalert -f
```

## How filtering works

The bot calls Gamma's `/events?tag_slug=sports&active=true&closed=false` and
then keeps an event if either:

1. its Polymarket tags include one of the league slugs (e.g. `nfl`, `epl`), or
2. its title contains a league keyword (`NBA`, `Premier League`, etc.) as a
   fallback when tags are missing.

Edit `LEAGUE_TAG_SLUGS` / `LEAGUE_KEYWORDS` in `polymarket.py` to add more
leagues (UFC, tennis, F1, etc.).
