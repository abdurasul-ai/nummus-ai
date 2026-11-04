"""Answer-language enforcement.

The registry stores Russian terms (products, statuses, trade types, units ...) and Uzbek region names.
The model copies exact data values (so every name stays verifiable); this module then localises them so that a
Russian question gets a Russian-only answer and an Uzbek question an Uzbek-only answer.
Company / broker names, INNs and codes are never touched."""
import re

CYR = re.compile(r'[а-яёА-ЯЁўқғҳЎҚҒҲ]')
LAT = re.compile(r'[A-Za-z]')
UZ_CYR = re.compile(r'[ўқғҳЎҚҒҲ]')
EN_WORDS = re.compile(r'\b(the|what|how|which|compare|ignore|invent|your|please|show|who|list|total|and|of|is|are|does|did|won|forward|contract|many|much)\b', re.I)


def detect_lang(q: str) -> str:
    """'ru' | 'uz' | 'en'.  Uzbek Cyrillic is answered in Uzbek Latin."""
    if UZ_CYR.search(q or ''):
        return 'uz'
    c, l = len(CYR.findall(q or '')), len(LAT.findall(q or ''))
    if c > l:
        return 'ru'
    if l and len(EN_WORDS.findall(q or '')) >= 1:
        return 'en'
    return 'uz'


# ---------- Russian data value -> Uzbek (Latin) ----------
PRODUCTS_UZ = {
    'Хлопок-сырец': 'Paxta xom ashyosi', 'Хлопок сырец': 'Paxta xom ashyosi', 'Мука пшеничная': 'Bug‘doy uni',
    'Портландцемент': 'Portlandsement', 'Пшеница продовольственная': 'Oziq-ovqatbop bug‘doy', 'Масло хлопковое': 'Paxta moyi',
    'Бензин автомобильный': 'Avtomobil benzini', 'Рис шлифованный': 'Silliqlangan guruch', 'Пиломатериалы': 'Arralangan yog‘och',
    'Шрот хлопковый': 'Paxta kunjarasi', 'Карбамид': 'Karbamid', 'Сжиженный газ': 'Suyultirilgan gaz', 'Битум нефтяной': 'Neft bitumi',
    'Эмаль': 'Emal', 'Вода питьевая': 'Ichimlik suvi', 'Аммиачная селитра': 'Ammiakli selitra', 'Пряжа хлопчатобумажная': 'Paxta ipi',
    'Арматура стальная': 'Po‘lat armatura', 'Полипропилен': 'Polipropilen', 'Трубы полиэтиленовые': 'Polietilen quvurlar',
    'Гипс строительный': 'Qurilish gipsi', 'Кирпич керамический': 'Keramik g‘isht', 'Стекло листовое': 'List oynasi',
    'Масло подсолнечное': 'Kungaboqar moyi', 'Полиэтилен': 'Polietilen', 'Лист стальной горячекатаный': 'Issiq prokatlangan po‘lat list',
    'Мазут топочный': 'Mazut', 'Дизельное топливо': 'Dizel yoqilg‘isi', 'Профиль алюминиевый': 'Alyuminiy profil',
    'Катод медный': 'Mis katodi', 'Поливинилхлорид': 'Polivinilxlorid', 'Комбикорм': 'Omixta yem', 'Аргон газообразный': 'Gazsimon argon',
    'Подшипник': 'Podshipnik', 'Известь негашеная': 'So‘ndirilmagan ohak', 'Сахар белый': 'Oq shakar', 'Кабель силовой': 'Kuch kabeli',
    'Проволока арматурная': 'Armatura simi', 'Азот': 'Azot', 'Серная кислота': 'Sulfat kislota', 'Соль пищевая': 'Oziq-ovqat tuzi',
    'Сода каустическая': 'Kaustik soda',
}
TERMS_UZ = {
    # statuses
    'Аннулирован(Не оплачен)': 'Bekor qilingan (to‘lanmagan)', 'Исполнен(Частично)': 'Qisman bajarilgan', 'Исполнен': 'Bajarilgan',
    'Ждёт оплату': 'To‘lov kutilmoqda', 'Оплачен': 'To‘langan', 'Заключен': 'Tuzilgan', 'Не подписан': 'Imzolanmagan', 'Новый': 'Yangi',
    # trade / contract
    'Английский аукцион': 'Ingliz auksioni', 'Обратный аукцион': 'Teskari auksion', 'Двусторонний аукцион': 'Ikki tomonlama auksion',
    'Внутренний': 'Ichki', 'Экспортный': 'Eksport', 'Спот': 'Spot', 'Форвард': 'Forvard', 'Фьючерс': 'Fyuchers',
    # units / currency
    'килограмм': 'kilogramm', 'тонна': 'tonna', 'литр': 'litr', 'штука': 'dona', 'куб.метр': 'kub metr', 'кв.метр': 'kvadrat metr',
    'метр': 'metr', 'Узбекский сум': 'O‘zbek so‘mi', 'Доллар США': 'AQSh dollari',
    # classification
    'Высоколиквидные товары': 'Yuqori likvidli tovarlar', 'Прочие товары': 'Boshqa tovarlar',
    'Сельскохозяйственная продукция': 'Qishloq xo‘jaligi mahsulotlari', 'Продовольственные товары': 'Oziq-ovqat tovarlari',
    'Нефтепродукты': 'Neft mahsulotlari', 'Строительные материалы': 'Qurilish materiallari', 'Химическая продукция': 'Kimyo mahsulotlari',
    'Полимерная продукция': 'Polimer mahsulotlari', 'Металлопродукция': 'Metall mahsulotlari', 'Промышленные товары': 'Sanoat tovarlari',
    'Сельское хозяйство': 'Qishloq xo‘jaligi', 'Пищевая промышленность': 'Oziq-ovqat sanoati', 'Нефтегазовая промышленность': 'Neft-gaz sanoati',
    'Строительная индустрия': 'Qurilish industriyasi', 'Химическая промышленность': 'Kimyo sanoati', 'Металлургия': 'Metallurgiya',
    'Лесная промышленность': 'O‘rmon sanoati', 'Текстильная промышленность': 'To‘qimachilik sanoati', 'Машиностроение': 'Mashinasozlik',
    'Электротехническая промышленность': 'Elektrotexnika sanoati',
    'Торговая компания': 'Savdo kompaniyasi', 'Перерабатывающее предприятие': 'Qayta ishlash korxonasi', 'Транспортная компания': 'Transport kompaniyasi',
    'Производственное предприятие': 'Ishlab chiqarish korxonasi', 'Строительная компания': 'Qurilish kompaniyasi', 'Производитель': 'Ishlab chiqaruvchi',
    'Кластер': 'Klaster', 'Продавец': 'Sotuvchi', 'Покупатель': 'Xaridor',
    'навалом': 'quyma holda',
}
# ---------- Uzbek region (as stored) -> Russian ----------
REGIONS_RU = {
    'Qoraqalpog‘iston Respublikasi': 'Республика Каракалпакстан', 'Toshkent shahri': 'г. Ташкент', 'Toshkent viloyati': 'Ташкентская область',
    'Namangan viloyati': 'Наманганская область', 'Samarqand viloyati': 'Самаркандская область', 'Buxoro viloyati': 'Бухарская область',
    'Farg‘ona viloyati': 'Ферганская область', 'Xorazm viloyati': 'Хорезмская область', 'Qashqadaryo viloyati': 'Кашкадарьинская область',
    'Navoiy viloyati': 'Навоийская область', 'Sirdaryo viloyati': 'Сырдарьинская область', 'Andijon viloyati': 'Андижанская область',
    'Surxondaryo viloyati': 'Сурхандарьинская область', 'Jizzax viloyati': 'Джизакская область',
}


def _compile(d, flags=0):
    keys = sorted(d, key=len, reverse=True)
    return re.compile('|'.join(re.escape(k) for k in keys), flags)


_RE_UZ_PROD = _compile(PRODUCTS_UZ, re.I)
_RE_UZ_TERMS = _compile({k: v for k, v in TERMS_UZ.items() if len(k) > 4})
_RE_UZ_SHORT = re.compile(r'(?<![А-Яа-яЁё])(%s)(?![А-Яа-яЁё])' % '|'.join(re.escape(k) for k in TERMS_UZ if len(k) <= 4))
_APOS = "[‘’ʻʼ'`]"
_RE_RU_REG = re.compile('|'.join(re.escape(k).replace('‘', _APOS) for k in sorted(REGIONS_RU, key=len, reverse=True)))
_PROD_LOWER = {k.lower(): v for k, v in PRODUCTS_UZ.items()}
_REG_FIX = {k.replace('‘', "'"): v for k, v in REGIONS_RU.items()}


def _prod(m):
    src = m.group(0)
    out = _PROD_LOWER.get(src.lower(), src)
    return out[:1].lower() + out[1:] if src[:1].islower() else out


def to_uzbek(text: str) -> str:
    text = _RE_UZ_PROD.sub(_prod, text)
    text = _RE_UZ_TERMS.sub(lambda m: TERMS_UZ[m.group(0)], text)
    text = _RE_UZ_SHORT.sub(lambda m: TERMS_UZ[m.group(0)], text)
    return text


def to_russian(text: str) -> str:
    def sub(m):
        key = re.sub(_APOS, '‘', m.group(0))
        return REGIONS_RU.get(key, m.group(0))
    return _RE_RU_REG.sub(sub, text)


_UZ_FIX = [
    (re.compile(r'\b(?:an+ul+at?siya\w*|annulyatsiya\w*)', re.I), 'bekor qilingan'),
    (re.compile(r'\bsuksess\w*', re.I), 'muvaffaqiyatli'),
    (re.compile(r'\bsum\b'), 'so‘m'),
    (re.compile(r'\bregion\b', re.I), 'hudud'),
    (re.compile(r'\bunit\b'), 'o‘lchov birligi'),
    (re.compile(r'\bstatus\b', re.I), 'holat'),
    (re.compile(r'\bamount\b'), 'summa'),
]
_RU_FIX = [
    (re.compile(r'\bregion\b', re.I), 'регион'),
    (re.compile(r'\bunit\b'), 'единице измерения'),
    (re.compile(r'\bstatus\b'), 'статус'),
    (re.compile(r'\bamount\b'), 'сумма'),
    (re.compile(r'\bcurrency\b'), 'валюта'),
    (re.compile(r'по полю\s+'), 'по '),
    (re.compile(r'(?:в|из)\s+таблиц\w*\s+реестр\w*\s+сделок'), 'в реестре сделок'),
    (re.compile(r'таблиц\w*\s+реестр\w*\s+сделок'), 'реестр сделок'),
]


def localize(text: str, lang: str) -> str:
    if not text:
        return text
    text = text.replace('‑', '-').replace('‐', '-')
    if lang == 'uz':
        text = to_uzbek(text)
        for rx, rep in _UZ_FIX:
            text = rx.sub(rep, text)
        return text
    if lang == 'ru':
        text = to_russian(text)
        for rx, rep in _RU_FIX:
            text = rx.sub(rep, text)
        return text
    return text


_META = re.compile(
    r"(nimalar(ni)?\s+bil(asan|ishing)|qanday\s+savol|nima\s+qila\s+olasan|nimaga\s+qodirsan|kim\s+san|o'zingni\s+tanishtir|o‘zingni\s+tanishtir|imkoniyat|"
    r"что\s+(ты\s+)?(умеешь|можешь|знаешь)|на\s+какие\s+вопросы|какие\s+вопросы|кто\s+ты|расскажи\s+о\s+себе|"
    r"what\s+can\s+you|what\s+do\s+you\s+know|who\s+are\s+you)", re.I)

_CAPS = {
 'uz': ("Men faqat UZEX birja bitimlari reyestri ma’lumotlari asosida javob beraman (2022-01-03 dan 2026-10-30 gacha).\n\n"
  "**Nimalar bo‘yicha savol berishingiz mumkin:**\n"
  "- Bitimlar soni, aylanma (so‘m va AQSh dollarida), hajm va o‘rtacha narx\n"
  "- Mahsulotlar va mahsulot guruhlari bo‘yicha reytinglar\n"
  "- Hududlar (viloyatlar) kesimidagi savdo\n"
  "- Kompaniyalar (sotuvchi va xaridorlar) va brokerlar faoliyati\n"
  "- Savdo turlari, shartnoma turlari va bitim holatlari (muvaffaqiyatli va bekor qilingan)\n"
  "- Oy, chorak va yillar bo‘yicha dinamika va davrlarni taqqoslash\n\n"
  "**Savol namunalari:**\n"
  "- 2025 yilda eng ko‘p savdo qilingan 5 ta mahsulot qaysi?\n"
  "- Xorazm viloyatida 2024 yilda nechta bitim bo‘lgan?\n"
  "- Paxta xom ashyosining o‘rtacha narxi 2023 va 2024 yillarda qanday o‘zgargan?\n"
  "- Eng faol broker kim va uning aylanmasi qancha?\n"
  "- Qaysi oyda bekor qilingan bitimlar ko‘p bo‘lgan?\n\n"
  "Ma’lumotlarda yo‘q narsalar (bashorat, yangiliklar, boshqa birjalar) bo‘yicha javob bermayman.",
  "Bu imkoniyatlar tavsifi; bitim ma’lumotlari so‘ralmadi."),
 'ru': ("Я отвечаю только по данным реестра биржевых сделок UZEX (с 2022-01-03 по 2026-10-30).\n\n"
  "**О чём можно спрашивать:**\n"
  "- Количество сделок, оборот (в сумах и долларах США), объёмы и средние цены\n"
  "- Рейтинги по товарам и товарным группам\n"
  "- Торговля в разрезе регионов\n"
  "- Деятельность компаний (продавцов и покупателей) и брокеров\n"
  "- Виды торгов, виды договоров и статусы сделок (успешные и аннулированные)\n"
  "- Динамика по месяцам, кварталам и годам, сравнение периодов\n\n"
  "**Примеры вопросов:**\n"
  "- Какие 5 товаров были самыми продаваемыми в 2025 году?\n"
  "- Сколько сделок было в Хорезмской области в 2024 году?\n"
  "- Как изменилась средняя цена хлопка-сырца в 2023 и 2024 годах?\n"
  "- Какой брокер самый активный и каков его оборот?\n"
  "- В каком месяце было больше всего аннулированных сделок?\n\n"
  "На вопросы вне этих данных (прогнозы, новости, другие биржи) я не отвечаю.",
  "Это описание возможностей; данные сделок не запрашивались."),
 'en': ("I answer only from the UZEX exchange-deal registry (2022-01-03 to 2026-10-30).\n\n"
  "**You can ask about:** deal counts, turnover (UZS/USD), volumes and average prices; rankings of products and product groups; regions; "
  "companies and brokers; trade and contract types; deal statuses; monthly/quarterly/yearly dynamics and period comparisons.\n\n"
  "**Examples:**\n- Which 5 products had the highest turnover in 2025?\n- How many deals were made in Khorezm in 2024?\n"
  "- Who is the most active broker?\n\nI do not answer anything outside this data (forecasts, news, other exchanges).",
  "This is a description of capabilities; no deal data was queried."),
}


def meta_answer(question: str):
    """Canned, data-free answer to 'what can you do' questions, or None."""
    if len(question) < 160 and _META.search(question or ''):
        a, b = _CAPS[detect_lang(question)]
        return a, b
    return None


_DEF = re.compile(
    r"(farqi\s+nima|farq\s+qiladi|nima\s+degani|nima\s+degani|^(uzex|birja)[\w'‘’ ]{0,20}\s+nima\s*\??\s*$|"
    r"что\s+такое|что\s+значит|в\s+чём\s+разница|в\s+чем\s+разница|чем\s+отличается|как\s+работает|"
    r"what\s+is\b|what\s+are\b|difference\s+between|how\s+does)", re.I)
_REFUSE = {
 'uz': ("Bu savol atamalarni tushuntirishni so‘rayapti, bitimlar ma’lumotlarini emas. Men faqat birja bitimlari reyestridagi ma’lumotlarga tayanaman va tashqi bilimlardan foydalanmayman, shuning uchun ta’rif bera olmayman.\n\n"
  "Reyestr asosida, masalan, quyidagilarni ko‘rsata olaman:\n- savdo turlari bo‘yicha bitimlar soni va aylanma\n- mahsulot yoki hudud bo‘yicha reytinglar\n- narxlar dinamikasi",
  "Bu ta’rif so‘rovi; bitim ma’lumotlari so‘ralmadi."),
 'ru': ("Этот вопрос просит объяснить термин, а не показать данные о сделках. Я опираюсь только на реестр биржевых сделок и не использую внешние знания, поэтому определений не даю.\n\n"
  "По реестру могу показать, например:\n- число сделок и оборот по видам торгов\n- рейтинги по товарам или регионам\n- динамику цен",
  "Это запрос определения; данные сделок не запрашивались."),
 'en': ("This asks me to explain a term rather than report deal data. I rely only on the exchange-deal registry and use no outside knowledge, so I cannot give definitions.\n\n"
  "From the registry I can show, for example:\n- deal counts and turnover by trade type\n- rankings by product or region\n- price dynamics",
  "This is a definition request; no deal data was queried."),
}
_old_meta = meta_answer


def meta_answer(question: str):  # noqa: F811
    r = _old_meta(question)
    if r:
        return r
    q = (question or '').strip()
    if len(q) < 140 and not re.search(r'\d', q) and _DEF.search(q):
        return _REFUSE[detect_lang(q)]
    return None
