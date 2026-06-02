"""Shared API layer for Plane REST API.

Provides authentication, retry with backoff, rate limit handling,
profile loading, and HTTP methods (GET, POST, PATCH).

Used by plane_snapshot.py (read) and plane_write.py (write).
"""

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
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
                body = resp.read().decode()
                if not body:
                    return {}  # e.g. 204 No Content from DELETE
                return json.loads(body)
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


def api_delete(path: str, *,
               max_retries: int = 3, critical: bool = True) -> dict:
    """DELETE request with retry and error handling."""
    url = f"{_base_url}/{path.lstrip('/')}"

    req = urllib.request.Request(url, headers=_headers(), method="DELETE")
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


# ── HTML → text ────────────────────────────────────────────────────────────

class _PlaneHTMLConverter(HTMLParser):
    """Converts Plane editor HTML to clean text with light markdown."""

    _BLOCK_TAGS = {"p", "div", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}
    _HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
    _SKIP_TAGS = {"image-component"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._list_stack: list[str] = []  # "ul" or "ol"
        self._ol_counters: list[int] = []
        self._in_li = False
        self._skip_depth = 0
        self._href: str | None = None
        self._link_text: list[str] = []
        self._in_pre = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr_map = dict(attrs)

        if tag in self._SKIP_TAGS:
            if self._skip_depth == 0:
                self._chunks.append("[image]")
            self._skip_depth += 1
            return
        if self._skip_depth:
            return

        if tag in self._HEADING_TAGS:
            level = int(tag[1])
            self._chunks.append(f"\n{'#' * level} ")
        elif tag == "p":
            pass  # text flows, newlines added on close
        elif tag == "br":
            self._chunks.append("\n")
        elif tag == "ul":
            self._list_stack.append("ul")
        elif tag == "ol":
            self._list_stack.append("ol")
            self._ol_counters.append(0)
        elif tag == "li":
            self._in_li = True
            indent = "  " * max(0, len(self._list_stack) - 1)
            if self._list_stack and self._list_stack[-1] == "ol":
                self._ol_counters[-1] += 1
                self._chunks.append(f"{indent}{self._ol_counters[-1]}. ")
            else:
                self._chunks.append(f"{indent}- ")
        elif tag in ("strong", "b"):
            self._chunks.append("**")
        elif tag in ("em", "i"):
            self._chunks.append("*")
        elif tag == "code" and not self._in_pre:
            self._chunks.append("`")
        elif tag == "pre":
            self._in_pre = True
            self._chunks.append("\n```\n")
        elif tag == "blockquote":
            self._chunks.append("\n> ")
        elif tag == "a":
            self._href = html.unescape(attr_map.get("href", ""))
            self._link_text = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()

        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return

        if tag in self._HEADING_TAGS:
            self._chunks.append("\n\n")
        elif tag == "p":
            if not self._in_li:
                self._chunks.append("\n\n")
            else:
                pass  # inside <li>, <p> is just a wrapper
        elif tag == "div":
            self._chunks.append("\n\n")
        elif tag == "ul":
            if self._list_stack:
                self._list_stack.pop()
            self._chunks.append("\n")
        elif tag == "ol":
            if self._list_stack:
                self._list_stack.pop()
            if self._ol_counters:
                self._ol_counters.pop()
            self._chunks.append("\n")
        elif tag == "li":
            self._in_li = False
            self._chunks.append("\n")
        elif tag in ("strong", "b"):
            self._chunks.append("**")
        elif tag in ("em", "i"):
            self._chunks.append("*")
        elif tag == "code" and not self._in_pre:
            self._chunks.append("`")
        elif tag == "pre":
            self._in_pre = False
            self._chunks.append("\n```\n")
        elif tag == "blockquote":
            self._chunks.append("\n\n")
        elif tag == "a":
            text = "".join(self._link_text).strip()
            href = self._href or ""
            if href and text and text != href:
                self._chunks.append(f"[{text}]({href})")
            elif href:
                self._chunks.append(href)
            else:
                self._chunks.append(text)
            self._href = None
            self._link_text = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._href is not None:
            self._link_text.append(data)
        else:
            self._chunks.append(data)

    def get_result(self) -> str:
        return "".join(self._chunks)


def html_to_text(raw: str) -> str:
    """Convert Plane description_html to clean text with light markdown."""
    if not raw:
        return ""
    converter = _PlaneHTMLConverter()
    converter.feed(raw)
    result = converter.get_result()
    result = html.unescape(result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()
