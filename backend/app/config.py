from pathlib import Path
import os
from dotenv import load_dotenv
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

KNOWLEDGE_DIR = BASE_DIR / "knowledge"
ROUTER_EXAMPLES_PATH = BASE_DIR / "data" / "router_examples.json"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
ROUTE_THRESHOLD = float(os.getenv("ROUTE_THRESHOLD", "0.70"))
MARGIN_THRESHOLD = float(os.getenv("MARGIN_THRESHOLD", "0.20"))
TOP_K = int(os.getenv("TOP_K", "3"))
