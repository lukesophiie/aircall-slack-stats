import os
import base64
import requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Env vars
AIRCALL_API_ID = os.environ["AIRCALL_API_ID"]
AIRCALL_API_TOKEN = os.environ["AIRCALL_API_TOKEN"]
SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]

# SDRs to report (stable Aircall user IDs)
SDRS = [
    {"id": 1811979, "name": "Jeremy"},
    {"id": 1731824, "name": "Dale"},
    {"id": 1731637, "name": "Ryan"},
    {"id": 1731817, "name": "Candice"},
    {"id": 1731818, "name": "Marcia"},
    {"id": 1731822, "name": "Steve"},
]

SDR_IDS = {u["id"] for u in SDRS}
SDR_NAME = {u["id"]: u["name"] for u in SDRS}

TZ = ZoneInfo("Australia/Brisbane")


def auth_header() -> str:
    raw = f"{AIRCALL_API_ID}:{AIRCALL_API_TOKEN}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("utf-8")


def fetch_calls(from_unix: int, page: int, per_page: int = 50) -> dict:
    url = "https://api.aircall.io/v1/calls"
    headers = {"Authorization": auth_header()}
    params = {
        "from": str(from_unix),
        "page": page,
        "per_page": per_page,
        "order": "asc",
    }
    r = requests.get(url, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def post_to_slack(text: str) -> None:
    r = requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=30)
    r.raise_for_status()


def main():
    # Brisbane "today so far" window
    now_local = datetime.now(TZ)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    start_utc = start_local.astimezone(timezone.utc)
    end_utc = now_local.astimezone(timezone.utc)

    from_unix = int(start_utc.timestamp())

    # Stats we’ll compute (outbound only)
    stats = {sid: {"outbound": 0, "connected": 0, "talk_s": 0} for sid in SDR_IDS}

    page = 1
    while True:
        data = fetch_calls(from_unix=from_unix, page=page, per_page=50)
        calls = data.get("calls", [])
        if not calls:
            break

        for c in calls:
            started_at = c.get("started_at")
            if not started_at:
                continue

            started_dt = datetime.fromtimestamp(int(started_at), tz=timezone.utc)
            if started_dt < start_utc or started_dt > end_utc:
                continue

            user = c.get("user") or {}
            uid = user.get("id")
            if uid not in SDR_IDS:
                continue

            # Outbound SDR activity only
            if c.get("direction") != "outbound":
                continue

            stats[uid]["outbound"] += 1

            answered_at = c.get("answered_at")
            ended_at = c.get("ended_at")
            if answered_at:
                stats[uid]["connected"] += 1
                if ended_at and int(ended_at) >= int(answered_at):
                    # talk time = ended_at - answered_at (excludes ringing)
                    stats[uid]["talk_s"] += int(ended_at) - int(answered_at)

        meta = data.get("meta", {})
        if not meta.get("next_page_link"):
            break
        page += 1

    # Build Slack message in your chosen order (SDRS list order)
    date_str = start_local.strftime("%a %d %b")
    upto_str = now_local.strftime("%-I:%M%p").lower() if "%" in "%-I" else now_local.strftime("%I:%M%p").lstrip("0").lower()

    lines = []
    lines.append(f"SDR stats so far today · {date_str} · up to {upto_str} (Brisbane)")
    lines.append("")

    for u in SDRS:
        sid = u["id"]
        name = u["name"]
        outbound = stats[sid]["outbound"]
        connected = stats[sid]["connected"]
        rate = (connected / outbound * 100) if outbound else 0.0
        talk_m = int(stats[sid]["talk_s"] // 60)
        lines.append(f"{name}: {outbound} outbound | {connected} connected ({rate:.0f}%) | {talk_m}m talk")

    post_to_slack("\n".join(lines))


if __name__ == "__main__":
    main()
