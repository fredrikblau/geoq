import time
import json
from typing import List, Optional, Dict, Any, Tuple
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
import uvicorn
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.documents import Document

from utils import (
    logger,
    normalize_farsi,
    get_session_history,
    save_session_history,
    retriever,
    rerank_docs,
    build_context_from_docs,
    google_search_summary,
    improved_route,
    vector_db,
    chain_with_history,
    llm_summarize_memory,
)
from config import PORT, MAX_HISTORY_LEN

# --- FastAPI App Setup ---

app = FastAPI(title="Qeshm AI - Production (Refactored)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Models ---


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: Optional[str] = None
    messages: List[Message]
    stream: bool = True
    session_id: Optional[str] = "default"


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[Dict[str, Any]]
    usage: Dict[str, int] = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


# --- Private Helper Functions ---


def _sync_history(
    messages: List[Message], session_id: str
) -> Tuple[ChatMessageHistory, str, str]:
    """
    Loads, updates, and saves chat history.
    Returns the history object, the latest user input, and a generated memory summary.
    """
    user_input = normalize_farsi(messages[-1].content)
    history = get_session_history(session_id)
    old_len = len(history.messages)

    # Re-sync history from request (minus the last message)
    history.messages.clear()
    for msg in messages[:-1]:
        norm_content = (
            normalize_farsi(msg.content) if msg.role == "user" else msg.content
        )
        if msg.role == "user":
            history.add_message(HumanMessage(content=norm_content))
        elif msg.role == "assistant":
            history.add_message(AIMessage(content=norm_content))

    # Add the new user input
    history.add_message(HumanMessage(content=user_input))

    # Cap history length
    if len(history.messages) > MAX_HISTORY_LEN:
        history.messages = history.messages[-MAX_HISTORY_LEN:]
        logger.warning(
            "History capped",
            extra={
                "session_id": session_id,
                "new_len": len(history.messages),
                "max_len": MAX_HISTORY_LEN,
            },
        )

    save_session_history(session_id, history)  # Async save
    logger.info(
        "History synced",
        extra={
            "session_id": session_id,
            "old_len": old_len,
            "new_len": len(history.messages),
        },
    )

    # Generate memory summary from the *new* history
    memory_text = llm_summarize_memory(session_id, history)
    logger.info(
        "Memory summary generated",
        extra={
            "session_id": session_id,
            "memory_len": len(memory_text),
            "memory": memory_text,
        },
    )
    return history, user_input, memory_text


def _build_history_summary(history: ChatMessageHistory) -> str:
    """Creates a simple summary of recent user messages for context."""
    if len(history.messages) <= 1:
        return ""

    recent_user_msgs = [
        m.content for m in history.messages[-4:-1] if isinstance(m, HumanMessage)
    ]
    summary = f"\nمتن مکالمه اخیر: {' | '.join(recent_user_msgs[-2:])}"
    logger.debug("Built history summary", extra={"summary": summary})
    return summary


def _perform_rag(query: str, session_id: str) -> Tuple[str, str, List[Document]]:
    """
    Performs vector search and reranking.
    Returns: (context, rag_fallback_reason, low_confidence_docs)
    """
    context = ""
    rag_fallback_reason = ""
    low_conf_docs = []
    raw_docs = []

    try:
        logger.debug(
            "Attempting RAG retrieval", extra={"session_id": session_id, "query": query}
        )
        raw_docs = retriever.invoke(query)
        logger.info(
            "RAG retrieval complete",
            extra={"session_id": session_id, "retrieved_doc_count": len(raw_docs)},
        )

        if not raw_docs:
            rag_fallback_reason = "no_docs_found"
            logger.warning(
                "RAG found no documents",
                extra={"session_id": session_id, "query": query},
            )
            return context, rag_fallback_reason, low_conf_docs

        # Normalize docs
        for d in raw_docs:
            d.page_content = normalize_farsi(d.page_content)

        # Rerank
        reranked = rerank_docs(query, raw_docs, top_k=6)
        docs = [d for d, s in reranked]
        rerank_best_score = reranked[0][1] if reranked else 0.0
        logger.debug(
            "RAG reranking complete",
            extra={
                "session_id": session_id,
                "reranked_count": len(reranked),
                "best_score": rerank_best_score,
            },
        )

        # Similarity score check
        scored = vector_db.similarity_search_with_score(query, k=3)
        best_sim_score = min([s for _, s in scored]) if scored else 999.0
        logger.debug(
            "RAG similarity score check",
            extra={"session_id": session_id, "best_sim_score": best_sim_score},
        )

        # Confidence Check
        is_rag_confident = (
            rerank_best_score > 0.05 and best_sim_score < 0.7 and len(docs) >= 1
        )
        logger.info(
            "RAG confidence check",
            extra={
                "session_id": session_id,
                "is_confident": is_rag_confident,
                "rerank_score": rerank_best_score,
                "sim_score": best_sim_score,
            },
        )

        if is_rag_confident:
            context = build_context_from_docs(docs)
            logger.info(
                "RAG context built (high confidence)",
                extra={"session_id": session_id, "context_chars": len(context)},
            )
        else:
            low_conf_docs = docs[:3] if docs else raw_docs[:3]
            rag_fallback_reason = f"low_confidence (rerank={rerank_best_score:.3f}, sim={best_sim_score:.3f})"
            logger.warning(
                "RAG low confidence",
                extra={"session_id": session_id, "reason": rag_fallback_reason},
            )

    except Exception as e:
        rag_fallback_reason = f"rag_exception: {str(e)}"
        logger.exception(
            "RAG pipeline failed", extra={"session_id": session_id, "query": query}
        )

    return context, rag_fallback_reason, low_conf_docs


def _handle_google_search(
    session_id: str,
    query: str,
    memory_text: str,
    history: ChatMessageHistory,
    rag_context_low: str,
    fallback_reason: str,
) -> ChatCompletionResponse:
    """
    Attempts to answer the query using Google Search as a fallback.
    Returns a complete ChatCompletionResponse.
    """
    logger.info(
        "Attempting Google Search fallback",
        extra={"session_id": session_id, "reason": fallback_reason, "query": query},
    )
    try:
        hist_summary = _build_history_summary(history)
        google_answer = google_search_summary(
            query=query,
            history_summary=f"{memory_text} | {hist_summary}",
            full_history=history.messages,
            rag_context=rag_context_low,
        )

        # Save the Google answer to history
        history.add_message(AIMessage(content=google_answer))
        save_session_history(session_id, history)
        logger.info(
            "Google Search successful",
            extra={
                "session_id": session_id,
                "response_len": len(google_answer),
                "response": google_answer,
            },
        )

        return ChatCompletionResponse(
            id=f"chatcmpl-{int(time.time())}",
            created=int(time.time()),
            model="gemini-2.5-flash (Google Search)",
            choices=[
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": google_answer},
                    "finish_reason": "stop",
                }
            ],
        )

    except Exception as e:
        logger.exception(
            "Google Search fallback failed",
            extra={"session_id": session_id, "error": str(e)},
        )
        fallback_msg = "متاسفانه نتونستم اطلاعات رو پیدا کنم. می‌تونی جزئیات بیشتری بدی؟"
        # Save failure message to history
        history.add_message(AIMessage(content=fallback_msg))
        save_session_history(session_id, history)

        return ChatCompletionResponse(
            id=f"chatcmpl-{int(time.time())}",
            created=int(time.time()),
            model="GEOQ-Fallback",
            choices=[
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": fallback_msg},
                    "finish_reason": "stop",
                }
            ],
        )


async def _stream_llm_response(
    cmpl_id: str,
    created: int,
    session_id: str,
    final_input: str,
    memory_text: str,
    history: ChatMessageHistory,
    route: str,
):
    """Yields SSE chunks for a streaming response."""
    full_content = ""
    try:
        logger.debug(
            "Starting stream generation",
            extra={"session_id": session_id, "route": route},
        )
        for chunk in chain_with_history.stream(
            {"input": final_input, "memory": memory_text},
            config={"configurable": {"session_id": session_id}},
        ):
            content_chunk = chunk.content if hasattr(chunk, "content") else str(chunk)
            full_content += content_chunk
            delta = {
                "id": cmpl_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": "gemini-2.5-flash",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": content_chunk},
                        "finish_reason": None,
                    }
                ],
            }
            yield f"data: {json.dumps(delta)}\n\n"

        # End of stream
        yield f"data: {json.dumps({'id': cmpl_id, 'object': 'chat.completion.chunk', 'created': created, 'model': 'gemini-2.5-flash', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
        yield "data: [DONE]\n\n"

    except Exception as e:
        logger.exception(
            "Stream generation failed",
            extra={"session_id": session_id, "error": str(e)},
        )
        full_content = "ببخشید، مشکلی پیش اومد."
        error_delta = {
            "id": cmpl_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": "gemini-2.5-flash",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": full_content},
                    "finish_reason": "stop",
                }
            ],
        }
        yield f"data: {json.dumps(error_delta)}\n\n"
        yield "data: [DONE]\n\n"

    finally:
        # Save full response to history *after* stream completes
        history.add_message(AIMessage(content=full_content))
        save_session_history(session_id, history)
        logger.info(
            "Stream generation complete",
            extra={
                "session_id": session_id,
                "route": route,
                "response_len": len(full_content),
                "response": full_content,
            },
        )


def _blocking_llm_response(
    cmpl_id: str,
    created: int,
    session_id: str,
    final_input: str,
    memory_text: str,
    history: ChatMessageHistory,
    route: str,
) -> ChatCompletionResponse:
    """Generates a non-streaming blocking response."""
    logger.debug(
        "Starting blocking generation", extra={"session_id": session_id, "route": route}
    )
    response = chain_with_history.invoke(
        {"input": final_input, "memory": memory_text},
        config={"configurable": {"session_id": session_id}},
    )
    assistant_text = response.content

    # Save response to history
    history.add_message(AIMessage(content=assistant_text))
    save_session_history(session_id, history)
    logger.info(
        "Blocking generation complete",
        extra={
            "session_id": session_id,
            "route": route,
            "response_len": len(assistant_text),
            "response": assistant_text,
        },
    )

    return ChatCompletionResponse(
        id=cmpl_id,
        created=created,
        model="gemini-2.5-flash",
        choices=[
            {
                "index": 0,
                "message": {"role": "assistant", "content": assistant_text},
                "finish_reason": "stop",
            }
        ],
    )


# --- FastAPI Endpoints ---


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    """Main chat endpoint (streaming or blocking)."""
    if not req.messages:
        logger.warning("Empty messages list received")
        raise HTTPException(status_code=400, detail="Messages list is required")

    session_id = req.session_id or "default"
    logger.info(
        "Received chat request",
        extra={
            "session_id": session_id,
            "stream": req.stream,
            "message_count": len(req.messages),
            "user_input": req.messages[-1].content,
        },
    )

    try:
        # 1. Sync History & Get Memory
        history, user_input, memory_text = _sync_history(req.messages, session_id)

        # 2. Determine Route
        route = improved_route(user_input, memory_text)
        logger.info(
            "Routing decision made",
            extra={"session_id": session_id, "route": route, "query": user_input},
        )

        # 3. Perform RAG (if applicable)
        context = ""
        rag_context_low = ""
        rag_fallback_reason = ""

        if route == "rag":
            context, rag_fallback_reason, low_conf_docs = _perform_rag(
                user_input, session_id
            )
            if low_conf_docs:
                rag_context_low = build_context_from_docs(low_conf_docs, max_chars=1500)
                logger.debug(
                    "Built low-confidence RAG context for Google",
                    extra={"session_id": session_id, "chars": len(rag_context_low)},
                )

        # 4. Fallback to Google Search (if RAG failed or wasn't used)
        if not context and route != "chat":
            response = _handle_google_search(
                session_id=session_id,
                query=user_input,
                memory_text=memory_text,
                history=history,
                rag_context_low=rag_context_low,
                fallback_reason=rag_fallback_reason or f"route_was_{route}",
            )
            return JSONResponse(content=response.model_dump())

        # 5. Prepare Final LLM Input & Generate Response
        hist_summary = _build_history_summary(history)
        final_input = f"{context}\n{hist_summary}\nسوال کاربر: {user_input}".strip()

        logger.debug(
            "Preparing final LLM input",
            extra={
                "session_id": session_id,
                "route": route,
                "final_input_len": len(final_input),
                "context_len": len(context),
                "history_summary_len": len(hist_summary),
                "memory_len": len(memory_text),
                "final_input": final_input,
            },
        )

        cmpl_id = f"chatcmpl-{int(time.time())}"
        created = int(time.time())

        if req.stream:
            return StreamingResponse(
                _stream_llm_response(
                    cmpl_id,
                    created,
                    session_id,
                    final_input,
                    memory_text,
                    history,
                    route,
                ),
                media_type="text/event-stream",
            )
        else:
            response = _blocking_llm_response(
                cmpl_id, created, session_id, final_input, memory_text, history, route
            )
            return JSONResponse(content=response.dict())

    except Exception as e:
        logger.critical(
            "Unhandled exception in chat_completions",
            extra={
                "session_id": session_id,
                "error": str(e),
                "user_input": req.messages[-1].content,
            },
        )

        # Generic fallback for unexpected errors
        fallback_msg = "ببخشید، مشکلی پیش اومد. می‌تونی سوالت رو دوباره بپرسی؟"

        # Try to save the error to history
        try:
            history = get_session_history(session_id)
            history.add_message(AIMessage(content=fallback_msg))
            save_session_history(session_id, history)
        except Exception as hist_e:
            logger.error(
                "Failed to save fallback message to history",
                extra={"session_id": session_id, "error": str(hist_e)},
            )

        response = ChatCompletionResponse(
            id=f"chatcmpl-{int(time.time())}",
            created=int(time.time()),
            model="GEOQ-Critical-Fallback",
            choices=[
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": fallback_msg},
                    "finish_reason": "error",
                }
            ],
        )
        return JSONResponse(content=response.dict(), status_code=500)


@app.get("/health")
async def health():
    """Health check endpoint."""
    logger.debug("Health check invoked")
    return {"status": "ok", "model": "GEOQ"}


@app.get("/v1/models")
async def list_models():
    """OpenAI-compatible model list endpoint."""
    logger.debug("Model list invoked")
    return {
        "object": "list",
        "data": [
            {
                "id": "GEOQ",
                "object": "model",
                "created": 1677610602,
                "owned_by": "qeshm-ai",
            }
        ],
    }


# --- Main Entry Point ---

if __name__ == "__main__":
    logger.info(f"Starting Qeshm AI server on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
