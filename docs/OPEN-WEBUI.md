# Open WebUI integration

Geoq’s intended full frontend is the customized [`geoq` branch of the Open WebUI fork](https://github.com/fredrikblau/open-webui/tree/geoq). It contains the Geoq branding and Persian-facing UI changes. It remains a separate repository so Open WebUI’s upstream history and frontend development stay independent from Geoq’s API and local knowledge.

## Fastest setup with Docker Compose

Clone both repositories side by side, then run this from the Geoq repository root:

```bash
git clone --branch geoq --depth 1 https://github.com/fredrikblau/open-webui.git ../open-webui
cp .env.example .env
# Add GEMINI_API_KEY to .env
OPEN_WEBUI_DIR=../open-webui docker compose -f docker-compose.yml -f docker-compose.open-webui.yml up --build
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

The frontend is intentionally external to this repository. To work on the customized branch:

```bash
git clone --branch geoq https://github.com/fredrikblau/open-webui.git ../open-webui
cd ../open-webui
git checkout geoq
```

To update the external frontend locally, pull the latest `geoq` branch:

```bash
git -C ../open-webui pull origin geoq
```

Keep frontend-specific changes in the Open WebUI fork. Keep Geoq API, knowledge, and integration documentation in this repository.
