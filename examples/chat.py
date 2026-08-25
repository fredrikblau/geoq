"""Small dependency-free client for the running Geoq API.

Usage:
    python examples/chat.py "برای یک روز در قشم برنامه بده"
"""

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def ask(base_url: str, question: str) -> str:
    payload = json.dumps({
        "model": "geoq-0",
        "stream": False,
        "session_id": "cli-demo",
        "messages": [{"role": "user", "content": question}],
    }).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=120) as response:
        body = json.load(response)
    return body["choices"][0]["message"]["content"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask Geoq a Persian travel question")
    parser.add_argument("question")
    parser.add_argument("--base-url", default="http://localhost:8001")
    args = parser.parse_args()
    try:
        print(ask(args.base_url, args.question))
    except (HTTPError, URLError, KeyError, TimeoutError) as error:
        print(f"Geoq request failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
