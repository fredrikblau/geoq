# Contributing to Geoq

Thanks for helping make local knowledge about Qeshm more useful.

## Before you start

1. Search existing issues and open an issue for large changes.
2. Never include secrets, private conversations, or scraped data without permission.
3. For tourism facts, prefer information that can be verified locally and include the date when it may change.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
python -m compileall api
```

Keep changes focused, add tests for behavior changes, and use clear commit messages. Pull requests should explain what changed, how it was tested, and whether Persian wording or safety behavior changed.
