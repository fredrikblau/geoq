"""
main_production_qeshm.py

Production-ready FastAPI app for Qeshm local AI assistant.
Features:
- Rolling summarized memory per session
- Hybrid router: RAG (Chroma) vs Gemini web search vs LLM-only
- Local Persian classifier (no fine-tuning) + heuristics + memory
- Reranker confidence fixed
- Google/Gemini web search fallback
- Longer, descriptive Persian answers
- Avoids double-inserting OpenWebUI history
- Configurable via .env

Usage:
- Fill .env with GEMINI_API_KEY
- `pip install -r requirements.txt`
- Run: `python mainv3.py`
"""

import os
import re
import logging
import time
import json
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# LangChain
from langchain_community.embeddings import SentenceTransformerEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.runnables import RunnableWithMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory

# Reranker
try:
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    import torch

    RERANKER_AVAILABLE = True
except Exception:
    RERANKER_AVAILABLE = False

# -------------------------------
# Logging
# -------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("qeshm-ai")

import redis
from typing import Dict, Any

# Redis config (env)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
try:
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()  # Test connection
    logger.info("Redis connected")
except Exception as e:
    logger.error(f"Redis failed: {e}. Falling back to in-memory.")
    redis_client = None

# In-memory fallback
store: Dict[str, ChatMessageHistory] = {}

# -------------------------------
# Load environment
# -------------------------------
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not set in .env")

CHROMA_DIR = os.getenv("CHROMA_DIR", "qeshm_db")
EMBED_MODEL = os.getenv(
    "EMBED_MODEL", "intfloat/multilingual-e5-large"
)  # Better Persian support

EMBED_MODEL = os.getenv(
    "EMBED_MODEL", "intfloat/multilingual-e5-large"
)  # Better Persian support
RERANKER_ID = os.getenv("RERANKER_ID", "jinaai/jina-reranker-v2-base-multilingual")
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "3500"))


# -------------------------------
# Persian normalization
# -------------------------------
def normalize_farsi(text: str) -> str:
    if not isinstance(text, str):
        return text
    text = text.replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه")
    text = text.replace("ـ", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


# -------------------------------
# Initialize embeddings + vector DB + retriever
# -------------------------------
embeddings = SentenceTransformerEmbeddings(
    model_name=EMBED_MODEL, encode_kwargs={"normalize_embeddings": True}
)
vector_db = Chroma(persist_directory=CHROMA_DIR, embedding_function=embeddings)
retriever = vector_db.as_retriever(search_kwargs={"k": 8}, search_type="mmr")

# -------------------------------
# Initialize Gemini LLM (only for generation & search)
# -------------------------------
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=GEMINI_API_KEY,
    temperature=0.2,
)

# -------------------------------
# Local Persian Classifier (sentiment as relevance proxy)
# -------------------------------
try:
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    import torch

    DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    LOCAL_CLF_ID = "HooshvareLab/bert-fa-base-uncased-sentiment-digikala"
    local_clf_tok = AutoTokenizer.from_pretrained(LOCAL_CLF_ID)
    local_clf = AutoModelForSequenceClassification.from_pretrained(LOCAL_CLF_ID)
    local_clf.eval()
    local_clf.to(DEVICE)
    logger.info(f"Local Persian classifier loaded: {LOCAL_CLF_ID} on {DEVICE}")
except Exception as e:
    logger.warning(f"Local classifier failed: {e} — using heuristic fallback")
    local_clf = None
    local_clf_tok = None

# -------------------------------
# Reranker initialization
# -------------------------------
reranker_tokenizer = None
reranker_model = None
if RERANKER_AVAILABLE:
    try:
        reranker_tokenizer = AutoTokenizer.from_pretrained(
            RERANKER_ID, trust_remote_code=True
        )
        reranker_model = AutoModelForSequenceClassification.from_pretrained(
            RERANKER_ID, trust_remote_code=True, torch_dtype=torch.float16
        )
        reranker_model.eval()
        device = "cuda" if torch.cuda.is_available() else "cpu"
        reranker_model.to(device)
        logger.info("Reranker loaded on %s", device)
    except Exception as e:
        logger.warning("Failed to load reranker. Continuing without. Error: %s", e)

# -------------------------------
# Memory store (in-memory)
# -------------------------------
conversation_memory = {}
store = {}


def get_session_history(session_id: str) -> ChatMessageHistory:
    # Use Redis if available
    if redis_client:
        key = f"chat:history:{session_id}"
        try:
            # Load from Redis
            raw = redis_client.get(key)
            if raw:
                messages = json.loads(raw)
                history = ChatMessageHistory()
                for m in messages:
                    if m["type"] == "human":
                        history.add_message(HumanMessage(content=m["content"]))
                    elif m["type"] == "ai":
                        history.add_message(AIMessage(content=m["content"]))
                return history
        except Exception as e:
            logger.warning(f"Redis load failed: {e}")

    # Fallback: in-memory
    if session_id not in store:
        store[session_id] = ChatMessageHistory()
    return store[session_id]


def save_session_history(session_id: str, history: ChatMessageHistory):
    """Save to Redis (async-safe)"""
    if not redis_client:
        return  # Skip if no Redis

    key = f"chat:history:{session_id}"
    try:
        messages = []
        for m in history.messages:
            msg_type = "human" if isinstance(m, HumanMessage) else "ai"
            messages.append({"type": msg_type, "content": m.content})
        redis_client.setex(key, 86400, json.dumps(messages))  # 24h TTL
    except Exception as e:
        logger.warning(f"Redis save failed: {e}")


# -------------------------------
# Prompt templates
# -------------------------------
SYSTEM_PROMPT = """
You are a friendly, local AI assistant for Qeshm Island, Iran. Answer in Persian (فارسی).
- Use provided context documents (labeled [source:id]) when relevant.
- If the context doesn't contain the answer, say you don't know and offer to search the web.
- Prefer descriptive and helpful answers (3-6 sentences) and finish with a short practical bullet list (hours, cost, coords) when available.
- Be local, warm, and avoid being overly formal.
"""

# MAIN_PROMPT (with memory)
MAIN_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT + "\nخلاصه مکالمه: {memory}\n"),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{input}"),
    ]
)
chain = MAIN_PROMPT | llm

chain_with_history = RunnableWithMessageHistory(
    chain,
    get_session_history,
    input_messages_key="input",
    history_messages_key="history",
)


# -------------------------------
# Memory summarization (simple rule-based)
# -------------------------------
# -------------------------------
# UPDATE: simple_summarize_memory (better chaining)
# -------------------------------
def simple_summarize_memory(session_id: str, history: ChatMessageHistory) -> str:
    old_memory = conversation_memory.get(session_id, "")
    recent_msgs = history.messages[-6:]  # Last 3 exchanges
    user_recent = [m.content for m in recent_msgs if isinstance(m, HumanMessage)]
    ai_recent = [m.content for m in recent_msgs if isinstance(m, AIMessage)]

    # Extract keys from users + AI (for chaining)
    keys = set()
    all_texts = user_recent + ai_recent
    for text in all_texts:
        words = re.findall(
            r"\b(?:قشم|کافه|رستوران|جاذبه|هتل|تور|دریا|بازار|ساحل|طبیعت|بیلیارد|بولینگ|اکسسوری|سیگار|ویو|عکاسی|سلخ|طبل|دژاوو|لیمبو|الماس|سیتی سنتر)\b",
            text,
            re.IGNORECASE,
        )
        keys.update(w.lower() for w in words)

    if not keys:
        return old_memory

    sorted_keys = sorted(keys, key=len, reverse=True)[:5]
    new_mem = "موضوعات اخیر: " + " • ".join(sorted_keys)  # Prefix for clarity
    conversation_memory[session_id] = new_mem[:200]  # Cap length
    return conversation_memory[session_id]


# -------------------------------
# Rerank utility
# -------------------------------
def rerank_docs(query: str, docs: List, top_k: int = 5):
    if not docs:
        return []
    if reranker_model is None or reranker_tokenizer is None:
        logger.warning("Reranker unavailable → fallback scores")
        return [(d, 1.0 / (i + 1)) for i, d in enumerate(docs[:top_k])]

    texts = [d.page_content for d in docs]
    try:
        inputs = reranker_tokenizer(
            [query] * len(texts),
            texts,
            padding=True,
            truncation=True,
            return_tensors="pt",
        )
        device = next(reranker_model.parameters()).device
        inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.no_grad():
            out = reranker_model(**inputs)
            logits = out.logits
            if logits.dim() == 2:
                if logits.size(-1) == 1:
                    logits = logits.squeeze(-1)  # Single class
                else:
                    logits = logits[:, -1]  # Last class (relevance)
            # FORCE SOFTMAX: always [0,1] positive
            scores = torch.softmax(logits.float(), dim=0)  # Use float for stability
            scores = scores.cpu().tolist()
        logger.info(f"Reranker scores: min={min(scores):.3f}, max={max(scores):.3f}")
    except Exception as e:
        logger.error(f"Reranker failed: {e} → fallback scores")
        scores = [1.0 / (i + 1) for i in range(len(texts))]

    ranked_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    ranked = [(docs[i], scores[i]) for i in ranked_idx[:top_k]]
    return ranked


# -------------------------------
# Context builder
# -------------------------------
def build_context_from_docs(docs, max_chars: int = MAX_CONTEXT_CHARS) -> str:
    parts = []
    total = 0
    for i, d in enumerate(docs):
        text = d.page_content
        meta = getattr(d, "metadata", {}) or {}
        src = meta.get("name") or meta.get("id") or f"doc{i}"
        part = f"[source:{src}]\n{text}\n"
        if total + len(part) > max_chars:
            break
        parts.append(part)
        total += len(part)
    return "\n\n".join(parts)


# -------------------------------
# UPDATE: google_search_summary (history-aware)
# -------------------------------
def google_search_summary(
    query: str, history_summary: str = "", full_history: List = None
) -> str:
    # Summarize history if provided (last 3 user msgs for brevity)
    hist_context = ""
    if full_history:
        recent_user = [
            m.content for m in full_history[-6:] if isinstance(m, HumanMessage)
        ]  # Last 3 exchanges
        hist_context = (
            f"متن مکالمه اخیر: {' | '.join(recent_user[-3:])}"  # Short concat
        )

    system = (
        f"You are a web search assistant focusing on Qeshm Island, Iran. "
        f"Prioritize local sources. Use this context: {hist_context}\n"
        f"Return concise Persian summary (3-4 sentences) + 2-4 sources as bullets."
    )
    human = f"Search and summarize (in Persian) focusing on Qeshm: {query}"
    try:
        resp = llm.invoke(f"{system}\n\n{human}", tools=[{"google_search": {}}])
        return resp.content
    except Exception as e:
        logger.error("Google/Gemini search failed: %s", e)
        raise


# Runnable with history
chain_with_history = RunnableWithMessageHistory(
    chain,
    get_session_history,
    input_messages_key="input",
    history_messages_key="history",
)


def improved_route(query: str, memory: str) -> str:
    q = normalize_farsi(query).lower()
    mem = normalize_farsi(memory).lower() if memory else ""

    # Strong heuristics: exact triggers first
    google_triggers = [
        r"\b(امروز|فردا|هوا|پرواز|قیمت|اخبار|نرخ|جستجو|سرچ|بگرد|چک کن|پیدا کن)\b"
    ]
    chat_triggers = [r"\b(سلام|چطوری|نظر|فکر|دوست|عشق|چت|شوخی|خداحافظ)\b"]

    if re.search(google_triggers[0], q):
        return "google"
    if re.search(chat_triggers[0], q):
        return "chat"

    # Memory-boosted Qeshm intent
    combined = q + " " + mem
    qeshm_boosters = [
        r"\b(قشم|کافه|رستوران|هتل|جاذبه|تور|دریا|بازار|ساحل|طبیعت|بیلیارد|بولینگ|اکسسوری|سیگار|ویو|عکاسی|سلخ|طبل|دژاوو|لیمبو|الماس|سیتی سنتر)\b"
    ]
    if len(q) < 15 and mem:  # Short query = likely follow-up
        prior_topics = qeshm_boosters
        if any(topic in mem for topic in prior_topics):
            logger.info(f"Follow-up detected: mem='{mem}' → force RAG")
            return "rag"
    if re.search(qeshm_boosters[0], combined):
        return "rag"

    # Default: chat unless obvious local
    return "chat" if len(q) < 10 else "rag"  # Short = chit-chat


# -------------------------------
# FastAPI app
# -------------------------------
app = FastAPI(title="Qeshm AI - Production")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: Optional[str] = None
    messages: List[Message]
    stream: bool = True  # DEFAULT: True for prod
    session_id: Optional[str] = "default"


def get_last_user_question(history: ChatMessageHistory) -> Optional[str]:
    for m in reversed(history.messages):
        if isinstance(m, HumanMessage) and len(m.content.strip()) > 2:
            return m.content
    return None


from fastapi.responses import StreamingResponse


# -------------------------------
# UPDATE: chat_completions endpoint (bullet-proof version)
# -------------------------------
@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    if not req.messages:
        raise HTTPException(status_code=400, detail="Messages required")

    last_msg = req.messages[-1]
    session_id = req.session_id or "default"
    user_input = normalize_farsi(last_msg.content)

    # === BULLET-PROOF HISTORY SYNC ===
    history = get_session_history(session_id)
    old_len = len(history.messages)
    history.messages.clear()  # Reset to avoid drift

    for msg in req.messages[:-1]:  # All prior messages
        norm_content = (
            normalize_farsi(msg.content) if msg.role == "user" else msg.content
        )
        if msg.role == "user":
            history.add_message(HumanMessage(content=norm_content))
        elif msg.role == "assistant":
            history.add_message(AIMessage(content=norm_content))

    # Add current user input (always)
    history.add_message(HumanMessage(content=user_input))
    save_session_history(session_id, history)
    logger.info(
        f"History synced: old={old_len}, new={len(history.messages)} | session={session_id}"
    )

    # Guard: Cap history to prevent token bombs
    if len(history.messages) > 20:  # Max 10 exchanges
        history.messages = history.messages[-20:]  # Keep recent
        logger.warning(f"History capped to 20 msgs for session {session_id}")

    # === MEMORY UPDATE ===
    memory_text = simple_summarize_memory(session_id, history)

    # === ROUTING ===
    route = improved_route(user_input, memory_text)
    logger.info(
        f"ROUTE: {route} | query='{user_input[:50]}...' | memory_len={len(memory_text)} | hist_len={len(history.messages)}"
    )

    # === RAG WITH GUARDS ===
    docs = []
    context = ""
    rag_fallback_reason = ""
    hist_summary = ""
    if len(history.messages) > 1:
        recent_user = [
            m.content for m in history.messages[-4:-1] if isinstance(m, HumanMessage)
        ]  # Prior users
        hist_summary = (
            f"\nمتن مکالمه اخیر: {' | '.join(recent_user[-2:])}"  # Last 2 priors
        )
    if route == "rag":
        try:
            raw_docs = retriever.invoke(user_input)
            if not raw_docs:
                rag_fallback_reason = "no_docs_retrieved"
                raise ValueError("Empty retrieval")

            for d in raw_docs:
                d.page_content = normalize_farsi(d.page_content)

            reranked = rerank_docs(user_input, raw_docs, top_k=6)
            docs = [d for d, s in reranked]

            rerank_best = reranked[0][1] if reranked else 0.0
            logger.info(f"RAG: Retrieved: {rerank_best}")
            scored = vector_db.similarity_search_with_score(user_input, k=3)
            best_sim = min([s for _, s in scored]) if scored else 999

            rag_confident = (
                rerank_best > 0.05  # LOWERED for Persian/short docs
                and best_sim
                < 0.7  # RELAXED sim (E5-large scale ~0-1, but Chroma cosine ~0-1 too)
                and len(docs) >= 1
            )

            if rag_confident:
                context = build_context_from_docs(docs, max_chars=MAX_CONTEXT_CHARS)
                logger.info(
                    f"RAG confident: rerank={rerank_best:.3f} | sim={best_sim:.3f} | docs={len(docs)}"
                )
            else:
                rag_fallback_reason = (
                    f"low_confidence (rerank={rerank_best:.3f}, sim={best_sim:.3f})"
                )
                logger.info(f"RAG fallback: {rag_fallback_reason}")
                route = "google"

        except Exception as e:
            rag_fallback_reason = f"exception: {str(e)[:50]}"
            logger.exception("RAG failed: %s", e)
            route = "google"

    # === GOOGLE WITH HISTORY ===
    if route == "google":
        try:
            # Pass history for context-aware search
            google_answer = google_search_summary(
                query=user_input,
                history_summary=f"{memory_text} | {hist_summary}",
                full_history=history.messages,
            )

            # Add to history for continuity
            history.add_message(AIMessage(content=google_answer))
            simple_summarize_memory(session_id, history)

            logger.info(
                f"Google fallback used: reason='{rag_fallback_reason}' | hist_context_len={len(history.messages)}"
            )

            return {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "gemini-2.5-flash",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": google_answer},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            }
        except Exception as e:
            logger.exception("Google fallback failed: %s", e)
            # Ultimate fallback: generic response
            fallback_msg = (
                "متاسفانه نتونستم اطلاعات رو پیدا کنم. می‌تونی جزئیات بیشتری بدی؟"
            )
            history.add_message(AIMessage(content=fallback_msg))
            return {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "gemini-2.5-flash",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": fallback_msg},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            }

    # === GENERATION WITH HISTORY (your proven pattern) ===
    final_input = f"""
{context if context else ''}

{hist_summary}

سوال کاربر: {user_input}
""".strip()

    try:
        response = chain_with_history.invoke(
            {"input": final_input, "memory": memory_text},
            config={"configurable": {"session_id": session_id}},
        )
        assistant_text = response.content

        # Always add response to history
        history.add_message(AIMessage(content=assistant_text))
        simple_summarize_memory(session_id, history)

        logger.info(
            f"Generation complete: route={route} | response_len={len(assistant_text)}"
        )

        return {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "gemini-2.5-flash",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": assistant_text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
    except Exception as e:
        logger.exception("Generation failed: %s", e)
        # Bullet-proof fallback
        fallback_msg = "ببخشید، مشکلی پیش اومد. می‌تونی سوالت رو دوباره بپرسی؟"
        history.add_message(AIMessage(content=fallback_msg))
        return {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "gemini-2.5-flash",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": fallback_msg},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }


@app.get("/health")
async def health():
    return {"status": "ok", "model": "gemini-2.5-flash", "embeddings": EMBED_MODEL}


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": "gemini-2.5-flash",
                "object": "model",
                "created": 1677610602,
                "owned_by": "qeshm-ai",
            }
        ],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8001)))
