"""lineage_logger.py — Append-only agent decision log."""
import json, os
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
LOG_PATH = os.path.join(DATA_DIR, "lineage_log.json")
os.makedirs(DATA_DIR, exist_ok=True)

class LineageLogger:
    def log(self, entry: dict):
        try:
            logs = []
            if os.path.exists(LOG_PATH):
                with open(LOG_PATH, "r") as f:
                    logs = json.load(f)
            entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
            logs.append(entry)
            with open(LOG_PATH, "w") as f:
                json.dump(logs, f, indent=2)
        except Exception as e:
            print(f"[LINEAGE LOGGER] Error: {e}")

    def get_recent(self, n: int = 50) -> list:
        try:
            if os.path.exists(LOG_PATH):
                with open(LOG_PATH, "r") as f:
                    logs = json.load(f)
                return logs[-n:]
        except Exception:
            pass
        return []

lineage_logger = LineageLogger()
