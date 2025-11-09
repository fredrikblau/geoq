import re
import json
import logging
import torch
from typing import List, Dict, Any
from langchain_community.embeddings import SentenceTransformerEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage
from langchain_community.chat_message_histories import ChatMessageHistory
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from langchain_core.runnables import RunnableWithMessageHistory
import redis
from config import (
    GEMINI_API_KEY,
    REDIS_URL,
    CHROMA_DIR,
    EMBED_MODEL,
    RERANKER_ID,
    MAX_CONTEXT_CHARS,
)
from prompts import get_main_prompt

# Logging setup (moved here for modularity)
logger = logging.getLogger("qeshm-ai")
logger.setLevel(logging.DEBUG)
json_handler = logging.StreamHandler()
formatter = logging.Formatter(
    "%(asctime)s %(name)s %(levelname)s %(message)s %(module)s %(funcName)s %(lineno)d"
)  # Plain for full logs; switch to JsonFormatter if needed
json_handler.setFormatter(formatter)
logger.addHandler(json_handler)

# Redis
try:
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()
    logger.info("Redis connected")
except Exception as e:
    logger.error(f"Redis failed: {e}. Falling back to in-memory.")
    redis_client = None

store: Dict[str, ChatMessageHistory] = {}
conversation_memory = {}

# Embeddings & DB
embeddings = SentenceTransformerEmbeddings(
    model_name=EMBED_MODEL, encode_kwargs={"normalize_embeddings": True}
)
vector_db = Chroma(persist_directory=CHROMA_DIR, embedding_function=embeddings)
retriever = vector_db.as_retriever(search_kwargs={"k": 8}, search_type="mmr")

# LLM
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash", google_api_key=GEMINI_API_KEY, temperature=0.2
)

# Reranker
reranker_tokenizer = None
reranker_model = None
try:
    from transformers import AutoTokenizer, AutoModelForSequenceClassification

    reranker_tokenizer = AutoTokenizer.from_pretrained(
        RERANKER_ID, trust_remote_code=True
    )
    reranker_model = AutoModelForSequenceClassification.from_pretrained(
        RERANKER_ID, trust_remote_code=True, torch_dtype=torch.float16
    )
    reranker_model.eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    reranker_model.to(device)
    logger.info(f"Reranker loaded on {device}")
except Exception as e:
    logger.warning(f"Failed to load reranker: {e}. Continuing without.")


def normalize_farsi(text: str) -> str:
    if not isinstance(text, str):
        return text
    text = text.replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه").replace("ـ", "")
    return re.sub(r"\s+", " ", text).strip()


def get_session_history(session_id: str) -> ChatMessageHistory:
    if redis_client:
        key = f"chat:history:{session_id}"
        try:
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
    if session_id not in store:
        store[session_id] = ChatMessageHistory()
    return store[session_id]


def save_session_history(session_id: str, history: ChatMessageHistory):
    if not redis_client:
        return
    key = f"chat:history:{session_id}"
    try:
        messages = [
            {
                "type": "human" if isinstance(m, HumanMessage) else "ai",
                "content": m.content,
            }
            for m in history.messages
        ]
        redis_client.setex(key, 86400, json.dumps(messages))  # Async for perf
    except Exception as e:
        logger.warning(f"Redis save failed: {e}")


def simple_summarize_memory(session_id: str, history: ChatMessageHistory) -> str:
    old_memory = conversation_memory.get(session_id, "")
    recent_msgs = history.messages[-6:]
    user_recent = [m.content for m in recent_msgs if isinstance(m, HumanMessage)]
    ai_recent = [m.content for m in recent_msgs if isinstance(m, AIMessage)]
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
    new_mem = "موضوعات اخیر: " + " • ".join(sorted_keys)
    conversation_memory[session_id] = new_mem[:200]
    return conversation_memory[session_id]


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
                logits = logits.squeeze(-1) if logits.size(-1) == 1 else logits[:, -1]
            scores = torch.softmax(logits.float(), dim=0).cpu().tolist()
        logger.info(f"Reranker scores: min={min(scores):.3f}, max={max(scores):.3f}")
    except Exception as e:
        logger.error(f"Reranker failed: {e} → fallback scores")
        scores = [1.0 / (i + 1) for i in range(len(texts))]
    ranked_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    ranked = [(docs[i], scores[i]) for i in ranked_idx[:top_k]]
    logger.debug(
        "Reranked docs", extra={"scores": scores, "top_k": len(ranked), "query": query}
    )
    return ranked


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
    context = "\n\n".join(parts)
    logger.info(
        "Built RAG context",
        extra={"doc_count": len(docs), "total_chars": total, "context": context},
    )  # Full log
    return context


def google_search_summary(
    query: str,
    history_summary: str = "",
    full_history: List = None,
    rag_context: str = "",
) -> str:
    logger.info(
        f"google_search_summary query={query} | history_summary={history_summary} | full_history={full_history} | rag_context={rag_context}"
    )
    hist_context = ""
    if full_history:
        recent_msgs = full_history[-8:]  # Take last 8 for more context (4 exchanges)
        formatted_history = []
        for m in recent_msgs:
            role = "کاربر" if isinstance(m, HumanMessage) else "دستیار"
            formatted_history.append(f"{role}: {m.content}")
        hist_context = (
            f"تاریخچه مکالمه اخیر (برای ادامه دادن استفاده کن):\n"
            + "\n".join(formatted_history)
        )

    rag_prompt = (
        f"\nاطلاعات محلی کم اطمینان (برای تایید یا تکمیل استفاده کن): {rag_context}\n"
        if rag_context
        else ""
    )

    system = f"""You are a web search assistant focusing on Qeshm Island, Iran. Prioritize local sources.
Use the provided conversation history to contextualize and refine your search query if needed. For example, if history mentions a location or preference, incorporate it into the summary.
History summary: {history_summary}
{hist_context}
{rag_prompt}
اگر از جستجو استفاده کردی، در پاسخ بگو 'اطلاعات محلی مطمئن نبود، پس جستجو کردم'.
Return concise Persian summary (3-4 sentences) + 2-4 sources as bullets.
Always continue naturally from the history—do not repeat or ignore it."""

    human = f"Search and summarize (in Persian) focusing on Qeshm: {query}"
    full_prompt = f"{system}\n\n{human}"
    try:
        # Proper tool schema (fix for your broken empty dict)
        tools = [{"google_search": {}}]
        resp = llm.invoke(full_prompt, tools=tools)
        logger.info(
            "Google search executed",
            extra={
                "query": query,
                "full_prompt": full_prompt,
                "output": resp.content,
            },
        )  # Full
        return resp.content
    except Exception as e:
        logger.exception(f"Google/Gemini search failed: {e}")
        raise


def improved_route(query: str, memory: str) -> str:
    q = normalize_farsi(query).lower()
    mem = normalize_farsi(memory).lower() if memory else ""
    clf_prompt = f"Classify query for Qeshm AI: '{query}' with memory '{mem}' use memory only to classify. Output: 'rag' for local info, 'google' for fresh/search, 'chat' for casual."
    route = llm.invoke(clf_prompt).content.strip().lower()
    logger.info(
        "Routing decision", extra={"route": route, "query": query, "memory": memory}
    )  # Full
    return route


# Chain setup
chain = get_main_prompt() | llm
chain_with_history = RunnableWithMessageHistory(
    chain,
    get_session_history,
    input_messages_key="input",
    history_messages_key="history",
)

# In utils.py, add this new function near the top
from langchain_core.prompts import ChatPromptTemplate

SUMMARIZE_PROMPT = ChatPromptTemplate.from_template(
    """
Summarize this conversation history in 1-2 Persian sentences, focusing on key topics, user queries, and any ongoing context about Qeshm Island. Keep it concise and relevant for future responses.

History:
{history_text}
"""
)


def llm_summarize_memory(session_id: str, history: ChatMessageHistory) -> str:
    if len(history.messages) <= 6:  # Threshold: Keep full if short
        recent_msgs = history.messages[-6:]
        user_recent = [m.content for m in recent_msgs if isinstance(m, HumanMessage)]
        ai_recent = [m.content for m in recent_msgs if isinstance(m, AIMessage)]
        return f"مکالمه اخیر: {' | '.join(user_recent[-3:])}"  # Fallback to simple recent for short histories

    # Full summary for longer
    history_text = "\n".join(
        [
            f"{'User' if isinstance(m, HumanMessage) else 'AI'}: {m.content}"
            for m in history.messages
        ]
    )
    try:
        summary_chain = SUMMARIZE_PROMPT | llm
        summary = summary_chain.invoke({"history_text": history_text}).content
        conversation_memory[session_id] = summary[:300]  # Cap to avoid bloat
        logger.info(f"LLM summarized memory for {session_id}: {summary}")
        return summary
    except Exception as e:
        logger.warning(f"LLM summary failed: {e}. Fallback to keyword.")
        return simple_summarize_memory(session_id, history)  # Keep old as fallback
