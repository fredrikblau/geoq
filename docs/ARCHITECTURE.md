# Architecture and extension guide

## Request flow

1. `api.app` validates the OpenAI-compatible request and normalizes the latest user message.
2. `api.graph` loads session history, memory summaries, and user facts.
3. The router chooses `rag`, `google`, or `chat`.
4. Local questions go through Chroma retrieval, reranking, and confidence checks.
5. Fresh or low-confidence questions can use the Google-grounded path.
6. The Persian prompt generates an answer, evaluates quality, optionally refines it, and saves the final message.
7. The API returns JSON or SSE chunks.

## Where to make changes

| Goal | File or directory |
| --- | --- |
| Add or change the public API | `api/app.py` |
| Change routing, retrieval, or refinement | `api/graph.py` and `api/utils.py` |
| Change Persian behavior and safety rules | `api/prompts.py` |
| Add local knowledge | `qa_*.json` |
| Rebuild embeddings | `embed_qa.py` |
| Add fast regression coverage | `tests/` |
| Explain a contributor-facing concept | `docs/` |

## Design boundaries

- Credentials and generated model state stay outside Git.
- Local knowledge is reviewable data, not an opaque model weight.
- Current or safety-sensitive information should be treated as uncertain and verified.
- Tests should not require Gemini, Redis, or downloaded model weights unless explicitly marked as integration tests.

## Current technical debt

- The AI dependency stack is heavyweight for a first install.
- The local index build is currently a manual command.
- A dedicated web client and a source/verification model for changing local facts are future improvements.

These are good contribution areas; open an issue before taking on a larger change.
