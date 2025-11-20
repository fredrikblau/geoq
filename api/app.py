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
    Streams the LangGraph execution and yields SSE chunks.
    """
    # Prepare initial state
    initial_state: ConversationState = {
        "session_id": session_id,
        "user_input_raw": user_input,
        "messages_from_request": [msg.dict() for msg in messages],
        "is_streaming": True,
        "completion_id": cmpl_id,
        "created_timestamp": created,
    }

    logger.info(
        "Starting graph execution (streaming)",
        extra={"session_id": session_id, "user_input": user_input},
    )

    full_content = ""
    route = "unknown"

    try:
        # Run the graph step by step
        state = initial_state
        for step_output in conversation_graph.stream(state):
            for node_name, node_state in step_output.items():
                state = node_state

                # Check if we've reached Google search node
                if node_name == "perform_google_search" and node_state.get(
                    "google_answer"
                ):
                    answer = node_state["google_answer"]
                    route = "google"

                    # Yield the answer in chunks
                    chunk_size = 50
                    for i in range(0, len(answer), chunk_size):
                        chunk_text = answer[i : i + chunk_size]
                        full_content += chunk_text

                        delta = {
                            "id": cmpl_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": "gemini-2.5-flash (Google Search)",
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": chunk_text},
                                    "finish_reason": None,
                                }
                            ],
                        }
                        yield f"data: {json.dumps(delta)}\n\n"

                    # End of stream
                    yield f"data: {json.dumps({'id': cmpl_id, 'object': 'chat.completion.chunk', 'created': created, 'model': 'gemini-2.5-flash', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                # Check if we've reached LLM generation node
                if node_name == "build_final_input":
                    # We have the final_input ready, now stream the LLM
                    final_input = node_state.get("final_input", "")
                    context_block = node_state.get("context_block", "")
                    clarification_suggestions = node_state.get(
                        "clarification_questions", ""
                    )
                    route = node_state.get("route", "unknown")
                    history = node_state.get("history")

                    logger.debug(
                        "Starting LLM stream generation",
                        extra={"session_id": session_id, "route": route},
                    )

                    # Build the prompt and stream directly from LLM

                    prompt = get_main_prompt()
                    chain = prompt | llm

                    # Stream the LLM output
                    for chunk in chain.stream(
                        {
                            "context_block": context_block,
                            "input": final_input,
                        }
                    ):
                        content_chunk = (
                            chunk.content if hasattr(chunk, "content") else str(chunk)
                        )
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

                    # Append and stream clarification suggestions if available
                    if clarification_suggestions:
                        suggestion_text = f"\n\n{clarification_suggestions}"
                        full_content += suggestion_text

                        # Stream the suggestions
                        chunk_size = 50
                        for i in range(0, len(suggestion_text), chunk_size):
                            chunk_text = suggestion_text[i : i + chunk_size]

                            delta = {
                                "id": cmpl_id,
                                "object": "chat.completion.chunk",
                                "created": created,
                                "model": "gemini-2.5-flash",
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {"content": chunk_text},
                                        "finish_reason": None,
                                    }
                                ],
                            }
                            yield f"data: {json.dumps(delta)}\n\n"

                    # Save the full response to history
                    if history:
                        history.add_message(AIMessage(content=full_content))
                        save_session_history(session_id, history)

                    logger.info(
                        "Stream generation complete",
                        extra={
                            "session_id": session_id,
                            "route": route,
                            "response_len": len(full_content),
                            "has_suggestions": bool(clarification_suggestions),
                        },
                    )

                    # End of stream
                    yield f"data: {json.dumps({'id': cmpl_id, 'object': 'chat.completion.chunk', 'created': created, 'model': 'gemini-2.5-flash', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
                    yield "data: [DONE]\n\n"
                    return

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
                model_name = "GEOQ-Critical-Fallback"
            elif route == "google" or final_state.get("google_answer"):
                model_name = "gemini-2.5-flash (Google Search)"
            else:
                model_name = "gemini-2.5-flash"

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


# ============================================================================
# Health & Model Endpoints (Unchanged)
# ============================================================================


@app.get("/health")
async def health():
    """Health check endpoint."""
    logger.debug("Health check invoked")
    return {"status": "ok", "model": "GEOQ", "orchestration": "LangGraph"}


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
