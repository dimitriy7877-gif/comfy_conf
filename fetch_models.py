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

Usage:
  python3 fetch_models.py -c models.yaml
  python3 fetch_models.py -c models.yaml --dry-run
  python3 fetch_models.py -c models.yaml --force
  python3 fetch_models.py -c models.yaml --comfyui /path/to/ComfyUI
"""

import argparse
import os
import shutil
import subprocess
import sys
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


def main():
    ap = argparse.ArgumentParser(description="ComfyUI universal model downloader")
    ap.add_argument("-c", "--config", required=True, help="YAML config path")
    ap.add_argument("--comfyui", help="Override comfyui_path from config")
    ap.add_argument("--force", action="store_true", help="Re-download even if present")
    ap.add_argument("--dry-run", action="store_true", help="Show actions, download nothing")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())

    comfyui = Path(args.comfyui or cfg.get("comfyui_path") or "").expanduser()
    if not comfyui:
        sys.exit("comfyui_path is not set (config or --comfyui).")
    models_root = comfyui / "models"

    token = cfg.get("hf_token") or os.environ.get("HF_TOKEN") or ""
    force = args.force or bool(cfg.get("overwrite"))
    headers = build_headers(token)

    log(f"ComfyUI:      {comfyui}")
    wf_dir = Path(
        cfg.get("workflows_path") or (comfyui / "user" / "default" / "workflows")
    ).expanduser()

    log(f"models root:  {models_root}")
    log(f"workflows:    {wf_dir}")
    log(f"HF token:     {'yes' if token else 'no'}")
    log(f"force:        {force} | dry-run: {args.dry_run}")
    print("-" * 60)

    models = cfg.get("models") or {}
    workflows = cfg.get("workflows") or []
    if not models and not workflows:
        sys.exit("Nothing to do: config has neither 'models' nor 'workflows'.")

    ok = fail = 0
    for mtype, items in models.items():
        type_dir = models_root / mtype
        log(f"=== model type: {mtype}  ->  {type_dir}", "#")
        o, f = fetch_list(items, type_dir, headers, force, args.dry_run)
        ok += o
        fail += f

    if workflows:
        log(f"=== workflows  ->  {wf_dir}", "#")
        o, f = fetch_list(workflows, wf_dir, headers, force, args.dry_run)
        ok += o
        fail += f

    print("-" * 60)
    log(f"Finished. ok={ok} fail={fail}", "+" if fail == 0 else "!")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
