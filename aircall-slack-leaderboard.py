import os
import base64
import requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

AIRCALL_API_ID = os.environ["AIRCALL_API_ID"]
AIRCALL_API_TOKEN = os.environ["AIRCALL_API_TOKEN"]
SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]

# Bump this any time you want to confirm which version is running in Slack
SCRIPT_VERSION = "LEADERBOARD_V2"

SDRS = [
    {"id": 1811979, "name": "Candice"},  # If you want, reorder or keep as-is; leaderboard is sorted by talk time anyway
    {"id": 1811979, "name": "Jeremy"},
    {"id": 1731824, "name": "Dale"},
    {"id": 1731637, "name": "Ryan"},
    {"id": 1731817, "name": "Candice"},
    {"id": 1731818, "name": "Marcia"},
    {"id": 1731822, "name": "Steve"},
]

# NOTE: Fix SDRS list above. It currently contains a duplicate ID/name line.
# Replace SDRS with the correct list below (kept here to avoid accidental mistakes):
SDRS = [
    {"id": 1811979, "name": "Jeremy"},
    {"id": 1731824, "name": "Dale"},
    {"id": 1731637, "name": "Ryan"},
    {"id": 1731817, "name": "Candice"},
    {"id": 1731818, "name": "Marcia"},
    {"id": 1731822, "name": "Steve"},
]

SDR_IDS = {u["id"] for u in SDRS}
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
    # Slack incoming webhooks accept simple {"text": "..."} payloads
    r = requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=30)
    r.raise_for_status()


def talk_seconds(call_obj: dict) -> int:
    answered_at = call_obj.get("answered_at")
    ended_at = call_obj.get("ended_at")
    if not answered_at or not ended_at:
        return 0
    try:
        a = int(answered_at)
        e = int(ended_at)
    except (TypeError, ValueError):
        return 0
    return max(0, e - a)


def main() -> None:
    now_local = datetime.now(TZ)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    start_utc = start_local.astimezone(timezone.utc)
    end_utc = now_local.astimezone(timezone.utc)
    from_unix = int(start_utc.timestamp())

    stats = {
        sid: {"out_total": 0, "in_total": 0, "talk_s_total": 0}
        for sid in SDR_IDS
    }

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

            direction = c.get("direction")
            if direction == "outbound":
                stats[uid]["out_total"] += 1
            elif direction == "inbound":
                stats[uid]["in_total"] += 1

            stats[uid]["talk_s_total"] += talk_seconds(c)

        meta = data.get("meta", {})
        if not meta.get("next_page_link"):
            break
        page += 1

    leaderboard = sorted(
        SDRS, key=lambda u: stats[u["id"]]["talk_s_total"], reverse=True
    )
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}

    date_str = start_local.strftime("%a %d %b")
    upto_str = now_local.strftime("%I:%M%p").lstrip("0").lower()

    lines = []
    lines.append(
        f"<!channel> this is the current talk time stats so far · {date_str} · up to {upto_str} (Brisbane) · {SCRIPT_VERSION}"
    )
    lines.append("")

    for i, u in enumerate(leaderboard):
        sid = u["id"]
        name = u["name"]
        medal = medals.get(i, "")

        talk_m = int(stats[sid]["talk_s_total"] // 60)
        out_total = stats[sid]["out_total"]
        in_total = stats[sid]["in_total"]

        lines.append(
            f"{name} {medal} : {talk_m} (mins) | {out_total} outbound | {in_total} inbound calls"
        )

    post_to_slack("\n".join(lines))


if __name__ == "__main__":
    main()
