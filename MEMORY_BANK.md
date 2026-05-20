# MEMORY BANK — ComfyUI Model/Workflow Downloader

> Snapshot of project state, decisions, and how to run things.
> Last updated: 2026-05-19 (rev3: custom-node install via comfy-cli/cm-cli,
> ComfyUI restart after install)

---

## 1. Goal

One command, run inside a RunPod pod, that:
1. Installs dependencies.
2. Downloads helper scripts + config from a server / GitHub repo.
3. Downloads workflows + models and lays them into ComfyUI folders.
4. Installs custom nodes listed in the config and restarts ComfyUI.

ComfyUI location on the pod: `/workspace/runpod-slim/ComfyUI`
(overridable — never hardcode it in logic).

---

## 2. Files (deliverables)

| File              | Role                                                                 |
|-------------------|----------------------------------------------------------------------|
| `bootstrap.sh`    | One-liner wrapper: installs deps, fetches script+config, runs it.     |
| `fetch_models.py` | Core downloader. Reads YAML, lays files into ComfyUI dirs, installs nodes. |
| `models.yaml`     | Config: ComfyUI path, HF token, models, workflows, custom nodes.     |

All three must sit at the same `BASE_URL`.

---

## 3. How to run

`BASE_URL` is resolved automatically in this priority:
1. explicit `BASE_URL=...` env (highest);
2. derived from `BOOTSTRAP_URL` = dirname of the bootstrap.sh URL;
3. hardcoded `DEFAULT_BASE_URL` in `bootstrap.sh` (plain `curl | bash`).

**Recommended one-liner** — URL typed once, reused for derivation. Binds to
the *directory* bootstrap.sh sits in (so a `workflows/` folder next to it is
auto-discovered), not the repo root:

```bash
# normal run
U="https://raw.githubusercontent.com/USER/REPO/main/SUBDIR/bootstrap.sh"
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash

# dry-run (also previews node installs + restart, installs nothing)
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash -s -- --dry-run

# force re-download
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash -s -- --force

# skip custom-node install / don't restart ComfyUI
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash -s -- --skip-nodes
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash -s -- --no-restart

# override ComfyUI path
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash -s -- --comfyui /workspace/runpod-slim/ComfyUI

# private/gated HF repo
curl -fsSL "$U" | BOOTSTRAP_URL="$U" HF_TOKEN=hf_xxx bash

# private GitHub repo / higher API rate limit for workflow discovery
curl -fsSL "$U" | BOOTSTRAP_URL="$U" GITHUB_TOKEN=ghp_xxx bash

# point at a different source (disables github workflow auto-discovery)
curl -fsSL "$U" | BASE_URL=https://my.server/comfy bash -s -- --dry-run

# plain mode: no BOOTSTRAP_URL -> uses DEFAULT_BASE_URL baked in the file
curl -fsSL https://raw.githubusercontent.com/USER/REPO/main/bootstrap.sh | bash
```

Note: full automatic self-URL detection is impossible with `curl | bash`
(the piped stream has no path of its own). The variable trick above is the
minimal form — one line, URL written once.

Wrapper working dir on pod: `/workspace/.comfy-fetch` (configurable via `WORKDIR`).

---

## 4. Config format (models.yaml)

Key idea: **type name == folder name under `<comfyui_path>/models/`**.
New model types need no code changes — just a new YAML section.

```yaml
comfyui_path: /workspace/runpod-slim/ComfyUI
hf_token: ""              # or env HF_TOKEN (env wins if config empty)
overwrite: false          # same as CLI --force
# workflows_path: <comfyui_path>/user/default/workflows  (default if omitted)

# custom node settings
custom_nodes_installer: comfy-cli   # comfy-cli (default) | cm-cli
restart: auto                       # auto | none | "<shell command>"
comfyui_port: 8188                  # for the auto-restart reboot endpoint
comfyui_venv: ""                    # env ComfyUI runs under (deps target!)
# comfyui_manager_repo: https://github.com/ltdrdata/ComfyUI-Manager.git

custom_nodes:                       # flat list
  - comfyui-kjnodes                              # registry id (shorthand)
  - https://github.com/user/Repo                 # git url    (shorthand)
  - id: comfyui-impact-pack
    version: 8.15.3                               # best-effort pin
  - url: https://github.com/user/Repo
    pip: false                                    # skip requirements

models:
  <type>:                 # e.g. diffusion_models / vae / text_encoders / loras
    - <url>                            # shorthand
    - url: <url>                       # full form
      filename: rename.safetensors     # optional rename
      subdir: SomeFolder               # optional nested subfolder

workflows:                # flat list, same item syntax as models
  - url: https://.../workflow.json
    filename: my_wf.json
    subdir: wan           # optional, under workflows_path
```

**Workflow auto-discovery (GitHub only):** unchanged — when `BASE_URL` is a
`raw.githubusercontent.com` URL, bootstrap.sh derives the GitHub Contents API
URL for the `workflows/` folder *next to bootstrap.sh* and passes it via
`--workflows-listing-url`. Top level only, explicit entries win on collision.

---

## 5. Current test payload

- `custom_nodes/` — ComfyUI-GGUF (required for the GGUF models),
  ComfyUI-VideoHelperSuite
- `diffusion_models/Wan2.2-T2V-A14B/` — Wan2.2 T2V A14B HighNoise + LowNoise Q8_0 GGUF
- `vae/` — Wan2.1_VAE.safetensors
- `text_encoders/` — umt5_xxl_fp8_e4m3fn_scaled.safetensors
- `loras/` — lightx2v 4-step distill + Instara high/low
- `workflows/` — wan2.2_t2v_A14B.json

---

## 6. Design decisions / behavior

- Downloader: `aria2c` (16 connections, resumable) if present, else `curl -C -`.
- Skips files already complete (HEAD content-length size check); `--force` overrides.
- `bootstrap.sh` uses `set -euo pipefail`; installs `git` + `comfy-cli` too.
- HF token applied to all hosts currently (safe for HF; see Known Issues).
- Type folder = `models/<type>`; workflows default to
  `<comfyui_path>/user/default/workflows`.
- **Custom nodes:** `comfy-cli` is primary (pip-installed; it wraps
  ComfyUI-Manager's `cm-cli.py`). Auto-fallback to calling `cm-cli.py`
  directly if `comfy` is not on PATH. ComfyUI-Manager is auto-cloned if
  missing (comfy-cli depends on it). registry id ->
  `comfy node registry-install`; git url -> `comfy node install`.
  `--skip-prompt` avoids the interactive telemetry consent that would hang
  a `curl | bash` run.
- **Order:** workflows → custom nodes → models → **single restart at the
  very end**. One restart only, and only if ≥1 node actually installed and
  not `--dry-run` — model downloads (which can be long) finish before the
  reboot so ComfyUI comes back up complete.
- **Restart `auto`:** ComfyUI-Manager reboot endpoint
  (`/api/manager/reboot`, then `/manager/reboot`, POST then GET) →
  fallback `pkill -f ComfyUI/main.py` (RunPod supervisor relaunches it).
  `restart: none` disables; `restart: "<cmd>"` runs a custom command.
- BASE_URL / workflow auto-discovery behavior unchanged from rev2.

---

## 7. Known issues / open items

- **Custom-node deps env.** Node `requirements.txt` must install into the
  *same* Python ComfyUI runs under or the nodes won't import. Set
  `comfyui_venv` to ComfyUI's venv; `fetch_models.py` exports
  `VIRTUAL_ENV`/`PATH` for the installer. Without a venv it falls to the
  active Python — verify on the pod.
- **comfy-cli telemetry prompt.** First run is interactive and would hang
  under `curl | bash`; mitigated with the global `--skip-prompt` flag.
- **comfy-cli ↔ ComfyUI-Manager.** comfy-cli delegates to `cm-cli.py` and
  requires the Manager present. Auto-clone covers a slim pod; repo/branch
  overridable via `comfyui_manager_repo`.
- **Gated HF repos** (e.g. `Instara/instareal-wan-2.2`): `aria2c errorCode=24
  Authorization failed`. Causes: token not passed / license not accepted /
  token scope. Quick check on pod:
  `curl -sI -H "Authorization: Bearer $HF_TOKEN" <file_url> | head -n1`
  (200/302 ok, 401 token bad, 403 license not accepted).
- **Auth header sent to all domains.** Fine for HF only. TODO: scope
  `Authorization` to `huggingface.co`.
- **Private GitHub** raw URLs need a token; raw file fetch of private repos
  still TODO (listing API already supports `GITHUB_TOKEN`).
- **Node version pinning** (`id: x, version: y`) is best-effort and depends
  on comfy-cli `registry-install` supporting `name==ver`.

---

## 8. Next steps (proposed, not yet done)

- [ ] Scope HF auth header to huggingface.co only.
- [x] ~~Динамическое формирование BASE_URL в bootstrap.sh~~ → done via
  `BOOTSTRAP_URL` (dirname).
- [x] ~~Загружать все workflows из каталога "workflows" в репе~~ → done via
  GitHub Contents API auto-discovery (top level only).
- [x] ~~workflows должны выгружаться перед моделями~~ → done.
- [x] ~~Optional GitHub token support in bootstrap.sh~~ → done via
  `GITHUB_TOKEN` / `--github-token` (listing API; raw file fetch TODO).
- [ ] Send GitHub token to raw.githubusercontent.com fetches too (private
  repo file downloads, not just the listing API).
- [x] ~~Установка кастомных нод через comfy-cli (или cm-cli); перечень в
  models.yaml; перезагрузка comfyui после установки~~ → done. comfy-cli
  primary, cm-cli fallback, `custom_nodes:` list, single restart at end.
- [ ] Optional `comfy node reinstall` path when `--force` is set (currently
  idempotency is delegated to comfy-cli / cm-cli).
- [ ] Restart-then-wait health check (poll the port until ComfyUI is back).
