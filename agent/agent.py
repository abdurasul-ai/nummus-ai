"""NummusAI agent loop: Claude tool use over DuckDB + entity resolver, with number-traceability verification."""
import json
import os
import time
import re

import threading

import duckdb

from agent.entity_index import DB_PATH, ROOT
from agent.tools import TOOLS, call_tool
from agent.verify import untraceable, ungrounded_entities
from agent.localize import detect_lang, localize

PROVIDER = os.environ.get('NUMMUS_PROVIDER') or ('groq' if os.environ.get('GROQ_API_KEY') else 'anthropic')
MODEL = (os.environ.get('NUMMUS_MODEL_GROQ', 'openai/gpt-oss-120b') if PROVIDER == 'groq'
         else os.environ.get('NUMMUS_MODEL', 'claude-sonnet-5-5'))
MAX_STEPS = int(os.environ.get('NUMMUS_MAX_STEPS', '8'))
MAX_TOKENS = 2000

_system = None


def system_prompt() -> str:
    global _system
    if _system is None:
        fname = 'system_prompt_full.md' if os.environ.get('NUMMUS_PROMPT') == 'full' else 'system_prompt.md'
        tpl = open(os.path.join(ROOT, 'agent', fname), encoding='utf8').read()
        con = duckdb.connect(DB_PATH, read_only=True)
        prods = con.execute("select product_family, count(*) from deals_enriched group by 1 order by 2 desc").fetchall()
        regs = con.execute("select region, count(*) from deals group by 1 order by 2 desc").fetchall()
        con.close()
        _system = (tpl.replace('{PRODUCTS}', '; '.join(p for p, _ in prods))
                      .replace('{REGIONS}', '; '.join(r for r, _ in regs)))
    return _system


_TPM_LIMIT = int(os.environ.get('NUMMUS_TPM', '7400'))     # per model; raise (e.g. 200000) on a paid Groq tier
_POOL = [
    {'model': 'openai/gpt-oss-120b', 'extra': {'reasoning_effort': os.environ.get('NUMMUS_REASONING', 'medium')}},
    {'model': 'qwen/qwen3.8-27b', 'extra': {'reasoning_effort': 'none'}},
    {'model': 'openai/gpt-oss-20b', 'extra': {'reasoning_effort': 'medium'}},
]
if os.environ.get('NUMMUS_POOL', '').lower() == 'single':
    _POOL = _POOL[:1]
_wins = {c['model']: [] for c in _POOL}     # model -> [[timestamp, tokens], ...]
_win_lock = threading.Lock()


def _reserve(est: int):
    """Pick the first pool model whose rolling 60 s token window has room; wait if none has. -> (cfg, entry)"""
    while True:
        with _win_lock:
            now = time.time()
            soonest = None
            for cfg in _POOL:
                w = _wins[cfg['model']]
                w[:] = [e for e in w if now - e[0] < 60]
                if sum(e[1] for e in w) + est <= _TPM_LIMIT or not w:
                    entry = [now, est]
                    w.append(entry)
                    return cfg, entry
                t = w[0][0] + 60 - now
                soonest = t if soonest is None else min(soonest, t)
        time.sleep(min(max(soonest or 0.5, 0.3), 3))


def _groq_call(client, kw, est):
    from groq import RateLimitError, BadRequestError
    last = None
    for attempt in range(8):
        cfg, entry = _reserve(est)
        try:
            resp = client.chat.completions.create(**{**kw, 'model': cfg['model'], **cfg['extra']})
            u = getattr(resp, 'usage', None)
            if u and getattr(u, 'total_tokens', None):
                entry[1] = u.total_tokens
            return resp
        except RateLimitError as e:
            last = e
            with _win_lock:
                entry[1] = _TPM_LIMIT          # this model's window is full: next loop picks another / waits
            time.sleep(0.4)
        except BadRequestError as e:           # e.g. unsupported parameter for this model -> retry without extras
            last = e
            entry[1] = 0
            if cfg['extra']:
                cfg['extra'] = {}
                continue
            raise
    raise last


class _Anthropic:
    """Claude tool-use backend."""

    def __init__(self):
        import anthropic
        self.c = anthropic.Anthropic(timeout=60.0, max_retries=2)
        self.sys = [{'type': 'text', 'text': system_prompt(), 'cache_control': {'type': 'ephemeral'}}]

    def start(self, history, question):
        return list(history or []) + [{'role': 'user', 'content': question}]

    def step(self, msgs):
        resp = self.c.messages.create(model=MODEL, max_tokens=MAX_TOKENS, system=self.sys, tools=TOOLS, messages=msgs)
        msgs.append({'role': 'assistant', 'content': resp.content})
        calls = [{'id': b.id, 'name': b.name, 'input': b.input} for b in resp.content if b.type == 'tool_use']
        text = ''.join(b.text for b in resp.content if b.type == 'text').strip()
        return text, calls

    def add_results(self, msgs, results, extra_text=None):
        content = [{'type': 'tool_result', 'tool_use_id': i, 'content': c} for i, c in results]
        if extra_text:
            content.append({'type': 'text', 'text': extra_text})
        msgs.append({'role': 'user', 'content': content})

    def add_user(self, msgs, text):
        msgs.append({'role': 'user', 'content': text})


class _Groq:
    """Groq (OpenAI-compatible) tool-calling backend."""

    def __init__(self):
        from groq import Groq
        self.c = Groq(timeout=60.0, max_retries=3)
        self.tools = [{'type': 'function', 'function': {'name': t['name'], 'description': t['description'], 'parameters': t['input_schema']}} for t in TOOLS]

    def start(self, history, question):
        return [{'role': 'system', 'content': system_prompt()}] + list(history or []) + [{'role': 'user', 'content': question}]

    def step(self, msgs):
        kw = dict(messages=msgs, tools=self.tools, tool_choice='auto', max_tokens=2000, temperature=0.1)
        est = int(len(json.dumps(msgs, ensure_ascii=False)) / 2.8) + 1800
        resp = _groq_call(self.c, kw, est)
        m = resp.choices[0].message
        am = {'role': 'assistant', 'content': m.content or ''}
        calls = []
        if m.tool_calls:
            am['tool_calls'] = [{'id': t.id, 'type': 'function', 'function': {'name': t.function.name, 'arguments': t.function.arguments or '{}'}} for t in m.tool_calls]
            for t in m.tool_calls:
                try:
                    args = json.loads(t.function.arguments or '{}')
                except ValueError:
                    args = {}
                calls.append({'id': t.id, 'name': t.function.name, 'input': args})
        msgs.append(am)
        return (m.content or '').strip(), calls

    def add_results(self, msgs, results, extra_text=None):
        for i, c in results:
            msgs.append({'role': 'tool', 'tool_call_id': i, 'content': c})
        if extra_text:
            msgs.append({'role': 'user', 'content': extra_text})

    def add_user(self, msgs, text):
        msgs.append({'role': 'user', 'content': text})


def _backend():
    return _Groq() if PROVIDER == 'groq' else _Anthropic()


def _limit(out: dict, cap: int = 3800) -> dict:
    """Shrink a tool result so it stays cheap for the model; the verifier only trusts what the model saw."""
    if not isinstance(out, dict) or not out.get('rows'):
        return out
    o = dict(out)
    rows = list(o['rows'])
    while rows and len(json.dumps({**o, 'rows': rows}, ensure_ascii=False, default=str)) > cap:
        rows = rows[: max(1, int(len(rows) * 0.8))] if len(rows) > 1 else []
    if len(rows) < len(o['rows']):
        o['truncated'] = True
        o['note'] = f"only first {len(rows)} of {len(o['rows'])} rows shown; use LIMIT / aggregate in SQL"
    o['rows'] = rows
    o.pop('sql', None)
    return o


def _short(res: dict) -> str:
    return json.dumps(res, ensure_ascii=False, default=str)


_HUMAN = {
    'is_successful': ('успешные', 'muvaffaqiyatli'),
    'is_annulled': ('аннулированные', 'bekor qilingan'),
    'amount_uzs': ('сумма в сумах', 'so‘mdagi summa'),
    'amount_usd': ('сумма в долларах', 'dollardagi summa'),
    'product_family': ('товар', 'mahsulot'),
    'unit_price': ('цена за единицу', 'birlik narxi'),
    'volume_units': ('объём', 'hajm'),
    'quantity_lots': ('количество лотов', 'lotlar soni'),
    'deal_date': ('дата сделки', 'bitim sanasi'),
    'seller_inn': ('ИНН продавца', 'sotuvchi STIRi'),
    'buyer_inn': ('ИНН покупателя', 'xaridor STIRi'),
    'seller_name': ('продавец', 'sotuvchi'),
    'buyer_name': ('покупатель', 'xaridor'),
    'deals_enriched': ('реестр сделок', 'bitimlar reestri'),
    'contract_type': ('тип контракта', 'shartnoma turi'),
    'contract_form': ('форма контракта', 'shartnoma shakli'),
    'trade_type': ('тип торгов', 'savdo turi'),
    'hs_code': ('код ТН ВЭД', 'TN VED kodi'),
}
_SNAKE = re.compile(r'`?\*{0,2}\b([a-z]+(?:_[a-z0-9]+)+)\b\*{0,2}`?')


def humanize(text: str) -> str:
    """Never show internal column names (snake_case) or code ticks to the user."""
    if not text:
        return text
    ru = len(re.findall(r'[а-яёА-ЯЁ]', text)) >= len(re.findall(r'[a-zA-Z]', text)) * 0.3
    idx = 0 if ru else 1

    def sub(m):
        name = m.group(1)
        if name in _HUMAN:
            return _HUMAN[name][idx]
        return name.replace('_', ' ')
    text = _SNAKE.sub(sub, text)
    return text.replace('`', '')


_BASIS = re.compile(r'<basis>(.*?)</basis>', re.S | re.I)


def split_basis(text: str):
    """-> (visible answer, basis text)"""
    m = _BASIS.search(text or '')
    if not m:
        return (text or '').replace('<basis>', '').strip(), ''
    return _BASIS.sub('', text).strip(), m.group(1).strip()


def _safe_fallback(question, steps, bad):
    """Verification failed: never show raw rows or unverified prose, just say the answer is not certain."""
    lang = detect_lang(question)
    if lang == 'ru':
        return 'Я не могу дать точный проверенный ответ на этот вопрос, поэтому не буду гадать. Попробуйте уточнить вопрос: период, товар, регион или компанию.'
    if lang == 'en':
        return 'I cannot give a precise, verified answer to this question, so I will not guess. Please make it more specific: period, product, region or company.'
    return 'Bu savolga aniq va tekshirilgan javob bera olmayman, shuning uchun taxmin qilmayman. Savolni aniqroq yozib ko‘ring: davr, mahsulot, hudud yoki kompaniyani ko‘rsating.'


def answer(question: str, history=None, on_event=None) -> dict:
    """Run the agent. Returns {answer, basis, steps:[{tool,input,output}], elapsed, unverified:[...]}"""
    emit = on_event or (lambda *_: None)
    t0 = time.time()
    from agent.localize import meta_answer
    _m = meta_answer(question)
    if _m:
        return {'answer': _m[0], 'basis': _m[1], 'steps': [], 'elapsed': 0.1, 'unverified': []}
    be = _backend()
    msgs = be.start(history, question)
    steps, tool_outputs = [], []
    final = ''
    repairs = empties = 0
    for _ in range(MAX_STEPS + 5):
        text, calls = be.step(msgs)
        if calls and len(steps) < MAX_STEPS:
            results = []
            for b in calls:
                emit('tool', {'name': b['name'], 'input': b['input']})
                out = call_tool(b['name'], b['input'])
                steps.append({'tool': b['name'], 'input': b['input'], 'output': out})
                shown = _limit(out)
                tool_outputs.append(shown)
                results.append((b['id'], _short(shown)))
            be.add_results(msgs, results)
            continue
        if calls:  # step budget exhausted: force a final answer
            be.add_results(msgs, [(b['id'], 'step budget exhausted') for b in calls],
                           'Give the final answer now using only data already retrieved.')
            continue
        if not text.strip() and empties < 2:   # a model stopped without writing the answer
            empties += 1
            be.add_user(msgs, 'Write the final answer for the user now, using only the tool results above, in the required format (including the <basis> block).')
            continue
        final = text
        bad = untraceable(final, question, tool_outputs) + ungrounded_entities(final, question, tool_outputs)
        if bad and repairs < 3:
            repairs += 1
            emit('status', {'msg': 'verifying numbers'})
            be.add_user(msgs, (
                f'Verification: these figures/names in your answer are not found in the tool results or the question: {", ".join(bad[:12])}. '
                'Rewrite the answer: use only values returned by the tools (run another query if you need a derived value, computing it in SQL), or delete the unsupported claim. '
                'Output ONLY the clean final answer for the user, in the question language, keeping the required format (including the <basis> block). '
                'Do NOT mention the verification, corrections, earlier drafts or this message.'))
            continue
        if bad:
            final = _safe_fallback(question, steps, bad) + chr(10) + '<basis>' + {'ru': 'Ответ не прошёл проверку по данным реестра.', 'en': 'The answer failed verification against the registry data.'}.get(detect_lang(question), 'Javob reyestr ma’lumotlari bilan tekshiruvdan o‘tmadi.') + '</basis>'
        vis, basis = split_basis(final)
        vis, basis = humanize(vis), humanize(basis)
        lang = detect_lang(question)
        vis, basis = localize(vis, lang), localize(basis, lang)
        return {'answer': vis, 'basis': basis, 'steps': steps, 'elapsed': round(time.time() - t0, 1), 'unverified': bad}
    return {'answer': final or 'Не удалось получить ответ / Javob olinmadi.', 'basis': '', 'steps': steps, 'elapsed': round(time.time() - t0, 1), 'unverified': []}
