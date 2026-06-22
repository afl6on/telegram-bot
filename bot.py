import telebot, os, requests, schedule, time, threading
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from io import BytesIO

TOKEN = os.environ.get('BOT_TOKEN')
bot = telebot.TeleBot(TOKEN)
CONTRACT = "0x444045b0ee1ee319a660a5e3d604ca0ffa35acaa"
URL = f"https://api.dexscreener.com/latest/dex/tokens/{CONTRACT}"

chat_ids = set()
last_price = None
last_liquidity = None
processed_txs = set()
triggered_targets = set()
daily_stats = {"high":0,"low":float('inf'),"open":None,"volume":0,"whale_alerts":0}
price_history = []
user_custom_alerts = {}
waiting_for_alert = set()

def get_data():
    try:
        r = requests.get(URL, timeout=10).json()
        if r and "pairs" in r and r["pairs"]:
            return max(r["pairs"], key=lambda x: float(x.get("liquidity",{}).get("usd",0) or 0))
    except: pass
    return None

def get_btc():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true", timeout=10).json()
        return r.get("bitcoin", {})
    except: return {}

def fmt(p):
    if p == 0: return "$0"
    return f"${p:.8f}" if p < 0.001 else f"${p:.4f}" if p < 1 else f"${p:.2f}"

def alert(msg):
    for cid in chat_ids:
        try: bot.send_message(cid, msg, parse_mode="HTML", reply_markup=main_menu())
        except: pass

def main_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("💰 السعر الحالي", callback_data="price"),
        InlineKeyboardButton("💧 السيولة", callback_data="liquidity"),
        InlineKeyboardButton("📊 تقرير فوري", callback_data="report"),
        InlineKeyboardButton("📈 رسم بياني", callback_data="chart"),
        InlineKeyboardButton("₿ مقارنة BTC", callback_data="compare"),
        InlineKeyboardButton("🔔 تنبيه مخصص", callback_data="custom_alert"),
        InlineKeyboardButton("📋 تنبيهاتي", callback_data="my_alerts"),
        InlineKeyboardButton("⛔ إيقاف", callback_data="stop"),
    )
    return markup

def generate_chart():
    if len(price_history) < 2: return None
    times = [x[0] for x in price_history[-60:]]
    prices = [x[1] for x in price_history[-60:]]
    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor('#1a1a2e')
    ax.set_facecolor('#16213e')
    ax.plot(times, prices, color='#00d4ff', linewidth=2)
    ax.fill_between(times, prices, min(prices), alpha=0.15, color='#00d4ff')
    ax.set_title('BTW Price Chart', color='white', fontsize=16, pad=15)
    ax.set_xlabel('Time', color='#aaaaaa')
    ax.set_ylabel('Price (USD)', color='#aaaaaa')
    ax.tick_params(colors='#aaaaaa')
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    plt.xticks(rotation=45)
    for spine in ax.spines.values(): spine.set_edgecolor('#333355')
    ax.grid(True, alpha=0.2, color='#333355')
    plt.tight_layout()
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=100, facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close()
    return buf

def check():
    global last_price, last_liquidity, daily_stats
    d = get_data()
    if not d: return
    price = float(d.get("priceUsd",0) or 0)
    liq = float(d.get("liquidity",{}).get("usd",0) or 0)
    vol = float(d.get("volume",{}).get("h24",0) or 0)

    price_history.append((datetime.now(), price))
    if len(price_history) > 720: price_history.pop(0)

    if daily_stats["open"] is None: daily_stats["open"] = price
    if price > daily_stats["high"]: daily_stats["high"] = price
    if price < daily_stats["low"]: daily_stats["low"] = price
    daily_stats["volume"] = vol

    for t in [0.10, 0.12, 0.15]:
        if t not in triggered_targets and last_price and last_price < t <= price:
            triggered_targets.add(t)
            alert(f"🎯 <b>تنبيه BTW - وصول هدف!</b>\n\n✅ السعر وصل ${t}\n💰 السعر: {fmt(price)}\n⏰ {datetime.now().strftime('%H:%M:%S')}")

    for cid, targets in list(user_custom_alerts.items()):
        for t in list(targets):
            if last_price and ((last_price < t <= price) or (last_price > t >= price)):
                targets.remove(t)
                direction = "📈 ارتفع" if price >= t else "📉 انخفض"
                try:
                    bot.send_message(cid,
                        f"🔔 <b>تنبيهك المخصص!</b>\n\n{direction} السعر إلى هدفك\n🎯 الهدف: {fmt(t)}\n💰 السعر: {fmt(price)}\n⏰ {datetime.now().strftime('%H:%M:%S')}",
                        parse_mode="HTML", reply_markup=main_menu())
                except: pass

    if last_price and last_price > 0:
        chg = ((price - last_price) / last_price) * 100
        if chg <= -5:
            alert(f"⚠️ <b>كسر دعم BTW</b>\n\n📉 انخفاض {abs(chg):.1f}%\n💰 السعر: {fmt(price)}\n⏰ {datetime.now().strftime('%H:%M:%S')}")
        elif chg >= 5:
            alert(f"🚀 <b>اختراق مقاومة BTW</b>\n\n📈 ارتفاع {chg:.1f}%\n💰 السعر: {fmt(price)}\n⏰ {datetime.now().strftime('%H:%M:%S')}")

    if last_liquidity and last_liquidity > 0:
        lchg = ((liq - last_liquidity) / last_liquidity) * 100
        if lchg >= 20:
            alert(f"💧 <b>إضافة سيولة كبيرة BTW</b>\n\n📈 زيادة {lchg:.1f}%\n💵 السيولة: ${liq:,.0f}\n⏰ {datetime.now().strftime('%H:%M:%S')}")
        elif lchg <= -50:
            alert(f"🚨 <b>انخفاض سيولة 50% BTW</b>\n\n📉 انخفاض {abs(lchg):.1f}%\n💵 السيولة: ${liq:,.0f}\n⏰ {datetime.now().strftime('%H:%M:%S')}")
        elif lchg <= -20:
            alert(f"🔴 <b>سحب سيولة كبيرة BTW</b>\n\n📉 انخفاض {abs(lchg):.1f}%\n💵 السيولة: ${liq:,.0f}\n⏰ {datetime.now().strftime('%H:%M:%S')}")

    last_price = price
    last_liquidity = liq

def check_whales():
    global daily_stats
    if not last_price or last_price == 0: return
    try:
        key = os.environ.get('BSCSCAN_API','')
        if not key: return
        url = f"https://api.bscscan.com/api?module=account&action=tokentx&contractaddress={CONTRACT}&page=1&offset=20&sort=desc&apikey={key}"
        txs = requests.get(url, timeout=10).json()
        if txs.get("status") != "1": return
        for tx in txs["result"][:10]:
            h = tx["hash"]
            if h in processed_txs: continue
            processed_txs.add(h)
            amt = int(tx["value"]) / (10 ** int(tx.get("tokenDecimal",18)))
            usd = amt * last_price
            for threshold, emoji in [(50000,"🐋"),(25000,"🐬"),(10000,"🐟")]:
                if usd >= threshold:
                    daily_stats["whale_alerts"] += 1
                    alert(f"{emoji} <b>تنبيه حوت BTW</b>\n\n💵 القيمة: ${usd:,.0f}\n🪙 الكمية: {amt:,.0f} BTW\n⏰ {datetime.now().strftime('%H:%M:%S')}")
                    break
    except Exception as e: print(f"Whale error: {e}")

def daily_report():
    global daily_stats
    p = last_price or 0
    chg = ((p - daily_stats["open"]) / daily_stats["open"] * 100) if daily_stats.get("open") else 0
    low = daily_stats["low"] if daily_stats["low"] != float('inf') else 0
    alert(
        f"📊 <b>التقرير اليومي - BTW</b>\n"
        f"{'='*28}\n\n"
        f"💰 السعر الحالي: {fmt(p)}\n"
        f"⬆️ أعلى سعر: {fmt(daily_stats['high'])}\n"
        f"⬇️ أقل سعر: {fmt(low)}\n"
        f"📊 حجم التداول: ${daily_stats['volume']:,.0f}\n"
        f"{'📈' if chg>=0 else '📉'} التغير: {chg:+.2f}%\n"
        f"🐋 تنبيهات الحيتان: {daily_stats['whale_alerts']}\n\n"
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    daily_stats = {"high":p,"low":p,"open":p,"volume":0,"whale_alerts":0}

def scheduler():
    schedule.every(2).minutes.do(check)
    schedule.every(5).minutes.do(check_whales)
    schedule.every(24).hours.do(daily_report)
    while True:
        schedule.run_pending()
        time.sleep(30)

@bot.message_handler(commands=['start'])
def start(m):
    chat_ids.add(m.chat.id)
    bot.send_message(m.chat.id,
        "🤖 <b>بوت مراقبة BTW الاحترافي</b>\n\n"
        "✅ تم تفعيل التنبيهات!\n\n"
        "اختر من القائمة:",
        parse_mode="HTML", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.chat.id in waiting_for_alert)
def handle_custom_alert(m):
    cid = m.chat.id
    try:
        target = float(m.text.strip().replace('$',''))
        if cid not in user_custom_alerts: user_custom_alerts[cid] = []
        user_custom_alerts[cid].append(target)
        waiting_for_alert.discard(cid)
        bot.send_message(cid,
            f"✅ <b>تم إضافة التنبيه!</b>\n\n🎯 سيتم تنبيهك عند {fmt(target)}",
            parse_mode="HTML", reply_markup=main_menu())
    except:
        bot.send_message(cid, "❌ أرسل رقماً صحيحاً مثال: 0.08")

@bot.callback_query_handler(func=lambda c: True)
def callback(c):
    cid = c.message.chat.id
    chat_ids.add(cid)
    d = get_data()

    if c.data == "price":
        bot.answer_callback_query(c.id, "⏳ جاري الجلب...")
        if d:
            p = float(d.get("priceUsd",0) or 0)
            chg = float(d.get("priceChange",{}).get("h24",0) or 0)
            vol = float(d.get("volume",{}).get("h24",0) or 0)
            bot.send_message(cid,
                f"💰 <b>سعر BTW</b>\n{'='*25}\n\n"
                f"السعر: {fmt(p)}\n"
                f"{'📈' if chg>=0 else '📉'} التغير 24h: {chg:+.2f}%\n"
                f"📊 حجم 24h: ${vol:,.0f}\n"
                f"⏰ {datetime.now().strftime('%H:%M:%S')}",
                parse_mode="HTML", reply_markup=main_menu())
        else:
            bot.send_message(cid, "❌ تعذر جلب البيانات", reply_markup=main_menu())

    elif c.data == "liquidity":
        bot.answer_callback_query(c.id, "⏳ جاري الجلب...")
        if d:
            liq = float(d.get("liquidity",{}).get("usd",0) or 0)
            bot.send_message(cid,
                f"💧 <b>سيولة BTW</b>\n{'='*25}\n\n"
                f"السيولة: ${liq:,.0f}\n"
                f"⏰ {datetime.now().strftime('%H:%M:%S')}",
                parse_mode="HTML", reply_markup=main_menu())
        else:
            bot.send_message(cid, "❌ تعذر جلب البيانات", reply_markup=main_menu())

    elif c.data == "report":
        bot.answer_callback_query(c.id, "⏳ جاري إعداد التقرير...")
        daily_report()

    elif c.data == "chart":
        bot.answer_callback_query(c.id, "⏳ جاري رسم الرسم البياني...")
        chart = generate_chart()
        if chart:
            bot.send_photo(cid, chart, caption="📈 <b>رسم بياني لسعر BTW</b>", parse_mode="HTML", reply_markup=main_menu())
        else:
            bot.send_message(cid, "⏳ يحتاج البوت وقتاً أكثر لجمع البيانات. حاول بعد دقيقتين.", reply_markup=main_menu())

    elif c.data == "compare":
        bot.answer_callback_query(c.id, "⏳ جاري المقارنة...")
        btc = get_btc()
        if d and btc:
            p = float(d.get("priceUsd",0) or 0)
            btw_chg = float(d.get("priceChange",{}).get("h24",0) or 0)
            btc_chg = btc.get("usd_24h_change", 0)
            diff = btw_chg - btc_chg
            verdict = f"✅ BTW يتفوق على BTC بـ {diff:.1f}%" if diff > 0 else f"⚠️ BTW أضعف من BTC بـ {abs(diff):.1f}%"
            bot.send_message(cid,
                f"₿ <b>مقارنة BTW vs BTC</b>\n{'='*28}\n\n"
                f"📊 BTW 24h: {btw_chg:+.2f}%\n"
                f"₿ BTC 24h: {btc_chg:+.2f}%\n\n"
                f"{verdict}\n\n"
                f"⏰ {datetime.now().strftime('%H:%M:%S')}",
                parse_mode="HTML", reply_markup=main_menu())
        else:
            bot.send_message(cid, "❌ تعذر جلب البيانات", reply_markup=main_menu())

    elif c.data == "custom_alert":
        bot.answer_callback_query(c.id)
        waiting_for_alert.add(cid)
        bot.send_message(cid,
            "🔔 <b>تنبيه مخصص</b>\n\n"
            "أرسل السعر الذي تريد التنبيه عنده\n"
            "مثال: <code>0.08</code>",
            parse_mode="HTML")

    elif c.data == "my_alerts":
        bot.answer_callback_query(c.id)
        alerts = user_custom_alerts.get(cid, [])
        if alerts:
            txt = "\n".join([f"🎯 {fmt(a)}" for a in alerts])
            bot.send_message(cid, f"📋 <b>تنبيهاتك المخصصة:</b>\n\n{txt}", parse_mode="HTML", reply_markup=main_menu())
        else:
            bot.send_message(cid, "📋 لا توجد تنبيهات مخصصة", reply_markup=main_menu())

    elif c.data == "stop":
        chat_ids.discard(cid)
        bot.answer_callback_query(c.id, "⛔ تم إيقاف التنبيهات")
        bot.send_message(cid, "⛔ تم إيقاف التنبيهات\n\nأرسل /start للعودة")

threading.Thread(target=scheduler, daemon=True).start()
print("BTW Monitor Bot Started!")
bot.infinity_polling()
