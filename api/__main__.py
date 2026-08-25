"""Run Geoq with ``python -m api``."""

import uvicorn

from .config import PORT


if __name__ == "__main__":
    uvicorn.run("api.app:app", host="0.0.0.0", port=PORT)
