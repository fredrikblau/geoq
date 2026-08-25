# Open WebUI integration

Geoq’s intended full frontend is the customized [`geoq` branch of the Open WebUI fork](https://github.com/fredrikblau/open-webui/tree/geoq). It contains the Geoq branding and Persian-facing UI changes. Geoq links to that exact branch as a git submodule at `frontend/open-webui`.

## Fastest setup with Docker Compose

From the Geoq repository root:

```bash
git submodule update --init --recursive
cp .env.example .env
# Add GEMINI_API_KEY to .env
docker compose -f docker-compose.yml -f docker-compose.open-webui.yml up --build
```

Then open [http://localhost:3000](http://localhost:3000). Open WebUI talks to the Geoq API through the Compose service name `geoq` at `http://geoq:8001/v1`.

The integration uses these settings:

| Setting | Value | Purpose |
| --- | --- | --- |
| `WEBUI_NAME` | `Geoq` | Geoq branding in the frontend |
| `OPENAI_API_BASE_URLS` | `http://geoq:8001/v1` | Geoq’s OpenAI-compatible API |
| `OPENAI_API_KEYS` | `geoq-local` | Placeholder accepted by the local Geoq backend |
| `WEBUI_URL` | `http://localhost:3000` | Browser-facing Open WebUI URL |

Geoq does not currently authenticate API keys. Do not expose this setup directly to the public internet without adding authentication and HTTPS.

## Manual Open WebUI setup

If you already run Open WebUI, use the `geoq` branch of the fork:

```bash
git clone --branch geoq --depth 1 https://github.com/fredrikblau/open-webui.git
cd open-webui
cp .env.example .env
```

Set the Open WebUI connection to:

- API base URL: `http://localhost:8001/v1` when Open WebUI runs on the host
- API base URL: `http://host.docker.internal:8001/v1` when Open WebUI runs in Docker and Geoq runs on the host
- API key: `geoq-local`

In the Open WebUI admin panel, the same connection can be added under **Settings → Connections → OpenAI API**. Select `geoq-0` after the connection is saved.

## Development workflow

The submodule is pinned by Geoq’s Git tree and tracks the `geoq` branch in `.gitmodules`:

```bash
git submodule update --init --recursive
cd frontend/open-webui
git checkout geoq
```

To update the pinned frontend intentionally, pull the latest `geoq` branch, return to the Geoq root, and commit the changed submodule pointer:

```bash
git -C frontend/open-webui pull origin geoq
git add frontend/open-webui
git commit -m "chore: update Open WebUI geoq frontend"
```

Keep frontend-specific changes in the Open WebUI fork. Keep Geoq API, knowledge, and integration documentation in this repository.
