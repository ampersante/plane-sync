"""Shared API layer for Plane REST API.

Provides authentication, retry with backoff, rate limit handling,
profile loading, and HTTP methods (GET, POST, PATCH, DELETE).

Consumers: plane_snapshot.py, plane_fetch.py, plane_write.py.
plane_diff.py is offline (no API).
"""

import html
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

__version__ = "0.2.1"

# ── Module state ────────────────────────────────────────────────────────────

_warnings: list[str] = []
_base_url: str = ""
_workspace: str = ""
_project: str = ""
_api_version: str = "1"
_v2_available: bool | None = None  # None = v2 probe not yet run
_request_count = 0
_count_lock = threading.Lock()

# Last observed rate-limit signal from X-RateLimit-Remaining (int) and
# X-RateLimit-Reset (UTC epoch seconds); None = header absent or unparsable.
_rl = {"remaining": None, "reset_epoch": None}
_rl_lock = threading.Lock()


def get_warnings() -> list[str]:
    """Return accumulated warnings."""
    return list(_warnings)


def clear_warnings() -> None:
    """Reset warnings list."""
    _warnings.clear()


def set_base_url(workspace: str, project: str) -> None:
    """Set the module-level base URLs (v1 and v2) for all API calls."""
    global _base_url, _workspace, _project
    _workspace = workspace
    _project = project
    _base_url = f"https://api.plane.so/api/v1/workspaces/{workspace}/projects/{project}"


def get_base_url() -> str:
    """Return current base URL."""
    return _base_url


def v2_base_url() -> str:
    """Return the v2 base URL for the current workspace/project."""
    return f"https://api.plane.so/api/v2/workspaces/{_workspace}/projects/{_project}"


def get_request_count() -> int:
    """Return the number of HTTP requests attempted since the last reset."""
    with _count_lock:
        return _request_count


def reset_request_count() -> None:
    """Reset the request counter to zero (for tests)."""
    global _request_count
    with _count_lock:
        _request_count = 0


# ── Config dir ───────────────────────────────────────────────────────────────

def config_dir() -> Path:
    """Resolve the plane-sync config directory.

    Precedence: $PLANE_SYNC_CONFIG_DIR > $XDG_CONFIG_HOME/plane-sync > ~/.config/plane-sync.
    """
    env_dir = os.environ.get("PLANE_SYNC_CONFIG_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg).expanduser() / "plane-sync"
    return Path.home() / ".config" / "plane-sync"


def profiles_path() -> Path:
    """Resolve profiles.json: config dir first, else legacy tool-root copy.

    Falls back to the config dir path (even if absent) so callers get a
    consistent, reportable location.
    """
    config_candidate = config_dir() / "profiles.json"
    if config_candidate.is_file():
        return config_candidate
    legacy_candidate = Path(__file__).resolve().parent / "profiles.json"
    if legacy_candidate.is_file():
        return legacy_candidate
    return config_candidate


# ── .env loader ─────────────────────────────────────────────────────────────

def load_dotenv(*search_dirs: Path, script_dir: Path | None = None) -> None:
    """Load KEY=VALUE pairs from .env file into os.environ (does not override).

    Searches in given directories, walks up from cwd, then falls back to the
    config dir, then the tool's own directory (lowest priority).
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

    # Config dir ranks below the cwd walk-up but above the tool root, so a
    # project-level .env always wins over the user's global config.
    candidates.append(config_dir() / ".env")

    # Tool root is the last fallback so a project-level .env always wins.
    if script_dir is None:
        script_dir = Path(__file__).resolve().parent
    candidates.append(script_dir / ".env")

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
        "User-Agent": f"plane-sync/{__version__}",
        "Accept": "application/json",
    }


# ── HTTP methods ────────────────────────────────────────────────────────────

def _update_rate_limit(headers) -> None:
    """Record X-RateLimit-Remaining/-Reset from any response (success or error).

    A missing or unparsable header clears its field to None — an absent signal
    must never be read as an empty quota. Header lookup is case-insensitive
    (http.client.HTTPMessage).
    """
    remaining = reset_epoch = None
    if headers is not None:
        raw_remaining = headers.get("X-RateLimit-Remaining")
        raw_reset = headers.get("X-RateLimit-Reset")
        if raw_remaining is not None:
            try:
                remaining = int(raw_remaining)
            except ValueError:
                remaining = None
        if raw_reset is not None:
            try:
                reset_epoch = float(raw_reset)
            except ValueError:
                reset_epoch = None
    with _rl_lock:
        _rl["remaining"] = remaining
        _rl["reset_epoch"] = reset_epoch


def _sleep_if_window_exhausted() -> None:
    """Proactively wait out the rate-limit window before sending a request.

    Best-effort: driven by the last observed X-RateLimit headers, one sleep per
    attempt with no re-check afterwards — the 429/Retry-After path stays the
    authority. The sleep runs outside the lock so other workers aren't blocked.
    """
    with _rl_lock:
        remaining = _rl["remaining"]
        reset_epoch = _rl["reset_epoch"]
    if remaining is None or remaining > 0 or reset_epoch is None:
        return
    delta = reset_epoch - time.time()
    if delta <= 0:
        return
    sleep_for = min(delta + 0.5, 65)  # limit window is 60s; 65 leaves margin
    print(f"  Rate limit window exhausted, sleeping {sleep_for:.1f}s...", file=sys.stderr)
    time.sleep(sleep_for)


def _problem_json_fields(e: urllib.error.HTTPError) -> tuple[str, str] | None:
    """Extract (code, detail) from an RFC 9457 problem+json error body.

    Returns None when the body is absent, unreadable, or not a JSON object
    carrying at least one of the code/detail fields — the caller then falls
    back to the generic error path.
    """
    try:
        payload = json.loads(e.read().decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict) or ("code" not in payload and "detail" not in payload):
        return None
    return str(payload.get("code", "")), str(payload.get("detail", ""))


def _request_with_retry(req: urllib.request.Request, path: str, *,
                        max_retries: int = 3, critical: bool = True,
                        problem_json: bool = False) -> dict:
    """Execute a request with retry, backoff, and rate limit handling.

    Before each send, the last observed X-RateLimit headers may trigger a
    proactive wait for the window to reset (best-effort throttle, see
    _sleep_if_window_exhausted).

    With problem_json=True (v2 reads), a 4xx whose body is an RFC 9457
    problem+json object is a definitive answer: no retry, one warning with the
    server's code/detail, empty dict return. Other failures keep the shared
    retry/warning path.

    429 (rate limited) waits out Retry-After and retries WITHOUT consuming the
    retry budget — rate limiting is transient and must not cause a request to be
    dropped (which would silently lose data, e.g. relations). A safety cap on
    consecutive 429s guards against a pathological never-ending loop.
    """
    global _request_count
    last_error = None
    attempt = 0          # counts only genuine errors, not 429 throttling
    rate_limited = 0     # consecutive 429s, capped to avoid an infinite loop
    while attempt <= max_retries:
        _sleep_if_window_exhausted()
        # every urlopen attempt is a request — retries and 429-waits included
        with _count_lock:
            _request_count += 1
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                _update_rate_limit(resp.headers)
                body = resp.read().decode()
                if not body:
                    return {}  # e.g. 204 No Content from DELETE
                return json.loads(body)
        except urllib.error.HTTPError as e:
            _update_rate_limit(e.headers)
            if e.code in (401, 403):
                print(f"Error: Authentication failed (HTTP {e.code}).", file=sys.stderr)
                print("Check your PLANE_API_TOKEN. Get one at: Plane → Settings → API Tokens", file=sys.stderr)
                sys.exit(1)
            if e.code == 429:
                rate_limited += 1
                if rate_limited > 20:
                    last_error = e
                    break  # give up only after 20 consecutive rate-limit waits
                retry_after = int(e.headers.get("Retry-After", 5))
                print(f"  Rate limited, waiting {retry_after}s...", file=sys.stderr)
                time.sleep(retry_after)
                continue  # don't count as a retry attempt
            if e.code == 404 and not critical:
                return {}
            if problem_json and 400 <= e.code < 500:
                fields = _problem_json_fields(e)
                if fields is not None:
                    code, detail = fields
                    _warnings.append(f"Failed {path}: {e} (code={code}, detail={detail})")
                    return {}
            last_error = e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_error = e

        rate_limited = 0
        if attempt < max_retries:
            backoff = 2 ** attempt  # 1, 2, 4
            print(f"  Retry {attempt + 1}/{max_retries} for {path} (waiting {backoff}s)...", file=sys.stderr)
            time.sleep(backoff)
        attempt += 1

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


def api_get_paginated(path: str, *, critical: bool = True) -> list:
    """GET a paginated endpoint, following cursor until exhausted."""
    all_results = []
    params = {"per_page": "100"}
    page = 1

    while True:
        print(f"  Fetching {path} (page {page})...", file=sys.stderr)
        data = api_get(path, params=params, critical=critical)

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


def detect_prefix(*, default: str = "??") -> str:
    """Auto-detect project ID prefix from the project endpoint."""
    try:
        project = api_get("", max_retries=2, critical=False)
        return project.get("identifier", default)
    except Exception:
        return default


# ── API version mode and v2 layer ───────────────────────────────────────────

def set_api_version(version: str) -> None:
    """Set the API version mode: "1" (default, v1 only) or "auto".

    Read from the profile's optional `api_version` key; no schema validation —
    any value other than "auto" behaves as v1.
    """
    global _api_version
    _api_version = version


def get_api_version() -> str:
    """Return the current API version mode."""
    return _api_version


def v2_available() -> bool:
    """Probe the v2 API once per run and cache the verdict.

    GET /api/v2/users/me/ is the cheapest authenticated v2 endpoint; a 404
    (self-hosted CE) or unreachable API yields False without aborting the run.
    The verdict is cached because it cannot change mid-run; reset_v2_cache()
    exists for tests. The cache is a plain module value: a concurrent first
    call could duplicate the probe, which is benign (idempotent GET, same
    verdict stored).
    """
    global _v2_available
    if _v2_available is not None:
        return _v2_available
    req = urllib.request.Request("https://api.plane.so/api/v2/users/me/",
                                 headers=_headers())
    data = _request_with_retry(req, "api/v2/users/me/", critical=False)
    _v2_available = bool(data)
    return _v2_available


def reset_v2_cache() -> None:
    """Forget the cached v2 probe verdict (for tests)."""
    global _v2_available
    _v2_available = None


def v2_enabled() -> bool:
    """True only when the mode is "auto" AND the probe confirmed v2.

    Mode "1" short-circuits before any network call: zero v2 requests,
    the probe included.
    """
    return get_api_version() == "auto" and v2_available()


def api_v2_get(path: str, *, params: dict | None = None) -> dict:
    """GET on the v2 base URL; returns the full v2 envelope.

    The v2 envelope carries rows under `data` with cursor fields
    `next_cursor`/`has_more` (v1 uses `results`/`next_page_results`). Reads are
    non-critical: an RFC 9457 problem+json 4xx body is reduced to one warning
    carrying the server's code/detail and an empty dict; every other failure
    follows the shared retry-and-warn path.
    """
    url = f"{v2_base_url()}/{path.lstrip('/')}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(url, headers=_headers())
    return _request_with_retry(req, path, critical=False, problem_json=True)


def api_v2_post(path: str, body: dict) -> dict:
    """POST on the v2 base URL (bulk mutations: bulk-create, bulk-update).

    Non-critical like every write mutation in this tool: an RFC 9457
    problem+json 4xx body is reduced to one warning carrying the server's
    code/detail and an empty dict; every other failure follows the shared
    retry-and-warn path.
    """
    url = f"{v2_base_url()}/{path.lstrip('/')}"
    data = json.dumps(body).encode()

    req = urllib.request.Request(url, data=data, headers=_headers(), method="POST")
    return _request_with_retry(req, path, critical=False, problem_json=True)


# ── Profile loader ──────────────────────────────────────────────────────────

def load_profile(name: str) -> dict:
    """Load a named profile from profiles.json (config dir, or legacy tool-root fallback)."""
    path = profiles_path()
    if not path.is_file():
        print(f"Error: profiles.json not found at {path}", file=sys.stderr)
        print("Create it at ~/.config/plane-sync/profiles.json (see profiles.example.json).",
              file=sys.stderr)
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        profiles = json.load(f)
    if name not in profiles:
        available = ", ".join(profiles.keys()) or "(none)"
        print(f"Error: profile '{name}' not found. Available: {available}", file=sys.stderr)
        sys.exit(1)
    return profiles[name]


def validate_profile_paths(profile: dict, *, require_output: bool) -> None:
    """Require profile env/output paths to be absolute after ~ expansion.

    `env` is always validated (all CLIs consume it); `output` only when the
    caller actually writes to it.
    """
    for key, required in (("env", True), ("output", require_output)):
        raw = profile.get(key)
        if not required or raw is None:
            continue
        path = Path(os.path.expanduser(str(raw)))
        if not path.is_absolute():
            print(
                f"Error: profile field '{key}' must be an absolute path, got '{raw}'.",
                file=sys.stderr,
            )
            print(f"Use a '~' path (e.g. '~/project/.env') or an absolute path.",
                  file=sys.stderr)
            sys.exit(1)


def list_profiles(path: Path | None = None) -> None:
    """Print available profiles from profiles.json (no network, no token)."""
    if path is None:
        path = profiles_path()
    if not path.is_file():
        print(f"profiles.json not found at {path}", file=sys.stderr)
        print("Create it at ~/.config/plane-sync/profiles.json (see profiles.example.json).",
              file=sys.stderr)
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        profiles = json.load(f)
    if not profiles:
        print("(no profiles)")
        return
    print(f"{'Profile':<20} {'Workspace':<24} {'Project':<40} Output")
    print("-" * 100)
    for name, p in profiles.items():
        workspace = p.get("workspace", "-")
        project = p.get("project", "-")
        output = p.get("output", "-")
        print(f"{name:<20} {workspace:<24} {project:<40} {output}")


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
