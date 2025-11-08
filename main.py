# main.py - OpenWebUI + Chat History (Modern LangChain v0.2+)
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.runnables import RunnableWithMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory
from dotenv import load_dotenv
import os
from fastapi.middleware.cors import CORSMiddleware
from langchain_community.vectorstores import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings

# Load vector DB


# -------------------------------
# Load API Key
# -------------------------------
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not set in .env")

# -------------------------------
# LLM
# -------------------------------
from langchain_community.embeddings import SentenceTransformerEmbeddings

embeddings = SentenceTransformerEmbeddings(
    model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
vector_db = Chroma(persist_directory="qeshm_db", embedding_function=embeddings)
retriever = vector_db.as_retriever(search_kwargs={"k": 3}, search_type="mmr")
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash", google_api_key=GEMINI_API_KEY, temperature=0.2
)

# -------------------------------
# Prompt Template (Modern)
# -------------------------------
prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
You are a friendly, local AI assistant for Qeshm Island, Iran.
Your goal is to give accurate, up-to-date, and concise answers in Farsi.
Keep your tone warm, conversational, and local — like someone from Qeshm who knows the area well.
Always:

Answer briefly but clearly.

Offer to help further by suggesting related questions or follow-up topics.

Use the latest available information from the web when relevant.

Avoid overly formal or academic language — speak like a helpful local friend.

Focus on Qeshm’s culture, events, attractions, transportation, weather, businesses, and daily life.
     
If you don't know the answer clearly say that.
    """,
        ),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{input}"),
    ]
)

# -------------------------------
# Chain + Memory (Modern)
# -------------------------------
chain = prompt | llm

# In-memory store for session history
store = {}  # {session_id: ChatMessageHistory}


def get_session_history(session_id: str):
    if session_id not in store:
        store[session_id] = ChatMessageHistory()
    return store[session_id]


# Runnable with history
chain_with_history = RunnableWithMessageHistory(
    chain,
    get_session_history,
    input_messages_key="input",
    history_messages_key="history",
)

# -------------------------------
# FastAPI App
# -------------------------------
app = FastAPI(title="Qeshm AI - با حافظه (LangChain v0.2+)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------------
# Request Schema
# -------------------------------
class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: Optional[str] = None
    messages: List[Message]
    stream: Optional[bool] = False
    session_id: Optional[str] = "default"  # OpenWebUI can send this


# -------------------------------
# /v1/chat/completions
# -------------------------------
@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    if not req.messages:
        raise HTTPException(status_code=400, detail="Messages required")

    # Use last message as input
    user_input = req.messages[-1].content
    session_id = req.session_id or "default"

    # Build history from OpenWebUI messages
    history = get_session_history(session_id)
    history.messages.clear()  # Sync with OpenWebUI

    for msg in req.messages[:-1]:  # All but last
        if msg.role == "user":
            history.add_message(HumanMessage(content=msg.content))
        elif msg.role == "assistant":
            history.add_message(AIMessage(content=msg.content))

    try:
        docs = retriever.invoke(user_input)
        context = "\n\n".join([d.page_content for d in docs])
        print(context)
        final_input = f"""
{context}

سوال کاربر: {user_input}
"""
        response = chain_with_history.invoke(
            {"input": final_input},
            config={"configurable": {"session_id": session_id}},
            tools=[{"google_search": {}}],
        )

        # Save assistant response
        history.add_message(AIMessage(content=response.content))

        return {
            "id": f"chatcmpl-{int(os.times()[4])}",
            "object": "chat.completion",
            "created": int(os.times()[4]),
            "model": "gemini-1.5-flash",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": response.content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 200,
                "completion_tokens": 300,
                "total_tokens": 400,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------
# /v1/models
# -------------------------------
@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": "gemini-1.5-flash",
                "object": "model",
                "created": 1677610602,
                "owned_by": "qeshm-ai",
            }
        ],
    }


# -------------------------------
# Run
# -------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
