"""
app.py - FastAPI application with LangGraph orchestration

This module:
- Exposes OpenAI-compatible /v1/chat/completions endpoint
- Uses LangGraph (graph.py) for conversation orchestration
- Preserves all existing API contracts and response formats
- Supports both streaming and non-streaming responses
"""

import time
import json
import asyncio
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
import uvicorn

from utils import (
    logger,
    normalize_farsi,
    chain_with_history,
    get_session_history,
    save_session_history,
    llm,
)
from langchain_core.messages import AIMessage
from config import PORT
from prompts import get_main_prompt

# Import the compiled LangGraph conversation graph
from graph import conversation_graph, ConversationState


# ============================================================================
# FastAPI App Setup
# ============================================================================

app = FastAPI(title="Qeshm AI - LangGraph Production")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Pydantic Models (Unchanged - OpenAI Compatible)
# ============================================================================


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


# ============================================================================
# Helper: Run Graph (Non-Streaming)
# ============================================================================


def run_graph_blocking(
    session_id: str,
    messages: List[Message],
    user_input: str,
) -> ConversationState:
    """
    Runs the LangGraph conversation graph to completion (blocking).

    Args:
        session_id: Session identifier
        messages: List of messages from request
        user_input: Normalized user input

    Returns:
        Final ConversationState with llm_output populated
    """
    # Prepare initial state
    initial_state: ConversationState = {
        "session_id": session_id,
        "user_input_raw": user_input,
        "messages_from_request": [msg.dict() for msg in messages],
        "is_streaming": False,
        "completion_id": f"chatcmpl-{int(time.time())}",
        "created_timestamp": int(time.time()),
    }

    logger.info(
        "Starting graph execution (blocking)",
        extra={"session_id": session_id, "user_input": user_input},
    )

    try:
        # Invoke the graph (runs until END node)
        final_state = conversation_graph.invoke(initial_state)

        logger.info(
            "Graph execution complete (blocking)",
            extra={
                "session_id": session_id,
                "route": final_state.get("route"),
                "has_llm_output": bool(final_state.get("llm_output")),
                "has_error": bool(final_state.get("error_info")),
            },
        )

        return final_state

    except Exception as e:
        logger.exception(
            "Graph execution failed (blocking)",
            extra={"session_id": session_id, "error": str(e)},
        )

        # Return a fallback state
        return {
            **initial_state,
            "llm_output": "ببخشید، مشکلی پیش اومد. میتونی سوالت رو دوباره بپرسی؟",
            "error_info": f"graph_execution_error: {str(e)}",
        }


# ============================================================================
# Helper: Stream Graph Execution
# ============================================================================


async def stream_graph_execution(
    session_id: str,
    messages: List[Message],
    user_input: str,
    cmpl_id: str,
    created: int,
):
    """
    Streams minimal, user-friendly <think> logs and ensures the final answer
    is streamed only once.
    """
    full_content = ""
    is_thinking_open = False
    # <--- THE FIX: New flag to prevent response duplication --->
    has_final_answer_streamed = False

    # Minimalist status messages - Only for major steps
    FRIENDLY_STATUSES = {
        "load_history_memory_and_facts": "در حال فکر کردن روی سوالت و مرور مکالمه قبلی هستم...",
        "perform_rag_retrieval": "در حال جمع آوری اطلاعات هستم...",
        "perform_google_search": "در حال جستجو در اینترنت هستم...",
        "generate_llm_response": "نتایج را بررسی می‌کنم و بهترین پاسخ را پیدا می‌کنم...",
        "finalize_answer": "تقریباً آماده است...",  # Added for a visible final step
    }

    try:
        # 1. Initialize State
        initial_state = {
            "session_id": session_id,
            "user_input_raw": user_input,
            "messages_from_request": [m.dict() for m in messages],
            "is_streaming": True,
            "completion_id": cmpl_id,
            "created_timestamp": created,
        }

        # 2. Open the <think> tag (Static start)
        start_think_chunk = {
            "id": cmpl_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": "geoq-0",
            "choices": [
                {"index": 0, "delta": {"content": "<think>\n"}, "finish_reason": None}
            ],
        }
        yield f"data: {json.dumps(start_think_chunk)}\n\n"
        is_thinking_open = True

        # 3. Stream LangGraph steps
        async for step_output in conversation_graph.astream(initial_state):
            for node_name, node_state in step_output.items():

                # --- Logic A: Minimal Thinking Logs ---
                # Only update if the node is in our friendly list
                status_msg = FRIENDLY_STATUSES.get(node_name)

                if status_msg and not has_final_answer_streamed:
                    log_chunk = {
                        "id": cmpl_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": "geoq-0",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": f"> {status_msg}\n"},
                                "finish_reason": None,
                            }
                        ],
                    }
                    yield f"data: {json.dumps(log_chunk)}\n\n"
                    await asyncio.sleep(0.01)

                # --- Logic B: Handle Final Output (Stream Only Once) ---

                llm_output = node_state.get("llm_output")

                # Check for final answers (Clarification, Google Answer, or Final LLM)
                is_clarification = (
                    node_name == "check_clarification_needed"
                    and node_state.get("needs_clarification")
                )
                is_google_direct = (
                    node_name == "perform_google_search"
                    and node_state.get("google_answer")
                )
                is_final_node = node_name == "finalize_answer"

                if (
                    llm_output
                    and (is_final_node or is_clarification or is_google_direct)
                    and not has_final_answer_streamed  # <--- THE CRITICAL CHECK
                ):

                    # 1. Close <think>
                    if is_thinking_open:
                        close_think = {
                            "id": cmpl_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": "geoq-0",
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": "\n</think>\n\n"},
                                    "finish_reason": None,
                                }
                            ],
                        }
                        yield f"data: {json.dumps(close_think)}\n\n"
                        is_thinking_open = False

                    # 2. Stream the Answer
                    # Split into chunks for "typing" effect
                    chunk_size = 30
                    for i in range(0, len(llm_output), chunk_size):
                        chunk_text = llm_output[i : i + chunk_size]
                        content_delta = {
                            "id": cmpl_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": "geoq-0",
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": chunk_text},
                                    "finish_reason": None,
                                }
                            ],
                        }
                        yield f"data: {json.dumps(content_delta)}\n\n"
                        await asyncio.sleep(0.01)

                    # 3. Mark as streamed
                    has_final_answer_streamed = True
                    full_content = llm_output

        # 4. Finish Stream safely
        # Note: If has_final_answer_streamed is True, we only need the DONE signal.
        if is_thinking_open:
            yield f"data: {json.dumps({'choices': [{'delta': {'content': '</think>'}}]})}\n\n"

        stop_delta = {
            "id": cmpl_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": "geoq-0",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(stop_delta)}\n\n"
        yield "data: [DONE]\n\n"

    except Exception as e:
        logger.exception(
            "stream_graph_execution failed",
            extra={"session_id": session_id, "error": str(e)},
        )
        if is_thinking_open:
            yield f"data: {json.dumps({'choices': [{'delta': {'content': f'\nError: {e}</think>'}}]})}\n\n"

        err_chunk = {
            "id": cmpl_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": "geoq-0",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": "ببخشید، مشکلی پیش اومد."},
                    "finish_reason": "stop",
                }
            ],
        }
        yield f"data: {json.dumps(err_chunk)}\n\n"
        yield "data: [DONE]\n\n"


# ============================================================================
# Main Endpoint: /v1/chat/completions
# ============================================================================


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    """
    Main chat endpoint (streaming or blocking) using LangGraph orchestration.

    This endpoint:
    - Validates the request
    - Normalizes the user input
    - Invokes the LangGraph conversation graph
    - Returns OpenAI-compatible responses (streaming or non-streaming)
    """
    if not req.messages:
        logger.warning("Empty messages list received")
        raise HTTPException(status_code=400, detail="Messages list is required")

    session_id = req.session_id or "default"
    user_input = normalize_farsi(req.messages[-1].content)

    logger.info(
        "Received chat request",
        extra={
            "session_id": session_id,
            "stream": req.stream,
            "message_count": len(req.messages),
            "user_input": user_input,
        },
    )

    cmpl_id = f"chatcmpl-{int(time.time())}"
    created = int(time.time())

    try:
        if req.stream:
            # Streaming response
            return StreamingResponse(
                stream_graph_execution(
                    session_id=session_id,
                    messages=req.messages,
                    user_input=user_input,
                    cmpl_id=cmpl_id,
                    created=created,
                ),
                media_type="text/event-stream",
            )
        else:
            # Non-streaming (blocking) response
            final_state = run_graph_blocking(
                session_id=session_id,
                messages=req.messages,
                user_input=user_input,
            )

            # Extract output and route
            llm_output = final_state.get("llm_output", "ببخشید، مشکلی پیش اومد.")
            route = final_state.get("route", "unknown")
            error_info = final_state.get("error_info")

            # Determine model name based on route
            if error_info:
                model_name = "Geoq-Critical-Fallback"
            elif route == "google" or final_state.get("google_answer"):
                model_name = "Geoq (Google Search)"
            else:
                model_name = "Geoq"

            response = ChatCompletionResponse(
                id=cmpl_id,
                created=created,
                model=model_name,
                choices=[
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": llm_output},
                        "finish_reason": "stop" if not error_info else "error",
                    }
                ],
            )

            return JSONResponse(content=response.dict())

    except Exception as e:
        logger.critical(
            "Unhandled exception in chat_completions",
            extra={
                "session_id": session_id,
                "error": str(e),
                "user_input": user_input,
            },
        )

        # Generic fallback for unexpected errors
        fallback_msg = "ببخشید، مشکلی پیش اومد. میتونی سوالت رو دوباره بپرسی؟"

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
            model="Geoq-Critical-Fallback",
            choices=[
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": fallback_msg},
                    "finish_reason": "error",
                }
            ],
        )

        return JSONResponse(content=response.dict(), status_code=500)


# ============================================================================
# Health & Model Endpoints (Unchanged)
# ============================================================================


@app.get("/health")
async def health():
    """Health check endpoint."""
    logger.debug("Health check invoked")
    return {"status": "ok", "model": "geoq-0", "orchestration": "LangGraph"}


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


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    logger.info(f"Starting Qeshm AI server with LangGraph on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
