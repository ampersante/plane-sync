#!/usr/bin/env bash
# plane-sync installer: fetches a release tarball, unpacks it into
# $PLANE_SYNC_HOME, and symlinks bin/plane-sync into $PLANE_SYNC_BIN.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/ampersante/plane-sync/main/install.sh | bash
#   bash install.sh --uninstall
#
# Env overrides:
#   PLANE_SYNC_TARBALL   URL or local path to a release tarball (skips lookup)
#   PLANE_SYNC_VERSION   release tag to install (e.g. v0.1.0)
#   PLANE_SYNC_HOME       default: $HOME/.local/share/plane-sync
#   PLANE_SYNC_BIN        default: $HOME/.local/bin
set -euo pipefail

PLANE_SYNC_HOME="${PLANE_SYNC_HOME:-$HOME/.local/share/plane-sync}"
PLANE_SYNC_BIN="${PLANE_SYNC_BIN:-$HOME/.local/bin}"
STAMP_FILE=".plane-sync-install"
REPO="ampersante/plane-sync"

log() { printf '%s\n' "$*" >&2; }

# Aborts unless $PLANE_SYNC_HOME is either absent or an install this script
# created (has the stamp file, and is not a dev checkout with .git).
guard_owned_install() {
  if [[ -e "$PLANE_SYNC_HOME" ]]; then
    if [[ ! -e "$PLANE_SYNC_HOME/$STAMP_FILE" ]] || [[ -e "$PLANE_SYNC_HOME/.git" ]]; then
      log "error: $PLANE_SYNC_HOME exists but doesn't look like a plane-sync install"
      log "       created by this script (missing $STAMP_FILE, or contains .git)."
      log "       Refusing to touch it — move it aside or set PLANE_SYNC_HOME elsewhere."
      exit 1
    fi
  fi
}

# Returns success (0) if $PLANE_SYNC_BIN/plane-sync exists and does NOT
# belong to this install — a regular file, a directory, or a symlink
# pointing somewhere other than $PLANE_SYNC_HOME/bin/plane-sync. Returns
# failure (1) if the entry is absent, or is a symlink that already points
# at our own target (so it's safe to overwrite/remove).
bin_entry_is_foreign() {
  local entry="$PLANE_SYNC_BIN/plane-sync"
  local target="$PLANE_SYNC_HOME/bin/plane-sync"

  if [[ ! -e "$entry" && ! -L "$entry" ]]; then
    return 1 # absent: nothing to protect
  fi

  if [[ -L "$entry" ]]; then
    local link_text
    link_text="$(readlink "$entry")"
    if [[ "$link_text" == "$target" ]]; then
      return 1 # ours, by literal link text
    fi
    local resolved_entry resolved_target
    resolved_entry="$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$entry" 2>/dev/null || true)"
    resolved_target="$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$target" 2>/dev/null || true)"
    if [[ -n "$resolved_entry" && "$resolved_entry" == "$resolved_target" ]]; then
      return 1 # ours, after resolving to absolute/real paths
    fi
    return 0 # symlink pointing elsewhere: foreign
  fi

  return 0 # regular file or directory: foreign
}

uninstall() {
  guard_owned_install
  local bin_foreign=1
  bin_entry_is_foreign && bin_foreign=0
  if [[ -e "$PLANE_SYNC_HOME" ]]; then
    rm -rf "$PLANE_SYNC_HOME"
    log "Removed $PLANE_SYNC_HOME"
  else
    log "$PLANE_SYNC_HOME does not exist, nothing to remove."
  fi
  if [[ "$bin_foreign" -eq 0 ]]; then
    log "warning: $PLANE_SYNC_BIN/plane-sync exists but is not a symlink to"
    log "         $PLANE_SYNC_HOME/bin/plane-sync — leaving it untouched."
  elif [[ -L "$PLANE_SYNC_BIN/plane-sync" || -e "$PLANE_SYNC_BIN/plane-sync" ]]; then
    rm -f "$PLANE_SYNC_BIN/plane-sync"
    log "Removed $PLANE_SYNC_BIN/plane-sync"
  fi
  log "Config in ~/.config/plane-sync was left untouched."
  exit 0
}

if [[ "${1:-}" == "--uninstall" ]]; then
  uninstall
fi

# --- resolve a local tarball path to absolute, before any cd happens ---
local_tarball_abs=""
if [[ -n "${PLANE_SYNC_TARBALL:-}" ]]; then
  case "$PLANE_SYNC_TARBALL" in
    http://*|https://*)
      : # URL, downloaded below
      ;;
    *)
      if [[ "$PLANE_SYNC_TARBALL" = /* ]]; then
        local_tarball_abs="$PLANE_SYNC_TARBALL"
      else
        local_tarball_abs="$(pwd)/$PLANE_SYNC_TARBALL"
      fi
      ;;
  esac
fi

# --- require python3 >= 3.10 ---
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  log "error: plane-sync requires python3 >= 3.10, which was not found on PATH."
  log "  macOS: brew install ampersante/tap/plane-sync   (pulls in a compatible python3)"
  log "  or install Python 3.10+ yourself and re-run this installer."
  exit 1
fi

# Refuse to clobber a foreign file/symlink at $PLANE_SYNC_BIN/plane-sync
# before doing any network/extraction work or touching $PLANE_SYNC_HOME.
if bin_entry_is_foreign; then
  log "error: $PLANE_SYNC_BIN/plane-sync already exists and is not a plane-sync symlink."
  log "       Remove or rename it, or set PLANE_SYNC_BIN to install elsewhere."
  exit 1
fi

mkdir -p "$(dirname "$PLANE_SYNC_HOME")" "$PLANE_SYNC_BIN"

tmp="$(mktemp -d "$(dirname "$PLANE_SYNC_HOME")/.plane-sync.XXXXXX")"
dl=""
cleanup() {
  rm -rf "$tmp"
  [[ -n "$dl" ]] && rm -f "$dl"
}
trap cleanup EXIT

if [[ -n "$local_tarball_abs" ]]; then
  # Local path: no network, no release lookup at all.
  if [[ ! -f "$local_tarball_abs" ]]; then
    log "error: PLANE_SYNC_TARBALL local path not found: $local_tarball_abs"
    exit 1
  fi
  archive="$local_tarball_abs"
elif [[ -n "${PLANE_SYNC_TARBALL:-}" ]]; then
  dl="$(mktemp)"
  log "Downloading $PLANE_SYNC_TARBALL ..."
  curl -fsSL -o "$dl" "$PLANE_SYNC_TARBALL"
  archive="$dl"
else
  if [[ -n "${PLANE_SYNC_VERSION:-}" ]]; then
    tag="$PLANE_SYNC_VERSION"
  else
    log "Looking up latest release of $REPO ..."
    tag="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
      | python3 -c 'import json, sys; print(json.load(sys.stdin)["tag_name"])')"
  fi
  url="https://github.com/${REPO}/archive/refs/tags/${tag}.tar.gz"
  dl="$(mktemp)"
  log "Downloading plane-sync ${tag} ..."
  curl -fsSL -o "$dl" "$url"
  archive="$dl"
fi

tar -xzf "$archive" --strip-components=1 -C "$tmp"

if [[ ! -f "$tmp/bin/plane-sync" ]]; then
  log "error: extracted archive does not contain bin/plane-sync — bad tarball?"
  exit 1
fi

date -u +"%Y-%m-%dT%H:%M:%SZ" > "$tmp/$STAMP_FILE"

guard_owned_install
if [[ -e "$PLANE_SYNC_HOME" ]]; then
  rm -rf "$PLANE_SYNC_HOME"
fi
mv "$tmp" "$PLANE_SYNC_HOME"

# Successful move: nothing left for the trap to clean up.
trap - EXIT
[[ -n "$dl" ]] && rm -f "$dl"

ln -sfn "$PLANE_SYNC_HOME/bin/plane-sync" "$PLANE_SYNC_BIN/plane-sync"

log ""
log "plane-sync installed to $PLANE_SYNC_HOME"
log "Symlinked $PLANE_SYNC_BIN/plane-sync"

case ":$PATH:" in
  *":$PLANE_SYNC_BIN:"*) ;;
  *)
    log ""
    log "warning: $PLANE_SYNC_BIN is not on your PATH."
    log "  Add it, e.g.: export PATH=\"$PLANE_SYNC_BIN:\$PATH\""
    ;;
esac

log ""
log "Next steps:"
log "  mkdir -p ~/.config/plane-sync"
log "  cp \"$PLANE_SYNC_HOME/profiles.example.json\" ~/.config/plane-sync/profiles.json"
log "  # then add your Plane API token to ~/.config/plane-sync/.env (PLANE_API_TOKEN=...)"
log "  $PLANE_SYNC_BIN/plane-sync --version"
