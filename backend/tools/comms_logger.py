"""comms_logger.py — Append-only communication history logger."""
import json, os
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
COMMS_PATH = os.path.join(DATA_DIR, "client_comms.json")
os.makedirs(DATA_DIR, exist_ok=True)

class CommsLogger:
    def log(self, client: str, entry: dict):
        try:
            data = {}
            if os.path.exists(COMMS_PATH):
                with open(COMMS_PATH, "r") as f:
                    data = json.load(f)
            if client not in data:
                data[client] = []
            entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
            data[client].append(entry)
            with open(COMMS_PATH, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[COMMS LOGGER] Error: {e}")

    def get(self, client: str) -> list:
        try:
            if os.path.exists(COMMS_PATH):
                with open(COMMS_PATH, "r") as f:
                    return json.load(f).get(client, [])
        except Exception:
            pass
        return []

comms_logger = CommsLogger()
