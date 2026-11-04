"""FastAPI service: chat UI + streaming API.   Run: uvicorn app.main:app --host 0.0.0.0 --port 8000"""
import asyncio
import json
import os
import re
import sys
import threading
import time
import queue

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from agent.agent import answer, system_prompt  # noqa: E402
from agent.entity_index import get_index  # noqa: E402
from agent.tools import run_sql  # noqa: E402

LOG_DIR = os.path.join(ROOT, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
app = FastAPI(title='NummusAI')
app.mount('/static', StaticFiles(directory=os.path.join(ROOT, 'app', 'static')), name='static')

_cache: dict = {}
_cache_lock = threading.Lock()
_sem = threading.Semaphore(int(os.environ.get('NUMMUS_CONCURRENCY', '8')))


@app.on_event('startup')
def warm():
    get_index()
    system_prompt()
    run_sql('select count(*) from deals_enriched')


def _key(q: str) -> str:
    return re.sub(r'\s+', ' ', q.strip().lower())


def log(entry: dict):
    try:
        with open(os.path.join(LOG_DIR, 'qa.jsonl'), 'a', encoding='utf8') as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + '\n')
    except Exception:  # noqa: BLE001
        pass


def public_steps(steps):
    out = []
    for s in steps:
        o = s['output']
        if s['tool'] == 'run_sql':
            out.append({'tool': 'run_sql', 'sql': o.get('sql') or s['input'].get('sql'), 'error': o.get('error'),
                        'columns': o.get('columns'), 'rows': (o.get('rows') or [])[:15], 'row_count': o.get('row_count'),
                        'truncated': o.get('truncated')})
        else:
            out.append({'tool': s['tool'], 'input': s['input'], 'candidates': (o.get('candidates') or [])[:5], 'error': o.get('error')})
    return out


def run_question(q: str, history, on_event):
    k = _key(q)
    if not history:
        with _cache_lock:
            hit = _cache.get(k)
        if hit:
            return {**hit, 'cached': True}
    with _sem:
        try:
            res = answer(q, history=history, on_event=on_event)
        except Exception as e:  # noqa: BLE001
            log({'ts': time.time(), 'q': q, 'error': repr(e)[:500]})
            return {'answer': 'Сервис временно недоступен, повторите запрос. / Xizmat vaqtincha ishlamayapti, qayta urinib ko‘ring.',
                    'steps': [], 'elapsed': 0, 'unverified': [], 'error': True}
    out = {'answer': res['answer'], 'basis': res.get('basis', ''), 'steps': public_steps(res['steps']), 'elapsed': res['elapsed'], 'unverified': res['unverified']}
    log({'ts': time.time(), 'q': q, **out})
    if not history and not res['unverified']:
        with _cache_lock:
            _cache[k] = out
    return out


@app.get('/')
def index():
    return FileResponse(os.path.join(ROOT, 'app', 'static', 'index.html'))


@app.get('/health')
def health():
    return {'ok': True}


@app.post('/api/ask')
async def ask(request: Request):
    body = await request.json()
    q = (body.get('question') or '').strip()[:2000]
    history = body.get('history') or []
    history = [{'role': h['role'], 'content': h['content']} for h in history[-6:]
               if h.get('role') in ('user', 'assistant') and isinstance(h.get('content'), str)]
    if not q:
        return JSONResponse({'error': 'empty'}, status_code=400)
    qu: 'queue.Queue' = queue.Queue()

    def worker():
        res = run_question(q, history, lambda ev, data: qu.put(('event', ev, data)))
        qu.put(('done', 'done', res))

    threading.Thread(target=worker, daemon=True).start()

    async def gen():
        yield 'event: status\ndata: {"msg":"start"}\n\n'
        while True:
            try:
                kind, ev, data = await asyncio.get_event_loop().run_in_executor(None, lambda: qu.get(timeout=1))
            except queue.Empty:
                yield ': ping\n\n'
                continue
            yield f'event: {ev}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n'
            if kind == 'done':
                break

    return StreamingResponse(gen(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
