# MEMORY BANK — ComfyUI Model/Workflow Downloader

> Snapshot of project state, decisions, and how to run things.
> Last updated: 2026-05-19 (rev2: dynamic BASE_URL, workflow auto-discovery, workflows-first)

---

## 1. Goal

One command, run inside a RunPod pod, that:
1. Installs dependencies.
2. Downloads helper scripts + config from a server / GitHub repo.
3. Downloads models and workflows and lays them out into ComfyUI folders.

ComfyUI location on the pod: `/workspace/runpod-slim/ComfyUI`
(overridable — never hardcode it in logic).

---

## 2. Files (deliverables)

| File              | Role                                                                 |
|-------------------|----------------------------------------------------------------------|
| `bootstrap.sh`    | One-liner wrapper: installs deps, fetches script+config, runs it.     |
| `fetch_models.py` | Core downloader. Reads YAML, lays files into ComfyUI dirs.            |
| `models.yaml`     | Config: ComfyUI path, HF token, model list by type, workflow list.   |

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

# dry-run
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash -s -- --dry-run

# force re-download
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash -s -- --force

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

**Workflow auto-discovery (GitHub only):** when `BASE_URL` is a
`raw.githubusercontent.com` URL, bootstrap.sh derives the GitHub Contents API
URL for the `workflows/` folder *next to bootstrap.sh* (the BASE_URL
directory, not the repo root) and passes it to `fetch_models.py` via
`--workflows-listing-url`. Every top-level `*.json` there is downloaded
automatically. Scope is **top level only** (no recursion). Explicit
`workflows:` entries in `models.yaml` take priority on filename collision
(they may carry custom `filename`/`subdir`); auto-discovered files are
appended otherwise. Non-GitHub `BASE_URL` → discovery silently disabled, the
explicit list still works.

Workflow links must be **raw JSON**:
- GitHub: `raw.githubusercontent.com/<user>/<repo>/<branch>/<path>.json`
- HuggingFace: `<repo>/resolve/main/<path>.json`
- Gist: `gist.githubusercontent.com/<user>/<id>/raw/<file>.json`

---

## 5. Current test payload

- `diffusion_models/Wan2.2-T2V-A14B/` — Wan2.2 T2V A14B HighNoise + LowNoise Q8_0 GGUF
- `vae/` — Wan2.1_VAE.safetensors
- `text_encoders/` — umt5_xxl_fp8_e4m3fn_scaled.safetensors
- `workflows/` — wan2.2_t2v_A14B.json

---

## 6. Design decisions / behavior

- Downloader: `aria2c` (16 connections, resumable) if present, else `curl -C -`.
- Skips files already complete (HEAD content-length size check); `--force` overrides.
- Resumes partial downloads.
- `bootstrap.sh` uses `set -euo pipefail` — fails loudly on dep/download errors.
- HF token applied to all hosts currently (safe for HF; see Known Issues).
- Type folder = `models/<type>`; workflows default to
  `<comfyui_path>/user/default/workflows`.
- **Workflows are downloaded FIRST, before any models** (order in `main()`).
- BASE_URL derived from `BOOTSTRAP_URL` (dirname); GitHub workflow
  auto-discovery via Contents API, top level only, stdlib `urllib` (no jq).
- Auto-discovery is non-fatal: 404 (no `workflows/` dir) or any API error →
  warn + skip, explicit yaml list still processed.

---

## 7. Known issues / open items

- **Gated HF repos** (e.g. `Instara/instareal-wan-2.2`): `aria2c errorCode=24
  Authorization failed`. Causes, in order:
  1. Token not passed → check header line `[*] HF token: yes` in output.
  2. License not accepted for that account → open the repo page, accept terms.
  3. Token lacks Read scope / fine-grained repo access.
  - Quick check on pod:
    `curl -sI -H "Authorization: Bearer $HF_TOKEN" <file_url> | head -n1`
    (200/302 ok, 401 token bad, 403 license not accepted).
- **Auth header sent to all domains.** Fine for HF only. TODO: scope
  `Authorization` to `huggingface.co`; emit a clear "repo gated, accept
  license" message instead of raw aria2 errorCode=24.
- **Private GitHub** raw URLs need a token; wrapper currently doesn't send one.
  Workaround: public repo or self-host files. TODO: optional GitHub token.

---

## 8. Next steps (proposed, not yet done)

- [ ] Scope HF auth header to huggingface.co only.
- [x] ~~Динамическое формирование BASE_URL в bootstrap.sh~~ → done via
  `BOOTSTRAP_URL` (dirname), привязка к каталогу bootstrap.sh, не к корню репо.
- [x] ~~Загружать все workflows из каталога "workflows" в репе~~ → done via
  GitHub Contents API auto-discovery (top level only).
- [x] ~~workflows должны выгружаться перед моделями~~ → done (workflows-first
  order in `main()`).
- [x] ~~Optional GitHub token support in bootstrap.sh for private repos~~ →
  done via `GITHUB_TOKEN` env / `--github-token` (used for the workflows
  listing API; raw file fetch of private repos still TODO).
- [ ] Send GitHub token to raw.githubusercontent.com fetches too (private
  repo file downloads, not just the listing API).
