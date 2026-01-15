import os
import base64
import requests
import random
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

AIRCALL_API_ID = os.environ["AIRCALL_API_ID"]
AIRCALL_API_TOKEN = os.environ["AIRCALL_API_TOKEN"]
SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]

SCRIPT_VERSION = "LEADERBOARD_V3"

TZ = ZoneInfo("Australia/Brisbane")

SDRS = [
    {"id": 1811979, "name": "Jeremy"},
    {"id": 1731824, "name": "Dale"},
    {"id": 1731637, "name": "Ryan"},
    {"id": 1731817, "name": "Candice"},
    {"id": 1731818, "name": "Marcia"},
    {"id": 1731822, "name": "Steve"},
    {"id": 1731823, "name": "Jake (UK)"},
]

# Exempt from "sad face last place" rule
SAD_FACE_EXEMPT_IDS = {1731823}

SDR_IDS = {u["id"] for u in SDRS}


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

    # Leaderboard sorted by talk time desc
    leaderboard = sorted(
        SDRS, key=lambda u: stats[u["id"]]["talk_s_total"], reverse=True
    )
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}

    # Determine who should get the sad face:
    # lowest-ranked person among NON-exempt IDs
    eligible = [u for u in leaderboard if u["id"] not in SAD_FACE_EXEMPT_IDS]
    sad_face_id = eligible[-1]["id"] if eligible else None

    date_str = start_local.strftime("%a %d %b")
    upto_str = now_local.strftime("%I:%M%p").lstrip("0").lower()

    lines = []
    lines.append(
        f"<!channel> this is the current talk time stats so far today (Brisbane day) · {date_str} · up to {upto_str} (Brisbane) · {SCRIPT_VERSION}"
    )
    lines.append("")

    for i, u in enumerate(leaderboard):
        sid = u["id"]
        name = u["name"]
        medal = medals.get(i, "")

        talk_m = int(stats[sid]["talk_s_total"] // 60)
        out_total = stats[sid]["out_total"]
        in_total = stats[sid]["in_total"]

        line = f"{name} {medal} : {talk_m} (mins) | {out_total} outbound | {in_total} inbound calls"

        # Bold top 3
        if i < 3:
            line = f"*{line}*"

        # Underline + sad face for last place (excluding exempt IDs)
        if sad_face_id is not None and sid == sad_face_id:
            line = f"_{line} 😢_"

        lines.append(line)

    post_to_slack("\n".join(lines))

def pick_top_by_talk(leaderboard: list[dict], stats: dict) -> tuple[str, int]:
    top = leaderboard[0]
    top_name = top["name"]
    top_mins = int(stats[top["id"]]["talk_s_total"] // 60)
    return top_name, top_mins


def pick_top_by_outbound(leaderboard: list[dict], stats: dict) -> tuple[str, int]:
    top = max(leaderboard, key=lambda u: stats[u["id"]]["out_total"])
    return top["name"], int(stats[top["id"]]["out_total"])


def pick_lowest_with_dials_gt_zero(
    leaderboard: list[dict],
    stats: dict,
    exempt_ids: set[int],
) -> tuple[str, int] | None:
    eligible = [
        u for u in leaderboard
        if u["id"] not in exempt_ids and stats[u["id"]]["out_total"] > 0
    ]
    if not eligible:
        return None
    low = min(eligible, key=lambda u: stats[u["id"]]["talk_s_total"])
    return low["name"], int(stats[low["id"]]["talk_s_total"] // 60)


def coaching_line(
    leaderboard: list[dict],
    stats: dict,
    sad_face_exempt_ids: set[int],
) -> str:
    top_name, top_mins = pick_top_by_talk(leaderboard, stats)
    top_dials_name, top_dials = pick_top_by_outbound(leaderboard, stats)
    low = pick_lowest_with_dials_gt_zero(leaderboard, stats, sad_face_exempt_ids)

    low_name = low[0] if low else None

    # 10 variations, some talk-time shoutouts, some dials shoutouts, some gentle nudge
    templates = [
        lambda: f"🔥 Big shoutout to {top_name} for {top_mins} mins on the phone so far. Let’s keep the energy up and finish strong 💪",
        lambda: f"🏆 {top_name} is leading talk time with {top_mins} mins. Love the hustle team, keep stacking quality convos 📞✨",
        lambda: f"🚀 Pace-setter today is {top_name}: {top_mins} mins talk time. Keep the momentum rolling into the afternoon 🌤️",
        lambda: f"📣 Huge effort from {top_name} with {top_mins} mins. Everyone aim for one more solid block of calls 🎯",
        lambda: f"📞 Love the dial activity from {top_dials_name}: {top_dials} outbound. Let’s turn the volume into booked wins ✅",
        lambda: f"🥇 {top_name} out front on talk time ({top_mins} mins). Team, stay consistent and keep pushing 📈",
        lambda: f"🌟 Shoutout {top_name} for {top_mins} mins talk time so far. Great work, let’s have a big rest of the day 🙌",
        lambda: (
            f"👀 We can lift the pace a bit. {low_name}, let’s pick it up from here and get a strong run home 💥"
            if low_name else
            f"✅ Looking good so far. Keep the calls tight, the notes clean, and the energy high 🔥"
        ),
        lambda: (
            f"⏱️ Quick reset: {top_name} leads talk time ({top_mins} mins). If you’re on the board today, push for a few more quality dials 📞💪"
            if low_name else
            f"⏱️ Quick reset: {top_name} leads talk time ({top_mins} mins). Keep building momentum 📞💪"
        ),
    ]

    return random.choice(templates)()

if __name__ == "__main__":
    main()
