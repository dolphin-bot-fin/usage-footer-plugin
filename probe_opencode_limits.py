#!/usr/bin/env python3
"""Probe OpenCode API for usage/limit endpoints (GET only, key from .env)."""
import json
import os
import urllib.request

key = ""
with open(os.path.expanduser("~/.hermes/.env")) as f:
    for line in f:
        if line.startswith("OPENCODE_GO_API_KEY="):
            key = line.split("=", 1)[1].strip().strip('"').strip("'")
            break

base = "https://opencode.ai/zen/go/v1"
candidates = [
    f"{base}/usage",
    f"{base}/limits",
    f"{base}/quota",
    f"{base}/me",
    f"{base}/account",
    "https://opencode.ai/api/usage",
    "https://opencode.ai/api/me",
    "https://opencode.ai/api/auth/session",
]
for url in candidates:
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "User-Agent": "hermes-agent"})
        with urllib.request.urlopen(req, timeout=8) as r:
            body = r.read().decode()[:300]
            print(f"{r.status} {url}\n  {body}\n")
    except urllib.error.HTTPError as e:
        print(f"{e.code} {url}  ({e.reason})")
    except Exception as e:
        print(f"ERR {url}  ({type(e).__name__}: {e})")
