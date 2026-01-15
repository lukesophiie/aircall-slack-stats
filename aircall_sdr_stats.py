import os
import base64
import requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

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


def talk_seconds(call_obj: dict) -> int:
    """
    Talk time excludes ringing:
    - If answered_at exists and ended_at exists, use ended_at - answered_at
    """
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


def main():
    # Brisbane "today so far" window
    now_local = datetime.now(TZ)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    start_utc = start_local.astimezone(timezone.utc)
    end_utc = now_local.astimezone(timezone.utc)
    from_unix = int(start_utc.timestamp())

    # Stats
    stats = {
        sid: {
            "outbound": 0,
            "inbound": 0,
            "total_calls": 0,
            "talk_s_total": 0,
        }
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
                stats[uid]["outbound"] += 1
            elif direction == "inbound":
                stats[uid]["inbound"] += 1

            stats[uid]["total_calls"] += 1
            stats[uid]["talk_s_total"] += talk_seconds(c)

        meta = data.get("meta", {})
        if not meta.get("next_page_link"):
            break
        page += 1

    # Leaderboard sorted by total talk time desc
    leaderboard = sorted(
        SDR_IDS,
        key=lambda sid: stats[sid]["talk_s_total"],
        reverse=True,
    )

    medals = {0: "🥇", 1: "🥈", 2: "🥉"}

    date_str = start_local.strftime("%a %d %b")
    upto_str = now_local.strftime("%I:%M%p").lstrip("0").lower()

    lines = []
    lines.append(f"SDR leaderboard (talk time) · {date_str} · up to {upto_str} (Brisbane)")
    lines.append("")

    for i, sid in enumerate(leaderboard):
        medal = medals.get(i, "  ")
        name = SDR_NAME.get(sid, str(sid))

        talk_m = int(stats[sid]["talk_s_total"] // 60)
        inbound = stats[sid]["inbound"]
        outbound = stats[sid]["outbound"]
        total_calls = stats[sid]["total_calls"]

        lines.append(
            f"{medal} {name} | Talk: {talk_m}m | In: {inbound} | Out: {outbound} | Total: {total_calls}"
        )

    post_to_slack("\n".join(lines))


if __name__ == "__main__":
    main()
