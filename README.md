# polyalert

Personal Telegram bot for [Polymarket](https://polymarket.com). Pushes
notifications when new markets are listed in the categories you care
about, and lets you query and search live markets directly from chat.

## What it does

Three things, all driven from one long-running Python process:

1. **New-market notifications** — polls Polymarket every few minutes
   and DMs you when a new event appears for any of your active
   filters (e.g. NFL, NBA, Soccer, Bitcoin, US elections). Already-seen
   events are tracked in SQLite so restarts don't re-spam.
2. **Filter-scoped market lookup** (`/markets`) — list currently
   available markets for one filter, optionally narrowed by a query
   like a team, player, manager, or candidate name.
3. **Free-text search** (`/search`) — substring search across every
   open Polymarket event in any category. Useful when you don't know
   which filter (or whether any filter) covers what you're looking for.

The bot is two-way: filters can be added, removed, and inspected live
from Telegram with no restart.

## One-liner quick start

One self-detecting command per shell family — it figures out the OS /
package manager, installs Python + git + pip deps, clones the repo, and
launches the setup wizard.

**Termux, Linux, macOS, WSL, git-bash** (any POSIX shell):
```sh
sh -c 'SUDO=$(command -v sudo); if [ -n "$PREFIX" ] && command -v pkg >/dev/null 2>&1; then pkg update -y && pkg install -y python git; elif command -v apt-get >/dev/null 2>&1; then $SUDO apt-get update && $SUDO apt-get install -y python3 python3-pip python3-venv git; elif command -v dnf >/dev/null 2>&1; then $SUDO dnf install -y python3 python3-pip git; elif command -v pacman >/dev/null 2>&1; then $SUDO pacman -Sy --noconfirm python python-pip git; elif command -v apk >/dev/null 2>&1; then $SUDO apk add --no-cache python3 py3-pip git; elif command -v brew >/dev/null 2>&1; then brew install python git; else echo "unsupported package manager — install python3 and git manually" >&2; exit 1; fi && git clone https://github.com/FASHAKING/polyalert.git && cd polyalert && PY=$(command -v python3 || command -v python) && $PY -m venv .venv 2>/dev/null && . .venv/bin/activate 2>/dev/null; $PY -m pip install -r requirements.txt && $PY run.py'
```

**Windows PowerShell:**
```powershell
$py = (Get-Command python -All -EA SilentlyContinue | Where-Object { $_.Source -notlike "*WindowsApps*" } | Select-Object -First 1).Source; if (-not $py) { winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements | Out-Null; $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User"); $py = (Get-Command python -All -EA SilentlyContinue | Where-Object { $_.Source -notlike "*WindowsApps*" } | Select-Object -First 1).Source; if (-not $py) { $py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" } }; if (-not (Get-Command git -EA SilentlyContinue)) { winget install -e --id Git.Git --accept-source-agreements --accept-package-agreements | Out-Null; $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User") }; git clone https://github.com/FASHAKING/polyalert.git; cd polyalert; & $py -m venv .venv; & .\.venv\Scripts\python.exe -m pip install -r requirements.txt; & .\.venv\Scripts\python.exe run.py
```

> The one-liner avoids two Windows-specific traps: (1) the
> `WindowsApps\python.exe` Microsoft Store stub that wins over real
> Python in PATH — sidestepped by resolving the real interpreter's full
> path via `Get-Command -All` filtered to exclude `WindowsApps`; and
> (2) PowerShell's default `Restricted` ExecutionPolicy that blocks
> `Activate.ps1` — sidestepped by skipping activation entirely and
> invoking `.\.venv\Scripts\python.exe` directly for both pip install
> and run.py.

The wizard walks you through four steps:

1. **Token** — paste your `@BotFather` token (hidden input). The
   wizard calls Telegram's `getMe` to verify it before continuing.
2. **Chat ID** — auto-detects from your recent messages to the bot
   via `getUpdates`. Send the bot any message first, then pick from
   the discovered list. (Manual entry also accepted.)
3. **Filters** — interactive picker, grouped by category. Toggle
   any combination from sports, crypto, politics, entertainment.
4. **Poll interval** — seconds between Polymarket checks (default
   300 / 5 minutes).

Answers are saved to `.env` (mode `0600`), then the wizard offers to
send a test message before launching the polling loop.

Re-run the wizard with `python run.py --reconfig`. Otherwise subsequent
launches reuse the saved `.env` and go straight to polling.

A `seen.db` file is created after the first poll — keep it around so
restarts don't re-notify. Stop with Ctrl+C.

## Telegram commands

| Command | What it does |
| --- | --- |
| `/status` | Active filters (grouped by category), poll interval, total notified |
| `/filters` | List every supported filter with on/off state |
| `/add <slug>` | Enable a filter. Multi-arg works: `/add nfl bitcoin us-election` |
| `/remove <slug>` | Disable a filter |
| `/search [filter\|category] <query>` | Free-text search across live markets, optionally scoped. Hyphens are normalized, so `/search soccer world-cup` finds World Cup markets even if Polymarket tags them as `world-cup` instead of generic soccer. |
| `/markets <filter> [query]` | List live markets **scoped to one filter**, optionally narrowed. e.g. `/markets world-cup`, `/markets nba chicago bulls`, `/markets soccer manunited`, `/markets nfl tom brady` |
| `/top [filter\|category]` | Show top open markets by 24h volume, optionally scoped to a filter or category. e.g. `/top`, `/top sports`, `/top world-cup` |
| `/watch <keyword>` | Add a custom keyword alert for any new live market matching text such as `/watch world-cup` or `/watch rate cut`. |
| `/watches` | List custom keyword alerts. |
| `/unwatch <keyword>` | Remove a custom keyword alert. |
| `/pause` / `/resume` | Pause or resume notification polling without stopping command handling. |
| `/interval <seconds>` | Change the poll interval live from Telegram. Minimum 30 seconds. |
| `/recent [filter] [day] [count]` | Show events the bot has **already notified you about** (from `seen.db`), grouped by day when spanning multiple days. Args are order-insensitive. Day can be `today`, `yesterday`, `Nd` (last N days), or `YYYY-MM-DD`. e.g. `/recent` (last 10, day-grouped), `/recent today`, `/recent nfl yesterday`, `/recent 7d 50`, `/recent nba 2026-05-15` |
| `/help` | List the commands |

`/leagues` is kept as an alias for `/filters` so old muscle memory still
works. Commands are also registered with Telegram's command menu, so
they autocomplete when you type `/`.

### `/search` vs `/markets` — when to use which

| | `/search` | `/markets` |
| --- | --- | --- |
| Scope | All live Polymarket events, or one optional filter/category scope | One filter's matching markets only |
| Filter argument | Optional first arg when followed by a query | Required first arg |
| Use when | "Find anything about X, maybe within sports/soccer" | "Show me markets that specifically match this filter" |
| Example | `/search soccer world-cup` | `/markets world-cup` |

`/search` ranks by 24h volume and normalizes punctuation/hyphens, so
`world-cup`, `World Cup`, and `worldcup` match the same text. `/markets`
is faster and stricter if you already know the exact filter.

## Available filters

Filters are organized into categories. Each filter has Polymarket tag
slugs it matches plus keyword fallbacks for when tags are missing.

| Category | Filter slugs |
| --- | --- |
| Sports | `nfl`, `nba`, `mlb`, `nhl`, `soccer`, `world-cup`, `epl`, `champions-league`, `mls`, `ufc`, `tennis`, `f1` |
| Crypto | `bitcoin`, `ethereum` |
| Weather | `weather` |
| Economics | `fed-rates` |
| Technology | `ai` |
| Politics | `us-election` |
| Entertainment | `oscars` |

Non-default filters ship turned off; enable any with `/add <slug>`. `world-cup` is included in the default sports watch list so World Cup markets are easier to discover.

## How it works

```
                       +--------------------+
                       |   Polymarket       |
                       |   Gamma API        |
                       +---------+----------+
                                 ^
                  one call per   |  scoped to category's
                  active category|  parent tag
                                 |
+---------------+         +------+-------+         +----------------+
|  Telegram     | <-----  |   polyalert  |  ---->  |   seen.db      |
|  (Bot API)    |  msgs   |   bot.py     |  state  |   (SQLite)     |
+-------+-------+         +------+-------+         +----------------+
        ^                        |
        |  /status /add /remove  |  push: new event found
        |  /search /markets      v
        |                  +-----------+
        +------------------+  user     |
                           +-----------+
```

The main loop runs a 2-second tick:

1. **Drain Telegram updates** — call `getUpdates` with the persisted
   offset, dispatch any pending commands. Messages from chats other
   than the configured `TELEGRAM_CHAT_ID` are silently ignored.
2. **Poll Polymarket** every `POLL_INTERVAL_SECONDS`. Active filters
   are grouped by category and the bot makes one Gamma API call per
   category, scoped to that category's parent tag (e.g.
   `tag_slug=sports`). This avoids pulling the firehose.
3. **Match each fetched event** against the category's active filters and any custom keyword watches.
   An event matches a filter if either:
   1. its Polymarket tags include one of the filter's tag slugs, or
   2. its title contains one of the filter's keyword fallbacks.
   Keyword watches normalize punctuation and hyphens, so `world-cup`, `World Cup`, and `worldcup` can match the same market text.
4. **Skip events already in `seen_events`**. For genuinely new events,
   send a Telegram message and record the event ID. The first time
   the bot ever runs (empty DB), it silently marks the existing
   backlog as seen so you only get notified about *future* listings.
5. **Adding a filter** with `/add` triggers the same backlog-silence
   logic for that filter, so enabling NBA mid-week doesn't send 50
   messages for games that listed yesterday.

`/search`, `/markets`, and `/top` query the Gamma API on demand — they don't
touch `seen.db`. Results order by 24h volume so liquid markets surface
first. `/search` accepts an optional filter/category scope, so
`/search soccer world-cup` searches sports/soccer-adjacent markets for
World Cup text without requiring Polymarket to tag the event as generic
`soccer`.

## Configuration

All via env vars or `.env`:

| Var | Default | Notes |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | *(required)* | From `@BotFather` |
| `TELEGRAM_CHAT_ID` | *(required)* | Integer; auto-detected by the wizard |
| `FILTERS` | `nfl,nba,mlb,soccer,world-cup,epl,champions-league` | Comma-separated. Only seeded on first run — afterwards filters live in `seen.db` and are mutated by `/add` / `/remove`. `LEAGUES` accepted as a legacy alias |
| `POLL_INTERVAL_SECONDS` | `300` | 5 min |
| `DB_PATH` | `seen.db` | SQLite file path |
| `LOG_LEVEL` | `INFO` | `DEBUG` for verbose |

## Manual setup (without the wizard)

Use this if `run.py` doesn't fit your environment (e.g. a Docker image
or a deploy pipeline that handles secrets externally).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
python bot.py
```

To get the values manually:

1. Message [@BotFather](https://t.me/BotFather) on Telegram, send
   `/newbot`, follow the prompts. Save the **bot token**.
2. Start a chat with your new bot and send it any message.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser,
   find `chat.id` in the JSON.

## Testing

The repo uses the Python standard-library `unittest` runner, so no extra
test dependency is required:

```bash
python -m unittest discover -s tests
```

## Running as a service (systemd)

```ini
# /etc/systemd/system/polyalert.service
[Unit]
Description=polyalert — Polymarket new-market notifier
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

## Extending

Adding a new filter is a one-line edit to `filters.py` — append to
`REGISTRY`:

```python
"trump-2028": _f(
    "trump-2028", "politics", "Trump 2028",
    {"trump"},          # Polymarket tag slugs to match
    ("trump",),         # title-keyword fallbacks (lowercase)
),
```

Adding a new category is one entry in `CATEGORIES`:

```python
"weather": Category("weather", "Weather", parent_tag="weather"),
```

Set `parent_tag=None` if the category should be scanned across all
Gamma events (slower; pulls without a tag filter). No other file
needs to change — polling, the wizard, `/add`, `/remove`, `/filters`,
and `/markets` all read from the registry.

## Files

| Path | Purpose |
| --- | --- |
| `bot.py` | Main loop: command dispatch + Polymarket polling |
| `polymarket.py` | Gamma API client: fetch / match / search / list |
| `filters.py` | Filter and category registry |
| `storage.py` | SQLite store (seen events, settings, keyword watches) |
| `telegram_client.py` | Minimal Telegram Bot API wrapper |
| `run.py` | Cross-platform interactive setup wizard |
| `requirements.txt` | `requests`, `python-dotenv` |
| `seen.db` | Runtime state (auto-created, gitignored) |
| `.env` | Credentials and config (gitignored) |

## What it deliberately doesn't do

- **No trading.** It never places a bet — it only notifies and queries.
- **No price/volume alerts.** Only *new listings* and custom keyword-watch
   matches trigger notifications. `/search`, `/markets`, and `/top` show
   volume, but the bot won't ping you when volume changes.
- **No historical search.** Only active, currently-open markets are
   considered.
- **No webhook server.** Uses Telegram long-polling, so no public IP
   or TLS cert needed.
