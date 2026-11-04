"""Telegram front-end sharing the same agent.  Run: python -X utf8 -m app.telegram_bot   (needs TELEGRAM_BOT_TOKEN)"""
import asyncio
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update  # noqa: E402
from telegram.constants import ChatAction  # noqa: E402
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters  # noqa: E402

from app.main import run_question, warm  # noqa: E402

LAST: dict = {}   # chat_id -> last result
HIST: dict = {}   # chat_id -> short history

WELCOME = """👋 <b>Assalomu alaykum! Men NummusAI — birja bitimlari bo‘yicha yordamchiman.</b>

📊 <b>Nimalarni bilaman:</b> 2022-yil 3-yanvardan 2026-yil 30-oktabrgacha bo‘lgan ~500 000 ta bitim, shartnomalar, kompaniyalar, brokerlar va dollar kursi.

✍️ Savolni <b>o‘zbek</b> (lotin yoki kirill) yoki <b>rus</b> tilida yozing.
✅ Faqat ma’lumotlardagi raqam, nom va kodlar bilan javob beraman. Ma’lumot bo‘lmasa — ochiq aytaman, o‘ylab topmayman.
🔎 Har javob ostidagi <b>«Asos»</b> tugmasi — javob qaysi so‘rov bilan olinganini ko‘rsatadi.

━━━━━━━━━━

👋 <b>Здравствуйте! Я NummusAI — агент по данным биржевых сделок.</b>

📊 <b>Что знаю:</b> ~500 000 сделок с 03.01.2022 по 30.10.2026, контракты, компании, брокеры и курс доллара.

✍️ Пишите вопрос по-<b>русски</b> или по-<b>узбекски</b> (латиница или кириллица).
✅ Отвечаю только по данным: цифры, названия и коды — из реестра. Если данных нет — скажу прямо, ничего не выдумываю.
🔎 Кнопка <b>«Основа»</b> под ответом показывает, каким запросом получен результат.

👇 <b>Попробуйте / Sinab ko‘ring:</b>"""

EXAMPLES = [
    "2025-yilda nechta bitim tuzilgan?",
    "Топ-5 продавцов по обороту в 2024 году",
    "Paxta xom ashyosi bo‘yicha qaysi viloyat yetakchi?",
    "Какая доля сделок аннулирована?",
]


def to_html(md: str) -> str:
    """Markdown-ish model text -> Telegram HTML (bold only), safe-escaped."""
    md = re.sub(r'^#{1,6}\s*', '', md or '', flags=re.M)
    md = md.replace('`', '')
    md = md.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return re.sub(r'\*\*(.+?)\*\*', lambda m: '<b>' + m.group(1) + '</b>', md)


def esc(t: str) -> str:
    return (t or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def chunks(s, n=3900):
    while s:
        if len(s) <= n:
            yield s
            return
        cut = s.rfind('\n', 0, n)
        cut = cut if cut > 0 else n
        yield s[:cut]
        s = s[cut:].lstrip('\n')


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(e, callback_data=f'ex:{i}')] for i, e in enumerate(EXAMPLES)])
    await update.message.reply_text(WELCOME, parse_mode='HTML', reply_markup=kb)


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await ask(update.message, (update.message.text or '').strip(), ctx)


async def on_example(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cq = update.callback_query
    await cq.answer()
    try:
        q = EXAMPLES[int(cq.data.split(':')[1])]
    except (ValueError, IndexError):
        return
    await cq.message.reply_text('❓ ' + q)
    await ask(cq.message, q, ctx)


async def ask(message, q, ctx: ContextTypes.DEFAULT_TYPE):
    if not q:
        return
    cid = message.chat_id
    await ctx.bot.send_chat_action(cid, ChatAction.TYPING)
    stop = asyncio.Event()

    async def keep_typing():
        while not stop.is_set():
            await asyncio.sleep(4)
            if not stop.is_set():
                try:
                    await ctx.bot.send_chat_action(cid, ChatAction.TYPING)
                except Exception:  # noqa: BLE001
                    pass

    t = asyncio.create_task(keep_typing())
    try:
        res = await asyncio.get_event_loop().run_in_executor(None, lambda: run_question(q, HIST.get(cid, [])[-4:], None))
    finally:
        stop.set()
        t.cancel()
    LAST[cid] = res
    HIST.setdefault(cid, []).extend([{'role': 'user', 'content': q}, {'role': 'assistant', 'content': res['answer']}])
    text = to_html(res['answer']) + chr(10) * 2 + f"<i>⏱ {res['elapsed']} s</i>"
    parts = list(chunks(text))
    for i, p in enumerate(parts):
        kb = InlineKeyboardMarkup([[InlineKeyboardButton('🔎 Javob asosi / Основа ответа', callback_data='basis')]]) if (i == len(parts) - 1 and res.get('basis')) else None
        try:
            await message.reply_text(p, parse_mode='HTML', reply_markup=kb)
        except Exception:  # noqa: BLE001  (malformed HTML after chunking) -> plain text
            await message.reply_text(re.sub(r'</?[a-z]+>', '', p), reply_markup=kb)


async def on_basis(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cq = update.callback_query
    await cq.answer()
    res = LAST.get(cq.message.chat_id)
    if not res or not res.get('basis'):
        return
    await cq.message.reply_text('🔎 <b>Javob asosi / Основа ответа</b>' + chr(10) * 2 + esc(res['basis']), parse_mode='HTML')


async def on_error(update, ctx: ContextTypes.DEFAULT_TYPE):
    print('bot error:', type(ctx.error).__name__, str(ctx.error)[:120], flush=True)


def main():
    token = os.environ['TELEGRAM_BOT_TOKEN']
    warm()
    app = Application.builder().token(token).concurrent_updates(True).connect_timeout(30).read_timeout(30).write_timeout(30).pool_timeout(30).get_updates_connect_timeout(30).get_updates_read_timeout(40).build()
    app.add_error_handler(on_error)
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', start))
    app.add_handler(CallbackQueryHandler(on_basis, pattern='^basis$'))
    app.add_handler(CallbackQueryHandler(on_example, pattern='^ex:'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
