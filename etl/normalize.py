"""Text normalisation helpers shared by ETL and the entity resolver."""
import re

_CYR = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo', 'ж': 'j', 'з': 'z', 'и': 'i', 'й': 'y',
    'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f',
    'х': 'x', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sh', 'ъ': '', 'ы': 'i', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    'ў': 'o', 'қ': 'q', 'ғ': 'g', 'ҳ': 'h', 'ҷ': 'j', 'ӣ': 'i',
}
_APOS = dict.fromkeys(map(ord, "ʻʼ’‘`´'ʹ′"), None)


def translit(s: str) -> str:
    """Cyrillic (RU/UZ) -> compact Latin key. Lossy but consistent, used only for matching."""
    s = (s or '').lower().translate(_APOS)
    return ''.join(_CYR.get(ch, ch) for ch in s)


def norm_key(s: str) -> str:
    """Lowercase, transliterate, drop quotes/punctuation, collapse spaces."""
    t = re.sub(r'[^0-9a-z]+', ' ', translit(s))
    return re.sub(r'\s+', ' ', t).strip()


_B = r'(?<![a-zа-я0-9])'
_E = r'(?![a-zа-я0-9])'


def norm_sort(txt: str) -> str:
    t = (txt or '').lower()
    if 'сорт' not in t and 'в/с' not in t:
        return ''
    if re.search(r'высш|в/с', t):
        return 'высший'
    if re.search(_B + r'(iii|3|третий|третьего)' + _E, t):
        return '3'
    if re.search(_B + r'(ii|2|второй|второго)' + _E, t):
        return '2'
    if re.search(_B + r'(i|1|первый|первого)' + _E, t):
        return '1'
    return ''


def norm_class(txt: str) -> str:
    t = (txt or '').lower()
    if 'класс' not in t:
        return ''
    for pat, v in ((r'(iv|4)', '4'), (r'(iii|3)', '3'), (r'(ii|2)', '2'), (r'(i|1)', '1')):
        if re.search(_B + pat + _E, t):
            return v
    return ''
