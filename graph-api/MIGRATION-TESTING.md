# Migration & Testing Guide

## Quick Start Migration

### Step 1: Install Dependencies

```bash
pip install langgraph
```

Verify installation:
```bash
python -c "import langgraph; print(langgraph.__version__)"
```

### Step 2: Backup Current System

```bash
# Backup existing files
cp app.py app.py.backup
cp utils.py utils.py.backup

# Or use git
git checkout -b langgraph-migration
git add .
git commit -m "Backup before LangGraph migration"
```

### Step 3: Deploy New Files

```bash
# Add new files
cp graph.py ./graph.py
cp app-langgraph.py ./app.py

# Keep existing files (no changes needed)
# config.py - unchanged
# prompts.py - unchanged
# utils.py - unchanged
```

### Step 4: Test Locally

```bash
# Start server
python app.py

# In another terminal, test health endpoint
curl http://localhost:8001/health

# Expected response:
# {"status":"ok","model":"GEOQ","orchestration":"LangGraph"}
```

## Testing Checklist

### ✅ Basic Functionality Tests

#### Test 1: Simple Chat (Non-Streaming)
```bash
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "سلام"}
    ],
    "stream": false,
    "session_id": "test-chat-1"
  }' | jq .
```

**Expected:**
- Status: 200
- Response contains: `"model": "gemini-2.5-flash"`
- `choices[0].message.content` is a Persian greeting
- No `error_info` in logs

#### Test 2: Simple Chat (Streaming)
```bash
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "سلام"}
    ],
    "stream": true,
    "session_id": "test-chat-2"
  }'
```

**Expected:**
- Content-Type: `text/event-stream`
- Multiple `data:` lines with JSON chunks
- Final line: `data: [DONE]`
- Each chunk has `delta.content`

#### Test 3: RAG Query (Local Knowledge)
```bash
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "رستوران‌های قشم کجاست؟"}
    ],
    "stream": false,
    "session_id": "test-rag-1"
  }' | jq .
```

**Expected:**
- Route in logs: `"route": "rag"`
- Response mentions specific restaurants from vector DB
- `RAG context built (high confidence)` in logs
- Model: `gemini-2.5-flash`

#### Test 4: Google Search Query
```bash
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "آخرین اخبار قشم چیه؟"}
    ],
    "stream": false,
    "session_id": "test-google-1"
  }' | jq .
```

**Expected:**
- Route in logs: `"google"` OR `"rag"` with low confidence fallback
- Model: `gemini-2.5-flash (Google Search)`
- Response mentions "جستجو کردم" or similar
- `Google Search successful` in logs

#### Test 5: Multi-Turn Conversation
```bash
# Turn 1
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "رستوران خوب قشم معرفی کن"}
    ],
    "stream": false,
    "session_id": "test-multiturn"
  }' | jq .choices[0].message.content

# Turn 2 (follow-up)
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "رستوران خوب قشم معرفی کن"},
      {"role": "assistant", "content": "..."},
      {"role": "user", "content": "ساعت کارش چیه؟"}
    ],
    "stream": false,
    "session_id": "test-multiturn"
  }' | jq .
```

**Expected:**
- Turn 2 uses context from Turn 1
- `memory_summary` in logs contains info from Turn 1
- History length increases in logs
- Response is contextually relevant

### ✅ Edge Cases & Error Handling

#### Test 6: Empty Messages List
```bash
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [],
    "stream": false,
    "session_id": "test-error-1"
  }'
```

**Expected:**
- Status: 400
- Error message: "Messages list is required"

#### Test 7: Very Long History
```bash
# Create a script to send 50 messages
for i in {1..50}; do
  curl -X POST http://localhost:8001/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d "{
      \"messages\": [{\"role\": \"user\", \"content\": \"پیام شماره $i\"}],
      \"stream\": false,
      \"session_id\": \"test-long-history\"
    }" > /dev/null 2>&1
done

# Check logs for history capping
grep "History capped" logs.txt
```

**Expected:**
- `History capped` appears in logs
- `new_len` = `MAX_HISTORY_LEN` (20 by default)
- No memory errors
- Response time stays consistent

#### Test 8: RAG Low Confidence Fallback
```bash
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "هواپیمای مریخ چطوری کار میکنه؟"}
    ],
    "stream": false,
    "session_id": "test-fallback-1"
  }' | jq .
```

**Expected:**
- Route: `"rag"` initially
- Log: `RAG low confidence`
- Fallback to Google Search
- Model: `gemini-2.5-flash (Google Search)`
- Response addresses the question using web search

#### Test 9: Redis Down (In-Memory Fallback)
```bash
# Stop Redis temporarily
sudo systemctl stop redis

# Make request
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "تست"}
    ],
    "stream": false,
    "session_id": "test-redis-down"
  }' | jq .

# Restart Redis
sudo systemctl start redis
```

**Expected:**
- Log: `Redis connection failed. Falling back to in-memory store.`
- Request succeeds (200)
- History stored in-memory
- No crash

#### Test 10: Vector DB Error Handling
```bash
# Rename Chroma directory temporarily to simulate missing DB
mv qeshm_db qeshm_db.backup

# Make RAG request
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "رستوران‌های قشم"}
    ],
    "stream": false,
    "session_id": "test-vectordb-error"
  }' | jq .

# Restore
mv qeshm_db.backup qeshm_db
```

**Expected:**
- Log: `RAG pipeline failed`
- Fallback to Google Search
- Response still generated (no 500 error)
- Model: `gemini-2.5-flash (Google Search)` or fallback

### ✅ Performance Tests

#### Test 11: Latency Benchmark
```bash
# Install Apache Bench
sudo apt-get install apache2-utils

# Run 100 requests with concurrency 10
ab -n 100 -c 10 -T 'application/json' -p request.json \
  http://localhost:8001/v1/chat/completions

# request.json:
# {
#   "messages": [{"role": "user", "content": "سلام"}],
#   "stream": false,
#   "session_id": "perf-test"
# }
```

**Expected:**
- Mean time < 3s for chat route
- No failed requests
- Memory usage stable

#### Test 12: Streaming Latency
```bash
# Measure time to first token (TTFT)
time curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "رستوران‌های قشم"}],
    "stream": true,
    "session_id": "test-ttft"
  }' | head -n 1
```

**Expected:**
- First chunk arrives < 2s
- Smooth streaming (no long pauses)

### ✅ Route Testing

#### Test 13: Explicit Route Testing
Create a test script `test_routes.py`:

```python
import requests
import json

base_url = "http://localhost:8001/v1/chat/completions"
session_id = "route-test"

test_cases = [
    {
        "name": "RAG Route",
        "query": "کافه‌های قشم کجاست؟",
        "expected_route": "rag",
    },
    {
        "name": "Google Route",
        "query": "آخرین اخبار جهان",
        "expected_route": "google",
    },
    {
        "name": "Chat Route",
        "query": "سلام، حالت چطوره؟",
        "expected_route": "chat",
    },
]

for test in test_cases:
    print(f"\nTesting: {test['name']}")
    response = requests.post(
        base_url,
        json={
            "messages": [{"role": "user", "content": test["query"]}],
            "stream": False,
            "session_id": session_id,
        },
    )
    print(f"Status: {response.status_code}")
    print(f"Model: {response.json()['model']}")
    print(f"Response preview: {response.json()['choices'][0]['message']['content'][:100]}...")
```

Run:
```bash
python test_routes.py
```

**Expected:**
- All tests pass with 200 status
- Routes match expectations (check logs)
- Responses are contextually appropriate

### ✅ Comparison Testing

#### Test 14: Side-by-Side Comparison

1. Keep backup of old system running on port 8002
2. Run new LangGraph system on port 8001
3. Send identical requests to both

```python
# compare_systems.py
import requests
import json

queries = [
    "رستوران‌های قشم معرفی کن",
    "آخرین اخبار قشم",
    "سلام، چطوری؟",
]

for query in queries:
    print(f"\n{'='*60}")
    print(f"Query: {query}")
    print('='*60)
    
    # Old system
    old_resp = requests.post(
        "http://localhost:8002/v1/chat/completions",
        json={"messages": [{"role": "user", "content": query}], "stream": False},
    )
    print(f"\nOLD: {old_resp.json()['choices'][0]['message']['content'][:200]}...")
    
    # New system
    new_resp = requests.post(
        "http://localhost:8001/v1/chat/completions",
        json={"messages": [{"role": "user", "content": query}], "stream": False},
    )
    print(f"\nNEW: {new_resp.json()['choices'][0]['message']['content'][:200]}...")
```

**Expected:**
- Both systems return similar quality responses
- New system has same or better route decisions
- No regressions in answer quality

## Log Inspection

### Viewing Structured Logs

```bash
# View all logs
tail -f logs.txt

# Filter by session
cat logs.txt | grep "test-session"

# Filter by level
cat logs.txt | grep "ERROR"

# View only graph node executions
cat logs.txt | grep "Node:"

# View routing decisions
cat logs.txt | grep "Routing decision"

# View RAG confidence checks
cat logs.txt | grep "RAG confidence"
```

### Key Log Patterns

**Successful RAG path:**
```
{"message": "Node: load_history_and_memory", ...}
{"message": "Node: route_and_refine_query", "route": "rag", ...}
{"message": "Node: perform_rag_retrieval", ...}
{"message": "Node: check_rag_confidence", "is_confident": true, ...}
{"message": "Node: build_final_input", ...}
{"message": "Node: generate_llm_response", ...}
```

**Google Search fallback:**
```
{"message": "RAG low confidence", ...}
{"message": "Node: perform_google_search", ...}
{"message": "Google Search successful", ...}
```

**Error scenario:**
```
{"levelname": "ERROR", "message": "...", "error_info": "..."}
{"message": "Fallback message", ...}
```

## Performance Monitoring

### Metrics to Track

```python
# Add timing to nodes (optional enhancement)
import time

def timed_node(func):
    def wrapper(state):
        start = time.time()
        result = func(state)
        duration = time.time() - start
        logger.info(
            f"Node {func.__name__} completed",
            extra={"duration_ms": duration * 1000}
        )
        return result
    return wrapper

@timed_node
def my_node(state):
    ...
```

### Expected Timings

```
load_history_and_memory:    10-50ms
route_and_refine_query:     300-800ms
perform_rag_retrieval:      150-500ms
check_rag_confidence:       50-150ms
perform_google_search:      1000-3000ms
build_final_input:          <5ms
generate_llm_response:      1000-5000ms
```

## Rollback Plan

If issues arise:

```bash
# Stop new server
pkill -f "python app.py"

# Restore backup
cp app.py.backup app.py

# Restart with old code
python app.py
```

Or with git:
```bash
git checkout main
git reset --hard HEAD
python app.py
```

## Common Issues & Solutions

### Issue 1: Import Error - `langgraph` not found
**Solution:**
```bash
pip install langgraph
# or
pip install langgraph>=0.0.1
```

### Issue 2: TypedDict error in Python < 3.9
**Solution:**
```python
# In graph.py, change:
from typing import TypedDict
# to:
from typing_extensions import TypedDict
```

### Issue 3: Graph not completing (stuck)
**Solution:**
- Check for missing edges
- Add debug logging in conditional functions
- Verify all nodes have paths to END

### Issue 4: Streaming returns nothing
**Solution:**
- Ensure SSE format: `f"data: {json.dumps(...)}\n\n"`
- Check that generator yields strings
- Verify `media_type="text/event-stream"`

### Issue 5: State not updating between nodes
**Solution:**
- Always return `{**state, "new_field": value}`
- Don't mutate state directly
- Check node output keys match expected fields

## Production Checklist

Before deploying to production:

- [ ] All 14 tests pass
- [ ] Logs are clean (no unexpected ERRORs)
- [ ] Performance meets SLA (< 5s for 95th percentile)
- [ ] Redis connection stable
- [ ] Vector DB accessible
- [ ] Environment variables set correctly
- [ ] Error handling tested
- [ ] Streaming tested with slow connections
- [ ] Multi-session concurrency tested
- [ ] Memory usage monitored (no leaks)
- [ ] Backup of old system available
- [ ] Rollback plan documented
- [ ] Team trained on new architecture
- [ ] Documentation updated

## Monitoring in Production

```bash
# Monitor server health
watch -n 5 'curl -s http://localhost:8001/health'

# Monitor error rate
tail -f logs.txt | grep ERROR

# Monitor response times
tail -f logs.txt | grep "duration_ms"

# Monitor route distribution
grep "Routing decision" logs.txt | grep -oP '"route": "\K\w+' | sort | uniq -c
```

## Next Steps

After successful migration:

1. **Add Checkpointing** (optional)
   ```python
   from langgraph.checkpoint import MemorySaver
   checkpointer = MemorySaver()
   app = workflow.compile(checkpointer=checkpointer)
   ```

2. **Add Human-in-the-Loop** (optional)
   ```python
   from langgraph.graph import interrupt
   
   def needs_approval(state):
       if state["confidence"] < 0.5:
           interrupt("Low confidence")
   ```

3. **Add More Tools**
   - Weather API
   - Database search
   - Image analysis
   - Audio transcription

4. **Optimize Performance**
   - Cache embeddings
   - Parallel RAG + Google
   - Batch reranking

5. **Improve Observability**
   - Add Prometheus metrics
   - Add distributed tracing
   - Add custom dashboards

## Support

For issues:
1. Check logs for `error_info`
2. Review this testing guide
3. Consult README-LangGraph.md
4. Review GRAPH-DIAGRAM.md
5. Inspect graph.py node functions

For questions:
- LangGraph docs: https://langchain-ai.github.io/langgraph/
- LangChain docs: https://python.langchain.com/
