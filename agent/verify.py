"""Number-traceability check: every significant number in the final answer must be supported by
the user's question or by a tool result (exact, rounded, or scaled with млн/млрд/mln/mlrd)."""
import json
import re

_MULT = {'трлн': 1e12, 'trln': 1e12, 'млрд': 1e9, 'mlrd': 1e9, 'млн': 1e6, 'mln': 1e6, 'тыс': 1e3, 'ming': 1e3, 'ming.': 1e3,
         'k': 1e3, 'm': 1e6, 'bn': 1e9}
_NUM = re.compile(r'(?<![\w.,])(\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?)(?:\s*(трлн|trln|млрд|mlrd|млн|mln|тыс|ming|bn|k|m)\b)?', re.I)
_DATE = re.compile(r'\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b|\b\d{4}-\d{2}(?:-\d{2})?\b|\b\d{1,2}:\d{2}(?::\d{2})?\b')


def _to_float(tok: str):
    t = tok.replace(' ', ' ').replace(' ', ' ')
    if re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?', t):
        return float(t.replace(',', ''))
    t = t.replace(' ', '').replace(',', '.')
    try:
        return float(t)
    except ValueError:
        return None


def extract_numbers(text: str):
    text = _DATE.sub(' ', text)
    out = []
    for m in _NUM.finditer(text):
        v = _to_float(m.group(1))
        if v is None:
            continue
        mult = _MULT.get((m.group(2) or '').lower(), 1)
        out.append((m.group(0).strip(), v * mult, m.group(1), mult))
    return out


def _collect(obj, acc):
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        acc.append(float(obj))
    elif isinstance(obj, str):
        for _, v, _, _ in extract_numbers(obj):
            acc.append(v)
        for tok in re.findall(r'\d+', obj):
            acc.append(float(tok))
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect(v, acc)


def _supported(v, mult, raw, pool, tol_cache):
    for p in pool:
        if p == v:
            return True
        if mult != 1:   # "1.23 млрд" -> relative tolerance by printed precision
            digits = len(raw.split('.')[-1]) if '.' in raw else 0
            rel = 0.5 * 10 ** (-digits) * mult / max(abs(p), 1) if p else 1
            if abs(p - v) <= 0.5 * 10 ** (-digits) * mult + 1e-9:
                return True
        else:
            digits = len(re.split(r'[.,]', raw)[-1]) if re.search(r'[.,]\d+$', raw) and not re.search(r'[.,]\d{3}$', raw) else 0
            if abs(p - v) <= 0.5 * 10 ** (-digits) + 1e-9:
                return True
            # percentages / rounded to integers etc.
            if digits == 0 and abs(round(p) - v) < 1e-9:
                return True
    return False


_FREE_INTS = {0, 1, 100}
_DATES_FIND = re.compile(r'\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b')
_GENERIC_CELLS = {'итого', 'всего', 'jami', 'total', 'сум', 'usd', "so'm", 'so‘m', 'сўм'}


def _iso_dates(text: str):
    out = set()
    for m in _DATES_FIND.finditer(text or ''):
        if m.group(1):
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            y, mo, d = int(m.group(4)), int(m.group(5)), int(m.group(6))
        out.add((y, mo, d))
    return out


def _is_boundary(y, mo, d):
    import calendar
    if not (1 <= mo <= 12):
        return False
    return d == 1 or d == calendar.monthrange(y, mo)[1]


def untraceable(answer: str, question: str, tool_results: list):
    """Numbers / dates in the answer that are supported by neither the question nor tool outputs."""
    pool = []
    _collect(tool_results, pool)
    for _, v, _, _ in extract_numbers(question):
        pool.append(v)
    for tok in re.findall(r'\d+', question):
        pool.append(float(tok))
    # table row numbers / list ranks 1..N where N = largest result size seen
    maxrows = 0
    for r in tool_results:
        if isinstance(r, dict) and isinstance(r.get('row_count'), int):
            maxrows = max(maxrows, r['row_count'])
    pool.extend(float(i) for i in range(1, min(maxrows, 100) + 1))
    pool = sorted(set(pool))
    bad = []
    for tok, v, raw, mult in extract_numbers(answer):
        if mult == 1 and v == int(v) and (int(v) in _FREE_INTS or 2022 <= v <= 2026):
            continue
        if not _supported(v, mult, raw, pool, None):
            bad.append(tok)
    # dates
    tool_text = json.dumps(tool_results, ensure_ascii=False, default=str)
    known = _iso_dates(tool_text) | _iso_dates(question) | {(2022, 1, 3), (2026, 10, 30), (2026, 10, 31)}
    for (y, mo, d) in _iso_dates(answer):
        if (y, mo, d) not in known and not _is_boundary(y, mo, d):
            bad.append(f'{d:02d}.{mo:02d}.{y}')
    return bad


def _nk(s):
    from etl.normalize import norm_key
    return norm_key(s)


def ungrounded_entities(answer: str, question: str, tool_results: list):
    """Names / codes in the answer (quoted names, bold names, BK codes, text cells of tables) that never appear
    in any tool result or in the question."""
    hay = _nk(json.dumps(tool_results, ensure_ascii=False, default=str) + ' ' + question)
    cands = []
    cands += re.findall(r'\bBK\d{3}\b', answer)
    cands += re.findall(r'«([^»]{3,80})»', answer)
    cands += re.findall(r'"([^"\n]{3,80})"', answer)
    # bold text is mostly formatting/labels; only company-like bold names (legal form words) are checked as entities,
    # numbers inside bold are verified by untraceable()
    cands += [b for b in re.findall(r'\*\*([^*\n]{3,80})\*\*', answer)
              if re.search(r'(?i)\b(mchj|mchzh|мчж|ооо|ao|qk|xk|llc)\b|[«"]', b) and not re.search(r'\d', b)]
    lines = [ln for ln in answer.splitlines() if ln.strip().startswith('|')]
    # first column of a "field | value" table holds labels (not data claims) -> not checked
    label_col = bool(lines) and bool(re.match(
        r'(?i)^\s*\|?\s*(поле|показатель|параметр|характеристика|атрибут|param\w*|field|maydon|ko.?rsatkich|xususiyat)\b',
        lines[0]))
    for ln in lines[2:]:   # skip header + separator
        for ci, c in enumerate(ln.strip().strip('|').split('|')):
            if label_col and ci == 0:
                continue
            c = c.strip().strip('*')
            if re.search(r'[^\W\d_]', c) and not re.fullmatch(r'[\d\s.,%+\-–—/:]*', c):
                cands.append(c)
    # numbered / bulleted list items: the leading name (before a dash, bracket or colon) must be grounded
    for ln in answer.splitlines():
        m = re.match(r'^\s*(?:\d{1,3}[.)]|[-•*])\s+(.+)$', ln)
        if not m:
            continue
        head = re.split(r'\s[—–-]\s|\s\(|:\s|,\s', m.group(1).replace('**', ''), maxsplit=1)[0].strip()
        if head[:1].isdigit():   # "79 720 кг", "05.01.2022 (...)": values/dates, verified by untraceable()
            continue
        if 0 < len(head.split()) <= 7 and re.search(r'[^\W\d_]', head) and not re.search(r'[.!?]$', head):
            cands.append(head)
    bad = []
    for c in cands:
        if c == c.lower():      # plain lowercase phrase in quotes is wording, not a name
            continue
        k = _nk(c)
        if not k or c.lower().strip() in _GENERIC_CELLS:
            continue
        if re.fullmatch(r'[\d\s]*', k):
            continue
        if k in hay:
            continue
        # tolerate cells made of several data values / units: every word must be known
        words = k.split()
        if words and all(w in hay for w in words):
            continue
        bad.append(c)
    return bad
