"""Load .env (if present) into the environment before anything reads keys."""
import os

_p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
if os.path.exists(_p):
    for _l in open(_p, encoding='utf8'):
        _l = _l.strip()
        if _l and not _l.startswith('#') and '=' in _l:
            _k, _v = _l.split('=', 1)
            if _v.strip():
                os.environ.setdefault(_k.strip(), _v.strip().strip('"\''))
