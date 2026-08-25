# Open WebUI integration

Geoq’s full frontend is the customized [`geoq` branch of the Open WebUI fork](https://github.com/fredrikblau/open-webui/tree/geoq), bundled under `frontend/open-webui`. It contains the Geoq branding and Persian-facing UI changes and is available in every Geoq clone.

## Fastest setup with Docker Compose

Run this from the Geoq repository root:

```bash
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

The bundled frontend is a snapshot of the customized `geoq` branch. To update it intentionally:

```bash
git clone --branch geoq --depth 1 https://github.com/fredrikblau/open-webui.git /tmp/open-webui-geoq
rsync -a --delete --exclude .git /tmp/open-webui-geoq/ frontend/open-webui/
```

Then review the diff and commit the bundled update:

```bash
git add frontend/open-webui
git commit -m "chore: update bundled Open WebUI geoq frontend"
```

Keep frontend-specific changes in the bundled frontend and preserve the upstream Open WebUI license and notices. Keep Geoq API, knowledge, and integration documentation in this repository.
