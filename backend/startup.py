"""
startup.py — Boot-time initialisation
Call seed_chromadb() from main.py's @app.on_event("startup") handler.
Loads chromadb_documents.json into ChromaDB once — skips docs already present.
"""

import os
from tools.chroma_tool import ChromaTool

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")   # backend/data/
CHROMADB_DOCS_PATH = os.path.join(DATA_DIR, "chromadb_documents.json")


def seed_chromadb():
    """
    Idempotent seed — safe to call on every startup.
    Documents already in the collection are skipped automatically.
    """
    chroma = ChromaTool()
    chroma.load_from_json(CHROMADB_DOCS_PATH)
    clients = chroma.list_all_clients()
    print(f"[STARTUP] ChromaDB ready. {len(clients)} client(s) loaded: {clients}")
