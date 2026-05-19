#!/usr/bin/env bash
# ===========================================================================
#  ComfyUI model/workflow downloader - bootstrap wrapper
# ---------------------------------------------------------------------------
#  Installs dependencies, downloads the downloader script + config from
#  BASE_URL, then runs it. Any extra args are passed through to fetch_models.py
#  (e.g. --dry-run, --force, --comfyui /path).
#
#  Run (defaults baked in below):
#     curl -fsSL <BASE_URL>/bootstrap.sh | bash
#
#  Override base location / config name / pass args:
#     curl -fsSL <BASE_URL>/bootstrap.sh \
#       | BASE_URL=https://my.server/comfy CONFIG=models.yaml bash -s -- --dry-run
# ===========================================================================
set -euo pipefail

# --- defaults: EDIT THESE to point at your server / GitHub raw URL ----------
BASE_URL="${BASE_URL:-https://raw.githubusercontent.com/USER/REPO/main}"
CONFIG="${CONFIG:-models.yaml}"
SCRIPT="${SCRIPT:-fetch_models.py}"
WORKDIR="${WORKDIR:-/workspace/.comfy-fetch}"
# ---------------------------------------------------------------------------

log() { echo "[bootstrap] $*"; }

log "BASE_URL = $BASE_URL"
log "config   = $CONFIG | script = $SCRIPT"
log "workdir  = $WORKDIR"

# --- 1. dependencies -------------------------------------------------------
need_apt=()
command -v python3 >/dev/null 2>&1 || need_apt+=(python3)
command -v pip3   >/dev/null 2>&1 || need_apt+=(python3-pip)
command -v curl   >/dev/null 2>&1 || need_apt+=(curl)
command -v aria2c >/dev/null 2>&1 || need_apt+=(aria2)   # fast parallel DL

if [ "${#need_apt[@]}" -gt 0 ]; then
  log "installing via apt: ${need_apt[*]}"
  if command -v sudo >/dev/null 2>&1; then SUDO=sudo; else SUDO=; fi
  $SUDO apt-get update -qq
  DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y -qq "${need_apt[@]}"
fi

log "installing pyyaml"
pip3 install -q --upgrade pyyaml --break-system-packages 2>/dev/null \
  || pip3 install -q --upgrade pyyaml

# --- 2. fetch script + config ---------------------------------------------
mkdir -p "$WORKDIR"
cd "$WORKDIR"

log "downloading $SCRIPT"
curl -fsSL "$BASE_URL/$SCRIPT" -o "$SCRIPT"

log "downloading $CONFIG"
curl -fsSL "$BASE_URL/$CONFIG" -o "$CONFIG"

# --- 3. run (pass through any extra args) ----------------------------------
log "running downloader..."
exec python3 "$SCRIPT" -c "$CONFIG" "$@"
