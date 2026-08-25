# LangGraph Quick Reference Card

## 🚀 Quick Start (30 seconds)

```bash
pip install langgraph
python app.py
curl http://localhost:8001/health
```

## 📁 Files

| File | Status | Purpose |
|------|--------|---------|
| `graph.py` | 🆕 NEW | LangGraph state machine (7 nodes, 2 conditionals) |
| `app.py` | 🔄 CHANGED | FastAPI integration (uses `conversation_graph`) |
| `config.py` | ✅ SAME | Environment config (no changes) |
| `prompts.py` | ✅ SAME | Prompts and templates (no changes) |
| `utils.py` | ✅ SAME | LLM, vector DB, helpers (no changes) |

## 🔄 Graph Flow (7 Nodes)

```
1. load_history_and_memory     → Load history, generate memory summary
2. route_and_refine_query      → Classify route (rag/google/chat), refine query
3. perform_rag_retrieval       → Retrieve docs, rerank (if route=rag)
4. check_rag_confidence        → Evaluate confidence, decide fallback
5. perform_google_search       → Google Search (if route=google or low confidence)
6. build_final_input           → Construct final LLM input string
7. generate_llm_response       → Call Gemini, save to history
```

## 🔀 Routes

| Route | Trigger | Path |
|-------|---------|------|
| `rag` | Local knowledge query | 1→2→3→4→6→7 (if confident) or 1→2→3→4→5 (if not) |
| `google` | Fresh/external info | 1→2→5 |
| `chat` | Casual conversation | 1→2→6→7 |

## 📊 State Fields (ConversationState)

```python
session_id           # Session identifier
user_input_raw       # Original user query
history              # ChatMessageHistory object
memory_summary       # LLM conversation summary
route                # "rag" | "google" | "chat"
refined_query        # Context-aware query
rag_context          # High-confidence RAG context
google_answer        # Google Search result
llm_output           # Final response
error_info           # Error details (if any)
```

## 🧪 Testing (3 Essential Tests)

```bash
# 1. Chat (should work instantly)
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"سلام"}],"stream":false}'

# 2. RAG (should mention specific places)
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"رستوران‌های قشم"}],"stream":false}'

# 3. Google (should mention search)
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"آخرین اخبار"}],"stream":false}'
```

## 🔍 Debugging

```bash
# View all logs
tail -f logs.txt

# Filter by node
tail -f logs.txt | grep "Node:"

# View routing decisions
tail -f logs.txt | grep "Routing decision"

# Check for errors
tail -f logs.txt | grep ERROR
```

## 📝 Log Patterns

**Success (RAG path):**
```
Node: load_history_and_memory
Node: route_and_refine_query → route: rag
Node: perform_rag_retrieval → 8 docs
Node: check_rag_confidence → confident: true
Node: build_final_input
Node: generate_llm_response
```

**Google fallback:**
```
RAG low confidence
Node: perform_google_search
Google Search successful
```

## ⚡ Performance

| Operation | Typical Time |
|-----------|-------------|
| Chat route | 1.5-5s |
| RAG route | 2-7s |
| Google route | 2-8s |
| LangGraph overhead | <10ms |

## 🐛 Common Issues

| Symptom | Fix |
|---------|-----|
| `ModuleNotFoundError: langgraph` | `pip install langgraph` |
| Graph stuck | Check edges, verify conditional returns |
| Streaming empty | Verify SSE format: `f"data: {json}\\n\\n"` |
| State not updating | Return `{**state, "field": value}` |

## 🔧 Adding a Node

```python
# 1. Define function
def my_node(state: ConversationState) -> ConversationState:
    result = do_something(state["refined_query"])
    return {**state, "my_field": result}

# 2. Add to graph
workflow.add_node("my_node", my_node)

# 3. Connect edges
workflow.add_edge("previous_node", "my_node")
workflow.add_edge("my_node", "next_node")

# 4. Recompile
conversation_graph = workflow.compile()
```

## 📚 Documentation

| File | Content |
|------|---------|
| `SUMMARY.md` | High-level overview, what changed |
| `README-LangGraph.md` | Complete architecture guide |
| `GRAPH-DIAGRAM.md` | Visual flow, debugging tips |
| `MIGRATION-TESTING.md` | 14 test cases, step-by-step migration |

## 🎯 Key Benefits

✅ **Modularity** - Each step is a pure function  
✅ **Visibility** - Graph structure is explicit  
✅ **Extensibility** - Add nodes without touching FastAPI  
✅ **Debugging** - Inspect state at each step  
✅ **Testing** - Test nodes in isolation  
✅ **Future-ready** - Checkpointing, parallel execution, tools  

## 🚨 Rollback

```bash
cp app.py.backup app.py
pkill -f "python app.py"
python app.py
```

## 🔐 Production Checklist

- [ ] All tests pass (14 test cases)
- [ ] No unexpected ERRORs in logs
- [ ] Performance < 5s (95th percentile)
- [ ] Redis connection stable
- [ ] Vector DB accessible
- [ ] Backup available
- [ ] Team trained

## 📞 Support

- **LangGraph Docs:** https://langchain-ai.github.io/langgraph/
- **Issue:** Check `error_info` in logs, review testing guide
- **Question:** Consult README-LangGraph.md → GRAPH-DIAGRAM.md → graph.py

---

**TL;DR:** Install `langgraph`, replace `app.py`, run 3 tests, deploy. Everything else unchanged. Zero API changes. Modular, visible, extensible architecture.
