import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not set in .env")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CHROMA_DIR = os.getenv("CHROMA_DIR", "qeshm_db")
EMBED_MODEL = os.getenv("EMBED_MODEL", "intfloat/multilingual-e5-large")
RERANKER_ID = os.getenv("RERANKER_ID", "jinaai/jina-reranker-v2-base-multilingual")
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "3500"))
PORT = int(os.getenv("PORT", 8001))
