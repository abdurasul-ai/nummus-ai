"""Entity resolution: fuzzy, script-insensitive lookup of products, regions, companies, brokers, contracts."""
import os
import re
import sys
import yaml
import duckdb
from rapidfuzz import fuzz, process

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from etl.normalize import norm_key  # noqa: E402

DB_PATH = os.environ.get('UZEX_DB', os.path.join(ROOT, 'data', 'uzex.duckdb'))

# strip legal-form words so "Gilo'su Polimer MChJ" == "ГИЛОСУ ПОЛИМЕР МЧЖ"
_LEGAL = re.compile(r'\b(mchj|mchzh|mchj|mchj|mas uliyati|masuliyati|masliyati|cheklangan|jamiyati|jamiyat|qk|xk|ooo|ao|mchj|mchj|mchj|mchzh|mchj)\b')


def _co_key(s: str) -> str:
    k = norm_key(s)
    k = _LEGAL.sub(' ', k)
    return re.sub(r'\s+', ' ', k).strip()


class EntityIndex:
    def __init__(self):
        con = duckdb.connect(DB_PATH, read_only=True)
        with open(os.path.join(ROOT, 'data', 'aliases.yaml'), encoding='utf8') as f:
            al = yaml.safe_load(f)
        # ---- products
        self.prod_rows = []   # (key, family)
        fam_stats = {r[0]: r[1:] for r in con.execute(
            "select product_family, any_value(hs_code), count(*) from deals_enriched group by 1").fetchall()}
        self.fam_stats = fam_stats
        for fam in fam_stats:
            self.prod_rows.append((norm_key(fam), fam))
            for a in al['products'].get(fam, []):
                self.prod_rows.append((norm_key(a), fam))
        for raw, fam in con.execute("select distinct product_name_raw, product_family from contracts").fetchall():
            self.prod_rows.append((norm_key(raw), fam))
        # ---- regions
        self.reg_rows = []
        for reg, aliases in al['regions'].items():
            self.reg_rows.append((norm_key(reg), reg))
            for a in aliases:
                self.reg_rows.append((norm_key(a), reg))
        self.reg_stats = {r[0]: r[1] for r in con.execute("select region, count(*) from deals group by 1").fetchall()}
        # ---- companies & brokers
        self.co = con.execute(
            """select p.inn, p.name, p.region, p.role, p.activity,
                      coalesce(s.n,0) as deals_as_seller, coalesce(b.n,0) as deals_as_buyer
               from participants p
               left join (select seller_inn inn, count(*) n from deals group by 1) s on s.inn=p.inn
               left join (select buyer_inn inn, count(*) n from deals group by 1) b on b.inn=p.inn""").fetchall()
        self.co_keys = [_co_key(r[1]) for r in self.co]
        self.co_by_inn = {r[0]: r for r in self.co}
        self.br = con.execute("select broker_code, name, inn, region from brokers").fetchall()
        self.br_keys = [_co_key(r[1]) for r in self.br]
        self.contract_ids = {r[0] for r in con.execute("select contract_id from contracts").fetchall()}
        con.close()
        self._prod_keys = [k for k, _ in self.prod_rows]
        self._reg_keys = [k for k, _ in self.reg_rows]

    # ------------------------------------------------------------------
    def _best(self, q, keys, rows, limit, cutoff):
        res = process.extract(q, keys, scorer=fuzz.WRatio, limit=60, score_cutoff=cutoff)
        out, seen = [], set()
        for key, score, idx in res:
            val = rows[idx][1]
            if val in seen:
                continue
            seen.add(val)
            # exact-word containment bonus
            out.append((val, score, key))
            if len(out) >= limit:
                break
        return out

    def products(self, text, limit=5):
        q = norm_key(text)
        if not q:
            return []
        exact = [fam for k, fam in self.prod_rows if k == q]
        res = []
        if exact:
            res.append({'product_family': exact[0], 'score': 100, 'match': 'exact'})
        for fam, score, key in self._best(q, self._prod_keys, self.prod_rows, limit + 2, 70):
            if fam != (exact[0] if exact else None):
                res.append({'product_family': fam, 'score': round(score), 'matched_on': key})
        # word-level containment (e.g. "хлопок" inside "хлопок сырец спот")
        qt = set(q.split())
        for k, fam in self.prod_rows:
            if qt and qt <= set(k.split()) and all(r['product_family'] != fam for r in res):
                res.append({'product_family': fam, 'score': 80, 'matched_on': k})
        res = sorted(res, key=lambda r: -r['score'])
        if exact:
            res = [r for r in res if r['score'] >= 95]
        res = res[:limit]
        for r in res:
            hs, n = self.fam_stats[r['product_family']]
            r['hs_code'] = hs
            r['deals'] = n
        return res

    def regions(self, text, limit=3):
        q = norm_key(text)
        out = []
        for fam, score, key in self._best(q, self._reg_keys, self.reg_rows, limit + 2, 72):
            out.append({'region': fam, 'score': round(score), 'matched_on': key, 'deals': self.reg_stats.get(fam, 0)})
        return out[:limit]

    def companies(self, text, limit=8):
        t = text.strip()
        m = re.search(r'\b(\d{9})\b', t)
        if m and m.group(1) in self.co_by_inn:
            r = self.co_by_inn[m.group(1)]
            return [self._co_dict(r, 100)]
        q = _co_key(t)
        if not q:
            return []
        res = process.extract(q, self.co_keys, scorer=fuzz.WRatio, limit=limit, score_cutoff=78)
        # also token containment for short queries
        out = [self._co_dict(self.co[i], round(s)) for _, s, i in res]
        return out

    def _co_dict(self, r, score):
        return {'inn': r[0], 'name': r[1], 'region': r[2], 'role': r[3], 'activity': r[4],
                'deals_as_seller': r[5], 'deals_as_buyer': r[6], 'score': score}

    def brokers(self, text, limit=5):
        m = re.search(r'\bbk\s*0*(\d{1,3})\b', text.lower())
        if m:
            code = 'BK%03d' % int(m.group(1))
            for r in self.br:
                if r[0] == code:
                    return [{'broker_code': r[0], 'name': r[1], 'inn': r[2], 'region': r[3], 'score': 100}]
        q = _co_key(re.sub(r'(?i)брокер|broker|brokeri|броке[рр]', ' ', text))
        res = process.extract(q or _co_key(text), self.br_keys, scorer=fuzz.WRatio, limit=limit, score_cutoff=75)
        return [{'broker_code': self.br[i][0], 'name': self.br[i][1], 'inn': self.br[i][2], 'region': self.br[i][3], 'score': round(s)}
                for _, s, i in res]

    def contract(self, text):
        m = re.search(r'\b(\d{6})\b', text)
        if m and m.group(1) in self.contract_ids:
            return [{'contract_id': m.group(1), 'score': 100}]
        return []

    def resolve(self, kind, text):
        kind = (kind or '').lower()
        fn = {'product': self.products, 'region': self.regions, 'company': self.companies, 'broker': self.brokers,
              'contract': self.contract}.get(kind)
        if not fn:
            return {'error': "kind must be one of product|region|company|broker|contract"}
        c = fn(text)
        return {'query': text, 'kind': kind, 'candidates': c,
                'note': 'no match found in the data' if not c else 'best candidates first; use exact values in SQL filters'}


_idx = None


def get_index():
    global _idx
    if _idx is None:
        _idx = EntityIndex()
    return _idx
