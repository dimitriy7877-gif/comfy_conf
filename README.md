# comfy_conf

**Стандартный запуск**
```bash
curl -fsSL [https://raw.githubusercontent.com/dimitriy7877-gif/comfy_conf/main/bootstrap.sh](https://raw.githubusercontent.com/dimitriy7877-gif/comfy_conf/main/bootstrap.sh) | bash
```

**Проверка без скачивания (dry-run)**
```bash
curl -fsSL [https://raw.githubusercontent.com/dimitriy7877-gif/comfy_conf/main/bootstrap.sh](https://raw.githubusercontent.com/dimitriy7877-gif/comfy_conf/main/bootstrap.sh) | bash -s -- --dry-run
```

**Перебить путь к ComfyUI / перекачать всё заново**
```bash
curl -fsSL [https://raw.githubusercontent.com/dimitriy7877-gif/comfy_conf/main/bootstrap.sh](https://raw.githubusercontent.com/dimitriy7877-gif/comfy_conf/main/bootstrap.sh) | bash -s -- --comfyui /workspace/runpod-slim/ComfyUI --force
```

**Взять скрипты с другого источника, не меняя файл**
```bash
curl -fsSL [https://raw.githubusercontent.com/dimitriy7877-gif/comfy_conf/main/bootstrap.sh](https://raw.githubusercontent.com/dimitriy7877-gif/comfy_conf/main/bootstrap.sh) | BASE_URL=[https://my.server/comfy](https://my.server/comfy) bash -s -- --dry-run
```

**Приватный HF-репозиторий**
```bash
curl -fsSL [https://raw.githubusercontent.com/dimitriy7877-gif/comfy_conf/main/bootstrap.sh](https://raw.githubusercontent.com/dimitriy7877-gif/comfy_conf/main/bootstrap.sh) | HF_TOKEN=hf_xxx bash
```