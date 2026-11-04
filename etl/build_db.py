"""Build data/uzex.duckdb from uzex_spot_data/*.csv.   Run: python -X utf8 -I etl/build_db.py"""
import os, re, sys, collections
import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from etl.normalize import norm_key, norm_sort, norm_class

SRC = os.path.join(ROOT, 'uzex_spot_data')
DB = os.path.join(ROOT, 'data', 'uzex.duckdb')
if os.path.exists(DB):
    os.remove(DB)
con = duckdb.connect(DB)
P = lambda f: os.path.join(SRC, f).replace('\\', '/')

REGION_RU2UZ = {
    'г. Ташкент': 'Toshkent shahri', 'Ташкентская область': 'Toshkent viloyati', 'Наманганская область': 'Namangan viloyati',
    'Самаркандская область': 'Samarqand viloyati', 'Бухарская область': 'Buxoro viloyati', 'Ферганская область': 'Farg‘ona viloyati',
    'Хорезмская область': 'Xorazm viloyati', 'Кашкадарьинская область': 'Qashqadaryo viloyati', 'Навоийская область': 'Navoiy viloyati',
    'Сырдарьинская область': 'Sirdaryo viloyati', 'Андижанская область': 'Andijon viloyati', 'Сурхандарьинская область': 'Surxondaryo viloyati',
    'Джизакская область': 'Jizzax viloyati', 'Республика Каракалпакстан': 'Qoraqalpog‘iston Respublikasi',
}

files = ','.join("'" + P(f'deals_{y}.csv') + "'" for y in range(2022, 2027))
con.execute(f"create table raw_deals as select * from read_csv([{files}], header=true, all_varchar=true)")
for name, f in [('contracts', 'contracts.csv'), ('participants', 'participants.csv'), ('brokers', 'brokers.csv'), ('rates', 'usd_rates.csv')]:
    con.execute(f"create table raw_{name} as select * from read_csv('{P(f)}', header=true, all_varchar=true)")

# ---------- contracts: product family + normalised attributes ----------
c = con.execute("select * from raw_contracts").fetchdf()


def strip_form(n):
    return re.sub(r'\s*\((спот|форвард|фьючерс)\)', '', n or '', flags=re.I).strip()


c['base_name'] = c['Наименование продукта'].map(lambda n: re.sub(r'\s+', ' ', strip_form(n)).lower())


def family_key(row):
    hs = row['Код ТН ВЭД']
    if hs == '271019':
        return hs + ('-mazut' if 'мазут' in row['base_name'] else '-diesel')
    return hs


c['family_key'] = c.apply(family_key, axis=1)
canon = {}
for fk, g in c.groupby('family_key'):
    cnt = collections.Counter(g['base_name'])
    canon[fk] = min([n for n, _ in cnt.most_common(3)], key=len)
canon.update({
    '520100': 'хлопок-сырец', '110100': 'мука пшеничная', '151229': 'масло хлопковое', '271012': 'бензин автомобильный',
    '310210': 'карбамид', '100199': 'пшеница продовольственная', '100630': 'рис шлифованный', '440711': 'пиломатериалы',
    '252329': 'портландцемент', '271112': 'сжиженный газ', '230610': 'шрот хлопковый', '520512': 'пряжа хлопчатобумажная',
    '740311': 'катод медный', '151219': 'масло подсолнечное', '310230': 'аммиачная селитра', '391721': 'трубы полиэтиленовые',
    '220190': 'вода питьевая', '721420': 'арматура стальная', '760421': 'профиль алюминиевый', '271320': 'битум нефтяной',
    '690410': 'кирпич керамический', '700529': 'стекло листовое', '271019-diesel': 'дизельное топливо', '271019-mazut': 'мазут топочный',
    '250100': 'соль пищевая', '252020': 'гипс строительный', '320810': 'эмаль', '230990': 'комбикорм', '280700': 'серная кислота',
    '170199': 'сахар белый', '252210': 'известь негашеная', '390120': 'полиэтилен', '390210': 'полипропилен',
})
c['product_family'] = c['family_key'].map(lambda k: canon[k][:1].upper() + canon[k][1:])


def attrs_text(r):
    return ' '.join(str(r[k]) for k in ['Наименование продукта', 'Марка товара', 'Размер товара', 'Сорт товара', 'Тип товара', 'Класс товара'] if r[k] and str(r[k]) != 'nan')


txt = c.apply(attrs_text, axis=1)
c['grade_norm'] = [norm_sort(t) for t in txt]
c['class_norm'] = [norm_class(t) for t in txt]
c['region_norm'] = c['Регион'].map(lambda r: REGION_RU2UZ.get(r, r))
con.register('c_df', c)
con.execute("""create table contracts as select
  cast("Номер контракта" as varchar) contract_id,
  "Наименование продукта" product_name_raw, product_family, family_key, "Код ТН ВЭД" hs_code,
  nullif("Марка товара",'') brand, nullif("Размер товара",'') as "size", nullif("Сорт товара",'') grade_raw, nullif("Тип товара",'') subtype,
  nullif("Класс товара",'') class_raw, nullif(grade_norm,'') grade, nullif(class_norm,'') as "class",
  "Группа товара" product_group, "Категория товара" category, "Отрасль промышленности" industry,
  "Единица измерения" unit, cast("Лот" as integer) lot_size, "Валюта" currency, cast("Базисная цена" as double) base_price,
  cast(replace(replace("Сумма залога",'%',''),' ','') as double) deposit_pct, "Базис поставки" delivery_basis, "Упаковка" packaging,
  region_norm region, "Регион" region_raw, "Адрес склада" warehouse_address, "Тип торгов" trade_type, "Тип контракта" contract_type,
  "Форма контракта" contract_form, cast("Срок оплаты" as integer) payment_term_days, cast("Срок поставки" as integer) delivery_term_days,
  "ИНН продавца" seller_inn, strptime("Дата регистрации",'%d.%m.%Y')::date registered_on, strptime("Действует до",'%d.%m.%Y')::date valid_until
  from c_df""")

# ---------- participants / brokers / rates ----------
p = con.execute('select * from raw_participants').fetchdf()
p['name_key'] = p['Наименование'].map(norm_key)
con.register('p_df', p)
con.execute("""create table participants as select "ИНН" inn, "Наименование" name, name_key, "Регион" region, "Вид деятельности" activity,
  "Роль" role, ("Плательщик НДС"='Да') vat_payer from p_df""")
b = con.execute('select * from raw_brokers').fetchdf()
b['name_key'] = b['Наименование'].map(norm_key)
con.register('b_df', b)
con.execute('create table brokers as select "Код брокера" broker_code, "Наименование" name, name_key, "ИНН" inn, "Регион" region from b_df')
con.execute("""create table usd_rates as select strptime("Дата",'%d.%m.%Y')::date rate_date, cast("Курс" as double) uzs_per_usd from raw_rates""")

# ---------- deals ----------
con.execute("""create table deals as select
  cast("Номер сделки" as bigint) deal_id,
  strptime("Дата сделки",'%d.%m.%Y')::date deal_date,
  cast("Время сделки" as time) deal_time,
  "Тип торгов" trade_type, cast("Количество" as bigint) quantity_lots,
  cast(replace(replace("Сумма сделки",' ',''),chr(160),'') as double) amount,
  cast(replace(replace("Стартовая цена",' ',''),chr(160),'') as double) start_price,
  cast("Номер контракта" as varchar) contract_id, "Наименование товара" product_name_deal,
  cast("Лот" as integer) lot_size, "Единица измерения" unit, "Регион" region,
  "Тип контракта" contract_type, "Форма контракта" contract_form, "Состояние сделки" status,
  "ИНН продавца" seller_inn, "ИНН покупателя" buyer_inn, "Брокер продавца" seller_broker, "Брокер покупателя" buyer_broker,
  try_strptime(nullif("Дата оплаты",''),'%d.%m.%Y')::date paid_on, try_strptime(nullif("Дата поставки",''),'%d.%m.%Y')::date delivered_on,
  cast(nullif("Поставлено",'') as bigint) delivered_lots
  from raw_deals""")

con.execute("""create view deals_enriched as select
  d.deal_id, d.deal_date, d.deal_time, year(d.deal_date) as year, month(d.deal_date) as month, quarter(d.deal_date) as quarter,
  strftime(d.deal_date,'%Y-%m') year_month, dayname(d.deal_date) weekday, hour(d.deal_time) as hour,
  d.trade_type, d.contract_type, d.contract_form, d.status,
  (d.status <> 'Аннулирован(Не оплачен)') is_successful, (d.status = 'Аннулирован(Не оплачен)') is_annulled,
  d.contract_id, c.product_family, c.product_name_raw, d.product_name_deal, c.hs_code, c.product_group, c.category, c.industry,
  c.brand, c."size" as "size", c.grade, c."class" as "class", c.subtype, c.packaging, c.delivery_basis, c.deposit_pct,
  d.quantity_lots, d.lot_size, d.unit, d.quantity_lots * d.lot_size volume_units,
  c.currency, d.amount, d.start_price,
  d.amount / (d.quantity_lots * d.lot_size) unit_price,
  r.uzs_per_usd usd_rate,
  case when c.currency = 'Доллар США' then d.amount * r.uzs_per_usd else d.amount end amount_uzs,
  case when c.currency = 'Доллар США' then d.amount else d.amount / r.uzs_per_usd end amount_usd,
  d.region, d.seller_inn, sp.name seller_name, sp.region seller_region, sp.activity seller_activity,
  d.buyer_inn, bp.name buyer_name, bp.region buyer_region, bp.activity buyer_activity,
  d.seller_broker, sb.name seller_broker_name, d.buyer_broker, bb.name buyer_broker_name,
  d.paid_on, d.delivered_on, d.delivered_lots, d.delivered_lots * d.lot_size delivered_units,
  d.quantity_lots - coalesce(d.delivered_lots, 0) undelivered_lots,
  date_diff('day', d.deal_date, d.paid_on) payment_lag_days, date_diff('day', d.paid_on, d.delivered_on) delivery_lag_days,
  c.payment_term_days, c.delivery_term_days
  from deals d
  join contracts c on c.contract_id = d.contract_id
  join usd_rates r on r.rate_date = d.deal_date
  left join participants sp on sp.inn = d.seller_inn
  left join participants bp on bp.inn = d.buyer_inn
  left join brokers sb on sb.broker_code = d.seller_broker
  left join brokers bb on bb.broker_code = d.buyer_broker""")

# ---------- integrity checks ----------
n_raw = con.execute('select count(*) from deals').fetchone()[0]
n_enr = con.execute('select count(*) from deals_enriched').fetchone()[0]
per_year = dict(con.execute("select year(deal_date), count(*) from deals group by 1 order by 1").fetchall())
exp = {2022: 84299, 2023: 93985, 2024: 106647, 2025: 115763, 2026: 99306}
assert n_raw == 500000, n_raw
assert n_enr == n_raw, ('join fan-out/loss', n_enr, n_raw)
assert per_year == exp, per_year
assert con.execute('select count(*) from deals where amount is null or deal_date is null').fetchone()[0] == 0
print('OK', n_raw, per_year)
for t in ['deals', 'contracts', 'participants', 'brokers', 'usd_rates']:
    con.execute(f'create index if not exists idx_{t}_noop on {t}(1)') if False else None
for t in ['raw_deals', 'raw_contracts', 'raw_participants', 'raw_brokers', 'raw_rates']:
    con.execute(f'drop table {t}')
con.close()
