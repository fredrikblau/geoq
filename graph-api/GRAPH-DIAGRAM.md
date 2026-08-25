# LangGraph Flow Diagram

## Complete Conversation Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI Request                          │
│                  POST /v1/chat/completions                      │
│         {messages: [...], stream: bool, session_id}             │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    LangGraph State Initialization                │
│  ConversationState = {                                           │
│    session_id, user_input_raw, messages_from_request,          │
│    is_streaming, completion_id, created_timestamp, ...          │
│  }                                                               │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│               NODE 1: load_history_and_memory                    │
│                                                                  │
│  • Load history from Redis/in-memory                             │
│  • Sync with incoming messages                                   │
│  • Cap history length (MAX_HISTORY_LEN)                          │
│  • Generate memory summary (llm_summarize_memory)                │
│                                                                  │
│  Output: history, memory_summary                                 │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│              NODE 2: route_and_refine_query                      │
│                                                                  │
│  • Refine query with conversation context                        │
│  • Classify route using LLM:                                     │
│    - "rag": Local knowledge needed                               │
│    - "google": Fresh/external info needed                        │
│    - "chat": Casual conversation                                 │
│                                                                  │
│  Output: route, refined_query                                    │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
                   ┌─────────┴─────────┐
                   │ CONDITIONAL EDGE  │
                   │ should_perform_rag│
                   └─────────┬─────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
   route="rag"          route="google"      route="chat"
        │                    │                    │
        ▼                    ▼                    ▼
┌──────────────┐   ┌────────────────┐   ┌───────────────┐
│  NODE 3:     │   │  NODE 5:       │   │  NODE 6:      │
│ perform_rag_ │   │ perform_google │   │ build_final   │
│  retrieval   │   │    _search     │   │    _input     │
│              │   │                │   │               │
│ • Vector DB  │   │ • Google tool  │   │ • History     │
│ • Retriever  │   │ • History ctx  │   │   summary     │
│ • Reranker   │   │ • RAG fallback │   │ • User query  │
│              │   │   context      │   │               │
│ Output:      │   │                │   │ Output:       │
│ raw_docs,    │   │ Output:        │   │ final_input   │
│ reranked_docs│   │ google_answer, │   │               │
└──────┬───────┘   │ llm_output     │   └───────┬───────┘
       │           └────────┬───────┘           │
       ▼                    │                   ▼
┌──────────────┐            │           ┌───────────────┐
│  NODE 4:     │            │           │  NODE 7:      │
│ check_rag_   │            │           │ generate_llm  │
│  confidence  │            │           │   _response   │
│              │            │           │               │
│ • Rerank     │            │           │ • Main LLM    │
│   score      │            │           │ • chain_with  │
│ • Similarity │            │           │   _history    │
│   score      │            │           │ • Save to     │
│              │            │           │   history     │
│ Output:      │            │           │               │
│ rag_context  │            │           │ Output:       │
│ OR           │            │           │ llm_output    │
│ rag_low_conf │            │           │               │
│ _context     │            │           └───────┬───────┘
└──────┬───────┘            │                   │
       │                    │                   │
       ▼                    │                   │
┌──────────────┐            │                   │
│ CONDITIONAL  │            │                   │
│ should_use_  │            │                   │
│ google_      │            │                   │
│ fallback     │            │                   │
└──────┬───────┘            │                   │
       │                    │                   │
  ┌────┴────┐              │                   │
  │         │              │                   │
high      low              │                   │
conf      conf             │                   │
  │         │              │                   │
  │         └──────────────┘                   │
  │                  │                         │
  ▼                  ▼                         │
┌────────┐   ┌──────────────┐                 │
│ NODE 6:│   │  NODE 5:     │                 │
│ build_ │   │ perform_     │                 │
│ final_ │   │ google_      │                 │
│ input  │   │ search       │                 │
└────┬───┘   └──────┬───────┘                 │
     │              │                         │
     ▼              ▼                         │
┌─────────┐   ┌──────────┐                   │
│ NODE 7: │   │   END    │                   │
│generate │   └──────────┘                   │
│_llm_    │                                   │
│response │                                   │
└────┬────┘                                   │
     │                                        │
     ▼                                        │
┌──────────┐                                  │
│   END    │◄─────────────────────────────────┘
└──────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI Response                              │
│                                                                  │
│  Non-streaming: ChatCompletionResponse JSON                      │
│  Streaming: SSE chunks (text/event-stream)                       │
│                                                                  │
│  {                                                               │
│    "id": "chatcmpl-...",                                         │
│    "object": "chat.completion",                                  │
│    "model": "gemini-2.5-flash",                                  │
│    "choices": [{"message": {"content": "..."}}]                  │
│  }                                                               │
└──────────────────────────────────────────────────────────────────┘
```

## State Fields by Node

```
Initial State:
  session_id ✓
  user_input_raw ✓
  messages_from_request ✓
  is_streaming ✓
  completion_id ✓
  created_timestamp ✓

After load_history_and_memory:
  + history
  + memory_summary

After route_and_refine_query:
  + route
  + refined_query

After perform_rag_retrieval:
  + raw_docs
  + reranked_docs
  + rag_fallback_reason (if no docs)

After check_rag_confidence:
  + rag_context (if high confidence)
  + rag_low_conf_context (if low confidence)
  + rag_fallback_reason (if low confidence)

After perform_google_search:
  + google_answer
  + llm_output

After build_final_input:
  + final_input

After generate_llm_response:
  + llm_output

Any node on error:
  + error_info
```

## Conditional Routing Logic

### Conditional 1: should_perform_rag

```python
def should_perform_rag(state: ConversationState) -> str:
    route = state.get("route", "google")
    if route == "rag":
        return "rag"       # → perform_rag_retrieval
    elif route == "google":
        return "google"    # → perform_google_search
    elif route == "chat":
        return "chat"      # → build_final_input
```

### Conditional 2: should_use_google_fallback

```python
def should_use_google_fallback(state: ConversationState) -> str:
    rag_context = state.get("rag_context", "")
    if rag_context:
        return "build_input"  # → build_final_input (high confidence)
    else:
        return "google"       # → perform_google_search (low confidence)
```

## Confidence Thresholds

```python
# In check_rag_confidence node
is_rag_confident = (
    rerank_best_score > 0.05     # Reranker score
    and best_sim_score < 0.7     # Vector similarity (lower is better)
    and len(docs) >= 1           # At least one document
)
```

## Error Handling

Every node follows this pattern:

```python
def node_function(state: ConversationState) -> ConversationState:
    try:
        # Business logic
        result = do_something()
        return {**state, "field": result}
    except Exception as e:
        logger.exception("Node failed", extra={"session_id": state["session_id"]})
        return {
            **state,
            "error_info": f"node_error: {str(e)}",
            "field": fallback_value,
        }
```

Errors don't crash the graph—they set `error_info` and provide fallback values.

## Streaming vs Non-Streaming

### Non-Streaming
```python
final_state = conversation_graph.invoke(initial_state)
llm_output = final_state["llm_output"]
# Return as ChatCompletionResponse
```

### Streaming
```python
for step_output in conversation_graph.stream(initial_state):
    for node_name, node_state in step_output.items():
        if node_name == "build_final_input":
            # Stream LLM output token-by-token
            for chunk in chain_with_history.stream(...):
                yield f"data: {json.dumps(chunk)}\n\n"
```

## Model Names by Route

```python
route == "rag" + high confidence:
  model = "gemini-2.5-flash"

route == "google" OR rag low confidence:
  model = "gemini-2.5-flash (Google Search)"

error_info present:
  model = "GEOQ-Critical-Fallback"
```

## Adding a New Node

Example: Add document search node

```python
# 1. Define node function
def search_documents(state: ConversationState) -> ConversationState:
    query = state["refined_query"]
    docs = document_db.search(query)
    return {**state, "document_results": docs}

# 2. Add to graph
workflow.add_node("search_documents", search_documents)

# 3. Add edges
workflow.add_edge("route_and_refine_query", "search_documents")
workflow.add_edge("search_documents", "build_final_input")

# 4. Update conditional routing
workflow.add_conditional_edges(
    "route_and_refine_query",
    lambda state: state["route"],
    {
        "rag": "perform_rag_retrieval",
        "google": "perform_google_search",
        "documents": "search_documents",  # New route
        "chat": "build_final_input",
    },
)
```

## Performance Characteristics

```
┌────────────────────┬──────────────┬─────────────┐
│ Operation          │ Time (avg)   │ Depends On  │
├────────────────────┼──────────────┼─────────────┤
│ History load       │ 5-20ms       │ Redis       │
│ Memory summarize   │ 200-500ms    │ LLM (short) │
│ Route & refine     │ 300-800ms    │ LLM         │
│ Vector retrieval   │ 50-200ms     │ Chroma      │
│ Reranking          │ 100-300ms    │ GPU/CPU     │
│ Google Search      │ 1-3s         │ Gemini tool │
│ LLM generation     │ 1-5s         │ Gemini      │
├────────────────────┼──────────────┼─────────────┤
│ Total (RAG path)   │ 2-7s         │ All above   │
│ Total (Chat path)  │ 1.5-5s       │ No RAG      │
│ Total (Google)     │ 2-8s         │ Search time │
└────────────────────┴──────────────┴─────────────┘
```

LangGraph overhead: < 10ms (negligible)

## Graph Introspection

```python
# Print graph structure
print(conversation_graph.get_graph().print_ascii())

# Get node list
nodes = conversation_graph.get_graph().nodes
print(f"Nodes: {nodes}")

# Get edges
edges = conversation_graph.get_graph().edges
print(f"Edges: {edges}")
```

## Debugging Tips

```python
# 1. Add debug prints in nodes
def my_node(state):
    print(f"DEBUG: {state['session_id']} - route={state['route']}")
    ...

# 2. Inspect intermediate state
for step in conversation_graph.stream(initial_state):
    print(f"Step: {step}")

# 3. Check final state
final_state = conversation_graph.invoke(initial_state)
print(f"Final state keys: {final_state.keys()}")
print(f"Output: {final_state.get('llm_output')}")
print(f"Errors: {final_state.get('error_info')}")
```
