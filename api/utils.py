import re
import json
import logging
import torch
from typing import List, Dict, Tuple
from langchain_community.embeddings import SentenceTransformerEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from langchain_community.chat_message_histories import ChatMessageHistory
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from langchain_core.runnables import RunnableWithMessageHistory
from langchain_core.documents import Document
import redis
from config import (
    GEMINI_API_KEY,
    REDIS_URL,
    CHROMA_DIR,
    EMBED_MODEL,
    RERANKER_ID,
    MAX_CONTEXT_CHARS,
)

# Import prompts from the centralized prompt file
from prompts import get_main_prompt, SUMMARIZE_PROMPT
from pythonjsonlogger import jsonlogger

# --- Logging Setup ---
# Set up a structured logger
logger = logging.getLogger("qeshm-ai")
logger.setLevel(logging.DEBUG)  # Set to DEBUG to capture all log levels
logger.propagate = False  # Prevent duplicate logs in root logger

if not logger.handlers:
    # Use a standard StreamHandler
    stream_handler = logging.StreamHandler()

    # OLD FORMATTER:
    # formatter = logging.Formatter(
    #     "%(asctime)s %(name)s %(levelname)s %(message)s [Module: %(module)s | Func: %(funcName)s | Line: %(lineno)d]"
    # )

    # --- 2. REPLACE the old formatter with this: ---
    # NEW JSON FORMATTER:
    # This formatter will automatically pick up all standard log fields
    # AND everything you pass in the 'extra' dictionary.
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s %(module)s %(funcName)s %(lineno)d"
    )
    # --- End of replacement ---

    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

logger.info("Logging configured")

# --- Service Initialization ---

# Redis Connection
try:
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()
    logger.info(f"Redis connected successfully to {REDIS_URL}")
except Exception as e:
    logger.error(
        f"Redis connection failed: {e}. Falling back to in-memory store.",
        exc_info=True,
    )
    redis_client = None

# In-memory fallbacks
in_memory_store: Dict[str, ChatMessageHistory] = {}
in_memory_conversation_memory: Dict[str, str] = {}


# Embeddings
try:
    embeddings = SentenceTransformerEmbeddings(
        model_name=EMBED_MODEL, encode_kwargs={"normalize_embeddings": True}
    )
    logger.info(f"Embedding model loaded: {EMBED_MODEL}")
except Exception as e:
    logger.critical(f"Failed to load embedding model: {e}", exc_info=True)
    raise

# Vector DB (Chroma)
try:
    vector_db = Chroma(persist_directory=CHROMA_DIR, embedding_function=embeddings)
    retriever = vector_db.as_retriever(search_kwargs={"k": 8}, search_type="mmr")
    logger.info(f"Chroma DB loaded from {CHROMA_DIR}. Retriever configured.")
except Exception as e:
    logger.critical(f"Failed to load Chroma DB: {e}", exc_info=True)
    raise

# LLM (Gemini)
try:
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash", google_api_key=GEMINI_API_KEY, temperature=0.2
    )
    logger.info("Gemini LLM initialized")
except Exception as e:
    logger.critical(f"Failed to initialize Gemini LLM: {e}", exc_info=True)
    raise

# Reranker
reranker_tokenizer = None
reranker_model = None
try:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    reranker_tokenizer = AutoTokenizer.from_pretrained(
        RERANKER_ID, trust_remote_code=True
    )
    reranker_model = AutoModelForSequenceClassification.from_pretrained(
        RERANKER_ID, trust_remote_code=True, torch_dtype=torch.float16
    )
    reranker_model.eval()
    reranker_model.to(device)
    logger.info(f"Reranker model loaded: {RERANKER_ID} on {device}")
except Exception as e:
    logger.warning(
        f"Failed to load reranker model: {e}. Reranking will be disabled.",
        exc_info=True,
    )


# --- Utility Functions ---


def normalize_farsi(text: str) -> str:
    """Cleans and normalizes Persian text."""
    if not isinstance(text, str):
        return text
    text = text.replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه").replace("ـ", "")
    return re.sub(r"\s+", " ", text).strip()


# --- History & Memory Management ---


def get_session_history(session_id: str) -> ChatMessageHistory:
    """Retrieves chat history from Redis or in-memory store."""
    if redis_client:
        key = f"chat:history:{session_id}"
        try:
            raw_data = redis_client.get(key)
            if raw_data:
                messages_data = json.loads(raw_data)
                history = ChatMessageHistory()
                for m in messages_data:
                    if m["type"] == "human":
                        history.add_message(HumanMessage(content=m["content"]))
                    elif m["type"] == "ai":
                        history.add_message(AIMessage(content=m["content"]))
                logger.debug(f"Loaded history from Redis: {session_id}")
                return history
        except Exception as e:
            logger.warning(
                f"Redis GET failed for {key}: {e}. Falling back to in-memory.",
                exc_info=True,
            )

    # Fallback to in-memory store
    if session_id not in in_memory_store:
        logger.debug(f"Creating new in-memory history for: {session_id}")
        in_memory_store[session_id] = ChatMessageHistory()
    else:
        logger.debug(f"Loaded history from in-memory: {session_id}")

    return in_memory_store[session_id]


def save_session_history(session_id: str, history: ChatMessageHistory):
    """Saves chat history to Redis (if available)."""
    if not redis_client:
        logger.debug(f"In-memory store updated for: {session_id}")
        return  # Using in-memory store

    key = f"chat:history:{session_id}"
    try:
        messages = [
            {
                "type": "human" if isinstance(m, HumanMessage) else "ai",
                "content": m.content,
            }
            for m in history.messages
        ]
        redis_client.setex(key, 86400, json.dumps(messages))  # 24-hour expiry
        logger.debug(f"Saved history to Redis: {session_id}")
    except Exception as e:
        logger.error(f"Redis SET failed for {key}: {e}", exc_info=True)


def simple_keyword_summary(history: ChatMessageHistory) -> str:
    """Original simple regex-based summarizer (as a fallback)."""
    recent_msgs = history.messages[-6:]
    user_recent = [m.content for m in recent_msgs if isinstance(m, HumanMessage)]
    ai_recent = [m.content for m in recent_msgs if isinstance(m, AIMessage)]

    all_texts = user_recent + ai_recent
    keys = set()
    for text in all_texts:
        words = re.findall(
            r"\b(?:قشم|کافه|رستوران|جاذبه|هتل|تور|دریا|بازار|ساحل|طبیعت|بیلیارد|بولینگ|اکسسوری|سیگار|ویو|عکاسی|سلخ|طبل|دژاوو|لیمبو|الماس|سیتی سنتر)\b",
            text,
            re.IGNORECASE,
        )
        keys.update(w.lower() for w in words)

    if not keys:
        return ""

    sorted_keys = sorted(keys, key=len, reverse=True)[:5]
    summary = "موضوعات اخیر: " + " • ".join(sorted_keys)
    logger.debug(f"Generated simple keyword summary: {summary}")
    return summary


def llm_summarize_memory(session_id: str, history: ChatMessageHistory) -> str:
    """Generates a concise summary of the conversation using an LLM."""

    # Use simple summary for very short histories
    if len(history.messages) <= 6:
        logger.debug("History too short, using simple keyword summary")
        summary = simple_keyword_summary(history)
        in_memory_conversation_memory[session_id] = summary
        return summary

    history_text = "\n".join(
        [
            f"{'User' if isinstance(m, HumanMessage) else 'AI'}: {m.content}"
            for m in history.messages
        ]
    )

    try:
        logger.debug(f"Attempting LLM summary for session: {session_id}")
        summary_chain = SUMMARIZE_PROMPT | llm
        summary = summary_chain.invoke({"history_text": history_text}).content

        summary_cap = summary[:300]  # Cap to avoid bloat
        in_memory_conversation_memory[session_id] = summary_cap
        logger.info(
            f"LLM summary generated for {session_id}",
            extra={"summary": summary_cap, "original_len": len(summary)},
        )
        return summary_cap

    except Exception as e:
        logger.warning(
            f"LLM summary failed: {e}. Falling back to simple summary.",
            exc_info=True,
        )
        # Fallback to simple keyword-based summary
        summary = simple_keyword_summary(history)
        in_memory_conversation_memory[session_id] = summary
        return summary


# --- RAG & Search ---


def rerank_docs(
    query: str, docs: List[Document], top_k: int = 5
) -> List[Tuple[Document, float]]:
    """Reranks retrieved documents using the reranker model."""
    if not docs:
        logger.debug("Rerank: received no documents")
        return []

    if reranker_model is None or reranker_tokenizer is None:
        logger.warning("Reranker unavailable. Returning top_k docs with dummy scores.")
        return [(d, 1.0 / (i + 1)) for i, d in enumerate(docs[:top_k])]

    texts = [d.page_content for d in docs]
    logger.debug(f"Reranking {len(texts)} docs for query: {query}")

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
                # Handle different model output shapes
                logits = logits.squeeze(-1) if logits.size(-1) == 1 else logits[:, -1]
            # Use softmax for a 0-1 score distribution
            scores = torch.softmax(logits.float(), dim=0).cpu().tolist()

        logger.debug(
            f"Reranker scores calculated",
            extra={
                "min": min(scores),
                "max": max(scores),
                "avg": sum(scores) / len(scores),
            },
        )

    except Exception as e:
        logger.error(
            f"Reranker failed: {e}. Falling back to dummy scores.", exc_info=True
        )
        scores = [1.0 / (i + 1) for i in range(len(texts))]

    # Combine docs with scores and sort
    ranked_results = sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)

    top_results = ranked_results[:top_k]
    logger.info(
        "Reranking complete",
        extra={
            "query": query,
            "initial_doc_count": len(docs),
            "final_doc_count": len(top_results),
            "top_score": top_results[0][1] if top_results else 0.0,
        },
    )
    return top_results


def build_context_from_docs(
    docs: List[Document], max_chars: int = MAX_CONTEXT_CHARS
) -> str:
    """Builds a single context string from a list of documents."""
    parts = []
    total_chars = 0
    doc_sources = []

    for i, d in enumerate(docs):
        text = d.page_content
        meta = getattr(d, "metadata", {}) or {}
        # Find a source identifier
        src = meta.get("name") or meta.get("source") or meta.get("id") or f"doc{i}"
        doc_sources.append(src)

        part = f"[source:{src}]\n{text}\n"

        if total_chars + len(part) > max_chars:
            logger.warning(
                "Context truncated",
                extra={
                    "max_chars": max_chars,
                    "total_chars": total_chars,
                    "docs_included": len(parts),
                    "docs_total": len(docs),
                },
            )
            break

        parts.append(part)
        total_chars += len(part)

    context = "\n\n".join(parts)
    logger.info(
        "Built RAG context",
        extra={
            "doc_count": len(parts),
            "total_chars": total_chars,
            "max_chars": max_chars,
            "doc_sources": doc_sources,
            "context": context,  # Log preview, not full context
        },
    )
    return context


def google_search_summary(
    query: str,
    history_summary: str = "",
    full_history: List[BaseMessage] = None,
    rag_context: str = "",
) -> str:
    """
    Generates a summary using Google Search, with context from history and RAG.
    """
    logger.info(
        "Google Search invoked",
        extra={
            "query": query,
            "history_summary_len": len(history_summary),
            "rag_context_len": len(rag_context),
            "full_history_len": len(full_history) if full_history else 0,
        },
    )

    # Build context from recent history
    hist_context = ""
    if full_history:
        recent_msgs = full_history[-8:]  # Last 4 exchanges
        formatted_history = []
        for m in recent_msgs:
            role = "کاربر" if isinstance(m, HumanMessage) else "دستیار"
            formatted_history.append(f"{role}: {m.content}")
        hist_context = (
            f"تاریخچه مکالمه اخیر (برای ادامه دادن استفاده کن):\n"
            + "\n".join(formatted_history)
        )

    # Add RAG context if available (from low-confidence RAG)
    rag_prompt_part = (
        f"\nاطلاعات محلی کم اطمینان (برای تایید یا تکمیل استفاده کن): {rag_context}\n"
        if rag_context
        else ""
    )

    # System prompt for the search LLM
    system_prompt = f"""You are a web search assistant focusing on Qeshm Island, Iran. Prioritize local sources.
Use the provided conversation history to contextualize and refine your search query if needed.
History summary: {history_summary}
{hist_context}
{rag_prompt_part}
اگر از جستجو استفاده کردی، در پاسخ بگو 'اطلاعات محلی مطمئن نبود، پس جستجو کردم'.
Return concise Persian summary (3-4 sentences) + 2-4 sources as bullets.
Always continue naturally from the history—do not repeat or ignore it."""

    human_prompt = f"Search and summarize (in Persian) focusing on Qeshm: {query}"

    full_llm_prompt = f"{system_prompt}\n\n{human_prompt}"

    logger.debug(
        "Google Search LLM prompt",
        extra={"prompt_len": len(full_llm_prompt), "prompt": full_llm_prompt},
    )

    try:
        # Define the tool for the LLM
        tools = [{"google_search": {}}]
        resp = llm.invoke(full_llm_prompt, tools=tools)

        logger.info(
            "Google Search LLM execution successful",
            extra={
                "query": query,
                "output_len": len(resp.content),
                "output": resp.content,
            },
        )
        return resp.content
    except Exception as e:
        logger.exception(f"Google/Gemini search tool failed: {e}")
        # Re-raise to be caught by the main handler in app.py
        raise


def improved_route(query: str, memory: str) -> str:
    """Classifies the user query into 'rag', 'google', or 'chat'."""
    q_norm = normalize_farsi(query).lower()
    mem_norm = normalize_farsi(memory).lower() if memory else ""

    # This prompt is a key part of the logic
    clf_prompt = f"Classify query for Qeshm AI: '{q_norm}' with memory '{mem_norm}' use memory only to classify. Output: 'rag' for local info, 'google' for fresh/search, 'chat' for casual."

    logger.debug("Attempting route classification", extra={"prompt": clf_prompt})

    try:
        route = llm.invoke(clf_prompt).content.strip().lower()

        # Basic validation
        if route not in ["rag", "google", "chat"]:
            logger.warning(
                f"Router returned invalid route: '{route}'. Defaulting to 'google'."
            )
            route = "google"

        logger.info(
            "Routing decision",
            extra={"route": route, "query": q_norm, "memory": mem_norm},
        )
        return route
    except Exception as e:
        logger.error(
            f"Router LLM failed: {e}. Defaulting to 'google'.",
            exc_info=True,
            extra={"query": q_norm, "memory": mem_norm},
        )
        return "google"


# --- LangChain Setup ---

# Main RAG chain with history
chain = get_main_prompt() | llm
chain_with_history = RunnableWithMessageHistory(
    chain,
    get_session_history,
    input_messages_key="input",
    history_messages_key="history",
)
logger.info("Main LangChain RAG chain with history initialized")
