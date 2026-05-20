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
  - Custom node installation via comfy-cli. Accepts BOTH git URLs and
    ComfyUI Registry IDs in the same list. Lazily installs the
    `comfyui-manager` pip package (modern comfy-cli >=1.5 looks for it
    via Python import, not as a git checkout in custom_nodes/).
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
#
#  Modern comfy-cli (>=1.5) finds ComfyUI-Manager by importing the pip
#  package `comfyui_manager`, NOT by looking at the git checkout in
#  custom_nodes/. The historical "git clone Manager into custom_nodes" trick
#  is silently ignored - "ComfyUI-Manager not found. 'cm-cli' command is not
#  available." is exactly the symptom.
#
#  So we install the Manager as a pip package into the Python interpreter
#  that comfy-cli will end up invoking ('/usr/bin/python3.12 -m cm_cli ...'
#  in our case - that's the one that runs ComfyUI on the pod).
#
#  After that, `comfy node install <ref>` works for both git URLs and
#  Registry IDs in a single uniform call.
# ===========================================================================

def normalize_node_ref(item):
    """
    Turn any node spec into (ref_str, pip_deps_bool).
      "comfyui-gguf"                              -> ("comfyui-gguf", True)
      "https://github.com/u/Repo"                 -> ("https://...", True)
      {url: <git>, pip: false}                    -> ("<git>",       False)
      {id: comfyui-impact-pack, version: 8.15.3}  -> ("comfyui-impact-pack@8.15.3", True)

    comfy-cli accepts URLs and Registry IDs in the same `node install`
    argument list - no need to distinguish them on our side.
    """
    if isinstance(item, str):
        return item, True

    pip = item.get("pip", True)
    if item.get("url"):
        return item["url"], pip

    ref = str(item["id"])
    if item.get("version"):
        ref = f'{ref}@{item["version"]}'
    return ref, pip


def node_env(cfg):
    """
    Env for sub-tools. Prepend the venv's bin/ if comfyui_venv is set, so
    any sub-tool that lives there (e.g. uv) is found.
    """
    env = os.environ.copy()
    venv = cfg.get("comfyui_venv")
    if venv:
        venv = str(Path(venv).expanduser())
        env["VIRTUAL_ENV"] = venv
        env["PATH"] = f"{venv}/bin:" + env.get("PATH", "")
    return env


def node_python(cfg):
    """
    Pick the Python interpreter that ComfyUI runs under. The Manager pip
    package and every node's requirements.txt must land in this exact
    interpreter, or comfy-cli won't find Manager (and nodes won't import).

    Priority:
      1. comfyui_venv/bin/python (if the config sets it and it exists)
      2. sys.executable (the python running this script - same one
         bootstrap.sh used; on the runpod-slim pod that's /usr/bin/python3.12,
         which is also what comfy-cli ends up invoking).
    """
    venv = cfg.get("comfyui_venv")
    if venv:
        py = Path(venv).expanduser() / "bin" / "python"
        if py.exists():
            log(f"node python: {py} (from comfyui_venv)", "*")
            return str(py)
        log(f"WARNING: comfyui_venv={venv} but {py} not found; "
            f"falling back to {sys.executable}", "!")
    return sys.executable


def pip_install(py_exe, env, args, dry_run):
    """
    Run `<py> -m pip install <args>` with --break-system-packages for
    PEP 668 environments (Ubuntu 24+ / Debian 12+). Falls back to a plain
    install if --break-system-packages isn't supported by the pip version.
    """
    if dry_run:
        log(f"DRY-RUN would: {py_exe} -m pip install {' '.join(args)}", ">")
        return True

    base = [py_exe, "-m", "pip", "install"]
    rc = subprocess.run(base + ["--break-system-packages"] + args,
                        env=env).returncode
    if rc == 0:
        return True
    # Older pip versions don't know --break-system-packages.
    log("pip install --break-system-packages failed; retrying without", "!")
    rc = subprocess.run(base + args, env=env).returncode
    return rc == 0


def ensure_manager(cfg, dry_run):
    """
    Make sure `import comfyui_manager` works in the target Python. If not,
    `pip install comfyui-manager` into it. Returns True on success.
    """
    py = node_python(cfg)
    env = node_env(cfg)

    check = subprocess.run(
        [py, "-c", "import comfyui_manager"],
        env=env, capture_output=True
    )
    if check.returncode == 0:
        log("ComfyUI-Manager pip package: already installed", "=")
        return True

    log(f"ComfyUI-Manager pip package missing; installing into {py}", ">")
    if not pip_install(py, env, ["comfyui-manager"], dry_run):
        log("FAILED to install comfyui-manager", "!")
        return False
    log("ComfyUI-Manager installed", "+")
    return True


def install_custom_nodes(nodes, comfyui: Path, cfg, dry_run, force):
    """
    Install all custom nodes via `comfy node install`. Returns
    (ok, fail, changed). `changed` counts successful installs that should
    trigger a restart - currently every successful invocation counts, since
    comfy-cli doesn't expose an "already installed, no-op" signal in its
    exit code.
    """
    ok = fail = changed = 0
    if not nodes:
        return 0, 0, 0

    if not shutil.which("comfy"):
        log("comfy-cli ('comfy') not on PATH; cannot install custom nodes "
            "(install with: pip install comfy-cli)", "!")
        return 0, len(nodes), 0

    if not ensure_manager(cfg, dry_run):
        log("ComfyUI-Manager unavailable; skipping custom-node installation",
            "!")
        return 0, len(nodes), 0

    env = node_env(cfg)

    for item in nodes:
        ref, pip_deps = normalize_node_ref(item)

        if dry_run:
            log(f"DRY-RUN would install: {ref}"
                f"{' (no deps)' if not pip_deps else ''}", ">")
            ok += 1
            continue

        cmd = ["comfy", "--skip-prompt", "--workspace", str(comfyui),
               "node", "install"]
        if not pip_deps:
            cmd.append("--no-deps")
        cmd.append(ref)

        log(f"installing node: {ref}", ">")
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
    Only fires if at least one node was successfully installed and not in
    dry-run mode.
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
