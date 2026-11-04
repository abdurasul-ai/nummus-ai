"""Tools exposed to the LLM agent: run_sql (hardened, read-only DuckDB) and resolve_entity."""
import datetime
import decimal
import os
import re
import threading

import duckdb

from agent.entity_index import DB_PATH, get_index

MAX_ROWS = 100
TIMEOUT_S = 20

_FORBIDDEN = re.compile(
    r'\b(attach|detach|copy|export|import|install|load|pragma|call|create|insert|update|delete|drop|alter|truncate|'
    r'set|reset|vacuum|checkpoint|read_csv|read_csv_auto|read_parquet|read_json|read_text|read_blob|glob|'
    r'parquet_scan|sniff_csv|httpfs|http_get|getenv|current_setting|duckdb_[a-z_]+|pragma_[a-z_]+)\b', re.I)

_local = threading.local()
_base = None
_lock = threading.Lock()


def _conn():
    global _base
    with _lock:
        if _base is None:
            _base = duckdb.connect(DB_PATH, read_only=True)
            _base.execute("SET enable_external_access=false") if False else None
    return _base.cursor()


def validate_sql(sql: str) -> str:
    s = sql.strip()
    s = re.sub(r'--[^\n]*', ' ', s)
    s = re.sub(r'/\*.*?\*/', ' ', s, flags=re.S).strip().rstrip(';').strip()
    if ';' in s:
        raise ValueError('Only a single statement is allowed.')
    if not re.match(r'(?is)^(select|with)\b', s):
        raise ValueError('Only SELECT / WITH queries are allowed.')
    # ignore string literals when scanning for forbidden words
    probe = re.sub(r"'(?:[^']|'')*'", "''", s)
    m = _FORBIDDEN.search(probe)
    if m:
        raise ValueError(f'Forbidden keyword in query: {m.group(0)}')
    return s


def _fmt(v):
    if v is None:
        return None
    if isinstance(v, float):
        if v != v:
            return None
        return round(v, 4) if abs(v) < 1e15 else v
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (datetime.date, datetime.datetime, datetime.time)):
        return v.isoformat()
    return v


def run_sql(sql: str) -> dict:
    try:
        s = validate_sql(sql)
    except ValueError as e:
        return {'error': str(e)}
    cur = _conn()
    timer = threading.Timer(TIMEOUT_S, cur.interrupt)
    timer.start()
    try:
        cur.execute(s)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(MAX_ROWS + 1)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if 'INTERRUPT' in msg.upper():
            msg = f'Query exceeded {TIMEOUT_S}s timeout; simplify or aggregate more.'
        return {'error': msg[:600]}
    finally:
        timer.cancel()
        try:
            cur.close()
        except Exception:  # noqa: BLE001
            pass
    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    return {'columns': cols, 'rows': [[_fmt(v) for v in r] for r in rows], 'row_count': len(rows),
            'truncated': truncated, 'sql': s}


def resolve_entity(kind: str, text: str) -> dict:
    try:
        return get_index().resolve(kind, text)
    except Exception as e:  # noqa: BLE001
        return {'error': str(e)[:300]}


TOOLS = [
    {
        'name': 'resolve_entity',
        'description': ('Find the exact database value for a product, region, company, broker or contract mentioned by the user. '
                        'Works across Russian / Uzbek (Latin & Cyrillic) / English spellings and typos. '
                        'ALWAYS call it before filtering by a company, broker or product name you are not 100% sure of. '
                        'kind: product | region | company | broker | contract. For company you may pass a name or a 9-digit INN.'),
        'input_schema': {'type': 'object', 'properties': {
            'kind': {'type': 'string', 'enum': ['product', 'region', 'company', 'broker', 'contract']},
            'text': {'type': 'string'}}, 'required': ['kind', 'text']},
    },
    {
        'name': 'run_sql',
        'description': ('Run ONE read-only DuckDB SELECT/WITH query over the exchange data (see schema in the system prompt). '
                        f'Returns at most {MAX_ROWS} rows. Use aggregation in SQL; never compute numbers by hand.'),
        'input_schema': {'type': 'object', 'properties': {'sql': {'type': 'string'}}, 'required': ['sql']},
    },
]


def call_tool(name: str, args: dict) -> dict:
    if name == 'run_sql':
        return run_sql(args.get('sql', ''))
    if name == 'resolve_entity':
        return resolve_entity(args.get('kind', ''), args.get('text', ''))
    return {'error': f'unknown tool {name}'}
