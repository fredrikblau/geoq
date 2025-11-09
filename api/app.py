import time
import json
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import uvicorn
from langchain_core.messages import HumanMessage, AIMessage
from utils import (
    logger,
    normalize_farsi,
    get_session_history,
    save_session_history,
    simple_summarize_memory,
    retriever,
    rerank_docs,
    build_context_from_docs,
    google_search_summary,
    improved_route,
    vector_db,
    chain_with_history,
    MAX_CONTEXT_CHARS,
    llm_summarize_memory,
)
from config import PORT

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
    stream: bool = True
    session_id: Optional[str] = "default"


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    if not req.messages:
        raise HTTPException(status_code=400, detail="Messages required")
    last_msg = req.messages[-1]
    session_id = req.session_id or "default"
    user_input = normalize_farsi(last_msg.content)
    history = get_session_history(session_id)
    old_len = len(history.messages)
    history.messages.clear()
    for msg in req.messages[:-1]:
        norm_content = (
            normalize_farsi(msg.content) if msg.role == "user" else msg.content
        )
        if msg.role == "user":
            history.add_message(HumanMessage(content=norm_content))
        elif msg.role == "assistant":
            history.add_message(AIMessage(content=norm_content))
    history.add_message(HumanMessage(content=user_input))
    save_session_history(session_id, history)  # Async
    logger.info(
        f"History synced: old={old_len}, new={len(history.messages)} | session={session_id}"
    )
    if len(history.messages) > 20:
        history.messages = history.messages[-20:]
        logger.warning(f"History capped to 20 msgs for session {session_id}")
    memory_text = llm_summarize_memory(session_id, history)
    route = improved_route(user_input, memory_text)
    logger.info(
        f"ROUTE: {route} | query='{user_input}' | memory={memory_text} | hist={history.messages}"
    )  # Full query
    docs = []
    context = ""
    rag_fallback_reason = ""
    hist_summary = ""
    rag_context_low = ""
    if len(history.messages) > 1:
        recent_user = [
            m.content for m in history.messages[-4:-1] if isinstance(m, HumanMessage)
        ]
        hist_summary = f"\nمتن مکالمه اخیر: {' | '.join(recent_user[-2:])}"
    if route == "rag":
        try:
            raw_docs = retriever.invoke(user_input)
            logger.info(f"retriever.invoke {raw_docs}")
            if raw_docs:
                for d in raw_docs:
                    d.page_content = normalize_farsi(d.page_content)
                reranked = rerank_docs(user_input, raw_docs, top_k=6)
                docs = [d for d, s in reranked]
                rerank_best = reranked[0][1] if reranked else 0.0
                scored = vector_db.similarity_search_with_score(user_input, k=3)
                best_sim = min([s for _, s in scored]) if scored else 999
                rag_confident = rerank_best > 0.05 and best_sim < 0.7 and len(docs) >= 1
                if rag_confident:
                    context = build_context_from_docs(docs)
                    logger.info(
                        f"RAG confident: rerank={rerank_best:.3f} | sim={best_sim:.3f} | context={context}"
                    )
                else:
                    low_docs = docs[:3] if docs else raw_docs[:3]
                    rag_context_low = build_context_from_docs(low_docs, max_chars=1500)
                    rag_fallback_reason = f"low_conf (rerank={rerank_best:.3f}) | rag context low {rag_context_low}"
                    logger.info(f"RAG low-conf: using partial context for Google")
            else:
                rag_fallback_reason = "no_docs"
                logger.info("RAG no docs → Google")
        except Exception as e:
            rag_fallback_reason = f"exception: {str(e)}"
            logger.exception(f"RAG failed: {e}")
    if not context and route != "chat":
        try:
            google_answer = google_search_summary(
                query=user_input,
                history_summary=f"{memory_text} | {hist_summary}",
                full_history=history.messages,
                rag_context=rag_context_low,
            )
            history.add_message(AIMessage(content=google_answer))
            save_session_history(session_id, history)
            logger.info(f"Google used: reason='{rag_fallback_reason}'")
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
            logger.exception(f"Google fallback failed: {e}")
            fallback_msg = (
                "متاسفانه نتونستم اطلاعات رو پیدا کنم. می‌تونی جزئیات بیشتری بدی؟"
            )
            history.add_message(AIMessage(content=fallback_msg))
            return {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "GEOQ",
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
    final_input = f"{context}\n{hist_summary}\nسوال کاربر: {user_input}".strip()
    logger.debug(
        "LLM input",
        extra={
            "final_input": final_input,
            "memory_text": memory_text,
            "session_id": session_id,
        },
    )  # Full
    try:
        cmpl_id = f"chatcmpl-{int(time.time())}"
        created = int(time.time())
        if req.stream:

            async def stream_generator():
                full_content = ""
                try:
                    for chunk in chain_with_history.stream(
                        {"input": final_input, "memory": memory_text},
                        config={"configurable": {"session_id": session_id}},
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
                    yield f"data: {json.dumps({'id': cmpl_id, 'object': 'chat.completion.chunk', 'created': created, 'model': 'gemini-2.5-flash', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
                    yield "data: [DONE]\n\n"
                except Exception as e:
                    logger.exception(f"Stream failed: {e}")
                    error_delta = {
                        "id": cmpl_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": "gemini-2.5-flash",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": "ببخشید، مشکلی پیش اومد."},
                                "finish_reason": "stop",
                            }
                        ],
                    }
                    yield f"data: {json.dumps(error_delta)}\n\n"
                    yield "data: [DONE]\n\n"
                    full_content = "ببخشید، مشکلی پیش اومد."
                history.add_message(AIMessage(content=full_content))
                save_session_history(session_id, history)
                simple_summarize_memory(session_id, history)
                logger.info(
                    "LLM streamed output",
                    extra={
                        "full_response": full_content,
                        "length": len(full_content),
                        "route": route,
                    },
                )  # Full post-stream

            return StreamingResponse(stream_generator(), media_type="text/event-stream")
        else:
            response = chain_with_history.invoke(
                {"input": final_input, "memory": memory_text},
                config={
                    "configurable": {"session_id": session_id}
                },  # Removed undefined handler
            )
            assistant_text = response.content
            history.add_message(AIMessage(content=assistant_text))
            save_session_history(session_id, history)
            simple_summarize_memory(session_id, history)
            logger.info(
                f"Generation complete: route={route} | response_len={len(assistant_text)}"
            )
            logger.info(
                "LLM output",
                extra={
                    "response": assistant_text,
                    "length": len(assistant_text),
                    "route": route,
                },
            )  # Full
            return {
                "id": cmpl_id,
                "object": "chat.completion",
                "created": created,
                "model": "gemini-2.5-flash",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": assistant_text},
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
        logger.exception(f"Generation failed: {e}")
        fallback_msg = "ببخشید، مشکلی پیش اومد. می‌تونی سوالت رو دوباره بپرسی؟"
        history.add_message(AIMessage(content=fallback_msg))
        save_session_history(session_id, history)
        logger.error(
            "Fallback triggered", extra={"reason": str(e), "query": user_input}
        )  # Full
        if req.stream:

            async def error_stream():
                yield f"data: {json.dumps({'id': f'chatcmpl-{int(time.time())}', 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': 'GEOQ', 'choices': [{'index': 0, 'delta': {'content': fallback_msg}, 'finish_reason': 'stop'}]})}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(error_stream(), media_type="text/event-stream")
        else:
            return {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "GEOQ",
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


@app.get("/health")
async def health():
    return {"status": "ok", "model": "GEOQ"}


@app.get("/v1/models")
async def list_models():
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


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
