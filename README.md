# timepiece-watch

Personal watcher for Timepiece Nightclub tickets on FIXR.

It polls the same app API the checkout page uses, then tells you when a Timepiece night has tickets that are not sold out: listed, buyable, or back after a sell-out. It does not buy tickets.

## Setup

Python 3.11+

```bash
cd timepiece-watch
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

```bash
python -m timepiece_watch check
python -m timepiece_watch watch
python -m timepiece_watch watch --once
python -m timepiece_watch --state /tmp/timepiece.json watch
```

| Command | What it does |
|---|---|
| `check` | One-shot status of current Timepiece listings |
| `watch` | Poll until Ctrl+C. First time a night is stored, any ticket that is not sold out / expired alerts; later runs only alert on changes |
| `watch --once` | One watch cycle, then exit |

For a one-off check, use the commands above. To keep polling whenever this laptop is on, use the systemd service below. Do not run `watch` in a terminal at the same time as the service.

## Run as a service (Linux)

This installs a systemd **user** service. It starts when the machine boots, restarts if it crashes, and keeps running until you stop or disable it.

Finish **Setup** and put `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env` first. Then:

```bash
chmod +x deploy/install-user-service.sh
./deploy/install-user-service.sh
```

That copies the unit to `~/.config/systemd/user/timepiece-watch.service`, enables it, starts it, and turns on lingering so it still runs after logout and at boot (not only while you are logged in).

| Command | What it does |
|---|---|
| `systemctl --user status timepiece-watch` | Show whether it is running |
| `journalctl --user -u timepiece-watch -f` | Follow live logs |
| `systemctl --user stop timepiece-watch` | Stop until the next boot (or until you start it again) |
| `systemctl --user start timepiece-watch` | Start it again |
| `systemctl --user restart timepiece-watch` | Restart after `.env` or code changes |
| `systemctl --user disable --now timepiece-watch` | Stop now and do not start at boot |

Sleep/suspend pauses network; the process stays running and continues polling after wake. Shut the laptop down and the watcher stops until the next boot.

After you change `.env` or pull new code, restart:

```bash
systemctl --user restart timepiece-watch
```

## Telegram

Create a bot with [@BotFather](https://t.me/BotFather), then message the bot once and get your chat id from [@userinfobot](https://t.me/userinfobot).

```bash
cp .env.example .env
```

```env
TELEGRAM_BOT_TOKEN=123456:your-token
TELEGRAM_CHAT_ID=123456789
```

For a group, add `@tpnights_bot` as admin, then set `TELEGRAM_CHAT_ID` to the group id (negative). If Telegram upgrades the group to a supergroup, the id changes to `-100...`. The watcher follows that migration, stores the new id in `.state.json`, and retries the send.

Failed Telegram sends keep the previous snapshot so ticket alerts are not marked seen. The log includes Telegram’s error description. Transient errors (429 / 5xx / timeouts) retry; HTML parse errors retry as plain text.

## Low battery

`watch` (including the systemd service) reads Linux `/sys/class/power_supply` on every cycle. If the laptop is at or below 15% and not charging, it sends a Telegram message so you can plug it in and keep the watcher online.

It alerts once, reminds again after 30 minutes if it is still low, and resets after you plug in or charge past 25%. The latch is stored in `.state.json`, so a service restart does not send the same alert again. Desktops with no battery are skipped. Override with:

```env
BATTERY_LOW_PERCENT=15
BATTERY_RECOVER_PERCENT=25
BATTERY_REMINDER_SECONDS=1800
BATTERY_ALERT=0
```

## Alerts

`watch` notifies when something that is **not sold out** (and not expired) appears or changes:

1. **NEW EVENT** — Timepiece listed a night that is not sold out (after a baseline already exists)
2. **ON SALE SOON** — tickets exist but FIXR has not opened them for checkout yet (`not_yet_valid`). Alerts with "Get ready — tickets opening soon!" so you can prepare to buy before they sell out
3. **ON SALE** — quantity buttons are live, including restocks
4. **SOLD FAST** — a slot went from on sale to sold out within 10 minutes of us first seeing it buyable
5. **SOLD OUT** — a night that was listed or on sale is now gone (and did not sell that quickly)

FIXR does not publish remaining stock. Sold-fast is inferred from how soon the slot flipped after it opened. Slots already on sale in `.state.json` without a timestamp are not treated as sold-fast. Override the window with `WATCH_SOLD_FAST_SECONDS=600`, or `0` to disable.

Anything FIXR has not marked sold out or expired is watched. A ticket is buyable only when it is not expired, not sold out, and not `not_yet_valid`.

## Watch intervals

`python -m timepiece_watch watch` always hits the Timepiece venue list, then fetches event checkout details on this cadence:

| Situation | Sleep until next poll | Event detail fetch |
|---|---|---|
| Any ticket **listed** but not buyable yet | ~25s (±15% jitter) | Every cycle |
| Any ticket **on sale** | ~45s | Every cycle |
| All sold out / expired / idle | ~90s | Sold-out nights rechecked every ~3 minutes for restocks |
| HTTP 429 / 403 / timeout / DNS | ~30s, doubling to 30 minutes | Uses `Retry-After` when present. DNS/timeouts retry 3 times first (1s, 2s) for FIXR and Telegram |

Also:

- 0.5s minimum gap between HTTP calls
- Browser-like Chrome `User-Agent`, `Origin`, and `Referer`
- New or not-sold-out listings are always fetched
- Known sold-out nights are not ignored; they are just checked less often so a restock still alerts as **ON SALE**

## What it watches

Venue `2783` (Timepiece). By default only Timepiece as organiser (FIXR sales account `5486166`). Other promoters in that room (for example Silent Disco) are ignored unless you add their sales-account id:

```env
WATCH_ORGANISER_IDS=509037417
```

Timepiece stays watched. Restart the service after changing `.env`.

FIXR has no official public API. This is unofficial and for personal use.

## Tests

```bash
pytest
```

## Browser Automation Platform

A Next.js 16 + Playwright + Upstash Redis headless browser platform for automated reservations and checkout flows is located in [`browser-automation-platform/`](file:///home/codewithyembot/programming/timepiece-watch/browser-automation-platform).

Whenever an event transitions to `ON_SALE`, you can dispatch a trigger webhook via [`timepiece_watch.webhook.send_automation_webhook`](file:///home/codewithyembot/programming/timepiece-watch/src/timepiece_watch/webhook.py) to immediately reserve tickets. See [`browser-automation-platform/README.md`](file:///home/codewithyembot/programming/timepiece-watch/browser-automation-platform/README.md) for full architecture and deployment documentation.

