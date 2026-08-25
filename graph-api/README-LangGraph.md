# LangGraph Refactor - Qeshm AI Backend

## Overview

This is a complete refactor of the Qeshm AI chatbot backend using **LangGraph** for conversation orchestration while preserving all existing FastAPI endpoints and OpenAI-compatible response formats.

## Architecture

### High-Level Flow

```
FastAPI Request (app.py)
    ↓
LangGraph StateGraph (graph.py)
    ↓
    ├─ Node: load_history_and_memory
    ├─ Node: route_and_refine_query
    ├─ Conditional Routing:
    │   ├─ "rag" → perform_rag_retrieval → check_rag_confidence
    │   │           ├─ High confidence → build_final_input → generate_llm_response
    │   │           └─ Low confidence → perform_google_search
    │   ├─ "google" → perform_google_search
    │   └─ "chat" → build_final_input → generate_llm_response
    ↓
OpenAI-Compatible Response
```

### File Structure

```
.
├── config.py           # Environment configuration (unchanged)
├── prompts.py          # System prompts and templates (unchanged)
├── utils.py            # Utilities, LLM, vector DB, reranker (unchanged)
├── graph.py            # 🆕 LangGraph state machine and nodes
└── app.py              # 🆕 FastAPI app using LangGraph
```

## Key Components

### 1. `graph.py` - LangGraph Orchestration

**ConversationState (TypedDict)**
- `session_id`: Session identifier
- `user_input_raw`: Original user query
- `messages_from_request`: Full message history from request
- `history`: ChatMessageHistory object
- `memory_summary`: LLM-generated conversation summary
- `route`: Routing decision (`"rag"`, `"google"`, or `"chat"`)
- `refined_query`: Context-aware refined query
- `rag_context`: High-confidence RAG context
- `rag_low_conf_context`: Low-confidence RAG context (for Google fallback)
- `rag_fallback_reason`: Reason for RAG failure/low confidence
- `google_answer`: Google Search response
- `final_input`: Complete input for main LLM
- `llm_output`: Final generated response
- `error_info`: Error details (if any)

**Graph Nodes**

1. **`load_history_and_memory`**
   - Loads conversation history from Redis/in-memory
   - Syncs history from incoming messages
   - Caps history length
   - Generates memory summary using `llm_summarize_memory`

2. **`route_and_refine_query`**
   - Refines user query with conversation context
   - Classifies route: `"rag"`, `"google"`, or `"chat"`
   - Uses combined LLM call for efficiency

3. **`perform_rag_retrieval`**
   - Retrieves documents from Chroma vector DB
   - Reranks using transformer model
   - Returns raw and reranked documents

4. **`check_rag_confidence`**
   - Evaluates RAG confidence using:
     - Rerank scores (threshold: > 0.05)
     - Similarity scores (threshold: < 0.7)
   - Builds high-confidence context OR low-confidence context for Google

5. **`perform_google_search`**
   - Fallback when RAG confidence is low or route is "google"
   - Uses Gemini with Google Search tool
   - Includes conversation context and low-confidence RAG context

6. **`build_final_input`**
   - Constructs final input string for main LLM
   - Combines RAG context, history summary, and user query

7. **`generate_llm_response`**
   - Calls main Gemini LLM with full context
   - Saves response to history
   - Returns final output

**Conditional Edges**

- **`should_perform_rag`**: Routes after routing decision
  - Returns `"rag"`, `"google"`, or `"chat"`

- **`should_use_google_fallback`**: Routes after RAG confidence check
  - Returns `"google"` (low confidence) or `"build_input"` (high confidence)

### 2. `app.py` - FastAPI Integration

**Key Functions**

- **`run_graph_blocking()`**: Runs graph to completion, returns final state
- **`stream_graph_execution()`**: Streams graph execution with token-by-token LLM output

**Endpoints** (Unchanged API Contract)

- `POST /v1/chat/completions` - Main chat endpoint
  - Supports `stream: true/false`
  - Returns OpenAI-compatible `ChatCompletion` or `ChatCompletionChunk` format
  
- `GET /health` - Health check
- `GET /v1/models` - Model list

**Response Formats Preserved**

```json
// Non-streaming
{
  "id": "chatcmpl-1700000000",
  "object": "chat.completion",
  "created": 1700000000,
  "model": "gemini-2.5-flash",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  }
}

// Streaming (SSE)
data: {"id":"chatcmpl-1700000000","object":"chat.completion.chunk","created":1700000000,"model":"gemini-2.5-flash","choices":[{"index":0,"delta":{"content":"..."},"finish_reason":null}]}

data: [DONE]
```

## Usage

### Installation

```bash
# Install additional dependency
pip install langgraph

# Existing dependencies (unchanged)
pip install -r requirements.txt
```

### Running the Server

```bash
# Start server
python app.py

# Server runs on port 8001 (or PORT env var)
```

### Testing

```bash
# Non-streaming request
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "رستوران‌های قشم رو معرفی کن"}
    ],
    "stream": false,
    "session_id": "test-session"
  }'

# Streaming request
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "رستوران‌های قشم رو معرفی کن"}
    ],
    "stream": true,
    "session_id": "test-session"
  }'
```

## What's Preserved

✅ **All FastAPI endpoints and response formats**  
✅ **OpenAI-compatible JSON schemas**  
✅ **Redis-based history storage (with in-memory fallback)**  
✅ **Vector DB (Chroma) and retriever configuration**  
✅ **Reranker model and logic**  
✅ **Google Search fallback**  
✅ **Conversation memory summarization**  
✅ **All prompts and system behavior**  
✅ **Structured logging with JSON format**  
✅ **Error handling and fallback messages**  
✅ **History length capping**  
✅ **Farsi text normalization**

## What Changed

🔄 **Orchestration moved from imperative code to declarative LangGraph**  
🔄 **All business logic extracted into pure node functions**  
🔄 **State management unified in `ConversationState` TypedDict**  
🔄 **Conditional routing implemented via graph edges**  
🔄 **Improved separation of concerns (orchestration vs business logic)**

## Benefits of LangGraph Architecture

1. **Modularity**: Each step is a testable node function
2. **Visibility**: Graph structure shows entire conversation flow
3. **Extensibility**: Add new nodes/routes without touching FastAPI code
4. **Debugging**: State is explicit and inspectable at each step
5. **Maintainability**: Business logic separated from orchestration
6. **Error Handling**: Isolated error handling per node
7. **Future-Ready**: Easy to add:
   - New tools (e.g., database search, API calls)
   - New routes (e.g., image analysis, audio processing)
   - Parallel execution (e.g., RAG + Google simultaneously)
   - Checkpointing (e.g., save/resume conversations)

## Adding New Features

### Example: Adding a Database Search Route

```python
# In graph.py

def perform_database_search(state: ConversationState) -> ConversationState:
    """New node: Search internal database."""
    session_id = state["session_id"]
    query = state["refined_query"]
    
    logger.info("Node: perform_database_search", extra={"session_id": session_id})
    
    # Your database search logic here
    result = search_internal_db(query)
    
    return {
        **state,
        "database_answer": result,
        "llm_output": result,
    }

# Update graph construction
workflow.add_node("perform_database_search", perform_database_search)

# Update conditional routing
workflow.add_conditional_edges(
    "route_and_refine_query",
    should_perform_rag,
    {
        "rag": "perform_rag_retrieval",
        "google": "perform_google_search",
        "database": "perform_database_search",  # New route
        "chat": "build_final_input",
    },
)

workflow.add_edge("perform_database_search", END)
```

### Example: Adding Parallel RAG + Google

```python
# Use LangGraph's parallel execution
from langgraph.graph import START

workflow.add_node("parallel_rag", perform_rag_retrieval)
workflow.add_node("parallel_google", perform_google_search)
workflow.add_node("merge_results", merge_rag_and_google_results)

workflow.add_edge("route_and_refine_query", "parallel_rag")
workflow.add_edge("route_and_refine_query", "parallel_google")
workflow.add_edge(["parallel_rag", "parallel_google"], "merge_results")
workflow.add_edge("merge_results", "build_final_input")
```

## Logging

All existing logging is preserved. Each node logs:
- Entry with context
- Success with metrics
- Errors with full traceback

Logs are structured JSON for easy parsing:

```json
{
  "asctime": "2024-01-20 18:34:22",
  "name": "qeshm-ai",
  "levelname": "INFO",
  "message": "Node: perform_rag_retrieval",
  "module": "graph",
  "funcName": "perform_rag_retrieval",
  "lineno": 123,
  "session_id": "test-session",
  "query": "رستوران‌های قشم"
}
```

## Error Handling

Each node has try-except blocks that:
1. Log the error with full context
2. Set `error_info` in state
3. Return fallback values
4. Allow graph to continue (graceful degradation)

Critical errors in FastAPI endpoint return:
- HTTP 500
- `GEOQ-Critical-Fallback` model name
- Fallback message in Persian
- Error saved to history

## Migration Notes

### Breaking Changes
**None** - All external APIs remain identical.

### Internal Changes
- Manual orchestration in `app.py` replaced with `conversation_graph.invoke()` / `.stream()`
- Helper functions (`_sync_history`, `_perform_rag`, etc.) moved to graph nodes
- State now explicit in `ConversationState` instead of local variables

### Testing Recommendations
1. Test all three routes: `rag`, `google`, `chat`
2. Test RAG high confidence vs low confidence paths
3. Test streaming vs non-streaming
4. Test error scenarios (Redis down, vector DB error, LLM timeout)
5. Test history persistence across multiple turns
6. Test memory summarization

## Performance

No performance degradation expected:
- Same LLM calls
- Same vector DB queries
- Same reranking logic
- LangGraph overhead is minimal (few milliseconds)

## Future Enhancements

With LangGraph, you can easily add:

1. **Checkpointing**: Save conversation state to resume later
   ```python
   from langgraph.checkpoint import MemorySaver
   checkpointer = MemorySaver()
   app = workflow.compile(checkpointer=checkpointer)
   ```

2. **Human-in-the-loop**: Pause execution for human approval
   ```python
   from langgraph.graph import interrupt
   
   def needs_approval(state):
       if state["confidence"] < 0.5:
           interrupt("Low confidence, needs approval")
   ```

3. **Tool calling**: Add structured tool use
   ```python
   from langchain_core.tools import tool
   
   @tool
   def get_weather(location: str) -> str:
       """Get weather for location."""
       return weather_api.get(location)
   
   workflow.add_node("use_tools", lambda state: tool_executor(state))
   ```

4. **Parallel execution**: Run multiple nodes simultaneously
5. **Subgraphs**: Nest graphs for complex workflows
6. **Dynamic routing**: Route based on LLM outputs

## Troubleshooting

### "Module 'langgraph' not found"
```bash
pip install langgraph
```

### "TypeError: TypedDict doesn't support total=False"
Update Python to 3.9+ or use:
```python
from typing_extensions import TypedDict
```

### Streaming not working
Check that `stream_graph_execution()` is yielding SSE-formatted strings:
```python
yield f"data: {json.dumps(delta)}\n\n"
```

### Graph stuck / not completing
Add debug logging to see which nodes are executing:
```python
for step in conversation_graph.stream(initial_state):
    print(f"Executed: {list(step.keys())}")
```

## License

Same as original project.

## Contributors

- Original codebase: Qeshm AI Team
- LangGraph refactor: [Your name]

## Questions?

For questions about:
- **LangGraph specifics**: See [LangGraph docs](https://langchain-ai.github.io/langgraph/)
- **Original logic**: Refer to `utils.py` and `prompts.py` (unchanged)
- **FastAPI integration**: See `app.py` comments
