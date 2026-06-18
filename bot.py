
import os
import json
import base64
from datetime import datetime, timedelta, timezone

import requests
import yfinance as yf
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TD_API_KEY = os.environ.get("TD_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN belum diisi di Railway Variables.")

WIB = timezone(timedelta(hours=7))
USER_STATE_FILE = "users.json"
TRIAL_LIMIT = 3
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "username_admin")
PREMIUM_PRICE_TEXT = os.environ.get("PREMIUM_PRICE_TEXT", "Rp299.000")
STOCK_USER_WATCHLIST_FILE = "stock_watchlists.json"
STOCK_ALERT_FILE = "stock_alerts.json"

PAIRS = {
    "XAUUSD": {"name": "XAU/USD", "td": ["XAU/USD", "XAUUSD"]},
    "XAGUSD": {"name": "XAG/USD", "td": ["XAG/USD", "XAGUSD"]},
    "BTCUSD": {"name": "BTC/USD", "td": ["BTC/USD", "BTCUSD"]},
    "ETHUSD": {"name": "ETH/USD", "td": ["ETH/USD", "ETHUSD"]},
    "EURUSD": {"name": "EUR/USD", "td": ["EUR/USD", "EURUSD"]},
    "GBPUSD": {"name": "GBP/USD", "td": ["GBP/USD", "GBPUSD"]},
    "USDJPY": {"name": "USD/JPY", "td": ["USD/JPY", "USDJPY"]},
    "NAS100": {"name": "NAS100", "td": ["NAS100", "NDX", "NQ"]},
    "US30": {"name": "US30", "td": ["DJI", "US30"]},
}


STOCK_WATCHLIST = {
    "BBCA.JK": "Bank Central Asia",
    "BBRI.JK": "Bank Rakyat Indonesia",
    "BMRI.JK": "Bank Mandiri",
    "TLKM.JK": "Telkom Indonesia",
    "ANTM.JK": "Aneka Tambang",
    "MDKA.JK": "Merdeka Copper Gold",
    "GOTO.JK": "GoTo",
    "ADRO.JK": "Adaro Energy",
    "AMMN.JK": "Amman Mineral",
    "BRPT.JK": "Barito Pacific",
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "NVDA": "NVIDIA",
    "TSLA": "Tesla",
    "AMZN": "Amazon",
    "GOOGL": "Alphabet",
    "META": "Meta",
    "AMD": "AMD",
    "PLTR": "Palantir",
}

TIMEFRAMES = {
    "M1": "1min",
    "M5": "5min",
    "M15": "15min",
    "M30": "30min",
    "H1": "1h",
    "H4": "4h",
}

def now_wib():
    return datetime.now(WIB)

def fmt(x):
    try:
        x = float(x)
        if abs(x) >= 1000:
            return f"{x:,.2f}"
        if abs(x) >= 10:
            return f"{x:.2f}"
        return f"{x:.5f}"
    except Exception:
        return str(x)

def load_json(path, default):
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def get_user(user_id):
    db = load_json(USER_STATE_FILE, {})
    uid = str(user_id)
    if uid not in db:
        db[uid] = {"pair": "XAUUSD", "tf": "M5", "premium": False, "trial_used": 0}
        save_json(USER_STATE_FILE, db)
    db[uid].setdefault("pair", "XAUUSD")
    db[uid].setdefault("tf", "M5")
    db[uid].setdefault("premium", False)
    db[uid].setdefault("trial_used", 0)
    save_json(USER_STATE_FILE, db)
    return db[uid]

def save_user(user_id, user):
    db = load_json(USER_STATE_FILE, {})
    db[str(user_id)] = user
    save_json(USER_STATE_FILE, db)

def is_premium(user):
    return bool(user.get("premium", False))


def can_use_analysis(user):
    return is_premium(user) or int(user.get("trial_used", 0)) < TRIAL_LIMIT


def add_trial_usage(user_id):
    user = get_user(user_id)
    if not is_premium(user):
        user["trial_used"] = int(user.get("trial_used", 0)) + 1
        save_user(user_id, user)
    return user


def premium_locked_text(user):
    used = int(user.get("trial_used", 0))
    return f"""
🔒 <b>AKSES PREMIUM TERKUNCI</b>

Trial gratis sudah habis.
Pemakaian trial: <b>{used}/{TRIAL_LIMIT}</b>

💎 <b>CAPITAL ELITE PREMIUM</b>
✅ Unlimited Forex/Crypto Analysis
✅ Analisa Saham IDX & US
✅ Top 10 Saham Potensi Terbang
✅ Heatmap Market
✅ Watchlist Saham
✅ AI Vision Screenshot
✅ Entry • SL • TP

Harga:
<s>Rp500.000</s>
🔥 <b>{PREMIUM_PRICE_TEXT}</b>

Hubungi Admin:
@{ADMIN_USERNAME}
"""


def premium_menu_text(user):
    status = "AKTIF ✅" if is_premium(user) else "BELUM AKTIF 🔒"
    used = int(user.get("trial_used", 0))
    sisa = max(TRIAL_LIMIT - used, 0)
    return f"""
💎 <b>CAPITAL ELITE PREMIUM</b>

Status: <b>{status}</b>
Trial tersisa: <b>{sisa}/{TRIAL_LIMIT}</b>

Fitur Premium:
✅ Unlimited Market Analysis
✅ Forex & Crypto Entry
✅ Saham IDX / US
✅ Top 10 Saham Potensi Terbang
✅ Heatmap IDX & US
✅ Watchlist Alert
✅ AI Vision Screenshot
✅ Entry • SL • TP otomatis

Harga:
<s>Rp500.000</s>
🔥 <b>{PREMIUM_PRICE_TEXT}</b>

Untuk upgrade:
Chat Admin @{ADMIN_USERNAME}
"""

def disclaimer():
    return """
━━━━━━━━━━━━━━━━━━━━
⚠️ <b>DISCLAIMER</b> ⚠️

Bukan saran finansial.
Trading memiliki risiko tinggi.
Gunakan stop loss dan money management.
━━━━━━━━━━━━━━━━━━━━
"""

def fetch_td_candles(pair_key, tf="M5", outputsize=180):
    if not TD_API_KEY:
        raise RuntimeError("TD_API_KEY belum diisi di Railway Variables.")

    url = "https://api.twelvedata.com/time_series"
    last_error = None
    for symbol in PAIRS[pair_key]["td"]:
        try:
            params = {
                "symbol": symbol,
                "interval": TIMEFRAMES.get(tf, "5min"),
                "outputsize": outputsize,
                "apikey": TD_API_KEY,
                "format": "JSON",
                "timezone": "Asia/Jakarta",
            }
            r = requests.get(url, params=params, timeout=20)
            data = r.json()
            if data.get("status") == "error":
                last_error = data.get("message", "TwelveData error")
                continue

            values = data.get("values", [])
            if not values:
                last_error = "Candle kosong."
                continue

            candles = []
            for v in reversed(values):
                candles.append({
                    "Open": float(v["open"]),
                    "High": float(v["high"]),
                    "Low": float(v["low"]),
                    "Close": float(v["close"]),
                    "Time": v.get("datetime", ""),
                })
            return candles
        except Exception as e:
            last_error = str(e)

    raise RuntimeError(last_error or "TwelveData gagal.")

def fetch_td_quote(pair_key):
    if not TD_API_KEY:
        raise RuntimeError("TD_API_KEY belum diisi di Railway Variables.")

    url = "https://api.twelvedata.com/quote"
    last_error = None
    for symbol in PAIRS[pair_key]["td"]:
        try:
            r = requests.get(url, params={"symbol": symbol, "apikey": TD_API_KEY}, timeout=12)
            data = r.json()
            if data.get("status") == "error":
                last_error = data.get("message", "Quote error")
                continue
            for k in ["close", "price", "bid"]:
                val = data.get(k)
                if val not in [None, "", "None"]:
                    return float(val), "TwelveData Live"
        except Exception as e:
            last_error = str(e)
    raise RuntimeError(last_error or "Quote gagal.")

def tail(c, n):
    return c[-n:] if len(c) >= n else c

def highs(c):
    return [x["High"] for x in c]

def lows(c):
    return [x["Low"] for x in c]

def avg_range(c, n=20):
    cs = tail(c, n)
    return sum(abs(x["High"] - x["Low"]) for x in cs) / max(len(cs), 1)

def structure_bias(c):
    if len(c) < 60:
        return "SIDEWAYS"
    cs = tail(c, 60)
    hi, lo = max(highs(cs)), min(lows(cs))
    eq = (hi + lo) / 2
    last = c[-1]["Close"]
    first = c[-30]["Close"]
    if last > first and last > eq:
        return "BUY"
    if last < first and last < eq:
        return "SELL"
    return "SIDEWAYS"

def premium_discount(c, price):
    cs = tail(c, 80)
    hi, lo = max(highs(cs)), min(lows(cs))
    eq = (hi + lo) / 2
    return ("DISCOUNT" if price < eq else "PREMIUM" if price > eq else "EQ", eq, hi, lo)

def find_fvg(c, direction):
    avg = avg_range(c, 20)
    for i in range(len(c)-1, 2, -1):
        c0, c2 = c[i-2], c[i]
        if direction == "BUY":
            low, high = c0["High"], c2["Low"]
            if high > low and high - low >= avg * 0.08:
                return {"low": low, "high": high, "mid": (low + high) / 2, "type": "FVG"}
        else:
            low, high = c2["High"], c0["Low"]
            if high > low and high - low >= avg * 0.08:
                return {"low": low, "high": high, "mid": (low + high) / 2, "type": "FVG"}
    return None

def find_ob(c, direction):
    avg = avg_range(c, 20)
    for i in range(len(c)-3, 3, -1):
        x, n = c[i], c[i+1]
        xdir = "BULLISH" if x["Close"] > x["Open"] else "BEARISH"
        ndir = "BULLISH" if n["Close"] > n["Open"] else "BEARISH"
        nrng = abs(n["High"] - n["Low"])
        if direction == "BUY" and xdir == "BEARISH" and ndir == "BULLISH" and nrng >= avg * 0.8:
            return {"low": x["Low"], "high": x["Open"], "mid": (x["Low"] + x["Open"]) / 2, "type": "OB"}
        if direction == "SELL" and xdir == "BULLISH" and ndir == "BEARISH" and nrng >= avg * 0.8:
            return {"low": x["Open"], "high": x["High"], "mid": (x["Open"] + x["High"]) / 2, "type": "OB"}
    return None

def find_crt(c, direction):
    if len(c) < 5:
        return None
    ref, last = c[-2], c[-1]
    hi, lo = ref["High"], ref["Low"]
    rng = max(hi - lo, 0.0001)
    mid = (hi + lo) / 2
    if direction == "BUY" and last["Low"] < lo and last["Close"] > lo:
        z1, z2 = lo + rng * 0.21, mid
        return {"low": min(z1, z2), "high": max(z1, z2), "mid": (z1 + z2) / 2, "type": "CRT"}
    if direction == "SELL" and last["High"] > hi and last["Close"] < hi:
        z1, z2 = mid, hi - rng * 0.21
        return {"low": min(z1, z2), "high": max(z1, z2), "mid": (z1 + z2) / 2, "type": "CRT"}
    return None

def overlap(a, b):
    if not a or not b:
        return None
    low, high = max(a["low"], b["low"]), min(a["high"], b["high"])
    if high > low:
        return {"low": low, "high": high, "mid": (low + high) / 2, "type": f"{a['type']} + {b['type']}"}
    return None

def fallback_zone(price, atr, direction, pair_key):
    if pair_key == "XAUUSD":
        width, pullback = max(atr * 0.15, 0.20), max(atr * 0.22, 0.25)
    elif pair_key in ["BTCUSD", "ETHUSD", "NAS100", "US30"]:
        width, pullback = max(atr * 0.20, price * 0.0007), max(atr * 0.25, price * 0.0008)
    else:
        width, pullback = max(atr * 0.20, 0.00025), max(atr * 0.25, 0.00030)
    if direction == "BUY":
        high, low = price - pullback, price - pullback - width
    else:
        low, high = price + pullback, price + pullback + width
    return {"low": min(low, high), "high": max(low, high), "mid": (low + high) / 2, "type": "Realtime Pullback"}

def risk_pips(pair_key, entry, sl):
    diff = abs(entry - sl)
    if pair_key in ["XAUUSD", "XAGUSD"]:
        return diff * 100
    if pair_key == "USDJPY":
        return diff * 100
    if pair_key in ["BTCUSD", "ETHUSD", "NAS100", "US30"]:
        return diff
    return diff * 10000

def build_analysis(pair_key, tf_key):
    pair = PAIRS[pair_key]
    try:
        c_m5 = fetch_td_candles(pair_key, "M5")
        c_m15 = fetch_td_candles(pair_key, "M15")
        c_h1 = fetch_td_candles(pair_key, "H1")
        c_h4 = fetch_td_candles(pair_key, "H4")
        try:
            price, source = fetch_td_quote(pair_key)
        except Exception:
            price, source = c_m5[-1]["Close"], "Candle Fallback"
    except Exception as e:
        return f"⚠️ <b>MARKET DATA ERROR</b>\n\nPair: <b>{pair['name']}</b>\nDetail: <code>{type(e).__name__}: {str(e)[:180]}</code>\n\nCek TD_API_KEY / kuota TwelveData."

    exec_c = c_m5 if tf_key in ["M1", "M5"] else c_m15
    atr = avg_range(exec_c, 20)

    h4, h1, m15, m5 = structure_bias(c_h4), structure_bias(c_h1), structure_bias(c_m15), structure_bias(c_m5)
    location, eq, rh, rl = premium_discount(c_h1, price)

    votes = [h4, h1, m15, m5]
    buy_votes, sell_votes = votes.count("BUY"), votes.count("SELL")
    if buy_votes > sell_votes:
        direction = "BUY"
    elif sell_votes > buy_votes:
        direction = "SELL"
    else:
        direction = "BUY" if location == "DISCOUNT" else "SELL"

    fvg, ob, crt = find_fvg(exec_c, direction), find_ob(exec_c, direction), find_crt(exec_c, direction)
    score, reasons = 45, []

    for label, bias, points in [("H4 searah", h4, 12), ("H1 searah", h1, 12), ("M15 searah", m15, 8)]:
        if bias == direction:
            score += points
            reasons.append(label)
    if fvg:
        score += 8
        reasons.append("FVG")
    if ob:
        score += 8
        reasons.append("OB")
    if crt:
        score += 6
        reasons.append("CRT")
    if direction == "BUY" and location == "DISCOUNT":
        score += 6
        reasons.append("Discount")
    if direction == "SELL" and location == "PREMIUM":
        score += 6
        reasons.append("Premium")
    score = min(score, 95)

    zone = overlap(fvg, ob) or overlap(fvg, crt) or overlap(ob, crt) or fvg or ob or crt
    zone_name = zone["type"] if zone else "Realtime Pullback"
    if not zone:
        zone = fallback_zone(price, atr, direction, pair_key)
        reasons.append("Pullback realtime")

    max_dist = max(atr * 1.5, 0.80 if pair_key == "XAUUSD" else abs(price) * 0.001)
    if abs(zone["mid"] - price) > max_dist:
        zone = fallback_zone(price, atr, direction, pair_key)
        zone_name = "Realtime Pullback"
        score = max(55, score - 10)
        reasons.append("Entry dekat harga realtime")

    entry_low, entry_high, entry = zone["low"], zone["high"], zone["mid"]

    if direction == "BUY":
        if pair_key == "XAUUSD":
            sl, tp1, tp2 = entry - 0.40, entry + 0.60, entry + 0.90
        else:
            sl = entry - max(atr * 0.9, abs(entry) * 0.0012)
            risk = max(entry - sl, 0.0001)
            tp1, tp2 = entry + risk * 1.3, entry + risk * 2.0
    else:
        if pair_key == "XAUUSD":
            sl, tp1, tp2 = entry + 0.40, entry - 0.60, entry - 0.90
        else:
            sl = entry + max(atr * 0.9, abs(entry) * 0.0012)
            risk = max(sl - entry, 0.0001)
            tp1, tp2 = entry - risk * 1.3, entry - risk * 2.0

    rr = abs(tp2 - entry) / max(abs(entry - sl), 0.0001)
    pips = risk_pips(pair_key, entry, sl)
    trend = "BULLISH" if direction == "BUY" else "BEARISH"
    icon = "🟢" if direction == "BUY" else "🔴"
    blocks = "⬛" * max(1, int(score / 10)) + "⬜" * max(0, 10 - int(score / 10))
    status = "HIGH PROBABILITY" if score >= 85 else "MEDIUM PROBABILITY" if score >= 70 else "LOW CONFIDENCE"

    if not reasons:
        reasons = ["Struktur market terbaca", "Entry dekat harga realtime"]

    ai = "Pasar cenderung bullish. Entry diambil dari area pullback/POI terdekat agar tidak mengejar harga." if direction == "BUY" else "Pasar cenderung bearish. Entry diambil dari area pullback/POI terdekat agar tidak mengejar harga."

    return f"""
✦ 💎 <b>CAPITAL ELITE PROJECT</b> 💎 ✦
━━━━━━━━━━━━━━━━━━━━

🗓️ <b>{now_wib().strftime("%d %B %Y pukul %H.%M WIB")}</b>
💱 Pair : <b>{pair['name']}</b>
⏱ Timeframe : <b>{tf_key}</b>

━━━━━━━━━━━━━━━━━━━━
🤖 <b>SINYAL TRADING AI</b>
━━━━━━━━━━━━━━━━━━━━

📈 Trend : <b>{trend}</b>
🎯 Confidence : <b>{score}%</b> {blocks}
📌 Status : <b>{status}</b>

{icon} Sinyal : <b>{direction}</b>
💰 Entry : <code>{fmt(entry)}</code>
📍 Area : <code>{fmt(entry_low)} - {fmt(entry_high)}</code>
⛔ Stop Loss : <code>{fmt(sl)}</code>
🎯 Take Profit : <code>{fmt(tp2)}</code>

━━━━━━━━━━━━━━━━━━━━
🤖 <b>ANALISA AI</b>
━━━━━━━━━━━━━━━━━━━━

{ai}

Validasi:
✅ {" | ".join(reasons[:6])}
⚖️ RR : <b>1:{rr:.2f}</b>
📏 Risk : <b>{pips:.0f} pips</b>
📌 Zone : <b>{zone_name}</b>
📡 Source : <b>{source}</b>

{disclaimer()}
"""

def main_menu(user_id):
    user = get_user(user_id)
    pair, tf = user.get("pair", "XAUUSD"), user.get("tf", "M5")
    premium_status = "💎 PREMIUM ACTIVE" if is_premium(user) else f"🆓 FREE TRIAL {max(TRIAL_LIMIT - int(user.get('trial_used', 0)), 0)}/{TRIAL_LIMIT}"

    text = f"""
👑 <b>CAPITAL ELITE PROJECT</b>
<code>AI-Powered Trading Intelligence</code>

{premium_status}

💱 Pair aktif: <b>{PAIRS[pair]['name']}</b>
⏱ TF aktif: <b>{tf}</b>

📊 <b>Market Analysis</b>
Entry • SL • TP otomatis

📈 <b>Stock Analysis</b>
IDX & US Stocks • Scanner breakout

🧠 <b>AI Vision</b>
Kirim screenshot chart + caption pair/TF
"""
    kb = [
        [InlineKeyboardButton("📊 Analisa Sekarang", callback_data="analyze")],
        [InlineKeyboardButton("📈 Analisa Saham", callback_data="stock_menu")],
        [InlineKeyboardButton("🚀 Top 10 Saham", callback_data="stock_top")],
        [InlineKeyboardButton("🔥 Heatmap", callback_data="stock_heatmap"), InlineKeyboardButton("⭐ Watchlist", callback_data="stock_watchlist")],
        [InlineKeyboardButton("💱 Ganti Pair", callback_data="pairs"), InlineKeyboardButton("⏱ Ganti TF", callback_data="tfs")],
        [InlineKeyboardButton("🧠 Cara AI Vision", callback_data="vision_help")],
        [InlineKeyboardButton("💎 Premium", callback_data="premium")],
    ]
    return text, InlineKeyboardMarkup(kb)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, kb = main_menu(update.effective_user.id)
    await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id, data = q.from_user.id, q.data
    user = get_user(user_id)

    if data == "home":
        text, kb = main_menu(user_id)
        await q.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
    elif data == "pairs":
        keys = list(PAIRS.keys())
        rows = []
        for i in range(0, len(keys), 2):
            rows.append([InlineKeyboardButton(PAIRS[k]["name"], callback_data=f"pair_{k}") for k in keys[i:i+2]])
        rows.append([InlineKeyboardButton("⬅️ Home", callback_data="home")])
        await q.edit_message_text("Pilih pair:", reply_markup=InlineKeyboardMarkup(rows))
    elif data.startswith("pair_"):
        p = data.replace("pair_", "")
        if p in PAIRS:
            user["pair"] = p
            save_user(user_id, user)
        text, kb = main_menu(user_id)
        await q.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
    elif data == "tfs":
        rows = [
            [InlineKeyboardButton("M1", callback_data="tf_M1"), InlineKeyboardButton("M5", callback_data="tf_M5"), InlineKeyboardButton("M15", callback_data="tf_M15")],
            [InlineKeyboardButton("M30", callback_data="tf_M30"), InlineKeyboardButton("H1", callback_data="tf_H1"), InlineKeyboardButton("H4", callback_data="tf_H4")],
            [InlineKeyboardButton("⬅️ Home", callback_data="home")]
        ]
        await q.edit_message_text("Pilih timeframe:", reply_markup=InlineKeyboardMarkup(rows))
    elif data.startswith("tf_"):
        tf = data.replace("tf_", "")
        if tf in TIMEFRAMES:
            user["tf"] = tf
            save_user(user_id, user)
        text, kb = main_menu(user_id)
        await q.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
    elif data == "analyze":
        if not can_use_analysis(user):
            await q.edit_message_text(
                premium_locked_text(user),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 Premium", callback_data="premium")], [InlineKeyboardButton("⬅️ Home", callback_data="home")]]),
                parse_mode="HTML"
            )
            return
        pair, tf = user.get("pair", "XAUUSD"), user.get("tf", "M5")
        await q.edit_message_text("📡 Ambil data realtime...")
        result = build_analysis(pair, tf)
        user = add_trial_usage(user_id)
        if not is_premium(user):
            result += f"\n\n🆓 Trial tersisa: <b>{max(TRIAL_LIMIT - int(user.get('trial_used', 0)), 0)}/{TRIAL_LIMIT}</b>"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="analyze")],
            [InlineKeyboardButton("💱 Pair", callback_data="pairs"), InlineKeyboardButton("⏱ TF", callback_data="tfs")],
            [InlineKeyboardButton("🏠 Home", callback_data="home")]
        ])
        await q.edit_message_text(result, reply_markup=kb, parse_mode="HTML")

    elif data == "stock_menu":
        rows = [
            [InlineKeyboardButton("BBCA.JK", callback_data="stock_BBCA.JK"), InlineKeyboardButton("BBRI.JK", callback_data="stock_BBRI.JK")],
            [InlineKeyboardButton("BMRI.JK", callback_data="stock_BMRI.JK"), InlineKeyboardButton("ANTM.JK", callback_data="stock_ANTM.JK")],
            [InlineKeyboardButton("NVDA", callback_data="stock_NVDA"), InlineKeyboardButton("TSLA", callback_data="stock_TSLA")],
            [InlineKeyboardButton("AAPL", callback_data="stock_AAPL"), InlineKeyboardButton("PLTR", callback_data="stock_PLTR")],
            [InlineKeyboardButton("⬅️ Home", callback_data="home")]
        ]
        await q.edit_message_text(
            "📈 <b>Pilih Saham</b>\n\nAtau pakai command:\n<code>/stock BBCA.JK</code>\n<code>/stock TSLA</code>",
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode="HTML"
        )

    elif data.startswith("stock_") and data not in ["stock_top", "stock_heatmap", "stock_watchlist"]:
        if not can_use_analysis(user):
            await q.edit_message_text(
                premium_locked_text(user),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 Premium", callback_data="premium")], [InlineKeyboardButton("⬅️ Home", callback_data="home")]]),
                parse_mode="HTML"
            )
            return
        symbol = data.replace("stock_", "")
        await q.edit_message_text("📡 Analisa saham...\nTunggu sebentar.")
        result = analyze_stock(symbol)
        user = add_trial_usage(user_id)
        if not is_premium(user):
            result += f"\n\n🆓 Trial tersisa: <b>{max(TRIAL_LIMIT - int(user.get('trial_used', 0)), 0)}/{TRIAL_LIMIT}</b>"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Scan Lagi", callback_data=f"stock_{symbol}")],
            [InlineKeyboardButton("🚀 Scanner", callback_data="stock_scan")],
            [InlineKeyboardButton("🏠 Home", callback_data="home")]
        ])
        await q.edit_message_text(result, reply_markup=kb, parse_mode="HTML")

    elif data == "stock_scan":
        await q.edit_message_text("🚀 Scanning saham potensial...\nTunggu sebentar.")
        result = scan_stocks()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh Scanner", callback_data="stock_scan")],
            [InlineKeyboardButton("📈 Pilih Saham", callback_data="stock_menu")],
            [InlineKeyboardButton("🏠 Home", callback_data="home")]
        ])
        await q.edit_message_text(result, reply_markup=kb, parse_mode="HTML")


    elif data == "stock_top":
        await q.edit_message_text("🚀 Scanning Top 10 saham...\nTunggu sebentar.")
        result = top_stock_scanner(10)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="stock_top")],
            [InlineKeyboardButton("📈 Pilih Saham", callback_data="stock_menu")],
            [InlineKeyboardButton("🏠 Home", callback_data="home")]
        ])
        await q.edit_message_text(result, reply_markup=kb, parse_mode="HTML")

    elif data == "stock_heatmap":
        await q.edit_message_text("🔥 Membuat heatmap saham...\nTunggu sebentar.")
        result = market_heatmap_text()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="stock_heatmap")],
            [InlineKeyboardButton("🚀 Top 10", callback_data="stock_top")],
            [InlineKeyboardButton("🏠 Home", callback_data="home")]
        ])
        await q.edit_message_text(result, reply_markup=kb, parse_mode="HTML")

    elif data == "stock_watchlist":
        result = watchlist_text(user_id)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Top 10", callback_data="stock_top")],
            [InlineKeyboardButton("🏠 Home", callback_data="home")]
        ])
        await q.edit_message_text(result, reply_markup=kb, parse_mode="HTML")

    elif data == "premium":
        await q.edit_message_text(
            premium_menu_text(user),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Home", callback_data="home")]]),
            parse_mode="HTML"
        )

    elif data == "vision_help":
        await q.edit_message_text("🧠 Kirim screenshot chart sebagai foto + caption contoh: BTCUSD M5", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Home", callback_data="home")]]))

def gemini_review(image_bytes, caption=""):
    if not GEMINI_API_KEY:
        return "⚠️ GEMINI_API_KEY belum diisi di Railway Variables."
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    prompt = f"Lu trader senior. Review screenshot chart ini. Caption: {caption}. Jawab BUY/SELL/NO TRADE, Entry, SL, TP, Probability, Alasan singkat. Bahasa Indonesia. Jangan janji profit."
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"inline_data": {"mime_type": "image/jpeg", "data": b64}}, {"text": prompt}]}], "generationConfig": {"temperature": 0.2, "maxOutputTokens": 800}}
    try:
        r = requests.post(url, json=payload, timeout=45)
        data = r.json()
        if r.status_code != 200:
            return f"⚠️ Gemini error: {data.get('error', {}).get('message', str(data))[:400]}"
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"]).strip()
    except Exception as e:
        return f"⚠️ Gemini gagal: {type(e).__name__}: {str(e)[:200]}"

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 AI Vision membaca chart...")
    photo = update.message.photo[-1]
    tg_file = await context.bot.get_file(photo.file_id)
    img = await tg_file.download_as_bytearray()
    result = gemini_review(bytes(img), update.message.caption or "")
    await update.message.reply_text(result + "\n\n⚠️ Not Financial Advice.", parse_mode="HTML")

async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not can_use_analysis(user):
        await update.message.reply_text(premium_locked_text(user), parse_mode="HTML")
        return
    await update.message.reply_text("📡 Ambil data realtime...")
    result = build_analysis(user.get("pair", "XAUUSD"), user.get("tf", "M5"))
    user = add_trial_usage(user_id)
    if not is_premium(user):
        result += f"\n\n🆓 Trial tersisa: <b>{max(TRIAL_LIMIT - int(user.get('trial_used', 0)), 0)}/{TRIAL_LIMIT}</b>"
    await update.message.reply_text(result, parse_mode="HTML")

async def pair_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Contoh: /pair XAUUSD")
        return
    p = context.args[0].upper()
    if p not in PAIRS:
        await update.message.reply_text("Pair tidak tersedia.")
        return
    user = get_user(update.effective_user.id)
    user["pair"] = p
    save_user(update.effective_user.id, user)
    await update.message.reply_text(f"Pair aktif: {PAIRS[p]['name']}")

async def tf_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Contoh: /tf M5")
        return
    tf = context.args[0].upper()
    if tf not in TIMEFRAMES:
        await update.message.reply_text("TF tidak tersedia.")
        return
    user = get_user(update.effective_user.id)
    user["tf"] = tf
    save_user(update.effective_user.id, user)
    await update.message.reply_text(f"TF aktif: {tf}")



# ==============================
# STOCK ENGINE - FULL READY
# ==============================
def normalize_stock_symbol(symbol):
    s = str(symbol).upper().strip()
    if s in IDX_SHORT:
        return s + ".JK"
    return s


def stock_price_fmt(symbol, price):
    try:
        price = float(price)
        if str(symbol).upper().endswith(".JK"):
            return f"{price:,.0f}"
        return f"{price:,.2f}"
    except Exception:
        return str(price)


def fetch_stock_df(symbol):
    symbol = normalize_stock_symbol(symbol)
    df = yf.download(symbol, period="6mo", interval="1d", progress=False, auto_adjust=True)
    if df is None or df.empty or len(df) < 60:
        return symbol, None
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return symbol, df


def stock_quick_score(symbol):
    symbol, df = fetch_stock_df(symbol)
    if df is None:
        return None
    close, high, low, vol = df["Close"], df["High"], df["Low"], df["Volume"]
    last = float(close.iloc[-1]); prev = float(close.iloc[-2])
    ma20 = float(close.rolling(20).mean().iloc[-1]); ma50 = float(close.rolling(50).mean().iloc[-1])
    res = float(high.tail(20).max()); sup = float(low.tail(20).min())
    avg_vol = float(vol.tail(20).mean()); last_vol = float(vol.iloc[-1])
    vol_ratio = last_vol / avg_vol if avg_vol else 1
    change_pct = ((last - prev) / prev) * 100 if prev else 0
    score = 35; tags = []
    if last > ma20: score += 15; tags.append("MA20")
    if ma20 > ma50: score += 20; tags.append("Trend")
    if last >= res * 0.985: score += 15; tags.append("Near BO")
    if last > res * 1.002: score += 20; tags.append("Breakout")
    if vol_ratio >= 1.5: score += 15; tags.append("Vol Spike")
    elif vol_ratio >= 1.1: score += 8; tags.append("Vol Up")
    if change_pct > 1: score += 8; tags.append("Momentum")
    elif change_pct < -2: score -= 10; tags.append("Weak")
    score = max(20, min(score, 95))
    return {"symbol": symbol, "price": last, "score": score, "change": change_pct, "volume": vol_ratio, "support": sup, "resistance": res, "ma20": ma20, "ma50": ma50, "tags": tags, "df": df}


def analyze_stock(symbol):
    symbol = normalize_stock_symbol(symbol)
    q = stock_quick_score(symbol)
    if not q:
        return f"⚠️ Data saham <b>{symbol}</b> tidak cukup / tidak ditemukan."
    df = q["df"]; high, low = df["High"], df["Low"]
    last = q["price"]; ma20 = q["ma20"]; ma50 = q["ma50"]
    support = q["support"]; resistance = q["resistance"]
    score = q["score"]; change_pct = q["change"]; vol_ratio = q["volume"]
    if score >= 85:
        grade = "POTENSI TERBANG / STRONG WATCH"; signal = "🟢 BUY ON PULLBACK / BREAKOUT"
    elif score >= 70:
        grade = "WATCHLIST BAGUS"; signal = "🟡 WAIT PULLBACK"
    elif score >= 55:
        grade = "NETRAL"; signal = "⚪ WAIT"
    else:
        grade = "WEAK"; signal = "🔴 AVOID DULU"
    atr_like = float((high - low).tail(14).mean())
    if last >= resistance * 0.985:
        entry_low = max(last - atr_like * 0.35, ma20); entry_high = last
    else:
        entry_low = ma20; entry_high = min(ma20 + atr_like * 0.45, last)
    sl = min(support, entry_low - atr_like * 0.75)
    risk = max(entry_high - sl, atr_like * 0.5)
    tp1 = entry_high + risk * 1.5; tp2 = entry_high + risk * 2.5
    name = STOCK_WATCHLIST.get(symbol, symbol)
    reasons_text = " | ".join(q.get("tags", [])[:6]) if q.get("tags") else "Belum ada konfirmasi kuat"
    return f"""
📈 <b>CAPITAL ELITE STOCK ANALYSIS</b>

🏢 Saham: <b>{symbol}</b>
📝 Nama: <b>{name}</b>
💵 Harga: <code>{stock_price_fmt(symbol, last)}</code>
📊 Change: <b>{change_pct:.2f}%</b>

🎯 Score: <b>{score}/100</b>
🏆 Grade: <b>{grade}</b>
📌 Signal: <b>{signal}</b>

📈 Trend:
MA20: <code>{stock_price_fmt(symbol, ma20)}</code>
MA50: <code>{stock_price_fmt(symbol, ma50)}</code>

🟢 Support: <code>{stock_price_fmt(symbol, support)}</code>
🔴 Resistance: <code>{stock_price_fmt(symbol, resistance)}</code>
📊 Volume: <b>{vol_ratio:.2f}x</b> rata-rata

💰 Entry Area:
<code>{stock_price_fmt(symbol, entry_low)} - {stock_price_fmt(symbol, entry_high)}</code>

⛔ Stop Loss:
<code>{stock_price_fmt(symbol, sl)}</code>

🎯 TP1:
<code>{stock_price_fmt(symbol, tp1)}</code>

🎯 TP2:
<code>{stock_price_fmt(symbol, tp2)}</code>

🤖 Analisa:
{reasons_text}

⚠️ Bukan rekomendasi pasti naik. Gunakan risk management.
"""


def scan_stocks(limit=7):
    results = []
    for sym in STOCK_WATCHLIST.keys():
        try:
            q = stock_quick_score(sym)
            if q: results.append(q)
        except Exception: pass
    results.sort(key=lambda x: (x["score"], x["volume"], x["change"]), reverse=True)
    if not results:
        return "⚠️ Scanner saham belum dapat data. Cek koneksi / yfinance."
    lines=[]
    for i,r in enumerate(results[:limit],1):
        tag = "🚀" if r["score"] >= 85 else "🟡" if r["score"] >= 70 else "⚪"
        lines.append(f"{i}. {tag} <b>{r['symbol']}</b> — Score <b>{r['score']}</b> | Change {r['change']:.2f}% | Vol {r['volume']:.2f}x")
    return f"""
🚀 <b>CAPITAL ELITE STOCK SCANNER</b>

Saham dengan momentum paling kuat:

{chr(10).join(lines)}

Rule:
Score 85+ = Watch serius
Score 70+ = Tunggu pullback/breakout
Score <70 = Jangan maksa

⚠️ Bukan rekomendasi pasti naik. Tetap cek chart dan risk.
"""


def top_stock_scanner(limit=10):
    return scan_stocks(limit)


def market_heatmap_text():
    idx = ["BBCA.JK", "BBRI.JK", "BMRI.JK", "TLKM.JK", "ANTM.JK", "MDKA.JK", "GOTO.JK", "ADRO.JK"]
    us = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "PLTR"]
    def line_for(symbols):
        out=[]
        for s in symbols:
            try:
                q=stock_quick_score(s)
                if not q: continue
                icon = "🟢" if q["score"] >= 80 else "🟡" if q["score"] >= 65 else "🔴"
                out.append(f"{icon} <b>{q['symbol']}</b> {q['change']:.2f}%")
            except Exception: pass
        return "\n".join(out) if out else "Data belum tersedia."
    return f"""
🔥 <b>CAPITAL ELITE MARKET HEATMAP</b>

🇮🇩 <b>IDX Watchlist</b>
{line_for(idx)}

🇺🇸 <b>US Watchlist</b>
{line_for(us)}

Legend:
🟢 Momentum kuat
🟡 Netral / tunggu konfirmasi
🔴 Lemah

⚠️ Heatmap hanya filter awal, tetap cek chart.
"""


def stock_news_ai_basic(symbol):
    symbol=normalize_stock_symbol(symbol)
    q=stock_quick_score(symbol)
    if not q: return f"⚠️ Data saham <b>{symbol}</b> belum tersedia."
    headlines=[]; sentiment_score=50
    try:
        ticker=yf.Ticker(symbol); news=ticker.news or []
        for item in news[:5]:
            title = item.get("title") or item.get("content", {}).get("title", "")
            if not title: continue
            headlines.append(title[:120]); t=title.lower()
            if any(w in t for w in ["beat","surge","record","growth","upgrade","profit","strong","rally","breakout","buy"]): sentiment_score += 8
            if any(w in t for w in ["miss","drop","fall","lawsuit","downgrade","loss","weak","sell","cut","risk"]): sentiment_score -= 8
    except Exception: pass
    final=int((sentiment_score*0.4)+(q["score"]*0.6)); final=max(0,min(final,100))
    verdict="🟢 Bullish Bias" if final>=75 else "🟡 Netral Positif" if final>=55 else "🔴 Hati-hati"
    headline_text="\n".join([f"• {h}" for h in headlines]) if headlines else "• Belum ada headline terbaru terbaca dari yfinance."
    return f"""
📰 <b>STOCK NEWS AI</b>

🏢 Saham: <b>{symbol}</b>
📊 Technical Score: <b>{q['score']}/100</b>
🧠 News + Technical Verdict: <b>{final}/100</b>
📌 Bias: <b>{verdict}</b>

Headline:
{headline_text}

AI Note:
Jika score teknikal kuat tapi news negatif, tunggu pullback dan konfirmasi volume.
Jika score teknikal + news sama-sama kuat, saham layak masuk watchlist utama.

⚠️ News dari yfinance bisa delay / terbatas.
"""


def get_user_stock_watchlist(user_id):
    db=load_json(STOCK_USER_WATCHLIST_FILE,{})
    return db.get(str(user_id), [])


def save_user_stock_watchlist(user_id, items):
    db=load_json(STOCK_USER_WATCHLIST_FILE,{})
    clean=[]
    for s in items:
        sym=normalize_stock_symbol(s)
        if sym not in clean: clean.append(sym)
    db[str(user_id)]=clean[:30]
    save_json(STOCK_USER_WATCHLIST_FILE, db)


def watchlist_text(user_id):
    items=get_user_stock_watchlist(user_id)
    if not items:
        return """
⭐ <b>WATCHLIST SAHAM PRIBADI</b>

Watchlist masih kosong.

Tambah:
<code>/watchadd BBCA.JK</code>
<code>/watchadd NVDA</code>
"""
    lines=[]
    for s in items:
        try:
            q=stock_quick_score(s)
            if q:
                icon="🚀" if q["score"]>=85 else "🟡" if q["score"]>=70 else "⚪"
                lines.append(f"{icon} <b>{q['symbol']}</b> — Score {q['score']}/100 | {q['change']:.2f}% | Vol {q['volume']:.2f}x")
            else: lines.append(f"⚪ <b>{s}</b> — data belum tersedia")
        except Exception: lines.append(f"⚪ <b>{s}</b> — error")
    return f"""
⭐ <b>WATCHLIST SAHAM PRIBADI</b>

{chr(10).join(lines)}

Command:
<code>/watchadd BBCA.JK</code>
<code>/watchdel BBCA.JK</code>
"""


async def stock_watch_alert_job(context):
    try:
        db=load_json(STOCK_USER_WATCHLIST_FILE,{})
        if not db: return
        alert_db=load_json(STOCK_ALERT_FILE,{})
        today=now_wib().strftime("%Y-%m-%d")
        for uid, symbols in db.items():
            for sym in symbols:
                try:
                    q=stock_quick_score(sym)
                    if not q: continue
                    near=q["price"] >= q["resistance"]*0.985
                    strong=q["score"] >= 85
                    if not near and not strong: continue
                    key=f"{uid}_{q['symbol']}_{today}"
                    if alert_db.get(key): continue
                    alert_db[key]=True
                    msg=f"""
🚀 <b>STOCK WATCHLIST ALERT</b>

Saham: <b>{q['symbol']}</b>
Score: <b>{q['score']}/100</b>
Harga: <code>{stock_price_fmt(q['symbol'], q['price'])}</code>
Resistance: <code>{stock_price_fmt(q['symbol'], q['resistance'])}</code>
Volume: <b>{q['volume']:.2f}x</b>

Gunakan:
<code>/stock {q['symbol']}</code>
untuk detail Entry / SL / TP.
"""
                    try: await context.bot.send_message(chat_id=int(uid), text=msg, parse_mode="HTML")
                    except Exception: pass
                except Exception: pass
        save_json(STOCK_ALERT_FILE, alert_db)
    except Exception as e:
        print("STOCK WATCH ALERT ERROR:", e)

async def stock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not context.args:
        await update.message.reply_text("Contoh:\n<code>/stock BBCA.JK</code>\n<code>/stock TSLA</code>", parse_mode="HTML")
        return
    if not can_use_analysis(user):
        await update.message.reply_text(premium_locked_text(user), parse_mode="HTML")
        return
    symbol = context.args[0].upper()
    await update.message.reply_text("📡 Analisa saham...\nTunggu sebentar.")
    result = analyze_stock(symbol)
    user = add_trial_usage(user_id)
    if not is_premium(user):
        result += f"\n\n🆓 Trial tersisa: <b>{max(TRIAL_LIMIT - int(user.get('trial_used', 0)), 0)}/{TRIAL_LIMIT}</b>"
    await update.message.reply_text(result, parse_mode="HTML")

async def stocks_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 Scanning saham potensial...\nTunggu sebentar.")
    await update.message.reply_text(scan_stocks(), parse_mode="HTML")



async def stocktop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 Scanning Top 10 saham...\nTunggu sebentar.")
    await update.message.reply_text(top_stock_scanner(10), parse_mode="HTML")


async def heatmap_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔥 Membuat heatmap saham...\nTunggu sebentar.")
    await update.message.reply_text(market_heatmap_text(), parse_mode="HTML")


async def stocknews_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Contoh: /stocknews NVDA atau /stocknews BBCA.JK")
        return
    symbol = context.args[0].upper()
    await update.message.reply_text("📰 Ambil stock news AI...\nTunggu sebentar.")
    await update.message.reply_text(stock_news_ai_basic(symbol), parse_mode="HTML")


async def watchlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(watchlist_text(update.effective_user.id), parse_mode="HTML")


async def watchadd_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Contoh: /watchadd BBCA.JK")
        return
    symbol = normalize_stock_symbol(context.args[0])
    items = get_user_stock_watchlist(update.effective_user.id)
    if symbol not in items:
        items.append(symbol)
    save_user_stock_watchlist(update.effective_user.id, items)
    await update.message.reply_text(f"✅ <b>{symbol}</b> ditambahkan ke watchlist.", parse_mode="HTML")


async def watchdel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Contoh: /watchdel BBCA.JK")
        return
    symbol = normalize_stock_symbol(context.args[0])
    items = [s for s in get_user_stock_watchlist(update.effective_user.id) if s != symbol]
    save_user_stock_watchlist(update.effective_user.id, items)
    await update.message.reply_text(f"✅ <b>{symbol}</b> dihapus dari watchlist.", parse_mode="HTML")


app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("analyze", analyze_cmd))
app.add_handler(CommandHandler("pair", pair_cmd))
app.add_handler(CommandHandler("tf", tf_cmd))
app.add_handler(CommandHandler("premium", premium_cmd))
app.add_handler(CommandHandler("approve", approve_cmd))
app.add_handler(CommandHandler("revoke", revoke_cmd))
app.add_handler(CommandHandler("myid", myid_cmd))
app.add_handler(CommandHandler("stock", stock_cmd))
app.add_handler(CommandHandler("stocks", stocks_cmd))
app.add_handler(CommandHandler("stocktop", stocktop_cmd))
app.add_handler(CommandHandler("heatmap", heatmap_cmd))
app.add_handler(CommandHandler("stocknews", stocknews_cmd))
app.add_handler(CommandHandler("watchlist", watchlist_cmd))
app.add_handler(CommandHandler("watchadd", watchadd_cmd))
app.add_handler(CommandHandler("watchdel", watchdel_cmd))
app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
app.add_handler(CallbackQueryHandler(button))

# Watchlist breakout alert every 1 hour
app.job_queue.run_repeating(
    stock_watch_alert_job,
    interval=3600,
    first=300
)

print("CAPITAL ELITE PROJECT NEW BOT ONLINE...")
app.run_polling()
