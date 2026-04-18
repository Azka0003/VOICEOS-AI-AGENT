"""
chroma_tool.py — ChromaDB Interface
The identity and history layer for DebtPilot.
All agents read client briefings from here before any LLM call.
Never invented details — if this returns None, HITL is triggered.
"""

import json
import os
from datetime import datetime

import chromadb

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")  # tools/ → backend/data/
CHROMADB_DOCS_PATH = os.path.join(DATA_DIR, "chromadb_documents.json")
COLLECTION_NAME = "debtpilot_clients"


class ChromaTool:
    """
    Wraps the ChromaDB collection for DebtPilot client data.
    Loaded from chromadb_documents.json on startup.
    """

    def __init__(self, persist_directory: str | None = None):
        if persist_directory:
            self.client = chromadb.PersistentClient(path=persist_directory)
        else:
            self.client = chromadb.Client()

        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )

    # ── Startup loader ────────────────────────────────────────────────────────

    def load_from_json(self, chromadb_documents_path: str = CHROMADB_DOCS_PATH):
        """
        Called once on startup. Reads chromadb_documents.json and
        populates the collection. Skips documents that already exist.

        Expected JSON format:
        [
          {
            "id": "unique_doc_id",
            "page_content": "Full briefing text...",
            "metadata": {
              "client": "Raj Traders",
              "contact_name": "Rajesh Kumar",
              "contact_email": "raj@rajtraders.com",
              "contact_phone": "+91-XXXXXXXXXX",
              "risk_score": 42,
              "risk_label": "Medium",
              "dispute_flag": false,
              "contact_count": 1,
              "last_contact_date": "2025-04-01",
              "last_contact_type": "email",
              "next_action": "send_urgent_followup",
              "hitl_required": false
            }
          }
        ]
        """
        if not os.path.exists(chromadb_documents_path):
            print(f"[CHROMA TOOL] Documents file not found: {chromadb_documents_path}")
            return

        with open(chromadb_documents_path, "r", encoding="utf-8") as f:
            documents = json.load(f)

        # Check what's already loaded to avoid duplicates
        existing = set()
        try:
            existing_data = self.collection.get()
            existing = set(existing_data.get("ids", []))
        except Exception:
            pass

        to_add_ids = []
        to_add_docs = []
        to_add_metas = []

        for doc in documents:
            # Support both "doc_id" (new format) and "id" (fallback)
            doc_id = doc.get("doc_id") or doc.get("id") or doc["metadata"]["client"].replace(" ", "_")
            if doc_id in existing:
                continue

            # Normalise metadata — ChromaDB requires str, int, float, or bool
            meta = doc["metadata"].copy()

            # Coerce booleans that may have come in as strings
            for bool_field in ("dispute_flag", "hitl_required"):
                val = meta.get(bool_field)
                if isinstance(val, str):
                    meta[bool_field] = val.lower() == "true"
                elif val is None:
                    meta[bool_field] = False

            # ChromaDB cannot store None values or lists — drop/convert them
            clean_meta = {}
            for k, v in meta.items():
                if v is None:
                    continue
                if isinstance(v, list):
                    clean_meta[k] = ", ".join(str(i) for i in v)
                elif isinstance(v, (str, int, float, bool)):
                    clean_meta[k] = v
                else:
                    clean_meta[k] = str(v)

            to_add_ids.append(doc_id)
            to_add_docs.append(doc["page_content"])
            to_add_metas.append(clean_meta)

        if to_add_ids:
            self.collection.add(
                ids=to_add_ids,
                documents=to_add_docs,
                metadatas=to_add_metas
            )
            print(f"[CHROMA TOOL] Loaded {len(to_add_ids)} documents into collection.")
        else:
            print("[CHROMA TOOL] All documents already loaded.")

    # ── Primary read ──────────────────────────────────────────────────────────

    def get_client_briefing(self, client_name: str) -> dict | None:
        """
        Primary query. Returns the full client briefing dict or None.
        Every agent must call this before making any LLM calls.

        Returns:
        {
            "page_content": str,   # injected directly into LLM prompts
            "metadata": dict       # structured fields (contact, risk, history)
        }
        """
        try:
            result = self.collection.query(
                query_texts=[f"complete briefing for {client_name}"],
                n_results=1,
                where={"client": client_name}
            )

            if not result["documents"] or not result["documents"][0]:
                return None

            page_content = result["documents"][0][0]
            metadata = result["metadatas"][0][0] if result["metadatas"] else {}

            if not page_content:
                return None

            return {
                "page_content": page_content,
                "metadata": metadata
            }

        except Exception as e:
            print(f"[CHROMA TOOL] Query failed for {client_name}: {e}")
            return None

    # ── Metadata update (after call or email) ─────────────────────────────────

    def update_client_metadata(self, client_name: str, updates: dict):
        """
        Updates specific metadata fields after a call or email.
        Does NOT overwrite page_content — that requires refresh_client_briefing().
        Called after every contact event to keep contact_count, last_contact_date,
        and next_action current.
        """
        try:
            result = self.collection.get(where={"client": client_name})
            if not result["ids"]:
                print(f"[CHROMA TOOL] Cannot update — no document found for {client_name}")
                return

            doc_id = result["ids"][0]
            current_meta = result["metadatas"][0] if result["metadatas"] else {}

            # Merge updates into current metadata
            merged = {**current_meta, **updates}
            merged["last_metadata_update"] = datetime.now().isoformat()

            self.collection.update(
                ids=[doc_id],
                metadatas=[merged]
            )

        except Exception as e:
            print(f"[CHROMA TOOL] Metadata update failed for {client_name}: {e}")

    # ── Full briefing refresh (HITL resolution, payment commitment, dispute close) ──

    def refresh_client_briefing(self, client_name: str, new_briefing: str):
        """
        Full document update — replaces page_content.
        Use when:
        - HITL resolves a missing contact (new contact name must appear in briefing)
        - A payment commitment is recorded (briefing should note the date)
        - A dispute is resolved (briefing must reflect the resolution)
        """
        try:
            result = self.collection.get(where={"client": client_name})
            if not result["ids"]:
                print(f"[CHROMA TOOL] Cannot refresh — no document for {client_name}")
                return

            doc_id = result["ids"][0]
            current_meta = result["metadatas"][0] if result["metadatas"] else {}
            current_meta["briefing_last_refreshed"] = datetime.now().isoformat()

            self.collection.update(
                ids=[doc_id],
                documents=[new_briefing],
                metadatas=[current_meta]
            )
            print(f"[CHROMA TOOL] Briefing refreshed for {client_name}.")

        except Exception as e:
            print(f"[CHROMA TOOL] Briefing refresh failed for {client_name}: {e}")

    # ── Semantic search (used by risk_agent for pattern detection) ────────────

    def search_payment_history(self, query: str, n_results: int = 5) -> list[dict]:
        """
        Semantic search across all client documents.
        Used by Risk Agent to find patterns:
          e.g. "clients who previously disputed and then paid"
               "clients who committed to payment but defaulted"

        Returns list of {"client": str, "page_content": str, "metadata": dict}
        """
        try:
            result = self.collection.query(
                query_texts=[query],
                n_results=n_results
            )

            output = []
            for i, doc in enumerate(result["documents"][0]):
                meta = result["metadatas"][0][i] if result["metadatas"] else {}
                output.append({
                    "client": meta.get("client", "unknown"),
                    "page_content": doc,
                    "metadata": meta
                })
            return output

        except Exception as e:
            print(f"[CHROMA TOOL] Semantic search failed: {e}")
            return []

    # ── Utility ───────────────────────────────────────────────────────────────

    def list_all_clients(self) -> list[str]:
        """Returns all client names currently in the collection."""
        try:
            result = self.collection.get()
            return [m.get("client", "") for m in result.get("metadatas", [])]
        except Exception:
            return []

    def client_exists(self, client_name: str) -> bool:
        """Quick existence check without fetching the full document."""
        try:
            result = self.collection.get(where={"client": client_name})
            return bool(result["ids"])
        except Exception:
            return False
