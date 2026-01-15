import os
import requests
from datetime import datetime

SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]

now = datetime.now().isoformat(timespec="seconds")
requests.post(SLACK_WEBHOOK_URL, json={"text": f"✅ GitHub Actions test message at {now}"}).raise_for_status()
