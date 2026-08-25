# Geoq (جعوک)

> A Persian-first, community-built local guide for discovering Qeshm Island.

[![CI](https://github.com/fredrikblau/geoq/actions/workflows/ci.yml/badge.svg)](https://github.com/fredrikblau/geoq/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-0b4f6c.svg)](LICENSE)
[![Good first issues](https://img.shields.io/github/issues/fredrikblau/geoq/good%20first%20issue?label=good%20first%20issues)](https://github.com/fredrikblau/geoq/issues?q=is%3Aissue+is%3Aopen+label%3A%22good%20first%20issue%22)

![Geoq browser chat](docs/assets/geoq-chat-demo.png)

Geoq is an open-source local chat assistant for Qeshm Island and the surrounding islands of Hormoz, Hengam, Lark, and Naz. It helps residents and visitors find useful local knowledge in Persian: places to visit, food, accommodation, transport, services, shopping, culture, and practical travel advice.

This project exists because local knowledge should be easy to access, easy to improve, and owned by the community that creates it. Geoq is a foundation for that work—not a replacement for local people, official information, or responsible travel planning.

## Why Geoq?

Generic travel assistants often miss the details that matter on an island: seasonal routes, local names, nearby alternatives, Persian context, and the difference between a recommendation and an official fact. Geoq combines a local knowledge base with an AI conversation layer so contributors can improve the answers directly.

## Features

- **Persian-first experience** — friendly Persian responses with Arabic/Persian text normalization and RTL-ready showcase UI.
- **Local knowledge retrieval** — Qeshm-focused question/answer data indexed for semantic search.
- **Multi-island coverage** — Qeshm, Hormoz, Hengam, Lark, and Naz Island seed data.
- **Smart routing** — chooses local retrieval, fresh web-grounded lookup, or general conversation based on the question.
- **Conversation memory** — short-term history with optional Redis persistence and an in-memory fallback for development.
- **Personalized recommendations** — uses conversation context and user preferences when available.
- **Clarifying questions** — asks for missing details such as budget, timing, location, or food preference instead of guessing.
- **RAG confidence fallback** — falls back when local retrieval is weak rather than presenting a low-confidence match as fact.
- **Quality gate and refinement** — can evaluate and improve generated answers before finalizing them.
- **OpenAI-compatible API** — supports normal JSON responses and Server-Sent Events streaming at `/v1/chat/completions`.
- **Contributor-friendly data** — tourism records are plain JSON, reviewable in pull requests, and protected by schema and uniqueness tests.
- **Local-first development** — health checks and the API shell can run before credentials, Redis, or model weights are available.

## A small showcase

The intended experience is a short, practical conversation—not a wall of generic travel copy:

```text
کاربر: برای یک روز در قشم کجاها بروم؟

جعوک: اگر اولین بار است به قشم می‌آیی، می‌توانی روزت را این‌طور تقسیم کنی:
۱. صبح: دره ستاره‌ها و روستای برکه خلف
۲. ظهر: ناهار دریایی در یک رستوران محلی
۳. عصر: تنگه چاهکوه
۴. غروب: ساحل ناز، با توجه به زمان جزر و مد

اگر با خودرو نیستی یا فصل سفرت را بگویی، برنامه را دقیق‌تر و عملی‌تر می‌کنم.
```

The repository also includes [`t.html`](t.html), a small RTL Persian landing/showcase card for embedding in a front end. For complete request/response examples and expected behavior, see [docs/SHOWCASE.md](docs/SHOWCASE.md).

For a working browser client, open [`examples/chat.html`](examples/chat.html) while the API is running. A dependency-free command-line client is available at [`examples/chat.py`](examples/chat.py).

## Architecture

```text
Client / web UI
      │
      ▼
FastAPI ── /health, /v1/models, /v1/chat/completions
      │
      ▼
LangGraph conversation pipeline
      ├── history + memory + facts
      ├── route: local RAG / fresh lookup / chat
      ├── retrieval + reranking + confidence fallback
      ├── Persian answer generation
      └── quality gate → refinement → saved answer
      │                 │
      ▼                 ▼
Chroma local index     Redis (optional conversation state)
```

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the data flow, boundaries, and extension points. The detailed LangGraph notes remain in [`api/`](api/).

## Run it locally

```bash
git clone https://github.com/fredrikblau/geoq.git
cd geoq
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Add GEMINI_API_KEY to .env for AI responses
python -m api
```

Open `http://localhost:8001/health`. A request without streaming:

```bash
curl http://localhost:8001/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"برای سفر به قشم چه جاهایی را پیشنهاد می‌کنی؟"}],"stream":false}'
```

Or run the CLI example:

```bash
python examples/chat.py "برای یک روز در قشم برنامه سفر بده"
```

To try the browser example, serve the repository from its root so the page is easy to open:

```bash
python -m http.server 8080
# open http://localhost:8080/examples/chat.html
```

For Redis-backed local development:

```bash
docker compose up --build
```

To build the local Chroma index from seed data, run `python embed_qa.py`. The generated `qeshm_db*` directories are intentionally ignored by Git.

## Configuration

Copy `.env.example` to `.env`. `GEMINI_API_KEY` is required for AI responses. `REDIS_URL` is optional; Geoq falls back to an in-memory store. `CORS_ORIGINS` accepts a comma-separated list of allowed browser origins.

## Repository map

```text
api/                         canonical FastAPI + LangGraph implementation
docs/                        public architecture and showcase documentation
data/knowledge/              reviewed local tourism seed data
embed_qa.py                 build the local Chroma index
tests/                       fast data, text, and repository contract tests
examples/                    standalone browser and CLI clients
t.html                      standalone Persian RTL showcase card
```

## Contributing

The best first contributions are verified local knowledge, Persian copy improvements, API tests, translations, and documentation. Browse the [good first issues](https://github.com/fredrikblau/geoq/issues?q=is%3Aissue+is%3Aopen+label%3A%22good%20first%20issue%22), read [CONTRIBUTING.md](CONTRIBUTING.md), and comment on an issue before starting substantial work.

Please do not commit API keys, private user conversations, scraped personal data, or unverified business claims. For changing information such as prices, opening hours, and transport schedules, include a source or verification date in the pull request.

## Project status and limitations

Geoq is an early open-source project. It is not yet a verified real-time travel authority, and AI answers can be wrong. Users should confirm safety, weather, transport, prices, opening hours, and official requirements with current local or official sources.

## License

Geoq is released under the [MIT License](LICENSE).
