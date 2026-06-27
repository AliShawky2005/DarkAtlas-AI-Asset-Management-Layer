"""
Rate limiting middleware — Bonus 4.

Uses `slowapi` (a Starlette/FastAPI wrapper around `limits`).

Limits:
  - 60 requests/minute per IP on all endpoints (global)
  - 10 requests/minute per IP on LLM-powered analysis endpoints

No Redis needed — limits are tracked in-process (fine for a single instance).
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

# Global limiter instance — imported by main.py and route files
limiter = Limiter(key_func=get_remote_address)
