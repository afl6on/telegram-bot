import telebot, os, requests, schedule, time, threading
from datetime import datetime

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

def get_data():
    try:
        r = requests.get(URL, timeout=10).json()
        if r and "pairs" in r and r["pairs"]:
            return max(r["pairs"], key=lambda x: float(x.get("liquidity",{}).get("usd",0) or 0))
    except: pass
    return None

def fmt(p):
    return f"${p:.8f}" if p < 0.001 else f"${p:.4f}" if p < 1 else f"${p:.2f}"

def alert(msg):
    for cid in chat_ids:
        try: bot.send_message(cid, msg, parse_mode="HTML")
        except: pass

def check():
    global last_price, last_liquidity, daily_stats
    d = get_data()
    if not d: return
    price = float(d.get("priceUsd",0) or 0)
    liq = float(d.get("liquidity",{}).get("usd",0) or 0)
    vol = float(d.get("volume",{}).get("h24",0) or 0)

    if daily_stats["open"] is None: daily_stats["open"] = price
    if price > daily_stats["high"]: daily_stats["high"] = price
    if price < daily_stats["low"]: daily_stats["low"] = price
    daily_stats["volume"] = vol

    # Price targets
    for t in [0.10, 0.12, 0.15]:
        if t not in triggered_targets and last_price and last_price < t <= price:
            triggered_targets.add(t)
            alert(f"🎯 <b>تنبيه BTW - وصول هدف!</b>\n\n✅ السعر وصل ${t}\n💰 السعر: {fmt(price)}\n⏰ {datetime.now().strftime('%H:%M:%S')}")

    # Support/Resistance
    if last_price and last_price > 0:
        chg = ((price - last_price) / last_price) * 100
        if chg <= -5:
            alert(f"⚠️ <b>كسر دعم BTW</b>\n\n📉 انخفاض {abs(chg):.1f}%\n💰 السعر: {fmt(price)}\n⏰ {datetime.now().strftime('%H:%M:%S')}")
        elif chg >= 5:
            alert(f"🚀 <b>اختراق مقاومة BTW</b>\n\n📈 ارتفاع {chg:.1f}%\n💰 السعر: {fmt(price)}\n⏰ {datetime.now().strftime('%H:%M:%S')}")

    # Liquidity alerts
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
    bot.reply_to(m,
        "🤖 <b>بوت مراقبة BTW</b>\n\n"
        "✅ تم تفعيل التنبيهات!\n\n"
        "الأوامر:\n"
        "/price - السعر الحالي\n"
        "/liquidity - السيولة\n"
        "/report - تقرير فوري\n"
        "/stop - إيقاف التنبيهات",
        parse_mode="HTML")

@bot.message_handler(commands=['price'])
def price_cmd(m):
    chat_ids.add(m.chat.id)
    d = get_data()
    if d:
        p = float(d.get("priceUsd",0) or 0)
        chg = float(d.get("priceChange",{}).get("h24",0) or 0)
        bot.reply_to(m, f"💰 <b>سعر BTW</b>\n\nالسعر: {fmt(p)}\n{'📈' if chg>=0 else '📉'} التغير 24h: {chg:+.2f}%", parse_mode="HTML")
    else:
        bot.reply_to(m, "❌ تعذر جلب البيانات")

@bot.message_handler(commands=['liquidity'])
def liq_cmd(m):
    chat_ids.add(m.chat.id)
    d = get_data()
    if d:
        liq = float(d.get("liquidity",{}).get("usd",0) or 0)
        bot.reply_to(m, f"💧 <b>سيولة BTW</b>\n\nالسيولة: ${liq:,.0f}", parse_mode="HTML")
    else:
        bot.reply_to(m, "❌ تعذر جلب البيانات")

@bot.message_handler(commands=['report'])
def report_cmd(m):
    chat_ids.add(m.chat.id)
    daily_report()

@bot.message_handler(commands=['stop'])
def stop_cmd(m):
    chat_ids.discard(m.chat.id)
    bot.reply_to(m, "⛔ تم إيقاف التنبيهات")

threading.Thread(target=scheduler, daemon=True).start()
print("BTW Monitor Bot Started!")
bot.infinity_polling()
