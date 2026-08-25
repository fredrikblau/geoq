# Geoq

Geoq (جعوک) is an open-source, Persian-first local travel assistant for Qeshm Island and its nearby islands: Hormoz, Lark, Hengam, and Naz Island. It combines a FastAPI-compatible chat API, LangGraph orchestration, retrieval over local tourism knowledge, optional Google Search grounding, and Redis-backed conversation memory.

The project is designed for people who know the island and want to make reliable local knowledge easier to discover for residents and visitors.

## What it does

- Answers in friendly Persian and keeps Qeshm at the center of the experience.
- Exposes an OpenAI-compatible `POST /v1/chat/completions` endpoint with streaming support.
- Routes questions between local retrieval, fresh web-grounded answers, and general conversation.
- Remembers short conversations and can personalize recommendations.
- Runs locally without Redis or model credentials for health checks and development of the API shell.

## Quick start

```bash
git clone https://github.com/YOUR_USERNAME/geoq.git
cd geoq
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Add GEMINI_API_KEY to .env for chat responses
uvicorn api.app:app --reload --port 8001
```

Check the service at `http://localhost:8001/health`. A minimal request looks like:

```bash
curl http://localhost:8001/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"برای سفر به قشم چه جاهایی را پیشنهاد می‌کنی؟"}],"stream":false}'
```

For Redis and a containerized setup, use `docker compose up --build`.

## Configuration

Copy `.env.example` to `.env`. `GEMINI_API_KEY` is required for AI answers. `REDIS_URL` is optional; the service falls back to an in-memory store for local development. The local Chroma database is intentionally ignored by Git because it contains generated model state.

## Project layout

```text
api/                 FastAPI app and LangGraph pipeline
qa_*.json            Seed tourism knowledge for local indexing
embed_qa.py          Build the local Chroma index
tests/               Fast, dependency-light behavior tests
```

## Contributing

Issues, Persian copy improvements, verified local recommendations, tests, and translations are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. Please do not commit API keys, private user conversations, or unverified business information.

## License

Geoq is released under the MIT License. See [LICENSE](LICENSE).
