# comfy_conf

Один command внутри RunPod-пода: ставит зависимости, тянет
`fetch_models.py` + `models.yaml` рядом с `bootstrap.sh`, скачивает workflows
и модели, ставит кастомные ноды и раскладывает всё по папкам ComfyUI.

`BASE_URL` определяется автоматически (приоритет):
1. явный `BASE_URL=...` в окружении;
2. производный из `BOOTSTRAP_URL` — это каталог, где лежит `bootstrap.sh`;
3. захардкоженный дефолт в `bootstrap.sh` (обычный `curl | bash`).

Рекомендуется задавать `BOOTSTRAP_URL`: привязка идёт к **каталогу**
`bootstrap.sh`, а не к корню репозитория, и каталог `workflows/` рядом с ним
скачивается автоматически (только верхний уровень). URL пишется один раз
через переменную — это по-прежнему одна команда.

```bash
U="https://raw.githubusercontent.com/dimitriy7877-gif/comfy_conf/main/bootstrap.sh"
```

**Стандартный запуск**
```bash
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash
```

**Проверка без скачивания (dry-run)** — также показывает, какие ноды
поставятся и будет ли рестарт, но ничего не делает
```bash
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash -s -- --dry-run
```

**Перебить путь к ComfyUI / перекачать всё заново**
```bash
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash -s -- --comfyui /workspace/runpod-slim/ComfyUI --force
```

**Не ставить кастомные ноды / не перезапускать ComfyUI**
```bash
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash -s -- --skip-nodes
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash -s -- --no-restart
```

**Приватный HF-репозиторий**
```bash
curl -fsSL "$U" | BOOTSTRAP_URL="$U" HF_TOKEN=hf_xxx bash
```

**Приватный GitHub-репозиторий / выше лимит GitHub API для авто-поиска workflows**
```bash
curl -fsSL "$U" | BOOTSTRAP_URL="$U" GITHUB_TOKEN=ghp_xxx bash
```

**Конфиг/скрипты в подкаталоге репозитория**
```bash
U="https://raw.githubusercontent.com/dimitriy7877-gif/comfy_conf/main/configs/wan/bootstrap.sh"
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash
# BASE_URL = .../main/configs/wan ; авто-поиск workflows в .../configs/wan/workflows/
```

**Взять скрипты с другого источника, не меняя файл** (авто-поиск workflows
для не-GitHub источника отключается, явный список в `models.yaml` работает)
```bash
curl -fsSL "$U" | BASE_URL=https://my.server/comfy bash -s -- --dry-run
```

**Простой режим без BOOTSTRAP_URL** (берётся `DEFAULT_BASE_URL` из файла)
```bash
curl -fsSL https://raw.githubusercontent.com/dimitriy7877-gif/comfy_conf/main/bootstrap.sh | bash
```

---

### Workflows

- Скачиваются **раньше моделей** (и раньше установки нод).
- Авто-поиск: для GitHub-источника берутся все `*.json` из каталога
  `workflows/`, лежащего рядом с `bootstrap.sh` (только верхний уровень, без
  рекурсии).
- Явные записи `workflows:` в `models.yaml` имеют приоритет при совпадении
  имени файла; авто-найденные добавляются, если имя не занято.
- Нет каталога `workflows/` (404) или иная ошибка API — не фатально:
  предупреждение и пропуск, явный список продолжает обрабатываться.

### Кастомные ноды

- Список — секция `custom_nodes:` в `models.yaml`. Элемент:
  registry-id строкой (`comfyui-kjnodes`), git-URL строкой, либо
  `{id: <reg>, version: <опц.>}` / `{url: <git>, pip: <bool>}`.
- Установщик — `comfy-cli` (по умолчанию; ставится в `bootstrap.sh`). Это
  обёртка над `cm-cli.py` из ComfyUI-Manager. Если `comfy` недоступен —
  автоматический фоллбэк на прямой вызов `cm-cli.py`. ComfyUI-Manager
  авто-клонируется, если его нет.
- Порядок: **workflows → ноды → модели → один рестарт ComfyUI в конце**.
  Рестарт срабатывает только если хотя бы одна нода реально установилась
  и это не `--dry-run`.
- `restart` в конфиге: `auto` (reboot-эндпоинт Manager → `pkill main.py`,
  супервизор пода поднимет заново), `none`, либо своя команда-строка
  (напр. `supervisorctl restart comfyui`).
- **Важно:** зависимости нод должны ставиться в то же Python-окружение, где
  работает ComfyUI. Если у ComfyUI свой venv — укажи его в `comfyui_venv`,
  иначе ноды не импортируются.

Полностью автоматически определить собственный URL при `curl | bash`
невозможно (у потока в bash нет своего пути) — приём с переменной выше это
минимальная форма: одна строка, URL указывается единожды.
