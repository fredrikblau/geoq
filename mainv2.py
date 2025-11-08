"""
main_production_qeshm.py

Production-ready FastAPI app for Qeshm local AI assistant.
Features:
- Rolling summarized memory per session (updated after each turn)
- Hybrid router: RAG (Chroma) vs Gemini web search vs LLM-only
- Reranker (optional, Jina) integration
- Google/Gemini web search prompt focused on Qeshm
- Longer, descriptive Persian answers by default
- Avoids double-inserting OpenWebUI history (only appends last message)
- Configurable via environment variables

Usage:
- Fill .env with GEMINI_API_KEY and optionally other overrides
- `pip install -r requirements.txt` (see comment at top for packages)
- Run: `python main_production_qeshm.py`

Notes:
- ChatMessageHistory is in-memory. For persistence use Redis/DB.
- Adjust EMBED_MODEL to e5-large if you have GPU.

"""

import os
import re
import logging
import time
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# LangChain-ish primitives (modern v0.2+ style used earlier in this thread)
from langchain_community.embeddings import SentenceTransformerEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import (
    ChatPromptTemplate,
    MessagesPlaceholder,
    PromptTemplate,
)
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.runnables import RunnableWithMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory

# Optional reranker
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

# -------------------------------
# Load environment
# -------------------------------
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not set in .env")

CHROMA_DIR = os.getenv("CHROMA_DIR", "qeshm_db")
EMBED_MODEL = os.getenv(
    "EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
RERANKER_ID = os.getenv("RERANKER_ID", "jinaai/jina-reranker-v2-base-multilingual")
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "3500"))
MEMORY_SUMMARY_TOKENS = int(os.getenv("MEMORY_SUMMARY_TOKENS", "200"))


# -------------------------------
# Persian normalization util
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
embeddings = SentenceTransformerEmbeddings(model_name=EMBED_MODEL)
vector_db = Chroma(persist_directory=CHROMA_DIR, embedding_function=embeddings)
retriever = vector_db.as_retriever(search_kwargs={"k": 8}, search_type="mmr")

# -------------------------------
# Initialize Gemini LLM (used for routing, memory summarization, web search and final answers)
# -------------------------------
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=GEMINI_API_KEY,
    temperature=0.2,
)

# -------------------------------
# Optional reranker initialization
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
        logger.warning(
            "Failed to load reranker (%s). Continuing without rerank. Error: %s",
            RERANKER_ID,
            e,
        )
        reranker_tokenizer = None
        reranker_model = None

# -------------------------------
# Memory store (rolling summaries)
# -------------------------------
# session_id -> memory string (short Persian bullet list or short paragraph)
conversation_memory = {}

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

# The main user-facing prompt: memory will be injected.
MAIN_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT + "\nConversation Memory:\n{memory}\n"),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{input}"),
    ]
)
chain = MAIN_PROMPT | llm

# Memory summarization prompt (short Persian bullets)
MEMORY_PROMPT = PromptTemplate.from_template(
    """
You are a memory updater for a Qeshm travel assistant. Given the recent conversation history and the existing short memory,
return an updated short memory in Persian (حداکثر 5 بند کوتاه). Keep it focused on: user's goals, topics asked about, entities mentioned (places), and outstanding follow-ups. Use short bullets.

History:
{history}

Existing memory:
{memory}

Return ONLY the updated memory text (no explanations).
"""
)

# Router prompt: return rag / google / chat
ROUTER_PROMPT = PromptTemplate.from_template(
    """
Decide EXACTLY one word: rag, google, or chat.

- rag: user likely asks about local Qeshm info (places, restaurants, transport, local tips) that should be answered from the local database first.
- google: user asks for up-to-date info, weather, flights, news, prices, or anything likely not covered in local DB.
- chat: casual conversation / small talk / opinions / general info that doesn't require retrieval.

Return only one word (rag / google / chat).
User query: {query}
"""
)

# -------------------------------
# Runnable with history
# -------------------------------
store = {}  # session_id -> ChatMessageHistory


def get_session_history(session_id: str) -> ChatMessageHistory:
    if session_id not in store:
        store[session_id] = ChatMessageHistory()
    return store[session_id]


chain_with_history = RunnableWithMessageHistory(
    chain,
    get_session_history,
    input_messages_key="input",
    history_messages_key="history",
)

# -------------------------------
# Utility: memory updater
# -------------------------------


def summarize_memory(session_id: str, history: ChatMessageHistory) -> str:
    """Call the LLM to update short rolling memory for the session.
    We feed only the last N messages to keep cost low.
    """
    old_memory = conversation_memory.get(session_id, "")
    # take last 8 messages for context
    snippets = []
    for m in history.messages[-8:]:
        role = "U" if isinstance(m, HumanMessage) else "A"
        snippets.append(f"{role}: {m.content}")
    hist_text = "\n".join(snippets)
    prompt = MEMORY_PROMPT.format(history=hist_text, memory=old_memory)
    try:
        # deterministic short memory
        resp = llm.invoke(prompt)
        mem = resp.content.strip()
        # small safety: truncate to 1000 chars
        mem = mem[:1000]
        conversation_memory[session_id] = mem
        return mem
    except Exception as e:
        logger.warning("Memory summarization failed: %s", e)
        return old_memory


# -------------------------------
# Utility: rerank
# -------------------------------


def rerank_docs(query: str, docs: List, top_k: int = 5):
    if reranker_model is None or reranker_tokenizer is None:
        return [(d, 1.0 / (i + 1)) for i, d in enumerate(docs[:top_k])]

    texts = [d.page_content for d in docs]
    inputs = reranker_tokenizer(
        [query] * len(texts), texts, padding=True, truncation=True, return_tensors="pt"
    )
    device = next(reranker_model.parameters()).device
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        out = reranker_model(**inputs)
        logits = out.logits
        if logits.dim() == 2 and logits.size(-1) == 1:
            scores = logits.squeeze(-1)
        elif logits.dim() == 2:
            scores = torch.softmax(logits, dim=1)[:, -1]
        else:
            scores = logits
        scores = scores.cpu().tolist()
    ranked_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    return [(docs[i], scores[i]) for i in ranked_idx[:top_k]]


# -------------------------------
# Utility: build context
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
# Google/Gemini search helper (focus on Qeshm)
# -------------------------------


def google_search_summary(query: str) -> str:
    """Ask Gemini to search the web but prefer results about Qeshm island.
    The function instructs Gemini to prioritize local Qeshm sources and to
    return a Persian summary + short sources list.
    """
    system = (
        "You are a web search assistant focusing on Qeshm Island, Iran. "
        "When searching, prioritize local sources about Qeshm (news, local blogs, tourism pages, official pages). "
        "Return a concise Persian summary (3-4 sentences) and then 2-4 short sources listed as bullets with short descriptions. "
        "If the query is ambiguous, infer the most likely Qeshm-related interpretation and say what you assumed."
    )
    human = f"Search and summarize (in Persian) focusing on Qeshm: {query}"
    try:
        resp = llm.invoke(f"{system}\n\n{human}")
        return resp.content
    except Exception as e:
        logger.error("Google/Gemini search failed: %s", e)
        raise


# -------------------------------
# Router: heuristic + LLM
# -------------------------------

GOOGLE_KEYWORDS = [
    "امروز",
    "فردا",
    "هوا",
    "پرواز",
    "قیمت",
    "اخبار",
    "نرخ",
    "برنامه",
    "رویداد",
]
FOLLOW_UP_PHRASES = [
    "جستجو کن",
    "سرچ کن",
    "بگرد",
    "چک کن",
    "پیدا کن",
    "بیار",
    "نشون بده",
]


def heuristic_route(query: str) -> Optional[str]:
    q = query.lower()
    for kw in GOOGLE_KEYWORDS:
        if kw in q:
            return "google"
    # simple follow-up detection
    for ph in FOLLOW_UP_PHRASES:
        if ph in q:
            return "followup_search"
    return None


def llm_route_query(query: str) -> str:
    try:
        resp = llm.invoke(ROUTER_PROMPT.format(query=query))
        route = resp.content.strip().lower().split()[0]
        if route not in {"rag", "google", "chat"}:
            return "rag"
        return route
    except Exception as e:
        logger.warning("Router LLM failed: %s — defaulting to rag", e)
        return "rag"


# -------------------------------
# FastAPI app
# -------------------------------
app = FastAPI(title="Qeshm AI - Production (Memory+RAG+Search)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------------
# Schemas
# -------------------------------
class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: Optional[str] = None
    messages: List[Message]
    stream: Optional[bool] = False
    session_id: Optional[str] = "default"


# -------------------------------
# Helper to find last meaningful user message in history
# -------------------------------


def get_last_user_question(history: ChatMessageHistory) -> Optional[str]:
    for m in reversed(history.messages):
        if isinstance(m, HumanMessage) and len(m.content.strip()) > 2:
            return m.content
    return None


# -------------------------------
# Chat endpoint
# -------------------------------
@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    if not req.messages:
        raise HTTPException(status_code=400, detail="Messages required")

    # Only append the last incoming user message to avoid duplication from OpenWebUI
    last_msg = req.messages[-1]
    session_id = req.session_id or "default"
    history = get_session_history(session_id)

    user_input = normalize_farsi(last_msg.content)

    # Add last user message to memory/history
    if last_msg.role == "user":
        history.add_message(HumanMessage(content=user_input))
    else:
        # If last message is not user (edgecase), still proceed
        user_input = user_input

    # Update rolling memory (short summary) BEFORE routing so router can use it
    memory_text = summarize_memory(session_id, history)

    # Decide route: heuristic first, then LLM router
    heur = heuristic_route(user_input)
    if heur == "followup_search":
        # replace with the last meaningful user question (prior to 'جستجو کن')
        last_topic = get_last_user_question(history)
        # find previous meaningful question (skip the current follow-up command)
        # reversed history includes the current command as last; find the first different earlier user message
        prev_topic = None
        found_current = False
        for m in reversed(history.messages):
            if isinstance(m, HumanMessage):
                if m.content == user_input and not found_current:
                    found_current = True
                    continue
                if found_current and len(m.content.strip()) > 2:
                    prev_topic = m.content
                    break
        if prev_topic:
            logger.info("Follow-up search detected. Using prev topic: %s", prev_topic)
            user_input = prev_topic
            route = "google"
        else:
            route = "google"
    elif heur is not None:
        route = heur
    else:
        # LLM router
        route = llm_route_query(user_input)

    logger.info(
        "Routing for session=%s query='%s' -> %s", session_id, user_input, route
    )

    # RAG path
    docs = []
    rag_confident = False
    if route == "rag":
        try:
            raw_docs = retriever.invoke(user_input)
            for d in raw_docs:
                d.page_content = normalize_farsi(d.page_content)
            reranked = rerank_docs(user_input, raw_docs, top_k=6)
            docs = [d for d, s in reranked]
            # simple confidence: at least one doc with length > 80 chars
            if docs and any(len(d.page_content.strip()) > 80 for d in docs):
                rag_confident = True
            else:
                rag_confident = False
        except Exception as e:
            logger.exception("RAG retrieval error: %s", e)
            rag_confident = False

        if not rag_confident:
            # fallback to google
            logger.info(
                "RAG not confident, falling back to Google search for: %s", user_input
            )
            try:
                google_answer = google_search_summary(user_input)
                # save assistant message
                history.add_message(AIMessage(content=google_answer))
                # update memory after assistant reply
                summarize_memory(session_id, history)
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
                logger.warning("Google fallback failed: %s", e)
                # continue to LLM-only
                route = "chat"

    if route == "google":
        try:
            google_answer = google_search_summary(user_input)
            history.add_message(AIMessage(content=google_answer))
            summarize_memory(session_id, history)
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
            logger.exception("Google search failed: %s", e)
            raise HTTPException(status_code=500, detail="Search failed")

    # At this point: route == 'rag' with docs OR route == 'chat' (LLM only)
    if docs:
        context = build_context_from_docs(docs, max_chars=MAX_CONTEXT_CHARS)
        final_input = f"{context}\n\nسوال کاربر: {user_input}"
    else:
        final_input = f"سوال کاربر: {user_input}"

    # Inject memory into prompt invocation
    memory_for_prompt = conversation_memory.get(session_id, "")
    try:
        response = chain_with_history.invoke(
            {"input": final_input, "memory": memory_for_prompt},
            config={"configurable": {"session_id": session_id}},
        )

        # Save assistant message
        assistant_text = response.content
        history.add_message(AIMessage(content=assistant_text))

        # Update memory AFTER assistant reply
        summarize_memory(session_id, history)

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
        logger.exception("LLM chain invocation failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------
# Health & models endpoints
# -------------------------------
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


@app.post("/v1/messages")
async def messages(req: ChatRequest):
    # Agent UI sends messages in the same format as Chat UI
    return await chat_completions(req)


# -------------------------------
# Run (dev)
# -------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8001)))
