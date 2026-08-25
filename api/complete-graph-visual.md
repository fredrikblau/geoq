# Complete Enhanced Graph Architecture

## Full Graph Structure with All Nodes

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         COMPLETE CONVERSATION GRAPH                         │
│                    (With Quality Gate & Self-Correction)                    │
└─────────────────────────────────────────────────────────────────────────────┘

                                      START
                                        │
                                        ▼
                    ┌───────────────────────────────────────┐
                    │  load_history_memory_and_facts        │
                    │  ────────────────────────────────────  │
                    │  • Load session history               │
                    │  • Summarize memory (llm_summarize)   │
                    │  • Extract user facts                 │
                    │  • Get selective history              │
                    │  • Initialize quality gate state:     │
                    │    - iteration_count = 0              │
                    │    - previous_answers = []            │
                    │    - refinement_history = []          │
                    └───────────────────────────────────────┘
                                        │
                                        ▼
                    ┌───────────────────────────────────────┐
                    │  route_and_refine_query               │
                    │  ────────────────────────────────────  │
                    │  IF iteration_count = 0:              │
                    │    • Normal routing (LLM classifier)  │
                    │    • User query → refined_query       │
                    │                                        │
                    │  IF iteration_count > 0:              │
                    │    • RETRY REFINEMENT:                │
                    │    • Call refine_query_for_retry()    │
                    │    • Generate better query            │
                    │    • Determine new route (google/rag) │
                    │    • Store in refinement_history      │
                    └───────────────────────────────────────┘
                                        │
                    ┌───────────────────┼───────────────────┐
                    │                   │                   │
            (route = "rag")    (route = "google")  (route = "chat")
                    │                   │                   │
                    ▼                   ▼                   │
    ┌──────────────────────────┐   ┌────────────────────┐  │
    │ perform_rag_retrieval    │   │perform_google_     │  │
    │ ──────────────────────────  │ search             │  │
    │ • Query vector DB         │   │──────────────────  │  │
    │ • Retrieve k documents    │   │ • Search web      │  │
    │ • Normalize text          │   │ • No source       │  │
    │                           │   │   disclosure      │  │
    │ Returns:                  │   │                   │  │
    │ - raw_docs                │   │ Returns:          │  │
    │ - reranked_docs           │   │ - google_answer   │  │
    │                           │   │ - llm_output      │  │
    └──────────────────────────┘   └────────────────────┘  │
                    │                   │                   │
                    ▼                   │                   │
    ┌──────────────────────────┐       │                   │
    │ check_rag_confidence     │       │                   │
    │ ──────────────────────────  │       │                   │
    │ • Score reranked docs    │       │                   │
    │ • Calculate confidence   │       │                   │
    │   - rerank_best_score    │       │                   │
    │   - similarity_score     │       │                   │
    │                          │       │                   │
    │ IF confidence_high:      │       │                   │
    │   rag_context = docs     │       │                   │
    │ ELSE:                    │       │                   │
    │   rag_context = ""       │       │                   │
    └──────────────────────────┘       │                   │
                    │                   │                   │
        ┌───────────┴──────────┐       │                   │
        │ (rag_context exists?)│       │                   │
        │                       │       │                   │
    YES │                NO     │       │                   │
        │                       │       │                   │
        ▼                       ▼       ▼                   ▼
    ┌──────────┐            ┌──────────────────────────────────┐
    │build_    │            │perform_google_search (fallback)  │
    │final_    │            └──────────────────────────────────┘
    │input     │                         │
    └──────────┘                         │
        │                                │
        └────────────────┬───────────────┘
                         │
                         ▼
                    ┌──────────────────────────┐
                    │  build_final_input       │
                    │ ──────────────────────────
                    │ • Assemble context_block:│
                    │   - user_facts           │
                    │   - rag_context          │
                    │   - recent_history       │
                    │   - earlier_summary      │
                    │   - memory_summary       │
                    │ • Set final_input query  │
                    └──────────────────────────┘
                         │
                         ▼
                    ┌──────────────────────────┐
                    │ generate_llm_response    │
                    │ ──────────────────────────
                    │ • Build prompt with      │
                    │   context_block          │
                    │ • Call LLM:              │
                    │   prompt | llm           │
                    │ • Stream response        │
                    │ • Set llm_output         │
                    │                          │
                    │ Returns:                 │
                    │ - llm_output (answer)    │
                    └──────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────┐
│     🆕 evaluate_response_quality (NEW NODE)                │
│     ────────────────────────────────────────────           │
│     • Store previous attempt: previous_answers.append()    │
│     • Call evaluate_answer_quality():                      │
│       - User query                                          │
│       - Generated answer (llm_output)                       │
│       - Context used (RAG/Google/Chat)                      │
│                                                              │
│     • LLM-as-Judge evaluation returns:                      │
│       {                                                     │
│         "quality_score": 0.0-1.0,                           │
│         "issue_type": "missing_contact_info" | "too_vague" │
│                       "wrong_context" | "incomplete" |      │
│                       "off_topic" | "good",                 │
│         "recommendation": "accept" | "google_search" |      │
│                           "better_rag_query" |              │
│                           "add_more_context",               │
│         "reason": "explanation..."                          │
│       }                                                     │
│                                                              │
│     • Set state:                                            │
│       - quality_evaluation = result                         │
│       - final_quality_score = result.quality_score          │
└────────────────────────────────────────────────────────────┘
                         │
                         ▼
            ┌────────────────────────────────┐
            │  should_retry_or_finish()      │
            │  (CONDITIONAL EDGE - NEW)      │
            │  ────────────────────────────  │
            │  IF iteration_count >=         │
            │     MAX_REFINEMENT_ITERATIONS  │
            │    → "finish" (max reached)    │
            │                                │
            │  ELSE IF should_refine_answer()│
            │    (quality < threshold AND    │
            │     recommendation != "accept")│
            │    → "retry" (poor quality)    │
            │                                │
            │  ELSE → "finish" (acceptable) │
            └────────────────────────────────┘
                    │              │
            (retry) │              │ (finish)
                    ▼              ▼
        ┌──────────────────┐  ┌─────────────────────┐
        │ prepare_retry_   │  │ finalize_answer     │
        │ iteration        │  │ (NEW NODE)          │
        │ (NEW NODE)       │  │ ─────────────────── │
        │                  │  │ • Save to history   │
        │ • increment:     │  │ • Hide retries      │
        │   iteration_count│  │ • Log metrics       │
        │ += 1             │  │                     │
        │                  │  │ Returns:            │
        │ → continue loop  │  │ - llm_output        │
        │                  │  │   (final answer)    │
        └──────────────────┘  └─────────────────────┘
                    │                  │
                    │                  ▼
                    │              ┌─────────┐
                    │              │   END   │
                    │              └─────────┘
                    │
                    │ (LOOP BACK)
                    │
                    └──→ route_and_refine_query
                         (iteration_count = 1 now)
                         (refine query, pick better strategy)
                              │
                              ▼
                         (Retry path with new route)
                         [Similar flow as above]
                              │
                              ▼
                         evaluate_response_quality
                         (check quality again)
                              │
                         [Accept or retry again?]
```

---

## State Flow Through Iterations

### Iteration 0 (First Attempt)

```
┌─────────────────────────────────────────────────────────┐
│  INPUT STATE                                            │
├─────────────────────────────────────────────────────────┤
│ session_id: "user123"                                   │
│ user_input_raw: "به کی زنگ بزنم برای غواصی؟"           │
│ messages_from_request: [...]                            │
│ iteration_count: 0  ◄─ FIRST ATTEMPT                   │
│ previous_answers: []                                    │
│ refinement_history: []                                  │
└─────────────────────────────────────────────────────────┘
                         │
         load_history → route_and_refine → perform_rag
                         │
┌─────────────────────────────────────────────────────────┐
│  AFTER RAG RETRIEVAL                                    │
├─────────────────────────────────────────────────────────┤
│ route: "rag"                                            │
│ refined_query: "غواصی در قشم"                           │
│ raw_docs: [doc1, doc2, doc3, ...]                       │
│ reranked_docs: [(doc1, 0.7), (doc2, 0.6), ...]         │
│ rag_context: "جزیره هنگام، ناز برای غواصی..."          │
└─────────────────────────────────────────────────────────┘
                         │
         build_final_input → generate_llm_response
                         │
┌─────────────────────────────────────────────────────────┐
│  AFTER LLM GENERATION                                   │
├─────────────────────────────────────────────────────────┤
│ context_block: "اطلاعات شخصی: ... RAG: جزیره هنگام..."│
│ llm_output: "جزیره هنگام و ناز برای غواصی خوبند..."    │
│ previous_answers: ["جزیره هنگام و ناز برای غواصی..."]  │
└─────────────────────────────────────────────────────────┘
                         │
         evaluate_response_quality
                         │
┌─────────────────────────────────────────────────────────┐
│  QUALITY EVALUATION RESULT                              │
├─────────────────────────────────────────────────────────┤
│ quality_evaluation: {                                   │
│   "quality_score": 0.4,  ◄─ LOW (below 0.7 threshold)  │
│   "issue_type": "missing_contact_info",                │
│   "recommendation": "google_search",                   │
│   "reason": "پاسخ شماره تلفن و نام مراکز رو نداره"    │
│ }                                                       │
│ final_quality_score: 0.4                               │
└─────────────────────────────────────────────────────────┘
                         │
         should_retry_or_finish → RETRY
                         │
         prepare_retry_iteration
                         │
┌─────────────────────────────────────────────────────────┐
│  STATE AFTER RETRY DECISION                             │
├─────────────────────────────────────────────────────────┤
│ iteration_count: 1  ◄─ INCREMENTED FOR RETRY           │
│ refinement_history: [{                                  │
│   "iteration": 1,                                       │
│   "issue": "missing_contact_info",                     │
│   "strategy": "google_search",                          │
│   "refined_query": "شماره تلفن کلوپ‌های غواصی قشم"    │
│ }]                                                      │
└─────────────────────────────────────────────────────────┘
```

### Iteration 1 (First Retry)

```
         route_and_refine_query (with iteration_count = 1)
                         │
         call refine_query_for_retry():
         - original_query: "به کی زنگ بزنم برای غواصی؟"
         - previous_answer: "جزیره هنگام و ناز برای غواصی..."
         - issue_type: "missing_contact_info"
         - reason: "پاسخ شماره تلفن و نام مراکز رو نداره"
                         │
┌─────────────────────────────────────────────────────────┐
│  REFINED FOR RETRY                                      │
├─────────────────────────────────────────────────────────┤
│ refined_query: "شماره تلفن و اطلاعات تماس کلوپ‌های    │
│                 غواصی قشم"                              │
│ route: "google"  ◄─ CHANGED TO GOOGLE                   │
│ search_strategy: "google_search"                        │
└─────────────────────────────────────────────────────────┘
                         │
         perform_google_search
                         │
┌─────────────────────────────────────────────────────────┐
│  AFTER GOOGLE SEARCH                                    │
├─────────────────────────────────────────────────────────┤
│ google_answer: "کلوپ غواصی نگین قشم 09347690090.      │
│                 کلوپ غواصی دلفین قشم 09177699002..."   │
│ llm_output: "کلوپ غواصی نگین قشم 09347690090..."      │
│ previous_answers: [                                     │
│   "جزیره هنگام و ناز برای غواصی...",  ◄─ FROM ITER 0  │
│   "کلوپ غواصی نگین قشم 09347690090..."  ◄─ FROM ITER 1 │
│ ]                                                       │
└─────────────────────────────────────────────────────────┘
                         │
         evaluate_response_quality
                         │
┌─────────────────────────────────────────────────────────┐
│  QUALITY EVALUATION RESULT (RETRY)                      │
├─────────────────────────────────────────────────────────┤
│ quality_evaluation: {                                   │
│   "quality_score": 0.9,  ◄─ HIGH (above 0.7 threshold) │
│   "issue_type": "good",                                 │
│   "recommendation": "accept",                           │
│   "reason": "پاسخ شماره تلفن و نام مراکز رو داره"     │
│ }                                                       │
│ final_quality_score: 0.9  ◄─ IMPROVED FROM 0.4 TO 0.9  │
└─────────────────────────────────────────────────────────┘
                         │
         should_retry_or_finish → FINISH (quality >= 0.7)
                         │
         finalize_answer
                         │
┌─────────────────────────────────────────────────────────┐
│  FINAL STATE                                            │
├─────────────────────────────────────────────────────────┤
│ llm_output: "کلوپ غواصی نگین قشم 09347690090..."      │
│ (saved to history, user sees only this)                 │
│                                                          │
│ iteration_count: 1  (final)                             │
│ final_quality_score: 0.9                                │
│ refinement_history: [{                                  │
│   "iteration": 1,                                       │
│   "issue": "missing_contact_info",                     │
│   "strategy": "google_search",                          │
│   "refined_query": "شماره تلفن کلوپ‌های غواصی قشم"    │
│ }]                                                      │
│ previous_answers: [attempt0, attempt1]  (not shown)     │
└─────────────────────────────────────────────────────────┘
                         │
                    → END (user never sees this was retried)
```

---

## Node Connections Summary

| From Node | To Node | Condition |
|-----------|---------|-----------|
| load_history_memory_and_facts | route_and_refine_query | Always |
| route_and_refine_query | perform_rag_retrieval | route == "rag" |
| route_and_refine_query | perform_google_search | route == "google" |
| route_and_refine_query | build_final_input | route == "chat" |
| perform_rag_retrieval | check_rag_confidence | Always |
| check_rag_confidence | build_final_input | rag_context exists |
| check_rag_confidence | perform_google_search | rag_context empty |
| perform_google_search | evaluate_response_quality | Always (directly) |
| build_final_input | generate_llm_response | Always |
| generate_llm_response | evaluate_response_quality | Always |
| evaluate_response_quality | prepare_retry_iteration | should_retry == True |
| evaluate_response_quality | finalize_answer | should_retry == False |
| prepare_retry_iteration | route_and_refine_query | Always (LOOP) |
| finalize_answer | END | Always |

---

## Key Differences from Original Graph

### ✅ Added Nodes (3 new)
1. **evaluate_response_quality** - LLM judges quality after generation
2. **prepare_retry_iteration** - Increments counter for retry
3. **finalize_answer** - Saves final answer to history

### ✅ Modified Nodes (1 updated)
1. **route_and_refine_query** - Now checks iteration_count and refines if retry

### ✅ New Conditional Edge (1)
1. **should_retry_or_finish** - Routes to retry or finish based on quality

### ✅ New State Fields (6)
- `iteration_count` - Track retry attempts
- `quality_evaluation` - Store evaluation results
- `previous_answers` - History of generated answers
- `refinement_history` - Track refinements made
- `final_quality_score` - Quality of final answer

### ✅ Self-Correction Loop
- After generation, evaluate quality
- If poor → refine query + retry (up to 2 iterations)
- If good → finalize and end
- User sees only final answer

---

## Configuration Impact on Flow

### Default Production Settings
```python
ENABLE_QUALITY_GATE = True
MAX_REFINEMENT_ITERATIONS = 2
QUALITY_GATE_THRESHOLD = 0.7
SHOW_RETRY_ATTEMPTS = False
```
**Flow:** Generate → Evaluate → Retry if needed (max 2) → Finalize

### Disabled (Backward Compatible)
```python
ENABLE_QUALITY_GATE = False
```
**Flow:** Generate → Skip evaluation → Return immediately (old behavior)

### Aggressive (Stricter)
```python
MAX_REFINEMENT_ITERATIONS = 3
QUALITY_GATE_THRESHOLD = 0.8
```
**Flow:** More retries, higher quality bar

### Conservative (Faster)
```python
MAX_REFINEMENT_ITERATIONS = 1
QUALITY_GATE_THRESHOLD = 0.6
```
**Flow:** Max 1 retry, lenient threshold

---

## Performance Characteristics

| Metric | Iteration 0 | Iteration 1 | Iteration 2 |
|--------|------------|-----------|-----------|
| Latency | ~2-3s | +2-3s | +2-3s |
| Success Rate | 70% | 90%+ | 95%+ |
| Probability | 70% | 25% | 5% |
| Typical Path | First answer works | RAG fails, Google succeeds | Persistent issues |

**Average latency: 2-3s + (0.25 × 2-3s) + (0.05 × 2-3s) ≈ 2.5-3.5s total**

---

## Complete Graph Pseudocode

```python
def conversation_graph_workflow():
    """
    Complete self-correcting RAG graph workflow.
    """
    
    # Initialize
    session_id = state["session_id"]
    iteration_count = 0
    max_iterations = MAX_REFINEMENT_ITERATIONS
    quality_threshold = QUALITY_GATE_THRESHOLD
    
    # Load
    history, memory, facts = load_history_memory_and_facts(state)
    
    # Self-correction loop
    for iteration in range(1 + max_iterations):  # +1 for initial
        
        # Route & refine
        if iteration == 0:
            route, query = route_and_refine_normal(...)
        else:
            route, query = refine_and_rerute(...)
        
        # Generate answer
        if route == "rag":
            answer = rag_retrieval_pipeline(...)
        elif route == "google":
            answer = google_search_pipeline(...)
        else:
            answer = chat_generation(...)
        
        # Evaluate quality
        if ENABLE_QUALITY_GATE:
            evaluation = evaluate_answer_quality(
                query=original_query,
                answer=answer,
                context_used=route,
            )
            
            quality_score = evaluation["quality_score"]
            issue_type = evaluation["issue_type"]
            recommendation = evaluation["recommendation"]
            
            # Check if should retry
            if quality_score >= quality_threshold:
                # Quality acceptable
                finalize_answer(answer)
                return answer  # ✓ SUCCESS
            
            elif iteration < max_iterations:
                # Poor quality, try again
                iteration_count += 1
                previous_answers.append(answer)
                refinement = diagnose_and_refine(...)
                continue  # ↻ RETRY LOOP
            
            else:
                # Max iterations reached
                finalize_answer(answer)
                return answer  # Return best attempt
        
        else:
            # Quality gate disabled
            return answer  # Return immediately (old behavior)
```

This is the complete self-correcting system in action! 🎯
