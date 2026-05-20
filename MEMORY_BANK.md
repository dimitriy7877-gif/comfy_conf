# MEMORY BANK — ComfyUI Model/Workflow Downloader

> Snapshot of project state, decisions, and how to run things.
> Last updated: 2026-05-20 (rev4: pip-installed ComfyUI-Manager, unified
> `comfy node install` for both git URLs and Registry IDs)

---

## 1. Goal

One command, run inside a RunPod pod, that:
1. Installs dependencies.
2. Downloads helper scripts + config from a server / GitHub repo.
3. Downloads workflows.
4. Installs custom nodes (declared in YAML) and restarts ComfyUI.
5. Downloads models and lays them into ComfyUI folders.

ComfyUI location on the pod: `/workspace/runpod-slim/ComfyUI`
(overridable — never hardcode it in logic).

---

## 2. Files (deliverables)

| File              | Role                                                                |
|-------------------|---------------------------------------------------------------------|
| `bootstrap.sh`    | One-liner wrapper: installs deps + comfy-cli, fetches script+config, runs it. |
| `fetch_models.py` | Core logic. Reads YAML, downloads files, installs nodes via comfy-cli, restarts. |
| `models.yaml`     | Config: paths, tokens, custom_nodes, workflows, models.             |

All three must sit at the same `BASE_URL`.

---

## 3. How to run

`BASE_URL` is resolved automatically in this priority:
1. explicit `BASE_URL=...` env (highest);
2. derived from `BOOTSTRAP_URL` = dirname of the bootstrap.sh URL;
3. hardcoded `DEFAULT_BASE_URL` in `bootstrap.sh`.

**Recommended one-liner** — URL typed once, reused for derivation:

```bash
U="https://raw.githubusercontent.com/dimitriy7877-gif/comfy_conf/main/bootstrap.sh"
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash

# dry-run (also previews node installs + restart, installs nothing)
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash -s -- --dry-run

# force re-download of files
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash -s -- --force

# skip nodes / skip restart
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash -s -- --skip-nodes
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash -s -- --no-restart

# private/gated HF repo
curl -fsSL "$U" | BOOTSTRAP_URL="$U" HF_TOKEN=hf_xxx bash

# private GitHub repo / higher API rate limit for workflow discovery
curl -fsSL "$U" | BOOTSTRAP_URL="$U" GITHUB_TOKEN=ghp_xxx bash
```

Wrapper working dir on the pod: `/workspace/.comfy-fetch` (configurable via `WORKDIR`).

---

## 4. Config format (models.yaml)

Sections in order of execution:

```yaml
# 1. global paths & flags
comfyui_path: /workspace/runpod-slim/ComfyUI
hf_token: ""              # or env HF_TOKEN (env wins if config empty)
overwrite: false          # same as CLI --force
# workflows_path: <comfyui_path>/user/default/workflows  (default if omitted)

# 2. workflows (same item syntax as models)
# workflows:
#   - https://.../wf.json
#   - url: https://.../wf.json
#     filename: my_wf.json
#     subdir: wan

# 3. custom nodes — settings + list in one section
restart: auto                       # auto | none | "<shell command>"
comfyui_port: 8188                  # used by the auto-restart reboot endpoint
comfyui_venv: ""                    # env ComfyUI runs under (deps target!)
custom_nodes:
  - comfyui-gguf                                   # Registry ID (shorthand)
  - https://github.com/user/Repo                   # git URL (shorthand)
  - id: comfyui-impact-pack
    version: 8.15.3                                # best-effort pin
  - url: https://github.com/user/Repo
    pip: false                                     # skip requirements.txt

# 4. models
models:
  <type>:                 # any name == folder under <comfyui>/models/
    - <url>                             # shorthand
    - url: <url>                        # full form
      filename: rename.safetensors      # optional rename
      subdir: SomeFolder                # optional nested subfolder
```

**Workflow auto-discovery** (unchanged from rev2): for github raw BASE_URL,
every top-level `*.json` from `workflows/` next to bootstrap.sh is pulled
automatically. Explicit entries win on filename collision.

---

## 5. Current test payload

- `custom_nodes/` — ComfyUI-GGUF (required for the GGUF diffusion models),
  ComfyUI-VideoHelperSuite, ComfyUI-KJNodes
- `diffusion_models/` — Wan2.2 T2V A14B High/Low noise Q8_0 GGUF
- `vae/` — Wan2.1_VAE.safetensors
- `text_encoders/` — umt5_xxl_fp8_e4m3fn_scaled.safetensors
- `loras/` — lightx2v 4-step distill (high+low), Instara realism (high+low)
- `workflows/` — wan22.json

Production-tested on a runpod-slim pod 2026-05-20: ok=12 fail=0.

---

## 6. Design decisions / behavior

### Downloads
- `aria2c` (16 connections, resumable) if present, else `curl -C -`.
- HEAD content-length size check; `--force` overrides.
- HF auth header sent to all hosts currently (known issue, scope to HF only TODO).
- Type folder = `models/<type>`; workflows default to `<comfyui_path>/user/default/workflows`.

### Custom nodes
- One installer, one command: `comfy --skip-prompt --workspace <path> node install <ref>`.
- comfy-cli accepts **both** git URLs and ComfyUI Registry IDs in this argument — no need to distinguish them on our side.
- `pip: false` in YAML → `--no-deps`.
- **ComfyUI-Manager must be installed as a pip package** (`comfyui-manager`), not as a git checkout. Modern comfy-cli (>=1.5) finds Manager via `import comfyui_manager`; the historical `custom_nodes/ComfyUI-Manager/` directory is ignored for `comfy-cli` purposes (though it still works for the in-browser Manager UI).
- `ensure_manager()` does `<python> -m pip install comfyui-manager` into `comfyui_venv/bin/python` (or `sys.executable` if no venv).
- Idempotency is delegated to comfy-cli/cm-cli: re-runs print `Already exists` and a misleading `ERROR`, but exit 0, and our log shows `[+] DONE` — confusing but correct (see known issues).

### Order & restart
- workflows → custom nodes → models → **single restart at the very end**.
- `restart: auto` tries `/api/manager/reboot` then `/manager/reboot` (POST then GET), falls back to `pkill -f ComfyUI/main.py` (RunPod supervisor relaunches).
- Fires only when at least one node install succeeded and not `--dry-run`.

### BASE_URL & workflow auto-discovery
- Unchanged from rev2/rev3. `BASE_URL = dirname(BOOTSTRAP_URL)`. GitHub
  Contents API used to enumerate `workflows/` (top level).

---

## 7. Known issues / open items

### Custom nodes
- **`Already exists` reported as `ERROR` by cm-cli but rc=0.** When a node
  is already installed, cm-cli prints
  `Already exists: '...'` + `ERROR: An error occurred while installing '...'`
  yet returns exit code 0 — and our code logs `[+] DONE` on top.
  Functionally correct (re-run is a no-op), visually noisy. Fix:
  capture stdout, detect this pattern, log as `[=] SKIP (already installed)`.
- **Restart `[!]` on a stopped ComfyUI.** If ComfyUI isn't running yet when
  the script finishes (typical first-time pod setup), Manager API on 8188
  doesn't answer and `pkill main.py` finds nothing → logged as `[!]`. It's
  actually fine (the next manual `python main.py` will pick up the new
  nodes), but the warning is misleading. Fix: probe `127.0.0.1:port/` first;
  if unreachable, log `[=] restart: ComfyUI not running, skipping`.
- **Node version pinning** (`id: x, version: y` → `<id>@<version>`) is
  best-effort; depends on Registry having that version.
- **comfy-cli picks `python3` magically.** It currently invokes
  `/usr/bin/python3.12 -m cm_cli`. If ComfyUI lives in a venv but
  `comfy-cli` runs from system Python, those pythons may disagree.
  Setting `comfyui_venv` in YAML solves it for our pip-installs, but
  `comfy node install`'s own pythonchoice is internal to comfy-cli.

### HuggingFace
- **Gated HF repos** (e.g. `Instara/instareal-wan-2.2`): `aria2c errorCode=24`
  → token missing / license not accepted / token scope. Check:
  ```bash
  curl -sI -H "Authorization: Bearer $HF_TOKEN" <file_url> | head -n1
  ```
  200/302 = ok, 401 = bad token, 403 = license not accepted.
- **Auth header sent to all domains.** Fine for HF only. TODO: scope to
  `huggingface.co`.

### GitHub
- **Private GitHub raw URLs** need a token; raw file fetch of private repos
  still TODO (listing API already supports `GITHUB_TOKEN`).

---

## 8. Next steps (proposed)

- [ ] Scope HF auth header to huggingface.co only.
- [x] ~~Dynamic BASE_URL in bootstrap.sh~~ (rev2)
- [x] ~~Auto-discover workflows from repo `workflows/`~~ (rev2)
- [x] ~~workflows-first order~~ (rev2)
- [x] ~~Optional GitHub token support~~ (rev2; listing API only)
- [x] ~~Custom node install + restart~~ (rev3 partial, **rev4 fully working**)
- [ ] Capture cm-cli output: log `Already exists` as `[=] SKIP`, not `[+] DONE`.
- [ ] Probe ComfyUI port before restart; skip cleanly when not running.
- [ ] Send GitHub token to raw.githubusercontent.com fetches (private repos).
- [ ] Optional restart-then-wait health check (poll port until ComfyUI is back).
- [ ] Optional `comfy node reinstall` path when `--force` is set.
