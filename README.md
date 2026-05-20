# comfy_conf

Одна команда внутри RunPod-пода ставит зависимости, тянет `fetch_models.py` +
`models.yaml` рядом с `bootstrap.sh`, скачивает workflows, ставит кастомные
ноды, скачивает модели и перезапускает ComfyUI.

Порядок выполнения зафиксирован:

```
workflows  ->  custom nodes  ->  models  ->  один рестарт в конце
```

## TL;DR

```bash
U="https://raw.githubusercontent.com/dimitriy7877-gif/comfy_conf/main/bootstrap.sh"
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash
```

---

## Содержание

1. [Примеры запуска](#1-примеры-запуска)
2. [Переменные окружения](#2-переменные-окружения)
3. [CLI-флаги fetch_models.py](#3-cli-флаги-fetch_modelspy)
4. [models.yaml — полная справка](#4-modelsyaml--полная-справка)
5. [Поведение и нюансы](#5-поведение-и-нюансы)

---

## 1. Примеры запуска

URL пишется один раз в переменную и переиспользуется — это нужно, чтобы
`bootstrap.sh` узнал свой собственный адрес (`BOOTSTRAP_URL`), извлёк из
него каталог (`BASE_URL`) и подтянул оттуда же `fetch_models.py`,
`models.yaml` и содержимое `workflows/`.

```bash
U="https://raw.githubusercontent.com/dimitriy7877-gif/comfy_conf/main/bootstrap.sh"
```

**Обычный запуск**
```bash
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash
```

**Dry-run** — показывает, что скачалось бы / какие ноды поставились бы /
будет ли рестарт; не делает ничего.
```bash
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash -s -- --dry-run
```

**Перекачать всё заново** (даже то, что уже на диске)
```bash
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash -s -- --force
```

**Перебить путь к ComfyUI**
```bash
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash -s -- --comfyui /workspace/runpod-slim/ComfyUI
```

**Только модели, без нод и без рестарта**
```bash
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash -s -- --skip-nodes --no-restart
```

**Приватный/gated HuggingFace-репозиторий**
```bash
curl -fsSL "$U" | BOOTSTRAP_URL="$U" HF_TOKEN=hf_xxx bash
```

**Приватный GitHub-репозиторий / выше лимит GitHub API**
```bash
curl -fsSL "$U" | BOOTSTRAP_URL="$U" GITHUB_TOKEN=ghp_xxx bash
```

**Скрипты в подкаталоге репозитория** — `BASE_URL` автоматически становится
этим подкаталогом, авто-поиск workflows ищет в `.../configs/wan/workflows/`.
```bash
U="https://raw.githubusercontent.com/USER/REPO/main/configs/wan/bootstrap.sh"
curl -fsSL "$U" | BOOTSTRAP_URL="$U" bash
```

**Скрипты с другого источника** (авто-поиск workflows работает только для
github raw; явный список в `models.yaml` продолжает работать)
```bash
curl -fsSL "$U" | BASE_URL=https://my.server/comfy bash -s -- --dry-run
```

**Самый простой режим, без BOOTSTRAP_URL** — используется
`DEFAULT_BASE_URL`, захардкоженный в `bootstrap.sh`.
```bash
curl -fsSL https://raw.githubusercontent.com/USER/REPO/main/bootstrap.sh | bash
```

Замечание: автоматически узнать собственный URL потока `curl | bash` нельзя
(у пайпа нет своего пути). Приём с переменной `U` выше — минимальная форма:
одна строка, URL пишется единожды.

---

## 2. Переменные окружения

Все распознаются `bootstrap.sh`. Передаются перед `bash` в одной строке.

| Переменная        | Назначение                                                                                                  | Дефолт                                |
|-------------------|-------------------------------------------------------------------------------------------------------------|---------------------------------------|
| `BOOTSTRAP_URL`   | Собственный URL `bootstrap.sh`. Из него выводится `BASE_URL` (= каталог скрипта).                            | пусто                                  |
| `BASE_URL`        | Откуда тянуть `fetch_models.py`, `models.yaml`, `workflows/`. Высший приоритет.                              | dirname(`BOOTSTRAP_URL`) или дефолт   |
| `HF_TOKEN`        | Токен HuggingFace для gated/приватных репо. Используется, если `hf_token` в YAML пуст.                       | пусто                                  |
| `GITHUB_TOKEN`    | Токен GitHub. Сейчас применяется только к Contents API (авто-поиск workflows); raw-файлы пока без него.       | пусто                                  |
| `CONFIG`          | Имя конфиг-файла, который тянет `bootstrap.sh`.                                                              | `models.yaml`                          |
| `SCRIPT`          | Имя скрипта-загрузчика.                                                                                      | `fetch_models.py`                      |
| `WORKDIR`         | Куда `bootstrap.sh` кладёт скачанные `script + config` на поде.                                              | `/workspace/.comfy-fetch`              |

**Приоритет разрешения `BASE_URL`:**
1. явный `BASE_URL=...` в окружении;
2. dirname от `BOOTSTRAP_URL`;
3. `DEFAULT_BASE_URL`, захардкоженный в `bootstrap.sh`.

---

## 3. CLI-флаги `fetch_models.py`

Передаются после `bash -s --`. Любой набор флагов прозрачно прокидывается
из `bootstrap.sh` в `fetch_models.py`.

| Флаг                                | Что делает                                                                                       |
|-------------------------------------|--------------------------------------------------------------------------------------------------|
| `-c <path>`, `--config <path>`      | Путь к YAML. **Обязательный** (bootstrap проставляет автоматически).                              |
| `--comfyui <path>`                  | Переопределяет `comfyui_path` из YAML.                                                            |
| `--force`                           | Перекачать всё, даже уже скачанное. Эквивалент `overwrite: true` в YAML.                          |
| `--dry-run`                         | Показать план: что качаем, какие ноды ставим, будет ли рестарт. Реально ничего не делать.        |
| `--skip-nodes`                      | Не ставить кастомные ноды.                                                                       |
| `--no-restart`                      | Не перезапускать ComfyUI после установки нод.                                                    |
| `--workflows-listing-url <url>`     | GitHub Contents API URL для авто-поиска workflows. Подставляется `bootstrap.sh` автоматически.    |
| `--github-token <token>`            | Токен для Contents API. По умолчанию берётся из `GITHUB_TOKEN`.                                  |

Коды выхода: `0` — всё ок; `1` — была хотя бы одна неудача (скачивание или
установка ноды).

---

## 4. models.yaml — полная справка

YAML состоит из четырёх логических секций. Формальная схема:

```yaml
# 1. Глобальные пути и флаги
comfyui_path: <path>          # required
hf_token: <str>               # optional
overwrite: <bool>             # optional
workflows_path: <path>        # optional

# 2. Workflows
workflows:                    # optional, flat list
  - <item>

# 3. Кастомные ноды (настройки + список)
custom_nodes_installer: <str> # optional
restart: <str>                # optional
comfyui_port: <int>           # optional
comfyui_venv: <path>          # optional
comfyui_manager_repo: <url>   # optional
custom_nodes:                 # optional, flat list
  - <node-item>

# 4. Модели
models:                       # optional but expected
  <type>: [ <item>, ... ]
  ...
```

Хотя бы одна из секций (`workflows`, `custom_nodes`, `models`) или
авто-найденные workflows должны быть непустыми — иначе скрипт завершится
ошибкой «nothing to do».

### 4.1. Глобальные ключи

| Ключ                     | Тип    | Описание                                                                                                           | Дефолт                                            |
|--------------------------|--------|--------------------------------------------------------------------------------------------------------------------|---------------------------------------------------|
| `comfyui_path`           | path   | Абсолютный путь к установке ComfyUI. Модели идут в `<comfyui_path>/models/<type>/...`. Перебивается `--comfyui`.    | — (обязателен)                                    |
| `hf_token`               | str    | Токен HuggingFace для gated/приватных репо. Если пусто — берётся `HF_TOKEN`.                                        | `""`                                              |
| `overwrite`              | bool   | Перекачать всё, даже уже скачанное. То же, что `--force`.                                                            | `false`                                           |
| `workflows_path`         | path   | Куда класть JSON-файлы workflow.                                                                                    | `<comfyui_path>/user/default/workflows`           |

### 4.2. Секция `workflows:`

Плоский список с общим синтаксисом элемента (см. [4.5](#45-синтаксис-элементов)).
JSON-файлы воркфлоу должны быть **raw**:

- GitHub: `https://raw.githubusercontent.com/<user>/<repo>/<branch>/<path>.json`
- HuggingFace: `https://huggingface.co/<repo>/resolve/main/<path>.json`
- Gist: `https://gist.githubusercontent.com/<user>/<id>/raw/<file>.json`

**Авто-поиск workflows.** Если `BASE_URL` — это `raw.githubusercontent.com`,
скрипт также подтягивает все `*.json` из каталога `workflows/`, лежащего
рядом с `bootstrap.sh` (только верхний уровень, без рекурсии). При
совпадении имени файла побеждает запись из `workflows:` — там можно задать
свой `filename`/`subdir`. Не-GitHub источник или отсутствующий каталог
`workflows/` — не фатально: предупреждение, явный список продолжает
обрабатываться.

### 4.3. Секция «Custom nodes»

Все ключи, относящиеся к нодам, лежат в одной секции — сначала настройки,
потом сам список.

#### Настройки

| Ключ                       | Тип    | Значения                                          | Описание                                                                                                                       |
|----------------------------|--------|---------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------|
| `custom_nodes_installer`   | str    | `comfy-cli` (дефолт) \| `cm-cli`                  | Чем ставить ноды. `comfy-cli` — pip-пакет, обёртка над `cm-cli.py` из ComfyUI-Manager. Авто-фоллбэк на `cm-cli`, если `comfy` нет на PATH. |
| `restart`                  | str    | `auto` (дефолт) \| `none` \| `"<shell-команда>"`  | Что делать после установки нод. `auto` — reboot-эндпоинт ComfyUI-Manager → фоллбэк `pkill main.py` (подхватит супервизор пода). Срабатывает только если реально что-то установилось и не `--dry-run`. |
| `comfyui_port`             | int    | `8188` (дефолт)                                    | Порт ComfyUI для `restart: auto`.                                                                                              |
| `comfyui_venv`             | path   | пусто (дефолт)                                     | Venv, в котором крутится ComfyUI. **Важно:** зависимости нод обязаны попасть в это окружение, иначе ноды не импортируются.       |
| `comfyui_manager_repo`     | url    | репо `ltdrdata/ComfyUI-Manager` (дефолт)           | Откуда клонировать ComfyUI-Manager, если его нет (он нужен `comfy-cli`).                                                       |

#### Список `custom_nodes:`

Плоский список. Элементом может быть строка (registry-id или git-URL) или
словарь. Правило: строка с `http(s)://` или `git@` → git-URL, иначе →
registry-id.

```yaml
custom_nodes:
  - comfyui-kjnodes                              # registry-id (шорткат)
  - https://github.com/user/Repo                 # git-URL (шорткат)
  - id: comfyui-impact-pack                      # registry-id + опц. пин
    version: 8.15.3                              # best-effort, зависит от comfy-cli
  - url: https://github.com/user/Repo            # git-URL
    pip: false                                   # не ставить requirements.txt ноды
```

Поля для словарной формы:

| Поле       | Где применимо   | Описание                                                                  |
|------------|-----------------|---------------------------------------------------------------------------|
| `id`       | registry-форма  | ID ноды в реестре ComfyUI-Manager.                                        |
| `version`  | registry-форма  | Опциональный пин версии. Best-effort — реально пина может не быть.        |
| `url`      | git-форма       | git-URL репо ноды.                                                        |
| `pip`      | обе формы       | `false` — не ставить `requirements.txt` ноды. По умолчанию `true`.        |

### 4.4. Секция `models:`

Это словарь `<type>: [ items ]`, где `<type>` — **буквально имя каталога**
в `<comfyui_path>/models/`. Любой ключ допустим: добавить новый тип моделей
== добавить новую секцию, кода менять не нужно.

```yaml
models:
  diffusion_models:
    - https://.../model.gguf
  vae:
    - https://.../vae.safetensors
  loras:
    - url: https://.../style.safetensors
      filename: my_style.safetensors
      subdir: SDXL
```

Типичные типы для ComfyUI: `checkpoints`, `diffusion_models`, `vae`,
`text_encoders`, `loras`, `controlnet`, `upscale_models`, `clip_vision`,
`embeddings`, `unet`. Скрипту они одинаковы — это просто имена подпапок.

### 4.5. Синтаксис элементов

Применяется ко всем спискам `workflows:` и `models.<type>:` одинаково.

**Шорткат:**
```yaml
- https://host/path/file.ext
```

**Полная форма:**
```yaml
- url: https://host/path/file.ext
  filename: rename.safetensors    # опционально: сохранить под другим именем
  subdir: SomeFolder              # опционально: вложенная подпапка
```

Имя файла по умолчанию извлекается из URL. `subdir` создаётся внутри
целевого каталога (`models/<type>/` или `workflows_path`).

---

## 5. Поведение и нюансы

### Загрузка

- Если установлен `aria2c` — используется он (16 соединений, докачка).
  `bootstrap.sh` ставит его при первом запуске.
- Иначе фоллбэк на `curl -C - -L --retry 5`.
- Проверка через HEAD: если локальный файл совпадает с `Content-Length` —
  пропускается; если меньше — докачивается; `--force`/`overwrite: true`
  игнорируют проверку.
- Авторизация (`hf_token`/`HF_TOKEN`) сейчас отправляется на все домены,
  не только на `huggingface.co` (см. known issues в `MEMORY_BANK.md`).

### Кастомные ноды

- `comfy-cli` запускается с глобальным `--skip-prompt`, чтобы не повис на
  интерактивном согласии на телеметрию.
- ComfyUI-Manager авто-клонируется в `<comfyui_path>/custom_nodes/ComfyUI-Manager`,
  если его нет (`comfy-cli` без него не работает).
- Идемпотентность делегируется самому установщику — повторный запуск без
  `--force` не сломается, если нода уже стоит.

### Рестарт

Срабатывает **в самом конце** (после моделей), один раз, и только если хотя
бы одна нода реально установилась + не `--dry-run`. Стратегия задаётся
ключом `restart`:

- `auto` — POST на `/api/manager/reboot`, при неудаче на `/manager/reboot`,
  при неудаче `pkill -f ComfyUI/main.py` (RunPod-шаблоны обычно
  перезапускают сервер автоматически).
- `none` — ничего не делать.
- `"<команда>"` — выполнить произвольный shell (например
  `supervisorctl restart comfyui`).

`--no-restart` отключает рестарт независимо от значения `restart` в YAML.

### Gated HF-репозитории

Признак — `aria2c errorCode=24 Authorization failed`. Проверь по очереди:

1. Токен реально передан. В выводе должно быть `[*] HF token: yes`.
2. Лицензия принята вашим аккаунтом на странице репо (для каждого
   gated-репо отдельно).
3. Токен имеет права на чтение / fine-grained доступ к этому репо.

Быстрая проверка с пода:
```bash
curl -sI -H "Authorization: Bearer $HF_TOKEN" <file_url> | head -n1
# 200/302 — ок; 401 — токен невалидный; 403 — лицензия не принята.
```
