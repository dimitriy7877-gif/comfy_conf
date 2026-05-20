#!/usr/bin/env python3
"""
Universal model downloader for ComfyUI (RunPod-friendly).

Reads a YAML config describing models grouped by type
(diffusion_models / checkpoints / text_encoders / vae / loras / ...)
and downloads each file into ComfyUI/models/<type>/.

Type name == subfolder name under <comfyui_path>/models/, so the schema
extends to any model type without touching this script.

Features:
  - Resumable downloads (aria2c if available, else curl -C -)
  - Skips files that already exist (size check, --force to override)
  - HuggingFace token support (gated repos) via config or HF_TOKEN env
  - Per-item rename + nested subfolder
  - Dry-run mode
  - Workflow auto-discovery: pulls every *.json from the repo's workflows/
    directory via the GitHub Contents API (top level only)
  - Custom node installation via comfy-cli (fallback: cm-cli.py),
    list declared in models.yaml, ComfyUI restarted afterwards
  - Order: workflows -> custom nodes -> models -> single restart

Usage:
  python3 fetch_models.py -c models.yaml
  python3 fetch_models.py -c models.yaml --dry-run
  python3 fetch_models.py -c models.yaml --force
  python3 fetch_models.py -c models.yaml --comfyui /path/to/ComfyUI
  python3 fetch_models.py -c models.yaml --workflows-listing-url <api_url>
  python3 fetch_models.py -c models.yaml --skip-nodes
  python3 fetch_models.py -c models.yaml --no-restart
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlsplit

try:
    import yaml
except ImportError:
    sys.exit("PyYAML not installed. Run: pip install pyyaml")


def log(msg, prefix="*"):
    print(f"[{prefix}] {msg}", flush=True)


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f}{unit}"
        n /= 1024


def filename_from_url(url):
    return unquote(os.path.basename(urlsplit(url).path))


def remote_size(url, headers):
    """Best-effort content length via HEAD; 0 if unknown."""
    cmd = ["curl", "-sIL", "--fail"]
    for h in headers:
        cmd += ["-H", h]
    cmd.append(url)
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return 0
    size = 0
    for line in out.splitlines():
        if line.lower().startswith("content-length:"):
            try:
                size = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
    return size


def build_headers(token):
    return [f"Authorization: Bearer {token}"] if token else []


def download(url, dest: Path, headers, force, dry_run):
    dest.parent.mkdir(parents=True, exist_ok=True)
    expected = remote_size(url, headers)

    if dest.exists() and not force:
        local = dest.stat().st_size
        if expected and local == expected:
            log(f"SKIP (complete): {dest.name} [{human(local)}]", "=")
            return True
        if not expected and local > 0:
            log(f"SKIP (exists, size unknown): {dest.name} [{human(local)}]", "=")
            return True
        log(f"Resuming partial: {dest.name} "
            f"[{human(local)}/{human(expected) if expected else '?'}]", ">")

    if dry_run:
        log(f"DRY-RUN would download -> {dest} "
            f"[{human(expected) if expected else 'size?'}]", ">")
        return True

    if shutil.which("aria2c"):
        cmd = [
            "aria2c", "--continue=true", "--max-connection-per-server=16",
            "--split=16", "--min-split-size=1M", "--summary-interval=10",
            "--console-log-level=warn", "--allow-overwrite=true",
            "--auto-file-renaming=false",
            "-d", str(dest.parent), "-o", dest.name,
        ]
        for h in headers:
            cmd += ["--header", h]
        cmd.append(url)
    else:
        cmd = ["curl", "-L", "--fail", "--retry", "5", "--retry-delay", "5",
               "-C", "-", "-o", str(dest)]
        for h in headers:
            cmd += ["-H", h]
        cmd.append(url)

    log(f"Downloading {dest.name} -> {dest.parent}", ">")
    rc = subprocess.run(cmd).returncode
    if rc != 0:
        log(f"FAILED ({rc}): {url}", "!")
        return False

    if expected and dest.exists() and dest.stat().st_size != expected:
        log(f"WARNING: size mismatch for {dest.name} "
            f"({human(dest.stat().st_size)} vs {human(expected)})", "!")
    log(f"DONE: {dest.name}", "+")
    return True


def fetch_list(items, base_dir: Path, headers, force, dry_run):
    """Download a flat list of items into base_dir. Returns (ok, fail)."""
    ok = fail = 0
    for item in items or []:
        if isinstance(item, str):
            item = {"url": item}
        url = item["url"]
        name = item.get("filename") or filename_from_url(url)
        sub = item.get("subdir", "")
        dest = (base_dir / sub / name) if sub else (base_dir / name)
        if download(url, dest, headers, force, dry_run):
            ok += 1
        else:
            fail += 1
    return ok, fail


def discover_workflows(listing_url, github_token):
    """
    Query the GitHub Contents API for a directory and return a list of
    workflow items ({"url": <raw_url>, "filename": <name>}) for every
    top-level *.json file. Non-fatal: returns [] on any problem.
    """
    if not listing_url:
        return []

    req = urllib.request.Request(listing_url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "comfy-fetch-models")
    if github_token:
        req.add_header("Authorization", f"Bearer {github_token}")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            log("workflow auto-discovery: no 'workflows/' dir in repo "
                "(404) - skipping", "=")
        else:
            log(f"workflow auto-discovery: HTTP {e.code} - skipping", "!")
        return []
    except Exception as e:
        log(f"workflow auto-discovery failed ({e}) - skipping", "!")
        return []

    if not isinstance(payload, list):
        log("workflow auto-discovery: unexpected API response - skipping", "!")
        return []

    found = []
    for entry in payload:
        if entry.get("type") != "file":
            continue
        name = entry.get("name", "")
        if not name.lower().endswith(".json"):
            continue
        raw = entry.get("download_url")
        if not raw:
            continue
        found.append({"url": raw, "filename": name})

    found.sort(key=lambda i: i["filename"].lower())
    log(f"workflow auto-discovery: found {len(found)} json file(s)", "#")
    return found


def merge_workflows(discovered, explicit):
    """
    Combine auto-discovered workflows with the explicit list from models.yaml.
    Explicit entries win on filename collisions (they may carry custom
    filename/subdir). Discovered files are appended only if their target
    filename is not already claimed by an explicit entry.
    """
    def norm(item):
        if isinstance(item, str):
            item = {"url": item}
        name = item.get("filename") or filename_from_url(item["url"])
        return item, name

    explicit_norm = [norm(i) for i in (explicit or [])]
    claimed = {name for _, name in explicit_norm}

    merged = [item for item, _ in explicit_norm]
    for item, name in (norm(i) for i in discovered):
        if name in claimed:
            log(f"workflow '{name}' overridden by models.yaml entry", "=")
            continue
        merged.append(item)
        claimed.add(name)
    return merged


# ===========================================================================
#  Custom nodes
# ===========================================================================

def normalize_node(item):
    """
    Accept a node spec in any of these shapes and return a normalized dict:
      "comfyui-kjnodes"                 -> registry id
      "https://github.com/u/Repo"       -> git url
      {url: <git>, pip: <bool>}         -> git url
      {id: <reg-id>, version: <v>, pip} -> registry id (optional pin)
    Returned: {"kind": "git"|"registry", "ref": str, "pip": bool}
    """
    if isinstance(item, str):
        if item.startswith(("http://", "https://", "git@")):
            item = {"url": item}
        else:
            item = {"id": item}

    if item.get("url"):
        return {"kind": "git", "ref": item["url"],
                "pip": item.get("pip", True)}

    ref = str(item["id"])
    if item.get("version"):
        ref = f'{ref}=={item["version"]}'
    return {"kind": "registry", "ref": ref, "pip": item.get("pip", True)}


def node_env(cfg):
    """
    Custom-node pip requirements MUST land in the same Python that ComfyUI
    runs under, otherwise the nodes won't import. If comfyui_venv is set we
    point the installer at it via VIRTUAL_ENV / PATH.
    """
    env = os.environ.copy()
    venv = cfg.get("comfyui_venv")
    if venv:
        venv = str(Path(venv).expanduser())
        env["VIRTUAL_ENV"] = venv
        env["PATH"] = f"{venv}/bin:" + env.get("PATH", "")
        log(f"node deps -> venv: {venv}", "*")
    return env


def ensure_manager(comfyui: Path, cfg, dry_run):
    """
    comfy-cli delegates to ComfyUI-Manager's cm-cli.py and requires it to be
    present. On a slim pod it may be missing -> clone it. Non-fatal.
    """
    mgr = comfyui / "custom_nodes" / "ComfyUI-Manager"
    if mgr.exists():
        return True
    repo = cfg.get("comfyui_manager_repo",
                    "https://github.com/ltdrdata/ComfyUI-Manager.git")
    if dry_run:
        log(f"DRY-RUN would clone ComfyUI-Manager from {repo}", ">")
        return True
    log(f"ComfyUI-Manager not found, cloning: {repo}", ">")
    rc = subprocess.run(
        ["git", "clone", "--depth", "1", repo, str(mgr)]
    ).returncode
    if rc != 0:
        log(f"FAILED to clone ComfyUI-Manager (rc={rc})", "!")
        return False
    return True


def install_custom_nodes(nodes, comfyui: Path, cfg, dry_run, force):
    """
    Install custom nodes. Returns (ok, fail, changed) where `changed` is the
    number of nodes for which an install command actually ran (used to decide
    whether a ComfyUI restart is warranted).
    """
    ok = fail = changed = 0
    installer = cfg.get("custom_nodes_installer", "comfy-cli")
    env = node_env(cfg)

    if installer == "comfy-cli":
        if not shutil.which("comfy"):
            log("comfy-cli ('comfy') not on PATH -> falling back to cm-cli", "!")
            installer = "cm-cli"
        else:
            ensure_manager(comfyui, cfg, dry_run)

    cm_cli = comfyui / "custom_nodes" / "ComfyUI-Manager" / "cm-cli.py"
    if installer == "cm-cli" and not dry_run and not cm_cli.exists():
        # cm-cli fallback still needs ComfyUI-Manager present
        if not ensure_manager(comfyui, cfg, dry_run) or not cm_cli.exists():
            log("cm-cli.py unavailable - cannot install custom nodes", "!")
            return ok, len(nodes or []), 0

    for spec in (normalize_node(x) for x in nodes or []):
        ref, kind = spec["ref"], spec["kind"]

        if dry_run:
            log(f"DRY-RUN would install [{installer}/{kind}] {ref}", ">")
            ok += 1
            continue

        if installer == "comfy-cli":
            cmd = ["comfy", "--skip-prompt", "--workspace", str(comfyui),
                   "node"]
            cmd += (["registry-install", ref] if kind == "registry"
                    else ["install", ref])
        else:  # cm-cli
            env["COMFYUI_PATH"] = str(comfyui)
            cmd = [sys.executable, str(cm_cli), "install", ref]

        log(f"installing custom node [{kind}]: {ref}", ">")
        rc = subprocess.run(cmd, env=env).returncode
        if rc == 0:
            log(f"DONE node: {ref}", "+")
            ok += 1
            changed += 1
        else:
            log(f"FAILED ({rc}) node: {ref}", "!")
            fail += 1

    return ok, fail, changed


def restart_comfyui(cfg, dry_run, changed, no_restart):
    """
    Restart strategy (config key `restart`):
      none / ""          -> never
      auto (default)     -> ComfyUI-Manager reboot endpoint, then fall back
                            to killing main.py (pod supervisor relaunches)
      "<command>"        -> run the given shell command
    Only fires if at least one node actually installed and not dry-run.
    """
    strat = cfg.get("restart", "auto")

    if no_restart:
        log("restart: disabled via --no-restart", "=")
        return
    if strat in (None, "", "none"):
        log("restart: disabled (restart=none)", "=")
        return
    if changed == 0:
        log("restart: skipped (no custom nodes changed)", "=")
        return
    if dry_run:
        log("DRY-RUN would restart ComfyUI", ">")
        return

    if strat == "auto":
        port = cfg.get("comfyui_port", 8188)
        for path in ("/api/manager/reboot", "/manager/reboot"):
            for method in ("POST", "GET"):
                try:
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{port}{path}", method=method)
                    urllib.request.urlopen(req, timeout=10)
                    log(f"restart: ComfyUI-Manager reboot triggered "
                        f"({method} {path})", "+")
                    return
                except Exception:
                    continue
        # Fallback: kill the server; RunPod templates typically relaunch it.
        rc = subprocess.run(["pkill", "-f", "ComfyUI/main.py"]).returncode
        if rc == 0:
            log("restart: killed main.py (pod supervisor should relaunch)",
                "+")
        else:
            log("restart: could not reach Manager API and no main.py "
                "process matched - restart ComfyUI manually", "!")
    else:
        log(f"restart: running custom command: {strat}", ">")
        subprocess.run(strat, shell=True)


def main():
    ap = argparse.ArgumentParser(description="ComfyUI universal model downloader")
    ap.add_argument("-c", "--config", required=True, help="YAML config path")
    ap.add_argument("--comfyui", help="Override comfyui_path from config")
    ap.add_argument("--force", action="store_true", help="Re-download even if present")
    ap.add_argument("--dry-run", action="store_true", help="Show actions, download nothing")
    ap.add_argument("--workflows-listing-url",
                    help="GitHub Contents API URL of the repo's workflows/ dir "
                         "(auto-supplied by bootstrap.sh)")
    ap.add_argument("--github-token",
                    help="GitHub token for the Contents API (private repos / "
                         "higher rate limit)")
    ap.add_argument("--skip-nodes", action="store_true",
                    help="Do not install custom nodes")
    ap.add_argument("--no-restart", action="store_true",
                    help="Do not restart ComfyUI after installing nodes")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())

    comfyui = Path(args.comfyui or cfg.get("comfyui_path") or "").expanduser()
    if not comfyui:
        sys.exit("comfyui_path is not set (config or --comfyui).")
    models_root = comfyui / "models"

    token = cfg.get("hf_token") or os.environ.get("HF_TOKEN") or ""
    github_token = args.github_token or os.environ.get("GITHUB_TOKEN") or ""
    force = args.force or bool(cfg.get("overwrite"))
    headers = build_headers(token)

    log(f"ComfyUI:      {comfyui}")
    wf_dir = Path(
        cfg.get("workflows_path") or (comfyui / "user" / "default" / "workflows")
    ).expanduser()

    log(f"models root:  {models_root}")
    log(f"workflows:    {wf_dir}")
    log(f"HF token:     {'yes' if token else 'no'}")
    log(f"GitHub token: {'yes' if github_token else 'no'}")
    log(f"force:        {force} | dry-run: {args.dry_run}")
    print("-" * 60)

    models = cfg.get("models") or {}
    explicit_workflows = cfg.get("workflows") or []
    custom_nodes = [] if args.skip_nodes else (cfg.get("custom_nodes") or [])

    discovered = discover_workflows(args.workflows_listing_url, github_token)
    workflows = merge_workflows(discovered, explicit_workflows)

    if not models and not workflows and not custom_nodes:
        sys.exit("Nothing to do: config has neither 'models', 'workflows' nor "
                 "'custom_nodes', and no workflows were auto-discovered.")

    ok = fail = 0
    nodes_changed = 0

    # --- workflows FIRST ---------------------------------------------------
    if workflows:
        log(f"=== workflows ({len(workflows)})  ->  {wf_dir}", "#")
        o, f = fetch_list(workflows, wf_dir, headers, force, args.dry_run)
        ok += o
        fail += f
    else:
        log("no workflows to download", "=")

    # --- custom nodes (after workflows, before models) ---------------------
    if custom_nodes:
        log(f"=== custom nodes ({len(custom_nodes)})", "#")
        o, f, ch = install_custom_nodes(
            custom_nodes, comfyui, cfg, args.dry_run, force)
        ok += o
        fail += f
        nodes_changed = ch
    else:
        log("no custom nodes to install", "=")

    # --- models ------------------------------------------------------------
    for mtype, items in models.items():
        type_dir = models_root / mtype
        log(f"=== model type: {mtype}  ->  {type_dir}", "#")
        o, f = fetch_list(items, type_dir, headers, force, args.dry_run)
        ok += o
        fail += f

    # --- single restart at the very end ------------------------------------
    restart_comfyui(cfg, args.dry_run, nodes_changed, args.no_restart)

    print("-" * 60)
    log(f"Finished. ok={ok} fail={fail}", "+" if fail == 0 else "!")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
