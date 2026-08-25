import os
from dotenv import load_dotenv

load_dotenv()

# --- Gemini API ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# Importing the package must remain safe for local development, tests, and
# health checks. The chat path reports a useful configuration error at runtime.

# --- Redis ---
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# --- Vector DB & Models ---
CHROMA_DIR = os.getenv("CHROMA_DIR", "qeshm_db")
EMBED_MODEL = os.getenv("EMBED_MODEL", "intfloat/multilingual-e5-large")
RERANKER_ID = os.getenv("RERANKER_ID", "jinaai/jina-reranker-v2-base-multilingual")

# --- RAG & History ---
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "3500"))
MAX_HISTORY_LEN = int(os.getenv("MAX_HISTORY_LEN", "20"))  # Max messages to keep

# --- Server ---
PORT = int(os.getenv("PORT", "8001"))

# Comma-separated origins, for example: https://geoq.ir,http://localhost:3000
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]


# 🆕 NEW: Self-Correction Configuration
MAX_REFINEMENT_ITERATIONS = 1  # Configurable max retries (default: 2)
ENABLE_QUALITY_GATE = True  # Toggle self-correction on/off
QUALITY_GATE_THRESHOLD = 0.5  # Minimum quality score (0-1) to accept answer
SHOW_RETRY_ATTEMPTS = False  # If True, show "I'm refining my answer..." to user

# Refinement strategies
REFINEMENT_STRATEGIES = {
    "missing_contact_info": "google_search",
    "too_vague": "better_rag_query",
    "wrong_context": "google_search",
    "incomplete": "add_more_context",
    "off_topic": "google_search",
}
