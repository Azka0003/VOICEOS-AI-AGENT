import asyncio
import uuid
from typing import Dict, Any, List

class HITLManager:
    def __init__(self):
        self.pending_actions: Dict[str, Dict[str, Any]] = {}

    async def wait_for_human(self, checkpoint_type: str, data: Any) -> Any:
        checkpoint_id = f"{checkpoint_type}_{uuid.uuid4().hex[:6]}"
        event = asyncio.Event()
        
        self.pending_actions[checkpoint_id] = {
            "id": checkpoint_id,
            "type": checkpoint_type,
            "event": event,
            "data": data,
            "response": None,
            "status": "pending"
        }
        
        print(f"\n[HITL PAUSE] ID: {checkpoint_id} | Type: {checkpoint_type}")
        await event.wait()
        
        result = self.pending_actions[checkpoint_id]["response"]
        self.pending_actions[checkpoint_id]["status"] = "resolved"
        return result

    def resolve_checkpoint(self, checkpoint_id: str, response: Any):
        if checkpoint_id in self.pending_actions:
            self.pending_actions[checkpoint_id]["response"] = response
            self.pending_actions[checkpoint_id]["event"].set()
            print(f"[HITL RESOLVED] {checkpoint_id}")
        else:
            print(f"[HITL ERROR] {checkpoint_id} not found.")

    def get_all_pending(self) -> List[Dict]:
        return [
            {"id": info["id"], "type": info["type"], "data": info["data"]}
            for info in self.pending_actions.values()
            if info["status"] == "pending"
        ]

hitl_manager = HITLManager()