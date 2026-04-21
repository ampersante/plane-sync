"""Shared API layer for Plane REST API.

Provides authentication, retry with backoff, rate limit handling,
profile loading, and HTTP methods (GET, POST, PATCH).

Used by plane_snapshot.py (read) and plane_write.py (write).
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ── Module state ────────────────────────────────────────────────────────────

_warnings: list[str] = []
_base_url: str = ""


def get_warnings() -> list[str]:
    """Return accumulated warnings."""
    return list(_warnings)


def clear_warnings() -> None:
    """Reset warnings list."""
    _warnings.clear()


def set_base_url(workspace: str, project: str) -> None:
    """Set the module-level base URL for all API calls."""
    global _base_url
    _base_url = f"https://api.plane.so/api/v1/workspaces/{workspace}/projects/{project}"


def get_base_url() -> str:
    """Return current base URL."""
    return _base_url


# ── .env loader ─────────────────────────────────────────────────────────────

def load_dotenv(*search_dirs: Path) -> None:
    """Load KEY=VALUE pairs from .env file into os.environ (does not override).

    Searches in given directories, then walks up from current working dir.
    """
    candidates = [d / ".env" for d in search_dirs]
    # Also walk up from cwd
    search = Path.cwd()
    for _ in range(10):
        candidates.append(search / ".env")
        parent = search.parent
        if parent == search:
            break
        search = parent

    for candidate in candidates:
        if candidate.is_file():
            with open(candidate, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = value
            return
    return


# ── Auth ────────────────────────────────────────────────────────────────────

def get_token() -> str:
    """Get PLANE_API_TOKEN from environment."""
    token = os.environ.get("PLANE_API_TOKEN", "")
    if not token:
        print("Error: PLANE_API_TOKEN not found.", file=sys.stderr)
        print("Set it in .env file or as environment variable.", file=sys.stderr)
        print("Get your API key at: Plane → workspace settings → API Tokens", file=sys.stderr)
        sys.exit(1)
    return token


def _headers() -> dict:
    """Build standard request headers."""
    return {
        "X-API-Key": get_token(),
        "Content-Type": "application/json",
        "User-Agent": "PlaneSync/1.0",
        "Accept": "application/json",
    }


# ── HTTP methods ────────────────────────────────────────────────────────────

def _request_with_retry(req: urllib.request.Request, path: str, *,
                        max_retries: int = 3, critical: bool = True) -> dict:
    """Execute a request with retry, backoff, and rate limit handling."""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                print(f"Error: Authentication failed (HTTP {e.code}).", file=sys.stderr)
                print("Check your PLANE_API_TOKEN. Get one at: Plane → Settings → API Tokens", file=sys.stderr)
                sys.exit(1)
            if e.code == 429:
                retry_after = int(e.headers.get("Retry-After", 5))
                print(f"  Rate limited, waiting {retry_after}s...", file=sys.stderr)
                time.sleep(retry_after)
                continue  # don't count as attempt
            if e.code == 404 and not critical:
                return {}
            last_error = e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_error = e

        if attempt < max_retries:
            backoff = 2 ** attempt  # 1, 2, 4
            print(f"  Retry {attempt + 1}/{max_retries} for {path} (waiting {backoff}s)...", file=sys.stderr)
            time.sleep(backoff)

    if critical:
        print(f"Error: Failed {path} after {max_retries} retries: {last_error}", file=sys.stderr)
        sys.exit(1)
    else:
        _warnings.append(f"Failed {path}: {last_error}")
        return {}


def api_get(path: str, *, params: dict | None = None,
            max_retries: int = 3, critical: bool = True) -> dict:
    """GET request with retry and error handling."""
    url = f"{_base_url}/{path.lstrip('/')}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(url, headers=_headers())
    return _request_with_retry(req, path, max_retries=max_retries, critical=critical)


def api_get_list(path: str, **kwargs) -> list:
    """GET a non-paginated list endpoint. Handles both 'result' and 'results' keys."""
    data = api_get(path, **kwargs)
    if "result" in data:
        return data["result"]
    if "results" in data:
        return data["results"]
    if isinstance(data, list):
        return data
    return []


def api_get_paginated(path: str) -> list:
    """GET a paginated endpoint, following cursor until exhausted."""
    all_results = []
    params = {"per_page": "100"}
    page = 1

    while True:
        print(f"  Fetching {path} (page {page})...", file=sys.stderr)
        data = api_get(path, params=params)

        results = data.get("results", data.get("result", []))
        if isinstance(results, list):
            all_results.extend(results)

        if data.get("next_page_results") and data.get("next_cursor"):
            params["cursor"] = data["next_cursor"]
            page += 1
        else:
            break

    return all_results


def api_post(path: str, body: dict, *,
             max_retries: int = 3, critical: bool = True) -> dict:
    """POST request with retry and error handling."""
    url = f"{_base_url}/{path.lstrip('/')}"
    data = json.dumps(body).encode()

    req = urllib.request.Request(url, data=data, headers=_headers(), method="POST")
    return _request_with_retry(req, path, max_retries=max_retries, critical=critical)


def api_patch(path: str, body: dict, *,
              max_retries: int = 3, critical: bool = True) -> dict:
    """PATCH request with retry and error handling."""
    url = f"{_base_url}/{path.lstrip('/')}"
    data = json.dumps(body).encode()

    req = urllib.request.Request(url, data=data, headers=_headers(), method="PATCH")
    return _request_with_retry(req, path, max_retries=max_retries, critical=critical)


# ── Profile loader ──────────────────────────────────────────────────────────

def load_profile(name: str) -> dict:
    """Load a named profile from profiles.json next to the calling script."""
    profiles_path = Path(__file__).resolve().parent / "profiles.json"
    if not profiles_path.is_file():
        print(f"Error: profiles.json not found at {profiles_path}", file=sys.stderr)
        sys.exit(1)
    with open(profiles_path, encoding="utf-8") as f:
        profiles = json.load(f)
    if name not in profiles:
        available = ", ".join(profiles.keys()) or "(none)"
        print(f"Error: profile '{name}' not found. Available: {available}", file=sys.stderr)
        sys.exit(1)
    return profiles[name]
