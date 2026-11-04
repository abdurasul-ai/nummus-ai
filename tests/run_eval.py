"""Run the agent on tests/golden.yaml.  Needs ANTHROPIC_API_KEY.   python -X utf8 tests/run_eval.py [--n 10]"""
import json
import os
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from agent.agent import answer  # noqa: E402

REFUSE = re.compile(r'нет|не найден|отсутств|не содерж|нельзя|не могу|yo.q|topilmad|mavjud emas|kiritilmagan|no data|not in|can.t|cannot|не буду|не могу', re.I)


def squash(s):
    return re.sub(r'[\s  ]', '', s).replace(',', '.')


def run(item):
    t = time.time()
    try:
        r = answer(item['q'])
    except Exception as e:  # noqa: BLE001
        return item, {'answer': f'ERROR {e}', 'unverified': [], 'steps': []}, time.time() - t
    return item, r, time.time() - t


def main():
    G = yaml.safe_load(open(os.path.join(ROOT, 'tests', 'golden.yaml'), encoding='utf8'))
    n = int(sys.argv[sys.argv.index('--n') + 1]) if '--n' in sys.argv else len(G)
    with ThreadPoolExecutor(4) as ex:
        results = list(ex.map(run, G[:n]))
    ok = tot = halluc = 0
    lat = []
    rows = []
    for item, r, dt in results:
        a = r['answer']
        lat.append(dt)
        if item.get('unanswerable'):
            good = bool(REFUSE.search(a)) and not r['unverified']
        elif item['expect']:
            sq = squash(a)
            good = all(squash(e) in sq for e in item['expect'])
        else:
            good = None   # manual
        if good is not None:
            tot += 1
            ok += int(good)
        if r['unverified']:
            halluc += 1
        rows.append({'q': item['q'], 'cat': item['cat'], 'pass': good, 'sec': round(dt, 1), 'unverified': r['unverified'], 'answer': a[:400]})
        print(('PASS' if good else 'MANUAL' if good is None else 'FAIL'), f'{dt:5.1f}s', item['q'])
    print(f'\naccuracy {ok}/{tot}  unverified-number answers {halluc}  p50 {statistics.median(lat):.1f}s  p95 {sorted(lat)[int(len(lat) * .95) - 1]:.1f}s')
    json.dump(rows, open(os.path.join(ROOT, 'tests', 'last_eval.json'), 'w', encoding='utf8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
