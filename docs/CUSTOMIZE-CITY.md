# Build a Geoq city pack

Geoq is a reusable local-assistant platform. Qeshm is the first city pack, not a hard limit.

## 1. Configure the identity

Copy `.env.example` and change:

```dotenv
GEOQ_NAME=Your local assistant name
GEOQ_REGION=Your city
GEOQ_SUPPORTED_AREAS=Your city and nearby areas
GEOQ_OFFICIAL_URL=your-official-site.example
GEOQ_CREATOR_TEXT=Built with local guides and residents.
```

These values localize the API identity and core prompt behavior without editing the orchestration code.

## 2. Replace the knowledge pack

Add one or more JSON files under `data/knowledge/`. Each record must contain:

```json
{
  "id": "city_001",
  "question": "Where can visitors ...?",
  "answer": "...",
  "category": "food",
  "tags": ["local", "verified"]
}
```

Use stable unique IDs. Prefer facts collected from residents, licensed guides, businesses, and official local organizations. Add a verification date or source in the pull request for information that changes.

## 3. Build the local index

```bash
python embed_qa.py
```

The script loads every `data/knowledge/qa_*.json` file, so a city pack can be split by neighborhood, language, or topic.

## 4. Brand the frontend

The customized Open WebUI frontend is vendored under `frontend/open-webui`. Update its branding and translations in that directory, then build the integrated stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.open-webui.yml up --build
```

Keep city-specific knowledge in `data/knowledge/`; keep reusable code and platform improvements city-neutral.
