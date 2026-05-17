# poltalert

Telegram bot that notifies you when new sports markets are listed on Polymarket.

Polls the [Polymarket Gamma API](https://gamma-api.polymarket.com/events) every
5 minutes, filters to the leagues you care about (NFL, NBA, MLB, soccer/EPL/UCL
by default), and sends a Telegram message for each new event it hasn't seen
before. Seen events are tracked in a local SQLite file so restarts don't
re-spam old listings.

## One-liner quick start

Replace `<TOKEN>` and `<CHAT_ID>` with the values from BotFather and
`getUpdates` (see [Setup](#setup) below). The clone-and-run command works on
all three platforms once Python + git are installed.

**Linux / macOS (bash / zsh):**
```bash
git clone https://github.com/FASHAKING/poltalert.git && cd poltalert && pip install -r requirements.txt && TELEGRAM_BOT_TOKEN=<TOKEN> TELEGRAM_CHAT_ID=<CHAT_ID> python3 bot.py
```

**Termux (Android)** — first install Python + git, then run the same line:
```bash
pkg install -y python git && git clone https://github.com/FASHAKING/poltalert.git && cd poltalert && pip install -r requirements.txt && TELEGRAM_BOT_TOKEN=<TOKEN> TELEGRAM_CHAT_ID=<CHAT_ID> python bot.py
```

**Windows PowerShell:**
```powershell
git clone https://github.com/FASHAKING/poltalert.git; cd poltalert; pip install -r requirements.txt; $env:TELEGRAM_BOT_TOKEN="<TOKEN>"; $env:TELEGRAM_CHAT_ID="<CHAT_ID>"; python bot.py
```

After the first successful run a `seen.db` file is created in the working
directory — keep that file around so the bot doesn't re-notify on restart.
Stop with Ctrl+C.

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
# /etc/systemd/system/poltalert.service
[Unit]
Description=Polymarket sports market notifier
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/poltalert
EnvironmentFile=/opt/poltalert/.env
ExecStart=/opt/poltalert/.venv/bin/python bot.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now poltalert
journalctl -u poltalert -f
```

## How filtering works

The bot calls Gamma's `/events?tag_slug=sports&active=true&closed=false` and
then keeps an event if either:

1. its Polymarket tags include one of the league slugs (e.g. `nfl`, `epl`), or
2. its title contains a league keyword (`NBA`, `Premier League`, etc.) as a
   fallback when tags are missing.

Edit `LEAGUE_TAG_SLUGS` / `LEAGUE_KEYWORDS` in `polymarket.py` to add more
leagues (UFC, tennis, F1, etc.).
