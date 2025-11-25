"""
Enhanced utilities with:
- Personalized facts extraction and storage
- Selective history compression
- Clarification detection
"""

import re
import json
import logging
import torch
import functools
import re
import json
from typing import Dict, Tuple
from langchain_core.messages import BaseMessage

from config import (
    MAX_REFINEMENT_ITERATIONS,
    ENABLE_QUALITY_GATE,
    QUALITY_GATE_THRESHOLD,
    REFINEMENT_STRATEGIES,
)
from prompts import (
    QUALITY_EVALUATION_PROMPT,
    QUERY_REFINEMENT_PROMPT,
    CONTEXT_ENHANCEMENT_PROMPT,
)
from typing import List, Dict, Tuple, Optional
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

from prompts import (
    get_main_prompt,
    SUMMARIZE_PROMPT,
    EXTRACT_FACTS_PROMPT,
    CLARIFICATION_CHECK_PROMPT,
    ROUTING_PROMPT_TEMPLATE,
    GOOGLE_SEARCH_SYSTEM_PROMPT,
    build_context_block,
)
from pythonjsonlogger import jsonlogger


# ============================================================================
# Logging Setup
# ============================================================================

logger = logging.getLogger("qeshm-ai")
logger.setLevel(logging.DEBUG)
logger.propagate = False

if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s %(module)s %(funcName)s %(lineno)d"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)


# ============================================================================
# Farsi Normalization
# ============================================================================


def normalize_farsi(text: str) -> str:
    """Normalize Persian/Farsi characters."""
    text = text.replace("ي", "ی").replace("ك", "ک")
    text = re.sub(r"[\u200c\u200d\u200e\u200f]+", " ", text)
    return text.strip()


# ============================================================================
# Redis Session History Storage
# ============================================================================

try:
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()
    logger.info("Redis connected successfully", extra={"url": REDIS_URL})
except Exception as e:
    logger.warning(
        "Redis connection failed. Falling back to in-memory store.",
        extra={"error": str(e)},
    )
    redis_client = None

in_memory_store: Dict[str, ChatMessageHistory] = {}
in_memory_facts: Dict[str, dict] = {}  # 🆕 In-memory facts storage


def get_session_history(session_id: str) -> ChatMessageHistory:
    """Retrieve conversation history for a session."""
    if redis_client:
        try:
            raw = redis_client.get(f"history:{session_id}")
            if raw:
                data = json.loads(raw)
                history = ChatMessageHistory()
                for msg in data:
                    if msg["type"] == "human":
                        history.add_message(HumanMessage(content=msg["content"]))
                    elif msg["type"] == "ai":
                        history.add_message(AIMessage(content=msg["content"]))
                logger.debug(
                    "History loaded from Redis",
                    extra={
                        "session_id": session_id,
                        "msg_count": len(history.messages),
                    },
                )
                return history
        except Exception as e:
            logger.error(
                "Failed to load history from Redis",
                extra={"session_id": session_id, "error": str(e)},
            )

    if session_id not in in_memory_store:
        in_memory_store[session_id] = ChatMessageHistory()
        logger.debug(
            "New in-memory history created",
            extra={"session_id": session_id},
        )
    return in_memory_store[session_id]


def save_session_history(session_id: str, history: ChatMessageHistory):
    """Save conversation history for a session."""
    if redis_client:
        try:
            data = [
                {
                    "type": "human" if isinstance(m, HumanMessage) else "ai",
                    "content": m.content,
                }
                for m in history.messages
            ]
            redis_client.set(f"history:{session_id}", json.dumps(data), ex=86400 * 7)
            logger.debug(
                "History saved to Redis",
                extra={"session_id": session_id, "msg_count": len(history.messages)},
            )
        except Exception as e:
            logger.error(
                "Failed to save history to Redis",
                extra={"session_id": session_id, "error": str(e)},
            )
    else:
        in_memory_store[session_id] = history


# ============================================================================
# User Facts Storage (Personalization) 🆕
# ============================================================================


def get_user_facts(session_id: str) -> dict:
    """Retrieve personalized facts for a user."""
    if redis_client:
        try:
            raw = redis_client.get(f"facts:{session_id}")
            if raw:
                facts = json.loads(raw)
                logger.debug(
                    "Facts loaded from Redis",
                    extra={"session_id": session_id, "facts": facts},
                )
                return facts
        except Exception as e:
            logger.error(
                "Failed to load facts from Redis",
                extra={"session_id": session_id, "error": str(e)},
            )

    return in_memory_facts.get(session_id, {})


def save_user_facts(session_id: str, facts: dict):
    """Save personalized facts for a user."""
    if redis_client:
        try:
            redis_client.set(f"facts:{session_id}", json.dumps(facts), ex=86400 * 30)
            logger.debug(
                "Facts saved to Redis",
                extra={"session_id": session_id, "facts": facts},
            )
        except Exception as e:
            logger.error(
                "Failed to save facts to Redis",
                extra={"session_id": session_id, "error": str(e)},
            )
    else:
        in_memory_facts[session_id] = facts


def extract_and_update_facts(session_id: str, history: ChatMessageHistory, llm) -> dict:
    """
    Extract facts from conversation history using LLM.

    Args:
        session_id: Session identifier
        history: Conversation history
        llm: LLM instance for extraction

    Returns:
        Updated facts dictionary
    """
    try:
        # Get last 10 messages for fact extraction
        recent_msgs = (
            history.messages[-10:] if len(history.messages) > 10 else history.messages
        )
        history_text = "\n".join(
            [
                f"{'کاربر' if isinstance(m, HumanMessage) else 'دستیار'}: {m.content}"
                for m in recent_msgs
            ]
        )

        # Extract facts using LLM
        extraction_chain = EXTRACT_FACTS_PROMPT | llm
        result = extraction_chain.invoke({"history_text": history_text})

        # Parse JSON response
        try:
            # Extract JSON from response (handle markdown code blocks)
            content = result.content if hasattr(result, "content") else str(result)
            # Remove markdown code blocks if present
            content = re.sub(r"```json\s*", "", content)
            content = re.sub(r"```\s*", "", content)
            new_facts = json.loads(content.strip())
        except json.JSONDecodeError:
            logger.warning(
                "Failed to parse facts JSON, using empty dict",
                extra={"session_id": session_id, "response": content[:200]},
            )
            new_facts = {}

        # Merge with existing facts
        existing_facts = get_user_facts(session_id)

        # Deep merge logic
        merged_facts = existing_facts.copy()
        for key, value in new_facts.items():
            if isinstance(value, dict) and key in merged_facts:
                merged_facts[key] = {**merged_facts[key], **value}
            elif isinstance(value, list) and key in merged_facts:
                # Merge lists and remove duplicates
                merged_facts[key] = list(set(merged_facts.get(key, []) + value))
            else:
                merged_facts[key] = value

        # Save updated facts
        save_user_facts(session_id, merged_facts)

        logger.info(
            "Facts extracted and updated",
            extra={"session_id": session_id, "facts": merged_facts},
        )

        return merged_facts

    except Exception as e:
        logger.exception(
            "Facts extraction failed",
            extra={"session_id": session_id, "error": str(e)},
        )
        return get_user_facts(session_id)


# ============================================================================
# Selective History Compression 🆕
# ============================================================================


def get_selective_history(
    history: ChatMessageHistory,
    recent_count: int = 4,
) -> Tuple[str, str]:
    """
    Get selective history: recent messages verbatim + older summary.

    Args:
        history: Full conversation history
        recent_count: Number of recent messages to include verbatim

    Returns:
        Tuple of (recent_history_text, earlier_summary_text)
    """
    if len(history.messages) <= recent_count:
        # All history is recent
        recent_text = "\n".join(
            [
                f"{'کاربر' if isinstance(m, HumanMessage) else 'دستیار'}: {m.content}"
                for m in history.messages
            ]
        )
        return recent_text, ""

    # Split history
    recent_msgs = history.messages[-recent_count:]
    earlier_msgs = history.messages[:-recent_count]

    # Recent messages verbatim
    recent_text = "\n".join(
        [
            f"{'کاربر' if isinstance(m, HumanMessage) else 'دستیار'}: {m.content}"
            for m in recent_msgs
        ]
    )

    # Earlier messages summary (simple compression for now)
    earlier_text = "\n".join(
        [
            f"{'کاربر' if isinstance(m, HumanMessage) else 'دستیار'}: {m.content[:100]}..."
            for m in earlier_msgs[-6:]  # Last 6 of the earlier messages
        ]
    )

    return recent_text, earlier_text


# ============================================================================
# Clarification Detection 🆕
# ============================================================================


def check_needs_clarification(
    query: str,
    user_facts: dict,
    memory: str,
    llm,
) -> Tuple[bool, str]:
    """
    Check if the query needs clarification.

    Args:
        query: User query
        user_facts: User's personalized facts
        memory: Conversation memory summary
        llm: LLM instance

    Returns:
        Tuple of (needs_clarification: bool, clarification_questions: str)
    """
    try:
        # Format user facts for prompt
        facts_str = (
            json.dumps(user_facts, ensure_ascii=False) if user_facts else "ندارد"
        )

        clarification_chain = CLARIFICATION_CHECK_PROMPT | llm
        result = clarification_chain.invoke(
            {
                "query": query,
                "user_facts": facts_str,
                "memory": memory or "ندارد",
            }
        )

        content = result.content if hasattr(result, "content") else str(result)

        if content.startswith("NEEDS_CLARIFICATION:"):
            questions = content.replace("NEEDS_CLARIFICATION:", "").strip()
            logger.info(
                "Clarification needed",
                extra={"query": query, "clarification": questions},
            )
            return True, questions
        else:
            logger.debug("Query is clear", extra={"query": query})
            return False, ""

    except Exception as e:
        logger.exception("Clarification check failed", extra={"error": str(e)})
        return False, ""


# ============================================================================
# LLM & Vector DB Setup (Unchanged)
# ============================================================================

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=GEMINI_API_KEY,
    temperature=0.2,
)

embeddings = SentenceTransformerEmbeddings(model_name=EMBED_MODEL)
vector_db = Chroma(
    persist_directory=CHROMA_DIR,
    embedding_function=embeddings,
)
retriever = vector_db.as_retriever(search_kwargs={"k": 8})

# Reranker setup
reranker_tokenizer = AutoTokenizer.from_pretrained(RERANKER_ID, trust_remote_code=True)
reranker_model = AutoModelForSequenceClassification.from_pretrained(
    RERANKER_ID, trust_remote_code=True
)
if torch.cuda.is_available():
    reranker_model = reranker_model.to("cuda")


# ============================================================================
# Chain with History
# ============================================================================

chain_with_history = RunnableWithMessageHistory(
    llm,
    get_session_history,
    input_messages_key="input",
    history_messages_key="history",
)


# ============================================================================
# Memory Summarization (Enhanced) 🆕
# ============================================================================


def llm_summarize_memory(session_id: str, history: ChatMessageHistory) -> str:
    """
    Summarize conversation memory using LLM.
    Also triggers fact extraction.
    """
    if len(history.messages) < 2:
        return ""

    try:
        # Extract and update facts in parallel
        extract_and_update_facts(session_id, history, llm)

        # Summarize memory
        history_text = "\n".join(
            [
                f"{'User' if isinstance(m, HumanMessage) else 'Assistant'}: {m.content}"
                for m in history.messages[-10:]
            ]
        )

        summary_chain = SUMMARIZE_PROMPT | llm
        result = summary_chain.invoke({"history_text": history_text})
        summary = result.content if hasattr(result, "content") else str(result)

        logger.debug(
            "Memory summarized",
            extra={"session_id": session_id, "summary": summary},
        )

        return summary.strip()

    except Exception as e:
        logger.exception(
            "Memory summarization failed",
            extra={"session_id": session_id, "error": str(e)},
        )
        # Fallback: simple keyword extraction
        keywords = []
        for msg in history.messages[-5:]:
            if isinstance(msg, HumanMessage):
                words = msg.content.split()[:5]
                keywords.extend(words)
        return " ".join(keywords[:15])


# ============================================================================
# Route and Refine (Enhanced) 🆕
# ============================================================================


def route_and_refine(
    user_input: str,
    memory: str,
    history: ChatMessageHistory,
    user_facts: dict,
) -> Tuple[str, str]:
    """
    Enhanced routing with user facts and selective history.
    """
    try:
        # Get selective history
        recent_history, _ = get_selective_history(history)

        # Format facts
        facts_str = (
            json.dumps(user_facts, ensure_ascii=False) if user_facts else "ندارد"
        )

        routing_chain = ROUTING_PROMPT_TEMPLATE | llm
        result = routing_chain.invoke(
            {
                "query": user_input,
                "memory": memory or "ندارد",
                "user_facts": facts_str,
                "recent_history": recent_history or "ندارد",
            }
        )

        content = result.content if hasattr(result, "content") else str(result)

        # Parse JSON
        content = re.sub(r"```json\s*", "", content)
        content = re.sub(r"```\s*", "", content)
        data = json.loads(content.strip())

        route = data.get("route", "google")
        refined_query = data.get("refined_query", user_input)

        logger.info(
            "Route and refine complete",
            extra={
                "original": user_input,
                "route": route,
                "refined": refined_query,
            },
        )

        return route, refined_query

    except Exception as e:
        logger.exception("Route and refine failed", extra={"error": str(e)})
        return "google", user_input


# ============================================================================
# RAG Functions (Unchanged)
# ============================================================================


def rerank_docs(
    query: str, docs: List[Document], top_k: int = 5
) -> List[Tuple[Document, float]]:
    """Rerank documents using cross-encoder."""
    if not docs:
        return []

    try:
        pairs = [[query, doc.page_content] for doc in docs]
        with torch.no_grad():
            inputs = reranker_tokenizer(
                pairs,
                padding=True,
                truncation=True,
                return_tensors="pt",
                max_length=512,
            )
            if torch.cuda.is_available():
                inputs = {k: v.to("cuda") for k, v in inputs.items()}
            scores = (
                reranker_model(**inputs, return_dict=True)
                .logits.view(-1)
                .cpu()
                .float()
                .numpy()
            )

        doc_score_pairs = list(zip(docs, scores))
        doc_score_pairs.sort(key=lambda x: x[1], reverse=True)
        return doc_score_pairs[:top_k]

    except Exception as e:
        logger.error("Reranking failed", extra={"error": str(e)})
        return [(d, 0.0) for d in docs[:top_k]]


def build_context_from_docs(
    docs: List[Document], max_chars: int = MAX_CONTEXT_CHARS
) -> str:
    """Build context string from documents."""
    context_parts = []
    char_count = 0

    for doc in docs:
        content = doc.page_content.strip()
        if char_count + len(content) > max_chars:
            break
        context_parts.append(content)
        char_count += len(content)

    return "\n\n".join(context_parts)


# ============================================================================
# Google Search (Enhanced - No Source Disclosure) 🆕
# ============================================================================


def google_search_summary(
    query: str,
    history_summary: str,
    full_history: List[BaseMessage],
    rag_context: str = "",
    user_facts: dict = None,
) -> str:
    """
    Enhanced Google Search with no source disclosure.
    """
    try:

        llm_with_tools = ChatGoogleGenerativeAI(
            model="gemini-2.5-pro",
            google_api_key=GEMINI_API_KEY,
            temperature=0.3,
        )

        # Build context
        context_parts = []
        if history_summary:
            context_parts.append(f"زمینه مکالمه: {history_summary}")
        if rag_context:
            context_parts.append(
                f"اطلاعات محلی (ممکنه قدیمی باشه): {rag_context[:500]}"
            )

        context = "\n".join(context_parts)

        # Use enhanced prompt (no source disclosure)
        prompt = GOOGLE_SEARCH_SYSTEM_PROMPT.format(
            context=context, query=query, user_facts=user_facts
        )

        response = llm_with_tools.invoke(prompt, tools=[{"google_search": {}}])
        answer = response.content if hasattr(response, "content") else str(response)

        logger.info(
            "Google Search complete (no source disclosure)",
            extra={"query": query, "answer_len": len(answer)},
        )

        return answer

    except Exception as e:
        logger.exception("Google search failed", extra={"error": str(e)})
        return "متاسفانه نتونستم اطلاعات رو پیدا کنم. میتونی جزئیات بیشتری بدی؟"


# 🆕 Quality Evaluation Function
def evaluate_answer_quality(
    query: str,
    answer: str,
    context_used: str,
) -> Dict:
    """
    Evaluate answer quality using LLM-as-judge.

    Args:
        query: Original user query
        answer: Generated answer
        context_used: Context source (RAG/Google/etc)

    Returns:
        Dict with quality_score, issue_type, recommendation, reason
    """
    try:
        evaluation_chain = QUALITY_EVALUATION_PROMPT | llm
        result = evaluation_chain.invoke(
            {
                "query": query,
                "answer": answer,
                "context_used": context_used or "ندارد",
            }
        )

        content = result.content if hasattr(result, "content") else str(result)

        # Parse JSON
        content = re.sub(r"```json\s*", "", content)
        content = re.sub(r"```\s*", "", content)
        evaluation = json.loads(content.strip())

        logger.info(
            "Quality evaluation complete",
            extra={
                "query": query[:100],
                "quality_score": evaluation.get("quality_score", 0),
                "issue_type": evaluation.get("issue_type", "unknown"),
                "recommendation": evaluation.get("recommendation", "unknown"),
            },
        )

        return evaluation

    except json.JSONDecodeError as e:
        logger.error(
            "Quality evaluation JSON parse failed",
            extra={"error": str(e), "response": content[:200]},
        )
        # Fallback: assume acceptable quality
        return {
            "quality_score": 0.8,
            "issue_type": "good",
            "recommendation": "accept",
            "reason": "Evaluation failed, assuming acceptable",
        }

    except Exception as e:
        logger.exception("Quality evaluation failed", extra={"error": str(e)})
        return {
            "quality_score": 0.8,
            "issue_type": "good",
            "recommendation": "accept",
            "reason": "Evaluation error, assuming acceptable",
        }


# 🆕 Query Refinement Function
def refine_query_for_retry(
    original_query: str,
    previous_answer: str,
    issue_type: str,
    reason: str,
    conversation_history: str,
) -> Tuple[str, str]:
    """
    Refine query based on identified issues.

    Args:
        original_query: Original user query
        previous_answer: Previous (poor quality) answer
        issue_type: Type of issue identified
        reason: Reason for poor quality
        conversation_history: Recent conversation context

    Returns:
        Tuple of (refined_query, search_strategy)
    """
    try:
        refinement_chain = QUERY_REFINEMENT_PROMPT | llm
        result = refinement_chain.invoke(
            {
                "original_query": original_query,
                "previous_answer": previous_answer,
                "issue_type": issue_type,
                "reason": reason,
                "conversation_history": conversation_history or "ندارد",
            }
        )

        content = result.content if hasattr(result, "content") else str(result)

        # Parse JSON
        content = re.sub(r"```json\s*", "", content)
        content = re.sub(r"```\s*", "", content)
        refinement = json.loads(content.strip())

        refined_query = refinement.get("refined_query", original_query)
        search_strategy = refinement.get("search_strategy", "google_search")

        logger.info(
            "Query refinement complete",
            extra={
                "original": original_query[:100],
                "refined": refined_query[:100],
                "strategy": search_strategy,
            },
        )

        return refined_query, search_strategy

    except Exception as e:
        logger.exception("Query refinement failed", extra={"error": str(e)})
        # Fallback: use original query + force Google
        return original_query, "google_search"


# 🆕 Context Enhancement Function
def enhance_answer_with_context(
    query: str,
    previous_answer: str,
    additional_context: str,
    issue_type: str,
    reason: str,
) -> str:
    """
    Enhance incomplete answer with additional context.

    Args:
        query: User query
        previous_answer: Incomplete answer
        additional_context: Additional context to incorporate
        issue_type: Type of issue
        reason: Reason for enhancement

    Returns:
        Enhanced answer
    """
    try:
        enhancement_chain = CONTEXT_ENHANCEMENT_PROMPT | llm
        result = enhancement_chain.invoke(
            {
                "query": query,
                "previous_answer": previous_answer,
                "additional_context": additional_context,
                "issue_type": issue_type,
                "reason": reason,
            }
        )

        enhanced_answer = result.content if hasattr(result, "content") else str(result)

        logger.info(
            "Answer enhancement complete",
            extra={
                "query": query[:100],
                "enhanced_len": len(enhanced_answer),
            },
        )

        return enhanced_answer

    except Exception as e:
        logger.exception("Answer enhancement failed", extra={"error": str(e)})
        return previous_answer  # Fallback to original


# 🆕 Check if refinement should happen
def should_refine_answer(evaluation: Dict) -> bool:
    """
    Decide if answer needs refinement based on evaluation.

    Args:
        evaluation: Quality evaluation result

    Returns:
        True if should refine, False otherwise
    """
    if not ENABLE_QUALITY_GATE:
        return False

    quality_score = evaluation.get("quality_score", 1.0)
    recommendation = evaluation.get("recommendation", "accept")

    # Refine if quality below threshold AND recommendation is not "accept"
    should_refine = (
        quality_score < QUALITY_GATE_THRESHOLD and recommendation != "accept"
    )

    logger.debug(
        "Refinement decision",
        extra={
            "quality_score": quality_score,
            "threshold": QUALITY_GATE_THRESHOLD,
            "recommendation": recommendation,
            "will_refine": should_refine,
        },
    )

    return should_refine


# 🆕 Get refinement strategy
def get_refinement_strategy(issue_type: str, recommendation: str) -> str:
    """
    Determine refinement strategy based on issue type.

    Args:
        issue_type: Type of quality issue
        recommendation: LLM recommendation

    Returns:
        Strategy name (google_search, better_rag_query, etc.)
    """
    # Use recommendation if it's a valid strategy
    if recommendation in ["google_search", "better_rag_query", "add_more_context"]:
        return recommendation

    # Otherwise use issue type mapping
    return REFINEMENT_STRATEGIES.get(issue_type, "google_search")
