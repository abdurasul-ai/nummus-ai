# NummusAI — agent over UZEX exchange-deal data

Text-to-SQL tool-using agent (Claude + DuckDB). Answers RU/UZ questions only from the 500 000-deal registry, shows the basis (SQL + rows) and refuses when the data has no answer. See [docs/SOLUTION.md](docs/SOLUTION.md).

## Run locally
```bash
pip install -r requirements.txt
python -X utf8 -I etl/build_db.py          # builds data/uzex.duckdb, asserts 500 000 rows, per-year counts, no join fan-out
# put keys in .env (see .env.example): GROQ_API_KEY=... (default backend) or ANTHROPIC_API_KEY=...
# paid Groq tier: NUMMUS_TPM=200000 NUMMUS_POOL=single NUMMUS_PROMPT=full
uvicorn app.main:app --port 8000           # web chat at http://localhost:8000
TELEGRAM_BOT_TOKEN=... python -X utf8 -m app.telegram_bot   # optional Telegram bot
```

## Tests
```bash
python -X utf8 -I tests/make_golden.py     # builds tests/golden.yaml from pandas + PASS/FAIL DB cross-checks
python -X utf8 tests/run_eval.py           # runs the agent on the golden set (needs API key)
```

## Deploy (Render)
Blueprint `render.yaml` + `Dockerfile` (prebuilt `data/uzex.duckdb` is in the repo). Set secret `GROQ_API_KEY` on Render. Health check: `GET /health`.

## Layout
`etl/` build DB · `agent/` prompt, tools, entity resolver, verifier · `app/` FastAPI + UI + Telegram · `tests/` golden set · `data/aliases.yaml` RU/UZ/EN aliases.
