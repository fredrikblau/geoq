"""
Enhanced LangGraph with:
1. Clarification step
2. No source disclosure
3. Personalized facts retrieval
4. Selective history usage
"""

import time
from typing import TypedDict, List, Literal, Optional
from langchain_core.messages import HumanMessage, AIMessage
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.documents import Document
from langgraph.graph import StateGraph, END
import time
from typing import TypedDict, List, Literal, Optional
from langchain_core.messages import HumanMessage, AIMessage
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.documents import Document
from langgraph.graph import StateGraph, END

from utils import (
    logger,
    normalize_farsi,
    get_session_history,
    save_session_history,
    get_user_facts,
    get_selective_history,
    llm_summarize_memory,
    route_and_refine,
    retriever,
    rerank_docs,
    vector_db,
    build_context_from_docs,
    google_search_summary,
    llm,
)
from utils import (
    evaluate_answer_quality,
    refine_query_for_retry,
    should_refine_answer,
    get_refinement_strategy,
)
from prompts import build_context_block
from config import MAX_HISTORY_LEN, MAX_REFINEMENT_ITERATIONS

from utils import (
    logger,
    normalize_farsi,
    get_session_history,
    save_session_history,
    get_user_facts,
    extract_and_update_facts,
    get_selective_history,
    check_needs_clarification,
    llm_summarize_memory,
    route_and_refine,
    retriever,
    rerank_docs,
    vector_db,
    build_context_from_docs,
    google_search_summary,
    chain_with_history,
    llm,
)
from prompts import build_context_block
from config import MAX_HISTORY_LEN


# ============================================================================
# Enhanced State Definition
# ============================================================================


class ConversationState(TypedDict, total=False):
    """Enhanced state with self-correction loop."""

    # Input & Session
    session_id: str
    user_input_raw: str
    messages_from_request: List[dict]

    # History & Memory
    history: ChatMessageHistory
    memory_summary: str
    user_facts: dict
    recent_history_text: str
    earlier_summary: str

    # Routing & Refinement
    route: Literal["rag", "google", "chat"]
    refined_query: str

    # RAG Pipeline
    rag_context: str
    rag_low_conf_context: str
    rag_fallback_reason: str
    raw_docs: List[Document]
    reranked_docs: List[tuple]

    # Google Search
    google_answer: str

    # LLM Generation
    context_block: str
    final_input: str
    llm_output: str

    # 🆕 Quality Gate & Iteration
    iteration_count: int  # Current retry iteration (0 = first attempt)
    quality_evaluation: dict  # {quality_score, issue_type, recommendation, reason}
    previous_answers: List[str]  # History of attempts
    refinement_history: List[dict]  # [{iteration, issue, strategy}]
    final_quality_score: float  # Quality of final answer

    # Error Handling
    error_info: Optional[str]

    # Streaming metadata
    is_streaming: bool
    completion_id: str
    created_timestamp: int


# ============================================================================
# Node 1: Load History, Memory & Facts (Enhanced) 🆕
# ============================================================================


def load_history_memory_and_facts(state: ConversationState) -> ConversationState:
    """Load history, generate memory summary, extract facts."""
    session_id = state["session_id"]
    messages = state["messages_from_request"]
    user_input = state["user_input_raw"]

    logger.info("Node: load_history_memory_and_facts", extra={"session_id": session_id})

    try:
        history = get_session_history(session_id)
        old_len = len(history.messages)

        history.messages.clear()
        for msg in messages[:-1]:
            norm_content = (
                normalize_farsi(msg["content"])
                if msg["role"] == "user"
                else msg["content"]
            )
            if msg["role"] == "user":
                history.add_message(HumanMessage(content=norm_content))
            elif msg["role"] == "assistant":
                history.add_message(AIMessage(content=norm_content))

        history.add_message(HumanMessage(content=user_input))

        if len(history.messages) > MAX_HISTORY_LEN:
            history.messages = history.messages[-MAX_HISTORY_LEN:]

        save_session_history(session_id, history)

        memory_text = llm_summarize_memory(session_id, history)
        user_facts = get_user_facts(session_id)
        recent_history_text, earlier_summary = get_selective_history(
            history, recent_count=4
        )

        logger.info(
            "History, memory, and facts loaded",
            extra={
                "session_id": session_id,
                "history_len": len(history.messages),
            },
        )

        return {
            **state,
            "history": history,
            "memory_summary": memory_text,
            "user_facts": user_facts,
            "recent_history_text": recent_history_text,
            "earlier_summary": earlier_summary,
            "iteration_count": 0,  # 🆕 Initialize iteration counter
            "previous_answers": [],  # 🆕 Initialize answer history
            "refinement_history": [],  # 🆕 Initialize refinement history
        }

    except Exception as e:
        logger.exception(
            "load_history_memory_and_facts failed", extra={"session_id": session_id}
        )
        return {
            **state,
            "error_info": f"history_load_error: {str(e)}",
            "history": ChatMessageHistory(),
            "memory_summary": "",
            "user_facts": {},
            "iteration_count": 0,
            "previous_answers": [],
            "refinement_history": [],
        }


# ============================================================================
# Node 2: Check Clarification (New) 🆕
# ============================================================================


def check_clarification_needed(state: ConversationState) -> ConversationState:
    """
    New node: Check if user query needs clarification before proceeding.
    """
    session_id = state["session_id"]
    user_input = state["user_input_raw"]
    memory = state.get("memory_summary", "")
    user_facts = state.get("user_facts", {})

    logger.info("Node: check_clarification_needed", extra={"session_id": session_id})

    try:
        needs_clarification, clarification_questions = check_needs_clarification(
            query=user_input,
            user_facts=user_facts,
            memory=memory,
            llm=llm,
        )

        if needs_clarification:
            logger.info(
                "Clarification needed",
                extra={
                    "session_id": session_id,
                    "query": user_input,
                    "clarification": clarification_questions,
                },
            )

            # Set output directly with clarification questions
            return {
                **state,
                "needs_clarification": True,
                "clarification_questions": clarification_questions,
                "llm_output": clarification_questions,  # Return clarification as output
            }
        else:
            logger.debug("No clarification needed", extra={"session_id": session_id})
            return {
                **state,
                "needs_clarification": False,
                "clarification_questions": "",
            }

    except Exception as e:
        logger.exception(
            "check_clarification_needed failed", extra={"session_id": session_id}
        )
        return {
            **state,
            "needs_clarification": False,
            "clarification_questions": "",
            "error_info": f"clarification_check_error: {str(e)}",
        }


# ============================================================================
# Node 3: Route & Refine (Enhanced) 🆕
# ============================================================================


def route_and_refine_query(state: ConversationState) -> ConversationState:
    """Route query, with refinement on retry iterations."""
    session_id = state["session_id"]
    user_input = state["user_input_raw"]
    memory = state.get("memory_summary", "")
    history = state.get("history", ChatMessageHistory())
    user_facts = state.get("user_facts", {})
    iteration_count = state.get("iteration_count", 0)
    quality_eval = state.get("quality_evaluation", {})
    previous_answers = state.get("previous_answers", [])

    logger.info(
        "Node: route_and_refine_query",
        extra={"session_id": session_id, "iteration": iteration_count},
    )

    try:
        # 🆕 If this is a retry iteration, refine the query
        if iteration_count > 0 and quality_eval:
            logger.info(
                "Retry iteration - refining query",
                extra={
                    "session_id": session_id,
                    "iteration": iteration_count,
                    "issue_type": quality_eval.get("issue_type", "unknown"),
                },
            )

            # Get recent history for context
            recent_history, _ = get_selective_history(history, recent_count=3)

            # Refine query based on identified issue
            refined_query, search_strategy = refine_query_for_retry(
                original_query=user_input,
                previous_answer=previous_answers[-1] if previous_answers else "",
                issue_type=quality_eval.get("issue_type", ""),
                reason=quality_eval.get("reason", ""),
                conversation_history=recent_history,
            )

            # Determine route from strategy
            route = "google" if "google" in search_strategy else "rag"

            # Store refinement in history
            refinement_history = state.get("refinement_history", [])
            refinement_history.append(
                {
                    "iteration": iteration_count,
                    "issue": quality_eval.get("issue_type", ""),
                    "strategy": search_strategy,
                    "refined_query": refined_query,
                }
            )

            return {
                **state,
                "route": route,
                "refined_query": refined_query,
                "refinement_history": refinement_history,
            }

        # 🆕 First iteration - normal routing
        else:
            route, refined_query = route_and_refine(
                user_input=user_input,
                memory=memory,
                history=history,
                user_facts=user_facts,
            )

            logger.info(
                "First iteration - normal routing",
                extra={
                    "session_id": session_id,
                    "route": route,
                    "refined_query": refined_query,
                },
            )

            return {
                **state,
                "route": route,
                "refined_query": refined_query,
            }

    except Exception as e:
        logger.exception(
            "route_and_refine_query failed", extra={"session_id": session_id}
        )
        return {
            **state,
            "route": "google",
            "refined_query": user_input,
            "error_info": f"routing_error: {str(e)}",
        }


# ============================================================================
# Nodes 4-5: RAG (Unchanged)
# ============================================================================


def perform_rag_retrieval(state: ConversationState) -> ConversationState:
    """Retrieve and rerank documents from vector DB."""
    session_id = state["session_id"]
    query = state["refined_query"]

    logger.info("Node: perform_rag_retrieval", extra={"session_id": session_id})

    try:
        raw_docs = retriever.invoke(query)

        if not raw_docs:
            return {
                **state,
                "raw_docs": [],
                "reranked_docs": [],
                "rag_fallback_reason": "no_docs_found",
            }

        for d in raw_docs:
            d.page_content = normalize_farsi(d.page_content)

        reranked = rerank_docs(query, raw_docs, top_k=6)

        logger.info(
            "RAG retrieval complete",
            extra={"session_id": session_id, "doc_count": len(reranked)},
        )

        return {
            **state,
            "raw_docs": raw_docs,
            "reranked_docs": reranked,
        }

    except Exception as e:
        logger.exception(
            "perform_rag_retrieval failed", extra={"session_id": session_id}
        )
        return {
            **state,
            "raw_docs": [],
            "reranked_docs": [],
            "rag_fallback_reason": f"rag_exception: {str(e)}",
        }


def check_rag_confidence(state: ConversationState) -> ConversationState:
    """Evaluate RAG confidence."""
    session_id = state["session_id"]
    query = state["refined_query"]
    reranked = state.get("reranked_docs", [])

    logger.info("Node: check_rag_confidence", extra={"session_id": session_id})

    if not reranked:
        return {
            **state,
            "rag_context": "",
            "rag_fallback_reason": state.get("rag_fallback_reason", "no_reranked_docs"),
        }

    try:
        docs = [d for d, s in reranked]
        rerank_best_score = reranked[0][1]

        scored = vector_db.similarity_search_with_score(query, k=3)
        best_sim_score = min([s for _, s in scored]) if scored else 999.0

        is_rag_confident = (
            rerank_best_score > 0.05 and best_sim_score < 0.7 and len(docs) >= 1
        )

        if is_rag_confident:
            context = build_context_from_docs(docs)
            return {
                **state,
                "rag_context": context,
                "rag_low_conf_context": "",
                "rag_fallback_reason": "",
            }
        else:
            low_conf_docs = docs[:3]
            rag_context_low = build_context_from_docs(low_conf_docs, max_chars=1500)
            fallback_reason = f"low_confidence (rerank={rerank_best_score:.3f}, sim={best_sim_score:.3f})"

            return {
                **state,
                "rag_context": "",
                "rag_low_conf_context": rag_context_low,
                "rag_fallback_reason": fallback_reason,
            }

    except Exception as e:
        logger.exception(
            "check_rag_confidence failed", extra={"session_id": session_id}
        )
        return {
            **state,
            "rag_context": "",
            "rag_fallback_reason": f"confidence_check_error: {str(e)}",
        }


def perform_google_search(state: ConversationState) -> ConversationState:
    """Google Search with no source disclosure."""
    session_id = state["session_id"]
    query = state["refined_query"]
    memory = state.get("memory_summary", "")
    history = state.get("history", ChatMessageHistory())
    rag_context_low = state.get("rag_low_conf_context", "")
    user_facts = state.get("user_facts", {})

    logger.info("Node: perform_google_search", extra={"session_id": session_id})

    try:
        recent_history, _ = get_selective_history(history, recent_count=3)

        google_answer = google_search_summary(
            query=query,
            history_summary=f"{memory} | {recent_history}",
            full_history=history.messages,
            rag_context=rag_context_low,
            user_facts=user_facts,
        )

        return {
            **state,
            "google_answer": google_answer,
            "llm_output": google_answer,
        }

    except Exception as e:
        logger.exception(
            "perform_google_search failed", extra={"session_id": session_id}
        )

        fallback_msg = "متاسفانه نتونستم اطلاعات رو پیدا کنم."

        return {
            **state,
            "google_answer": fallback_msg,
            "llm_output": fallback_msg,
            "error_info": f"google_search_error: {str(e)}",
        }


def build_final_input(state: ConversationState) -> ConversationState:
    """Build context block with personalization."""
    session_id = state["session_id"]
    rag_context = state.get("rag_context", "")
    user_facts = state.get("user_facts", {})
    recent_history = state.get("recent_history_text", "")
    earlier_summary = state.get("earlier_summary", "")
    memory = state.get("memory_summary", "")
    query = state["refined_query"]

    logger.info("Node: build_final_input", extra={"session_id": session_id})

    try:
        context_block = build_context_block(
            rag_context=rag_context,
            user_facts=user_facts,
            recent_history=recent_history,
            earlier_summary=earlier_summary,
            memory=memory,
        )

        return {
            **state,
            "context_block": context_block,
            "final_input": query,
        }

    except Exception as e:
        logger.exception("build_final_input failed", extra={"session_id": session_id})
        return {
            **state,
            "context_block": "",
            "final_input": query,
            "error_info": f"final_input_build_error: {str(e)}",
        }


def generate_llm_response(state: ConversationState) -> ConversationState:
    """Generate response with full personalized context."""
    session_id = state["session_id"]
    context_block = state.get("context_block", "")
    final_input = state.get("final_input", "")

    logger.info("Node: generate_llm_response", extra={"session_id": session_id})

    try:
        from prompts import get_main_prompt

        prompt = get_main_prompt()
        chain = prompt | llm

        response = chain.invoke(
            {
                "context_block": context_block,
                "input": final_input,
            }
        )

        assistant_text = response.content

        logger.info(
            "LLM generation complete",
            extra={
                "session_id": session_id,
                "response_len": len(assistant_text),
            },
        )

        return {
            **state,
            "llm_output": assistant_text,
        }

    except Exception as e:
        logger.exception(
            "generate_llm_response failed", extra={"session_id": session_id}
        )

        fallback_msg = "ببخشید، مشکلی پیش اومد."

        return {
            **state,
            "llm_output": fallback_msg,
            "error_info": f"llm_generation_error: {str(e)}",
        }


# ============================================================================
# Conditional Edges
# ============================================================================


def should_clarify_or_proceed(state: ConversationState) -> str:
    """
    New conditional: Check if clarification is needed.
    """
    if state.get("needs_clarification", False):
        logger.debug(
            "Conditional: needs clarification -> END",
            extra={"session_id": state["session_id"]},
        )
        return "clarify"
    else:
        logger.debug(
            "Conditional: proceed to routing", extra={"session_id": state["session_id"]}
        )
        return "proceed"


def should_perform_rag(state: ConversationState) -> str:
    """Route based on classification."""
    route = state.get("route", "google")
    return route


def should_use_google_fallback(state: ConversationState) -> str:
    """Decide Google fallback after RAG."""
    rag_context = state.get("rag_context", "")
    return "build_input" if rag_context else "google"


# ============================================================================
# Graph Construction (Enhanced)
# ============================================================================


def create_conversation_graph() -> StateGraph:
    """
    Enhanced graph with clarification step and personalization.

    New flow:
    START → load_history_memory_and_facts → check_clarification_needed
      ├─ needs_clarification → END (return clarification questions)
      └─ proceed → route_and_refine_query → [existing RAG/Google/Chat paths]
    """
    workflow = StateGraph(ConversationState)

    # Add nodes
    workflow.add_node("load_history_memory_and_facts", load_history_memory_and_facts)
    workflow.add_node("check_clarification_needed", check_clarification_needed)
    workflow.add_node("route_and_refine_query", route_and_refine_query)
    workflow.add_node("perform_rag_retrieval", perform_rag_retrieval)
    workflow.add_node("check_rag_confidence", check_rag_confidence)
    workflow.add_node("perform_google_search", perform_google_search)
    workflow.add_node("build_final_input", build_final_input)
    workflow.add_node("generate_llm_response", generate_llm_response)

    # Define edges
    workflow.set_entry_point("load_history_memory_and_facts")

    workflow.add_edge("load_history_memory_and_facts", "check_clarification_needed")

    # New conditional: clarification check
    workflow.add_conditional_edges(
        "check_clarification_needed",
        should_clarify_or_proceed,
        {
            "clarify": END,  # Return clarification questions immediately
            "proceed": "route_and_refine_query",
        },
    )

    # Existing routing logic
    workflow.add_conditional_edges(
        "route_and_refine_query",
        should_perform_rag,
        {
            "rag": "perform_rag_retrieval",
            "google": "perform_google_search",
            "chat": "build_final_input",
        },
    )

    workflow.add_edge("perform_rag_retrieval", "check_rag_confidence")

    workflow.add_conditional_edges(
        "check_rag_confidence",
        should_use_google_fallback,
        {
            "google": "perform_google_search",
            "build_input": "build_final_input",
        },
    )

    workflow.add_edge("build_final_input", "generate_llm_response")

    workflow.add_edge("perform_google_search", END)
    workflow.add_edge("generate_llm_response", END)

    app = workflow.compile()

    logger.info("Enhanced LangGraph compiled with clarification + personalization")

    return app


# ============================================================================
# Export
# ============================================================================

conversation_graph = create_conversation_graph()


def evaluate_response_quality(state: ConversationState) -> ConversationState:
    """
    Evaluate generated answer quality using LLM-as-judge.
    Decides if answer is good enough or needs refinement.
    """
    session_id = state["session_id"]
    query = state["user_input_raw"]
    answer = state.get("llm_output", "")
    route = state.get("route", "unknown")
    rag_context = state.get("rag_context", "")
    iteration_count = state.get("iteration_count", 0)

    logger.info(
        "Node: evaluate_response_quality",
        extra={"session_id": session_id, "iteration": iteration_count},
    )

    try:
        # Determine context source
        if route == "google":
            context_used = "Google Search"
        elif rag_context:
            context_used = "RAG (پایگاه داده محلی)"
        else:
            context_used = "Chat (بدون زمینه خاص)"

        # Evaluate quality
        evaluation = evaluate_answer_quality(
            query=query,
            answer=answer,
            context_used=context_used,
        )

        # Store answer in history
        previous_answers = state.get("previous_answers", [])
        previous_answers.append(answer)

        logger.info(
            "Quality evaluation result",
            extra={
                "session_id": session_id,
                "iteration": iteration_count,
                "quality_score": evaluation.get("quality_score", 0),
                "issue_type": evaluation.get("issue_type", "unknown"),
                "recommendation": evaluation.get("recommendation", "unknown"),
            },
        )

        return {
            **state,
            "quality_evaluation": evaluation,
            "previous_answers": previous_answers,
            "final_quality_score": evaluation.get("quality_score", 0),
        }

    except Exception as e:
        logger.exception(
            "evaluate_response_quality failed", extra={"session_id": session_id}
        )
        # On error, assume quality is acceptable
        return {
            **state,
            "quality_evaluation": {
                "quality_score": 0.8,
                "issue_type": "good",
                "recommendation": "accept",
                "reason": "Evaluation failed",
            },
            "previous_answers": state.get("previous_answers", []) + [answer],
            "final_quality_score": 0.8,
        }


# ============================================================================
# 🆕 Node 8: Prepare Retry (NEW)
# ============================================================================


def prepare_retry_iteration(state: ConversationState) -> ConversationState:
    """
    Prepare for retry iteration by incrementing counter.
    """
    session_id = state["session_id"]
    iteration_count = state.get("iteration_count", 0)

    new_iteration = iteration_count + 1

    logger.info(
        "Node: prepare_retry_iteration",
        extra={
            "session_id": session_id,
            "iteration": new_iteration,
        },
    )

    return {
        **state,
        "iteration_count": new_iteration,
    }


# ============================================================================
# 🆕 Node 9: Finalize Answer (NEW)
# ============================================================================


def finalize_answer(state: ConversationState) -> ConversationState:
    """
    Finalize answer and save to history.
    No retry attempts are shown to user (hidden).
    """
    session_id = state["session_id"]
    llm_output = state.get("llm_output", "")
    history = state.get("history", ChatMessageHistory())
    iteration_count = state.get("iteration_count", 0)
    final_quality_score = state.get("final_quality_score", 0)

    logger.info(
        "Node: finalize_answer",
        extra={
            "session_id": session_id,
            "iterations": iteration_count,
            "final_quality": final_quality_score,
        },
    )

    try:
        # Save final answer to history (no retry disclosure)
        history.add_message(AIMessage(content=llm_output))
        save_session_history(session_id, history)

        logger.info(
            "Answer finalized",
            extra={
                "session_id": session_id,
                "total_iterations": iteration_count + 1,
                "final_quality_score": final_quality_score,
            },
        )

        return {
            **state,
            "llm_output": llm_output,
        }

    except Exception as e:
        logger.exception("finalize_answer failed", extra={"session_id": session_id})
        return state


# ============================================================================
# Conditional Edges
# ============================================================================


def should_perform_rag(state: ConversationState) -> str:
    """Route based on classification."""
    route = state.get("route", "google")
    return route


def should_use_google_fallback(state: ConversationState) -> str:
    """Decide Google fallback after RAG."""
    rag_context = state.get("rag_context", "")
    return "build_input" if rag_context else "google"


def should_retry_or_finish(state: ConversationState) -> str:
    """
    🆕 NEW: Decide if answer needs refinement or is acceptable.

    Returns:
        "retry" if should refine and retry
        "finish" if answer is acceptable or max iterations reached
    """
    iteration_count = state.get("iteration_count", 0)
    quality_evaluation = state.get("quality_evaluation", {})

    # Check max iterations
    if iteration_count >= MAX_REFINEMENT_ITERATIONS:
        logger.info(
            "Max iterations reached, finishing",
            extra={
                "session_id": state.get("session_id"),
                "iterations": iteration_count,
            },
        )
        return "finish"

    # Check if should refine
    if should_refine_answer(quality_evaluation):
        logger.info(
            "Quality gate failed, will retry",
            extra={
                "session_id": state.get("session_id"),
                "iteration": iteration_count,
                "quality_score": quality_evaluation.get("quality_score", 0),
            },
        )
        return "retry"
    else:
        logger.info(
            "Quality acceptable, finishing",
            extra={
                "session_id": state.get("session_id"),
                "quality_score": quality_evaluation.get("quality_score", 0),
            },
        )
        return "finish"


# ============================================================================
# Graph Construction with Self-Correction Loop
# ============================================================================


def create_conversation_graph() -> StateGraph:
    """
    Enhanced graph with quality gate and iterative refinement.

    Flow:
    START → load_history → route_and_refine → [RAG/Google paths]
          → generate_llm_response → evaluate_quality
          ├─ Good quality OR max iterations? → finalize → END
          └─ Poor quality? → prepare_retry → route_and_refine (loop back)
    """
    workflow = StateGraph(ConversationState)

    # Add nodes
    workflow.add_node("load_history_memory_and_facts", load_history_memory_and_facts)
    workflow.add_node("route_and_refine_query", route_and_refine_query)
    workflow.add_node("perform_rag_retrieval", perform_rag_retrieval)
    workflow.add_node("check_rag_confidence", check_rag_confidence)
    workflow.add_node("perform_google_search", perform_google_search)
    workflow.add_node("build_final_input", build_final_input)
    workflow.add_node("generate_llm_response", generate_llm_response)

    # 🆕 NEW: Quality gate nodes
    workflow.add_node("evaluate_response_quality", evaluate_response_quality)
    workflow.add_node("prepare_retry_iteration", prepare_retry_iteration)
    workflow.add_node("finalize_answer", finalize_answer)

    # Define edges
    workflow.set_entry_point("load_history_memory_and_facts")

    workflow.add_edge("load_history_memory_and_facts", "route_and_refine_query")

    # Routing logic
    workflow.add_conditional_edges(
        "route_and_refine_query",
        should_perform_rag,
        {
            "rag": "perform_rag_retrieval",
            "google": "perform_google_search",
            "chat": "build_final_input",
        },
    )

    workflow.add_edge("perform_rag_retrieval", "check_rag_confidence")

    workflow.add_conditional_edges(
        "check_rag_confidence",
        should_use_google_fallback,
        {
            "google": "perform_google_search",
            "build_input": "build_final_input",
        },
    )

    workflow.add_edge("build_final_input", "generate_llm_response")

    # 🆕 NEW: After generation, evaluate quality
    workflow.add_edge("generate_llm_response", "evaluate_response_quality")

    # 🆕 NEW: Self-correction loop
    workflow.add_conditional_edges(
        "evaluate_response_quality",
        should_retry_or_finish,
        {
            "retry": "prepare_retry_iteration",  # Poor quality → retry
            "finish": "finalize_answer",  # Good quality → finish
        },
    )

    # 🆕 NEW: Retry loop back to routing
    workflow.add_edge("prepare_retry_iteration", "route_and_refine_query")

    # Google search goes directly to quality evaluation
    workflow.add_edge("perform_google_search", "evaluate_response_quality")

    # Final answer goes to END
    workflow.add_edge("finalize_answer", END)

    app = workflow.compile()

    logger.info(
        "Self-correcting LangGraph compiled with quality gate and iterative refinement"
    )

    return app


# ============================================================================
# Export
# ============================================================================

conversation_graph = create_conversation_graph()
