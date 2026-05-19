"# comfy_conf" 

curl -fsSL https://raw.githubusercontent.com/USER/REPO/main/bootstrap.sh | bash

# проверка без скачивания
curl -fsSL https://raw.githubusercontent.com/USER/REPO/main/bootstrap.sh | bash -s -- --dry-run

# перебить путь к ComfyUI / перекачать всё заново
curl -fsSL .../bootstrap.sh | bash -s -- --comfyui /workspace/runpod-slim/ComfyUI --force

# взять скрипты с другого источника, не меняя файл
curl -fsSL .../bootstrap.sh | BASE_URL=https://my.server/comfy bash -s -- --dry-run

# приватный HF-репозиторий
curl -fsSL .../bootstrap.sh | HF_TOKEN=hf_xxx bash