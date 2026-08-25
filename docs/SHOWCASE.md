# Geoq showcase

This page demonstrates the public API and the product behavior contributors are helping improve.

## Health and model discovery

```bash
curl http://localhost:8001/health
```

Typical response before AI credentials are configured:

```json
{
  "status": "degraded",
  "model": "geoq-0",
  "orchestration": "LangGraph",
  "ai_resources": "not_ready"
}
```

This is intentional: contributors can verify that the API shell is alive without downloading model weights or connecting to Gemini.

## Non-streaming conversation

```bash
curl http://localhost:8001/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "geoq-0",
    "stream": false,
    "session_id": "demo-visitor",
    "messages": [
      {"role": "user", "content": "برای یک روز در قشم برنامه سفر بده"}
    ]
  }'
```

The response follows the familiar OpenAI-compatible shape:

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1760000000,
  "model": "Geoq",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "...پاسخ فارسی جعوک..."},
      "finish_reason": "stop"
    }
  ]
}
```

## Streaming

Set `"stream": true` to receive Server-Sent Events. Each event contains a small content delta, and the stream ends with `data: [DONE]`.

## Product behavior examples

| User need | Geoq behavior | Where to improve it |
| --- | --- | --- |
| «رستوران خوب معرفی کن» | Ask about cuisine, budget, and location | Clarification prompt and local data |
| «بهترین مسیر امروز چیست؟» | Use fresh lookup when current conditions matter | Search integration and safety copy |
| «دره ستاره‌ها کجاست؟» | Prefer local retrieval and Persian context | `qa_qeshm.json` |
| «من غذای دریایی دوست دارم» then «کجا بروم؟» | Use conversation memory to personalize | Memory and fact extraction |

## Visual showcase

![Geoq Persian showcase](assets/geoq-showcase.png)

Open [`t.html`](../t.html) locally in a browser to see the RTL Persian introduction card for جعوک. It is standalone and can be embedded into a future web client.

The working chat client looks like this before connecting to the API:

![Geoq browser chat demo](assets/geoq-chat-demo.png)

## Working browser example

Start the API, then serve the repository root:

```bash
python -m api
python -m http.server 8080
```

Open [`examples/chat.html`](../examples/chat.html) at `http://localhost:8080/examples/chat.html`. The page sends real non-streaming requests to `http://localhost:8001/v1/chat/completions` and displays the Persian response. The browser API requires `CORS_ORIGINS=http://localhost:8080` in `.env`.
