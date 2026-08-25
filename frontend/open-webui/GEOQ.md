# Geoq frontend

This directory is the customized Open WebUI frontend and backend shipped with
Geoq. It is intentionally committed as ordinary source code so a city project
can be cloned, reviewed, modified, and deployed without fetching a frontend
from another repository at runtime.

## Run it with Geoq

From the repository root:

```bash
cp .env.example .env
docker compose -f docker-compose.yml -f docker-compose.open-webui.yml up --build
```

Open <http://localhost:3000>. The bundled frontend is configured by the
compose overlay to use the Geoq OpenAI-compatible API at `http://geoq:8001/v1`.

## Customize it for a city

Keep city knowledge and branding in the root project where possible:

1. Set the `GEOQ_*` values in `.env`.
2. Add or update city knowledge under `data/knowledge/`.
3. Rebuild embeddings with `python embed_qa.py`.
4. Rebuild the compose stack after frontend changes.

See [`docs/CUSTOMIZE-CITY.md`](../../docs/CUSTOMIZE-CITY.md) for the complete
workflow and [`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md) for the
upstream Open WebUI attribution and source commit.

## Updating the bundled source

The source is based on the `geoq` branch of the project’s customized Open WebUI
fork. Updates must be reviewed as source changes, tested with the Geoq compose
overlay, and committed here. Do not convert this directory to a submodule or a
runtime download: the point of this copy is that the working frontend ships
with the project.
