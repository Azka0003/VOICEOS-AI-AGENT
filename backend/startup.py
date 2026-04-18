"""
startup.py — Boot-time initialisation
Call seed_chromadb() from main.py's lifespan handler.
Loads chromadb_documents.json into the shared ChromaTool singleton once —
skips docs already present.
"""

import os
from tools.chroma_tool import chroma_tool

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")   # backend/data/
CHROMADB_DOCS_PATH = os.path.join(DATA_DIR, "chromadb_documents.json")


def seed_chromadb():
    """
    Idempotent seed — safe to call on every startup.
    Seeds the shared singleton so all agents see the same data.
    Documents already in the collection are skipped automatically.
    """
    chroma_tool.load_from_json(CHROMADB_DOCS_PATH)
    clients = chroma_tool.list_all_clients()
    print(f"[STARTUP] ChromaDB ready. {len(clients)} client(s) loaded: {clients}")
