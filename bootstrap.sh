#!/usr/bin/env bash
# ===========================================================================
#  ComfyUI model/workflow downloader - bootstrap wrapper
# ---------------------------------------------------------------------------
#  Installs dependencies, downloads the downloader script + config from
#  BASE_URL, then runs it. Any extra args are passed through to fetch_models.py
#  (e.g. --dry-run, --force, --comfyui /path, --skip-nodes, --no-restart).
#
#  BASE_URL resolution order:
#    1. explicit  BASE_URL=...           (env, highest priority)
#    2. derived from BOOTSTRAP_URL       (dirname of the bootstrap.sh URL)
#    3. hardcoded default below          (plain `curl ... | bash`)
#
#  Recommended one-liner (URL typed once, reused for BASE_URL derivation):
#     U="https://raw.githubusercontent.com/USER/REPO/main/SUBDIR/bootstrap.sh"
#     curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash
# ===========================================================================
set -euo pipefail

# --- defaults --------------------------------------------------------------
DEFAULT_BASE_URL="https://raw.githubusercontent.com/dimitriy7877-gif/comfy_conf/main"
CONFIG="${CONFIG:-models.yaml}"
SCRIPT="${SCRIPT:-fetch_models.py}"
WORKDIR="${WORKDIR:-/workspace/.comfy-fetch}"
BOOTSTRAP_URL="${BOOTSTRAP_URL:-}"
GITHUB_TOKEN="${GITHUB_TOKEN:-}"
# ---------------------------------------------------------------------------

log() { echo "[bootstrap] $*"; }

# --- 0. resolve BASE_URL ---------------------------------------------------
if [ -n "${BASE_URL:-}" ]; then
  log "BASE_URL from env (explicit)"
elif [ -n "$BOOTSTRAP_URL" ]; then
  BASE_URL="${BOOTSTRAP_URL%/*}"
  log "BASE_URL derived from BOOTSTRAP_URL"
else
  BASE_URL="$DEFAULT_BASE_URL"
  log "BASE_URL from hardcoded default"
fi
BASE_URL="${BASE_URL%/}"

log "BASE_URL = $BASE_URL"
log "config   = $CONFIG | script = $SCRIPT"
log "workdir  = $WORKDIR"

# --- 0b. derive GitHub Contents API URL for the repo's workflows/ dir ------
WORKFLOWS_LISTING_URL=""
case "$BASE_URL" in
  https://raw.githubusercontent.com/*)
    rest="${BASE_URL#https://raw.githubusercontent.com/}"
    owner="$(printf '%s' "$rest" | cut -d/ -f1)"
    repo="$(printf '%s'  "$rest" | cut -d/ -f2)"
    branch="$(printf '%s' "$rest" | cut -d/ -f3)"
    dirpath="$(printf '%s' "$rest" | cut -d/ -f4-)"
    dirpath="${dirpath#/}"; dirpath="${dirpath%/}"
    if [ -n "$owner" ] && [ -n "$repo" ] && [ -n "$branch" ]; then
      if [ -n "$dirpath" ]; then
        wf_path="$dirpath/workflows"
      else
        wf_path="workflows"
      fi
      WORKFLOWS_LISTING_URL="https://api.github.com/repos/$owner/$repo/contents/$wf_path?ref=$branch"
      log "workflows dir API = $WORKFLOWS_LISTING_URL"
    fi
    ;;
  *)
    log "BASE_URL is not a github raw URL -> workflow auto-discovery disabled"
    ;;
esac

# --- 1. dependencies -------------------------------------------------------
need_apt=()
command -v python3 >/dev/null 2>&1 || need_apt+=(python3)
command -v pip3   >/dev/null 2>&1 || need_apt+=(python3-pip)
command -v curl   >/dev/null 2>&1 || need_apt+=(curl)
command -v git    >/dev/null 2>&1 || need_apt+=(git)      # for node clones
command -v aria2c >/dev/null 2>&1 || need_apt+=(aria2)    # fast parallel DL

if [ "${#need_apt[@]}" -gt 0 ]; then
  log "installing via apt: ${need_apt[*]}"
  if command -v sudo >/dev/null 2>&1; then SUDO=sudo; else SUDO=; fi
  $SUDO apt-get update -qq
  DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y -qq "${need_apt[@]}"
fi

log "installing pyyaml"
pip3 install -q --upgrade pyyaml --break-system-packages 2>/dev/null \
  || pip3 install -q --upgrade pyyaml

# comfy-cli drives custom-node installation. fetch_models.py will further
# install the `comfyui-manager` pip package into the right Python on first
# run (it's required for `comfy node install` to work).
log "installing comfy-cli"
pip3 install -q --upgrade comfy-cli --break-system-packages 2>/dev/null \
  || pip3 install -q --upgrade comfy-cli \
  || log "WARNING: comfy-cli install failed (custom-node installation will fail)"

# --- 2. fetch script + config ---------------------------------------------
mkdir -p "$WORKDIR"
cd "$WORKDIR"

log "downloading $SCRIPT"
curl -fsSL "$BASE_URL/$SCRIPT" -o "$SCRIPT"

log "downloading $CONFIG"
curl -fsSL "$BASE_URL/$CONFIG" -o "$CONFIG"

# --- 3. run (pass through any extra args) ----------------------------------
extra=()
if [ -n "$WORKFLOWS_LISTING_URL" ]; then
  extra+=(--workflows-listing-url "$WORKFLOWS_LISTING_URL")
fi
if [ -n "$GITHUB_TOKEN" ]; then
  extra+=(--github-token "$GITHUB_TOKEN")
fi

log "running downloader..."
exec python3 "$SCRIPT" -c "$CONFIG" "${extra[@]}" "$@"
