# AGENTS.md

Single-user ttkbootstrap GUI app. No tests, lint, typecheck, or CI.

## Run

```powershell
uv venv --python 3.12.8
uv sync
uv run python main.py
```

- Entry: `main.py` → `app/main_window.py:run_app()`. GUI only, no CLI.
- `pyproject.toml` has `package = false`; deps are `ttkbootstrap`, `Pillow`, `requests`.
- Offline smoke test: select `Mock` provider in GUI (no network, returns copy).

## Architecture

- `app/main_window.py` — `ttk.Notebook` with 运行 (input/list/log/run) + 配置 (provider/params/prompt) tabs; mode combobox exists on both tabs sharing one var. Progress bar sits below notebook (always visible). Threading via `ThreadPoolExecutor`, `concurrency` 1–8. Batch run writes `results.csv` after completion.
- `core/pipeline.py:process_one()` — `auto` = full-image edit (retry `retries` times) → fallback crop-refill; `full` never falls back; `crop` / per-image `force_crop` (double-click toggle) goes crop-first, but with no boxes falls back to full edit instead of failing.
- `core/neko.py:load_neko()` — `.neko` is a zip; `texts.json` path varies (suffix search), `project.json` optional. Box pick: `bubbleBox` → `box`; skip `noTextDetected`.
- `core/scanner.py:attach_neko()` — image→uid matching is name-stem (lowercased) first, then positional order fallback. Never raises; unmatched items get `box_count=0`.
- `core/crops.py` — `pad_px` (default 20) + clamp to image, `min_size=32`. Failed patches keep original pixels; image fails only if `ok == 0`. Returned patches are `LANCZOS`-resized to box.
- `providers/` — `factory.create_provider()` passes model name straight through (UI Combobox is editable, no validation). `openai_provider` hits `{base}/images/edits` (multipart); `gemini_provider` separate REST path; `grok_provider` hits `{base}/images/edits` with JSON + `image_url` data URI (xAI rejects multipart); `base.fit_back()` resizes output to input size. `image_size` config ("" / "auto" = default, else pass-through) is sent as OpenAI `size` verbatim (non-WxH rejected client-side with a Chinese hint); `gemini_provider.gemini_image_config()` maps it to `imageConfig` ("WxH"→nearest aspect+1K/2K/4K, "1K/2K/4K"→size+source aspect, "16:9"→aspect only) and retries once without it on 400 `imageConfig` errors (old models); `grok_provider.grok_image_config()` maps it to `aspect_ratio`+`resolution` ("WxH"→nearest aspect+1k/2k, "1k/2k"→resolution+source aspect with "4k" clamped to 2k, "16:9"→aspect only) with the same drop-and-retry fallback; Mock ignores it. Size dropdown options are per-protocol (`OPENAI_SIZE_PRESETS` / `GEMINI_SIZE_PRESETS` / `GROK_SIZE_PRESETS`); switching protocol auto-drops inapplicable values via `base.size_for_provider()` (Grok keeps all, mapping normalizes).
- `utils/config.py` — `config.json` at repo root; unknown keys dropped on load, only `default_config()` keys saved. Key resolution: saved key → `OPENAI_API_KEY` / `GEMINI_API_KEY` / `GOOGLE_API_KEY` / `XAI_API_KEY` (Grok); `remember_key=false` clears stored key on save.

## Gotchas

- `config.json` is gitignored but may contain a real key locally — never commit it; use env vars.
- Output defaults to `<input_dir>/cleaned/` as `原名_cleaned.jpg` (+ dedup `_1`) with `results.csv`; both gitignored (`cleaned/`, `*/cleaned/`).
- `example-manga/`, `example-neko/` are manual test fixtures, not automated tests.
