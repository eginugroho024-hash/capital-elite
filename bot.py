from tradingview_ta import TA_Handler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from datetime import datetime, timedelta
import json
import os
import re
import requests
import time as pytime

# ==============================
# CONFIG
# ==============================
import os

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ADMIN_ID = 7889334774  # ganti kalau ID admin lu beda
FMP_API_KEY = os.environ.get("FMP_API_KEY", "")
USER_FILE = "users.json"
TRIAL_LIMIT_MARKET = 5
TRIAL_LIMIT_NEWS = 3

# Isi pembayaran lu di sini
PAYMENT_TEXT = "DANA / QRIS: 085778001402"
ADMIN_CONTACT = "@egingroho"

PAIRS = {
    "XAUUSD": {
    "symbol": "XAUUSD",
    "screener": "cfd",
    "exchange": "FOREXCOM",
    "name": "XAU/USD"
},
    "XAGUSD": {
    "symbol": "SILVER",
    "screener": "cfd",
    "exchange": "TVC",
    "name": "XAG/USD"
},
    "BTCUSD": {"symbol": "BTCUSD", "screener": "crypto", "exchange": "BITSTAMP", "name": "BTC/USD"},
    "ETHUSD": {"symbol": "ETHUSD", "screener": "crypto", "exchange": "BITSTAMP", "name": "ETH/USD"},
}

TIMEFRAMES = {
    "M1": "1m", "M3": "3m", "M5": "5m", "M15": "15m",
    "M30": "30m", "H1": "1h", "H4": "4h", "DAILY": "1d",
}

IMPORTANT_NEWS_KEYWORDS = [
    "Non-Farm", "Nonfarm", "NFP", "CPI", "Core CPI", "FOMC",
    "Federal Funds Rate", "Fed Interest Rate", "PMI", "ISM", "Manufacturing PMI",
    "Services PMI", "PCE", "Core PCE", "Unemployment Rate", "Average Hourly Earnings"
]

# ==============================
# USER DATABASE
# ==============================
def load_users():
    if not os.path.exists(USER_FILE):
        return {}
    try:
        with open(USER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_users(users):
    with open(USER_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=4)


def get_user(user_id):
    users = load_users()
    uid = str(user_id)

    if uid not in users:
        users[uid] = {
            "market_used": 0,
            "news_used": 0,
            "premium": False,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        save_users(users)

    # Admin otomatis premium
    if int(uid) == ADMIN_ID:
        users[uid]["premium"] = True
        save_users(users)

    return users[uid]


def update_user(user_id, data):
    users = load_users()
    users[str(user_id)] = data
    save_users(users)


def can_use_market(user_id):
    user = get_user(user_id)
    return user["premium"] or user["market_used"] < TRIAL_LIMIT_MARKET


def can_use_news(user_id):
    user = get_user(user_id)
    return user["premium"] or user["news_used"] < TRIAL_LIMIT_NEWS


def add_market_usage(user_id):
    user = get_user(user_id)
    if not user["premium"]:
        user["market_used"] += 1
        update_user(user_id, user)


def add_news_usage(user_id):
    user = get_user(user_id)
    if not user["premium"]:
        user["news_used"] += 1
        update_user(user_id, user)

# ==============================
# HELPERS
# ==============================
def fmt(x):
    try:
        return f"{float(x):.2f}"
    except Exception:
        return "-"


def conf_bar(conf):
    full = int(conf / 10)
    return "█" * full + "░" * (10 - full)


def clean_num(value):
    if value is None:
        return None
    value = str(value).replace(",", "").replace("%", "").replace("K", "").replace("M", "")
    m = re.search(r"-?\d+(\.\d+)?", value)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None


def dynamic_sl_tp(pair_key, signal, entry, high, low):
    rng = abs(high - low)

    if pair_key == "XAUUSD":
        min_sl, min_tp = 3.0, 6.0
        max_sl, max_tp = 4.0, 10.0
    elif pair_key == "XAGUSD":
        min_sl, min_tp = 0.12, 0.25
        max_sl, max_tp = 0.20, 0.45
    elif pair_key == "BTCUSD":
        min_sl, min_tp = 120, 250
        max_sl, max_tp = 250, 600
    else:  # ETHUSD
        min_sl, min_tp = 10, 25
        max_sl, max_tp = 20, 50

    sl_dist = max(min_sl, min(rng * 1.2, max_sl))
    tp_dist = max(min_tp, min(sl_dist * 2.2, max_tp))

    if signal == "BUY":
        return entry - sl_dist, entry + tp_dist
    return entry + sl_dist, entry - tp_dist

# ==============================
# MARKET ANALYSIS: CAPITAL ELITE SMC ENGINE
# ==============================
def get_market_analysis(pair_key, tf_key):
    pair = PAIRS[pair_key]

    tf_key = str(tf_key).upper().strip()

    if tf_key not in TIMEFRAMES:
        tf_key = "M5"

    def fetch_tf(tf):
        tv_interval = TIMEFRAMES.get(tf, "5m")

        handler = TA_Handler(
            symbol=pair["symbol"],
            screener=pair["screener"],
            exchange=pair["exchange"],
            interval=tv_interval
        )
        data = handler.get_analysis()
        ind = data.indicators
        summ = data.summary

        price = ind.get("close")
        open_price = ind.get("open")
        high = ind.get("high")
        low = ind.get("low")
        ema20 = ind.get("EMA20")
        ema50 = ind.get("EMA50")
        rsi = ind.get("RSI")
        rec = summ.get("RECOMMENDATION", "NEUTRAL")

        if price is None or high is None or low is None:
            raise Exception("Data market belum lengkap.")

        price = float(price)
        open_price = float(open_price) if open_price else price
        high = float(high)
        low = float(low)
        ema20 = float(ema20) if ema20 else price
        ema50 = float(ema50) if ema50 else price
        rsi = float(rsi) if rsi else 50.0
        eq = (high + low) / 2
        rng = max(abs(high - low), 0.0001)
        candle = "BULLISH" if price > open_price else "BEARISH"

        if rec in ["BUY", "STRONG_BUY"] or price > ema20 > ema50:
            bias = "BULLISH"
        elif rec in ["SELL", "STRONG_SELL"] or price < ema20 < ema50:
            bias = "BEARISH"
        else:
            bias = "SIDEWAYS"

        return {
            "price": price, "open": open_price, "high": high, "low": low,
            "eq": eq, "range": rng, "bias": bias, "candle": candle,
            "rsi": rsi, "rec": rec, "ema20": ema20, "ema50": ema50
        }

    try:
        tf_data = fetch_tf(tf_key)
        pytime.sleep(1.6)

        h1 = fetch_tf("H1") if tf_key != "H1" else tf_data
        pytime.sleep(1.6)

        m15 = fetch_tf("M15") if tf_key != "M15" else tf_data
        pytime.sleep(1.6)

        m5 = fetch_tf("M5") if tf_key != "M5" else tf_data

    except Exception as e:
        return f"""
👑 <b>CAPITAL ELITE PROJECT</b>

⚠️ <b>DEBUG ERROR</b>

Type:
{type(e).__name__}

Detail:
{str(e)}
"""

    price = tf_data["price"]
    market_range = tf_data["range"]
    h1_bias = h1["bias"]
    m15_bias = m15["bias"]
    m5_bias = m5["bias"]

    # Session WIB
    wib_now = datetime.utcnow() + timedelta(hours=7)
    hour = wib_now.hour
    if 5 <= hour < 14:
        session_tag = "Asia"
        session_score = 4
    elif 14 <= hour < 20:
        session_tag = "London"
        session_score = 10
    else:
        session_tag = "New York"
        session_score = 10

    # ==============================
    # SMC PROXY ENGINE
    # ==============================
    # Karena tradingview_ta tidak memberi candle history penuh, engine ini pakai proxy:
    # HTF bias, premium/discount, liquidity sweep range, dan trigger M5.
    htf_bull = h1_bias == "BULLISH"
    htf_bear = h1_bias == "BEARISH"
    setup_bull = m15_bias in ["BULLISH", "SIDEWAYS"]
    setup_bear = m15_bias in ["BEARISH", "SIDEWAYS"]

    in_discount = price <= m15["eq"]
    in_premium = price >= m15["eq"]
    sell_side_swept = (m5["low"] <= m15["low"]) or (price <= m5["eq"])
    buy_side_swept = (m5["high"] >= m15["high"]) or (price >= m5["eq"])
    bullish_mss = (m5["candle"] == "BULLISH") or (price > m5["ema20"])
    bearish_mss = (m5["candle"] == "BEARISH") or (price < m5["ema20"])

    # Tentukan arah terbaik: tidak harus sempurna, agar bot tetap kasih area.
    buy_score = 0
    sell_score = 0
    if htf_bull: buy_score += 28
    if htf_bear: sell_score += 28
    if setup_bull: buy_score += 18
    if setup_bear: sell_score += 18
    if in_discount: buy_score += 15
    if in_premium: sell_score += 15
    if sell_side_swept: buy_score += 12
    if buy_side_swept: sell_score += 12
    if bullish_mss: buy_score += 12
    if bearish_mss: sell_score += 12
    buy_score += session_score
    sell_score += session_score

    signal = "BUY" if buy_score >= sell_score else "SELL"
    confidence = min(max(buy_score if signal == "BUY" else sell_score, 45), 96)

    # V2 rule: bot jangan kebanyakan NO SETUP.
    # 80+  = Execute small
    # 60-79 = Retest entry tetap keluar area
    # <60  = baru NO SETUP
    score_gap = abs(buy_score - sell_score)
    true_no_setup = confidence < 60

    if pair_key == "XAUUSD":
        sl_dist = max(3.0, min(market_range * 0.85, 6.0))
    elif pair_key == "XAGUSD":
        sl_dist = max(0.12, min(market_range * 0.85, 0.28))
    elif pair_key == "BTCUSD":
        sl_dist = max(120, min(market_range * 0.85, 350))
    else:
        sl_dist = max(10, min(market_range * 0.85, 40))

    # Entry logic: aggressive = anti ketinggalan moment, sniper = minim floating.
    if signal == "BUY":
        aggressive_low = price - (sl_dist * 0.15)
        aggressive_high = price + (sl_dist * 0.08)
        sniper_low = min(price, m15["eq"]) - (sl_dist * 0.35)
        sniper_high = min(price, m15["eq"]) - (sl_dist * 0.10)
        sl = min(m5["low"], m15["low"], sniper_low - (sl_dist * 0.55))
        tp1 = price + (sl_dist * 1.1)
        tp2 = price + (sl_dist * 2.0)
        tp3 = price + (sl_dist * 3.0)
        signal_label = "🟢 BUY SETUP"
        poi_label = "Discount POI"
        sweep_label = "Sell-side sweep"
        mss_label = "Bullish trigger"
        htf_text = "H1 bullish bias" if htf_bull else "H1 belum full bullish"
        invalid_text = "Invalid kalau low POI jebol kuat."
    else:
        aggressive_low = price - (sl_dist * 0.08)
        aggressive_high = price + (sl_dist * 0.15)
        sniper_low = max(price, m15["eq"]) + (sl_dist * 0.10)
        sniper_high = max(price, m15["eq"]) + (sl_dist * 0.35)
        sl = max(m5["high"], m15["high"], sniper_high + (sl_dist * 0.55))
        tp1 = price - (sl_dist * 1.1)
        tp2 = price - (sl_dist * 2.0)
        tp3 = price - (sl_dist * 3.0)
        signal_label = "🔴 SELL SETUP"
        poi_label = "Premium POI"
        sweep_label = "Buy-side sweep"
        mss_label = "Bearish trigger"
        htf_text = "H1 bearish bias" if htf_bear else "H1 belum full bearish"
        invalid_text = "Invalid kalau high POI jebol kuat."

    confidence_bar = conf_bar(confidence)
    entry_mid = (aggressive_low + aggressive_high) / 2
    rr = round(abs(tp2 - entry_mid) / max(abs(entry_mid - sl), 0.0001), 1)

    if confidence >= 80:
        mode = "🚀 <b>EXECUTE SMALL</b>"
        vibe = "Setup cakep. Masuk kecil boleh, add pas retest."
    elif confidence >= 65:
        mode = "🟡 <b>RETEST ENTRY</b>"
        vibe = "Setup ada, jangan cuma nunggu doang. Pakai Sniper buat minim floating."
    else:
        mode = "⚪ <b>NO SETUP</b>"
        vibe = "Market belum worth it. Simpan peluru."

    if true_no_setup:
        return f"""
👑 <b>CAPITAL ELITE PROJECT</b>

💱 <b>{pair['name']}</b> | <b>{tf_key}</b>
⚪ <b>NO SETUP</b>

📊 Confidence <b>{confidence}%</b>
{confidence_bar}

🧠 <b>Market Read</b>
• HTF belum clean
• Momentum dua arah masih tarik-tarikan
• Belum ada edge yang enak buat akun kecil

🛡️ <b>Small Account Rule</b>
Jangan maksa entry kalau RR belum jelas.
Better miss than MC.

⚠️ <b>DISCLAIMER</b>
Bukan saran finansial.
Trading mengandung risiko — kelola modal dengan bijak.
"""

    return f"""
👑 <b>CAPITAL ELITE PROJECT V2</b>
<code>SMC Signal Desk</code>

💱 <b>{pair['name']}</b> | <b>{tf_key}</b> • {session_tag}
<b>{signal_label}</b>

⚡ <b>Gas Kecil</b>
<code>{fmt(aggressive_low)} - {fmt(aggressive_high)}</code>

💎 <b>Sniper Zone</b>
<code>{fmt(sniper_low)} - {fmt(sniper_high)}</code>

🛑 <b>SL</b> <code>{fmt(sl)}</code>
🎯 <b>TP</b> <code>{fmt(tp1)}</code> | <code>{fmt(tp2)}</code> | <code>{fmt(tp3)}</code>
⚖️ <b>RR</b> 1:{rr}

📊 Confidence <b>{confidence}%</b>
{confidence_bar}

🧠 <b>Alasan Entry</b>
• {htf_text}
• {poi_label}
• {sweep_label}
• {mss_label}

{mode}
<i>{vibe}</i>

🛡️ <b>Mode Akun Kecil</b>
Entry kecil dulu. Add cuma kalau retest valid.
{invalid_text}

⚠️ <b>DISCLAIMER</b>
Bukan saran finansial.
Trading mengandung risiko — kelola modal dengan bijak.
"""

# ==============================
# NEWS IMPACT ENGINE
# ==============================
def parse_forex_factory_today():
    """
    Scrape Forex Factory calendar. Gratis, tapi bisa gagal kalau website block request.
    Kalau gagal, bot tetap punya manual analyzer lewat /news dan /fomc.
    """
    url = "https://www.forexfactory.com/calendar"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        r = requests.get(url, headers=headers, timeout=15)
        html = r.text

        # Regex ringan: ambil blok sekitar event USD. Struktur FF bisa berubah kapan saja.
        # Karena FF sering ubah HTML, ini dibuat fallback-friendly.
        events = []
        rows = re.findall(r"<tr[^>]*calendar__row[^>]*>(.*?)</tr>", html, flags=re.S | re.I)

        for row in rows:
            txt = re.sub(r"<[^>]+>", " ", row)
            txt = re.sub(r"\s+", " ", txt).strip()

            if " USD " not in (" " + txt + " "):
                continue

            if not any(k.lower() in txt.lower() for k in IMPORTANT_NEWS_KEYWORDS):
                continue

            impact = "HIGH" if "High Impact" in row or "impact--high" in row else "NEWS"
            events.append({"raw": txt, "impact": impact})

        return events[:8]
    except Exception:
        return []


def analyze_news_result(news_type, actual, forecast, previous=None):
    nt = news_type.lower()
    actual_num = clean_num(actual)
    forecast_num = clean_num(forecast)

    if actual_num is None or forecast_num is None:
        return "Format angka tidak valid. Contoh: /news cpi actual=3.2 forecast=3.4 previous=3.5"

    usd_bias = "NEUTRAL"
    market_reason = "Actual sama dengan forecast. Market bisa choppy."
    confidence = 65

    # CPI/PCE: lebih tinggi = inflasi kuat = USD bullish, gold/crypto bearish
    if "cpi" in nt or "pce" in nt:
        if actual_num > forecast_num:
            usd_bias = "BULLISH"
            market_reason = "Inflasi lebih tinggi dari forecast. Potensi Fed lebih hawkish."
            confidence = 88
        elif actual_num < forecast_num:
            usd_bias = "BEARISH"
            market_reason = "Inflasi lebih rendah dari forecast. Potensi Fed lebih dovish."
            confidence = 88

    # NFP/PMI/ISM/Unemployment earnings general rules
    elif "nfp" in nt or "nonfarm" in nt or "pmi" in nt or "ism" in nt or "jobs" in nt:
        if actual_num > forecast_num:
            usd_bias = "BULLISH"
            market_reason = "Data ekonomi lebih kuat dari forecast. USD cenderung menguat."
            confidence = 86
        elif actual_num < forecast_num:
            usd_bias = "BEARISH"
            market_reason = "Data ekonomi lebih lemah dari forecast. USD cenderung melemah."
            confidence = 86

    # Unemployment rate kebalik: angka lebih tinggi = USD bearish
    if "unemployment" in nt:
        if actual_num > forecast_num:
            usd_bias = "BEARISH"
            market_reason = "Unemployment lebih tinggi dari forecast. USD cenderung melemah."
            confidence = 86
        elif actual_num < forecast_num:
            usd_bias = "BULLISH"
            market_reason = "Unemployment lebih rendah dari forecast. USD cenderung menguat."
            confidence = 86

    if usd_bias == "BULLISH":
        xau = "SELL"
        xag = "SELL"
        btc = "SELL / RISK-OFF"
        eth = "SELL / RISK-OFF"
    elif usd_bias == "BEARISH":
        xau = "BUY"
        xag = "BUY"
        btc = "BUY / RISK-ON"
        eth = "BUY / RISK-ON"
    else:
        xau = xag = btc = eth = "WAIT FOR VOLATILITY"

    now = datetime.now().strftime("%d-%m-%Y %H:%M WIB")

    return f"""
⬜━━━━━━━━━━━━━━━━━━━━⬜
🚨 <b>NEWS IMPACT ANALYSIS</b>
⬜━━━━━━━━━━━━━━━━━━━━⬜

📅 <b>Waktu</b>     : {now}
📰 <b>News</b>      : <b>{news_type.upper()}</b>
📊 <b>Actual</b>    : <code>{actual}</code>
📈 <b>Forecast</b>  : <code>{forecast}</code>
📉 <b>Previous</b>  : <code>{previous if previous else '-'}</code>

⬜━━━━━━━━━━━━━━━━━━━━⬜
🤖 <b>AI VERDICT</b>
⬜━━━━━━━━━━━━━━━━━━━━⬜

💵 <b>USD Bias</b>   : <b>{usd_bias}</b>
🎯 <b>Confidence</b> : <b>{confidence}%</b> {conf_bar(confidence)}

🥇 XAU/USD : <b>{xau}</b>
🥈 XAG/USD : <b>{xag}</b>
₿ BTC/USD : <b>{btc}</b>
♦ ETH/USD : <b>{eth}</b>

✅ <b>Reason</b>:
{market_reason}

⬜━━━━━━━━━━━━━━━━━━━━⬜
⚠️ <b>NEWS TRADING RULE</b>
⬜━━━━━━━━━━━━━━━━━━━━⬜

<i>Jangan entry di detik rilis news.
Tunggu 1-2 candle M5 close, spread normal, lalu cari retest.</i>

🤍 <b>Capital Elite Project — News Engine</b>
"""


def analyze_fomc(tone):
    t = tone.lower()
    if "hawk" in t or "naik" in t or "higher" in t:
        usd = "BULLISH"
        xau = "SELL"
        btc = "SELL / RISK-OFF"
        reason = "Nada FOMC hawkish. Market melihat peluang suku bunga lebih tinggi/lebih lama."
        conf = 88
    elif "dov" in t or "turun" in t or "cut" in t:
        usd = "BEARISH"
        xau = "BUY"
        btc = "BUY / RISK-ON"
        reason = "Nada FOMC dovish. Market melihat peluang pelonggaran kebijakan."
        conf = 88
    else:
        usd = "NEUTRAL"
        xau = "WAIT"
        btc = "WAIT"
        reason = "Tone FOMC belum jelas. Tunggu press conference dan reaksi candle."
        conf = 65

    return f"""
⬜━━━━━━━━━━━━━━━━━━━━⬜
🏦 <b>FOMC IMPACT ANALYSIS</b>
⬜━━━━━━━━━━━━━━━━━━━━⬜

🧠 <b>Tone</b>      : <b>{tone.upper()}</b>
💵 <b>USD Bias</b>  : <b>{usd}</b>
🎯 <b>Confidence</b>: <b>{conf}%</b> {conf_bar(conf)}

🥇 XAU/USD : <b>{xau}</b>
🥈 XAG/USD : <b>{xau}</b>
₿ BTC/USD : <b>{btc}</b>
♦ ETH/USD : <b>{btc}</b>

✅ <b>Reason</b>:
{reason}

⚠️ Tunggu 1-2 candle M5 setelah statement/press conference.
"""

# ==============================
# MENUS
# ==============================
def main_menu(user_id):
    user = get_user(user_id)

    if user["premium"]:
        status_line = "💎 <b>ELITE MEMBER</b>"
        access_line = "Unlimited signal access"
    else:
        market_left = TRIAL_LIMIT_MARKET - user["market_used"]
        news_left = TRIAL_LIMIT_NEWS - user["news_used"]
        status_line = "🆓 <b>TRIAL MODE</b>"
        access_line = f"Market {market_left}x • News {news_left}x"

    text = f"""
👑 <b>CAPITAL ELITE PROJECT</b>
<code>SMC Signal Bot Dan Analisa</code>

{status_line}
{access_line}

📊 <b>Market Scan</b>
Aggressive • Sniper • SL • TP

🧠 <b>SMC Engine</b>
HTF Bias • Liquidity • POI • MSS

📰 <b>News Desk</b>
CPI • NFP • FOMC • PMI

🟢 <b>Engine Online</b>
Gas pilih menu di bawah

link group ada di bio
"""

    keyboard = [
        [InlineKeyboardButton("📊 Scan Market", callback_data="menu_pairs")],
        [InlineKeyboardButton("📰 News Desk", callback_data="menu_news")],
        [InlineKeyboardButton("👤 Akun", callback_data="account")],
        [InlineKeyboardButton("💎 Upgrade", callback_data="upgrade")],
    ]
    return text, InlineKeyboardMarkup(keyboard)

# ==============================
# TELEGRAM HANDLERS
# ==============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, keyboard = main_menu(update.effective_user.id)
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id
    user = get_user(user_id)
    data = q.data

    if data == "menu_pairs":
        if not can_use_market(user_id):
            await q.edit_message_text(
                "🚫 <b>FREE TRIAL MARKET HABIS</b>\n\nUpgrade premium untuk akses unlimited.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 Upgrade Premium", callback_data="upgrade")]]),
                parse_mode="HTML"
            )
            return
        keyboard = [
            [InlineKeyboardButton("🥇 XAU/USD", callback_data="pair_XAUUSD"), InlineKeyboardButton("🥈 XAG/USD", callback_data="pair_XAGUSD")],
            [InlineKeyboardButton("₿ BTC/USD", callback_data="pair_BTCUSD"), InlineKeyboardButton("♦ ETH/USD", callback_data="pair_ETHUSD")],
            [InlineKeyboardButton("⬅️ Kembali", callback_data="back_start")]
        ]
        await q.edit_message_text("🏆 <b>Kategori: Komoditas & Crypto</b>\n\nPilih pair:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data.startswith("pair_"):
        pair_key = data.replace("pair_", "")
        keyboard = [
            [InlineKeyboardButton("M1", callback_data=f"tf_{pair_key}_M1"), InlineKeyboardButton("M3", callback_data=f"tf_{pair_key}_M3"), InlineKeyboardButton("M5", callback_data=f"tf_{pair_key}_M5")],
            [InlineKeyboardButton("M15", callback_data=f"tf_{pair_key}_M15"), InlineKeyboardButton("M30", callback_data=f"tf_{pair_key}_M30"), InlineKeyboardButton("H1", callback_data=f"tf_{pair_key}_H1")],
            [InlineKeyboardButton("H4", callback_data=f"tf_{pair_key}_H4"), InlineKeyboardButton("DAILY", callback_data=f"tf_{pair_key}_DAILY")],
            [InlineKeyboardButton("⬅️ Kembali", callback_data="menu_pairs")]
        ]
        await q.edit_message_text(f"💱 <b>{PAIRS[pair_key]['name']}</b>\n\nPilih timeframe:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data.startswith("tf_"):
        if not can_use_market(user_id):
            await q.edit_message_text("🚫 <b>FREE TRIAL MARKET HABIS</b>\n\nUpgrade premium untuk akses unlimited.", parse_mode="HTML")
            return
        parts = data.split("_")
        pair_key, tf_key = parts[1], parts[2]
        await q.edit_message_text("🔍 Scanning liquidity...\n⚡ Validating POI...\n🧠 Building setup...")
        try:
            hasil = get_market_analysis(pair_key, tf_key)
            add_market_usage(user_id)
            user = get_user(user_id)
            if not user["premium"]:
                hasil += f"\n\n🆓 Sisa trial market: {TRIAL_LIMIT_MARKET - user['market_used']} analisa"
        except Exception as e:
            hasil = "Error ambil data market: " + str(e)
        keyboard = [[InlineKeyboardButton("🔁 Analisa Lagi", callback_data=f"pair_{pair_key}")], [InlineKeyboardButton("🏠 Menu Utama", callback_data="back_start")]]
        await q.edit_message_text(hasil, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data == "menu_news":
        if not can_use_news(user_id):
            await q.edit_message_text("🚫 <b>FREE TRIAL NEWS HABIS</b>\n\nUpgrade premium untuk akses unlimited.", parse_mode="HTML")
            return
        keyboard = [
            [InlineKeyboardButton("📅 Forex Factory Today", callback_data="news_ff")],
            [InlineKeyboardButton("📌 Cara Input Manual", callback_data="news_manual_help")],
            [InlineKeyboardButton("⬅️ Kembali", callback_data="back_start")]
        ]
        await q.edit_message_text("📰 <b>NEWS IMPACT ENGINE</b>\n\nPilih menu news:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data == "news_ff":
        if not can_use_news(user_id):
            await q.edit_message_text("🚫 <b>FREE TRIAL NEWS HABIS</b>\n\nUpgrade premium untuk akses unlimited.", parse_mode="HTML")
            return
        await q.edit_message_text("⏳ Mengambil data Forex Factory...")
        events = parse_forex_factory_today()
        add_news_usage(user_id)
        if events:
            text = "⬜━━━━━━━━━━━━━━━━━━━━⬜\n📰 <b>FOREX FACTORY TODAY</b>\n⬜━━━━━━━━━━━━━━━━━━━━⬜\n\n"
            for idx, ev in enumerate(events, 1):
                text += f"<b>{idx}. USD {ev['impact']}</b>\n{ev['raw']}\n\n"
            text += "Gunakan command manual setelah actual keluar:\n<code>/news cpi actual=3.2 forecast=3.4 previous=3.5</code>"
        else:
            text = "⚠️ Forex Factory gagal dibaca / tidak ada news USD penting.\n\nGunakan manual:\n<code>/news nfp actual=250 forecast=180 previous=190</code>\n<code>/fomc hawkish</code>"
        user = get_user(user_id)
        if not user["premium"]:
            text += f"\n\n🆓 Sisa trial news: {TRIAL_LIMIT_NEWS - user['news_used']}"
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu Utama", callback_data="back_start")]]), parse_mode="HTML")

    elif data == "news_manual_help":
        text = """
📰 <b>MANUAL NEWS ANALYZER</b>

Format:
<code>/news cpi actual=3.2 forecast=3.4 previous=3.5</code>
<code>/news nfp actual=250 forecast=180 previous=190</code>
<code>/news pmi actual=53.2 forecast=51.8 previous=50.9</code>
<code>/fomc hawkish</code>
<code>/fomc dovish</code>

Rule:
CPI tinggi = USD bullish = XAU cenderung bearish.
NFP/PMI tinggi = USD bullish = XAU cenderung bearish.
FOMC hawkish = USD bullish.
FOMC dovish = USD bearish.
"""
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="menu_news")]]), parse_mode="HTML")

    elif data == "account":
        user = get_user(user_id)
        status = "💎 PREMIUM" if user["premium"] else "🆓 FREE TRIAL"
        market_left = "Unlimited" if user["premium"] else f"{TRIAL_LIMIT_MARKET - user['market_used']} / {TRIAL_LIMIT_MARKET}"
        news_left = "Unlimited" if user["premium"] else f"{TRIAL_LIMIT_NEWS - user['news_used']} / {TRIAL_LIMIT_NEWS}"
        text = f"""
👤 <b>AKUN SAYA</b>

ID Telegram:
<code>{user_id}</code>

Status: <b>{status}</b>
Trial Market: <b>{market_left}</b>
Trial News: <b>{news_left}</b>
"""
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="back_start")]]), parse_mode="HTML")

    elif data == "upgrade":
        text = f"""
👑 <b>CAPITAL ELITE PROJECT</b>

💎 <b>ELITE ACCESS</b>
Bot signal SMC buat bantu cari area entry yang lebih presisi.

📊 Aggressive Entry
💎 Sniper Entry
🛑 Structure SL
🎯 TP Area
📰 News Impact
🧠 Edukasi Harian

💰 <b>Lifetime Access</b>
<s>Rp 499.000</s> 🔥 <b>Rp 299.000</b>

💳 <b>Payment</b>
<code>{PAYMENT_TEXT}</code>

📩 <b>Admin</b>
{ADMIN_CONTACT}

⚡ Setelah bayar, kirim bukti. Akses langsung diaktifin.
"""
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="back_start")]]), parse_mode="HTML")

    elif data == "back_start":
        text, keyboard = main_menu(user_id)
        await q.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")


async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not can_use_news(user_id):
        await update.message.reply_text("🚫 Free trial news habis. Upgrade premium untuk akses unlimited.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Format: /news cpi actual=3.2 forecast=3.4 previous=3.5")
        return

    news_type = context.args[0]
    raw = " ".join(context.args[1:])
    actual = re.search(r"actual=([^\s]+)", raw, re.I)
    forecast = re.search(r"forecast=([^\s]+)", raw, re.I)
    previous = re.search(r"previous=([^\s]+)", raw, re.I)

    if not actual or not forecast:
        await update.message.reply_text("Format salah. Contoh: /news nfp actual=250 forecast=180 previous=190")
        return

    hasil = analyze_news_result(news_type, actual.group(1), forecast.group(1), previous.group(1) if previous else None)
    add_news_usage(user_id)
    await update.message.reply_text(hasil, parse_mode="HTML")


async def fomc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not can_use_news(user_id):
        await update.message.reply_text("🚫 Free trial news habis. Upgrade premium untuk akses unlimited.")
        return
    if len(context.args) < 1:
        await update.message.reply_text("Format: /fomc hawkish atau /fomc dovish")
        return
    tone = " ".join(context.args)
    hasil = analyze_fomc(tone)
    add_news_usage(user_id)
    await update.message.reply_text(hasil, parse_mode="HTML")


async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Lu bukan admin.")
        return
    if len(context.args) < 1:
        await update.message.reply_text("Format: /premium ID_TELEGRAM")
        return
    target_id = context.args[0]
    users = load_users()
    if target_id not in users:
        users[target_id] = {"market_used": 0, "news_used": 0, "premium": True, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    else:
        users[target_id]["premium"] = True
    save_users(users)
    await update.message.reply_text(f"User {target_id} sudah PREMIUM.")


async def unpremium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Lu bukan admin.")
        return
    if len(context.args) < 1:
        await update.message.reply_text("Format: /unpremium ID_TELEGRAM")
        return
    target_id = context.args[0]
    users = load_users()
    if target_id in users:
        users[target_id]["premium"] = False
        save_users(users)
    await update.message.reply_text(f"Premium user {target_id} dicabut.")


async def cekuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Lu bukan admin.")
        return
    if len(context.args) < 1:
        await update.message.reply_text("Format: /cekuser ID_TELEGRAM")
        return
    uid = context.args[0]
    users = load_users()
    if uid not in users:
        await update.message.reply_text("User belum ada di database.")
        return
    u = users[uid]
    await update.message.reply_text(f"ID: {uid}\nPremium: {u.get('premium')}\nMarket used: {u.get('market_used')}\nNews used: {u.get('news_used')}")


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Lu bukan admin.")
        return
    msg = " ".join(context.args)
    if not msg:
        await update.message.reply_text("Format: /broadcast pesan")
        return
    users = load_users()
    sent = 0
    for uid, u in users.items():
        if u.get("premium"):
            try:
                await context.bot.send_message(chat_id=int(uid), text=msg, parse_mode="HTML")
                sent += 1
            except Exception:
                pass
    await update.message.reply_text(f"Broadcast terkirim ke {sent} premium user.")


EDUKASI_TIPS = [
    "Jangan cari entry sempurna. Cari risk yang masih aman kalau salah.",
    "Akun kecil grow bukan dari overlot, tapi dari survive lebih lama.",
    "Kalau SL bikin deg-degan, lot lu kebesaran. Simple.",
    "Setup A+ tetap bisa loss. Yang penting akun masih hidup buat setup berikutnya.",
    "Jangan entry karena FOMO. Entry karena area, validasi, dan RR masuk akal.",
    "Profit kecil konsisten lebih sehat daripada sekali jackpot lalu MC.",
    "No trade itu posisi juga. Trader sabar biasanya hidup lebih lama.",
]

async def risk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Format: /risk 100000 5\nArtinya modal 100rb, risk 5% per trade.")
        return
    modal = clean_num(context.args[0])
    risk_pct = clean_num(context.args[1])
    if not modal or not risk_pct:
        await update.message.reply_text("Format salah. Contoh: /risk 100000 5")
        return
    risk_money = modal * risk_pct / 100
    daily_max = modal * min(risk_pct * 2, 10) / 100
    text = f"""
👑 <b>CAPITAL ELITE PROJECT</b>

🛡️ <b>Risk Plan</b>
Modal: <code>Rp{modal:,.0f}</code>
Risk: <code>{risk_pct}%</code>
Max loss/trade: <code>Rp{risk_money:,.0f}</code>
Max loss harian: <code>Rp{daily_max:,.0f}</code>

📌 <b>Rule akun kecil</b>
• Max 2-3 trade/hari
• Stop kalau kena 2x SL
• Minimal RR 1:2
• Jangan overlot buat balas dendam

<i>Goal pertama bukan kaya cepat. Goal pertama: akun jangan MC.</i>
"""
    await update.message.reply_text(text, parse_mode="HTML")

async def edukasi_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Command ini khusus admin.")
        return
    import random
    tip = random.choice(EDUKASI_TIPS)
    text = f"""
👑 <b>CAPITAL ELITE PROJECT</b>

🧠 <b>Elite Mindset Drop</b>
{tip}

📌 <b>Reminder</b>
Entry bagus + lot kebesaran = tetap bahaya.
Jaga risk, biar akun kecil bisa napas.

⚠️ Bukan saran finansial.
"""
    users = load_users()
    sent = 0
    for uid, u in users.items():
        if u.get("premium"):
            try:
                await context.bot.send_message(chat_id=int(uid), text=text, parse_mode="HTML")
                sent += 1
            except Exception:
                pass
    await update.message.reply_text(f"Edukasi terkirim ke {sent} premium user.")

async def marketnews_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Command ini khusus admin.")
        return
    events = parse_forex_factory_today()
    if events:
        news_lines = ""
        for ev in events[:5]:
            news_lines += f"• USD {ev['impact']} — {ev['raw'][:90]}\n"
    else:
        news_lines = "• Tidak ada data high impact terbaca. Tetap cek kalender manual sebelum entry.\n"
    today = (datetime.utcnow() + timedelta(hours=7)).strftime("%d %b %Y")
    text = f"""
👑 <b>CAPITAL ELITE PROJECT</b>

🚨 <b>Market Brief — {today}</b>

📰 <b>News Watch</b>
{news_lines}
📊 <b>Trading Note</b>
• Hindari entry 5 menit sebelum news besar
• Tunggu spread normal
• Cari sweep liquidity + retest POI

⚠️ Bukan saran finansial.
"""
    users = load_users()
    sent = 0
    for uid, u in users.items():
        if u.get("premium"):
            try:
                await context.bot.send_message(chat_id=int(uid), text=text, parse_mode="HTML")
                sent += 1
            except Exception:
                pass
    await update.message.reply_text(f"Market news terkirim ke {sent} premium user.")
import random

async def auto_broadcast(context):
    pesan = random.choice([
        """📢 Mau Akses Bot Analisa Trading?

✅ Analisa Market Harian
✅ Area Entry Potensial
✅ Market Outlook
✅ Update News Penting

💬 Chat Admin untuk mendapatkan akses.

⚠️ DISCLAIMER

Bukan saran finansial (Not Financial Advice).

Trading forex, crypto, dan instrumen keuangan lainnya memiliki risiko tinggi dan dapat menyebabkan kerugian sebagian maupun seluruh modal.
""",

        """🚀 Trading Lebih Terarah

Jangan asal buy atau sell tanpa rencana.

🎯 Tunggu setup
🎯 Kelola risiko
🎯 Ikuti disiplin

💬 Chat Admin untuk mendapatkan akses.

⚠️ DISCLAIMER

Bukan saran finansial (Not Financial Advice).

Segala keputusan trading sepenuhnya menjadi tanggung jawab masing-masing pengguna.
"""
    ])

    users = load_users()

    for uid in users.keys():
        try:
            await context.bot.send_message(
                chat_id=int(uid),
                text=pesan
            )
        except:
            pass
async def auto_news_alert(context):
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        url = f"https://financialmodelingprep.com/api/v3/economic_calendar?from={today}&to={today}&apikey={FMP_API_KEY}"

        response = requests.get(url, timeout=10)
        data = response.json()
        users = load_users()

        for event in data:
            event_name = str(event.get("event", "")).lower()
            country = str(event.get("country", "")).upper()

            if country == "USD" and (
                "cpi" in event_name or
                "consumer price index" in event_name or
                "core cpi" in event_name or
                "nfp" in event_name or
                "fomc" in event_name
            ):
                text = f"""
📰 CAPITAL ELITE NEWS ALERT

🔥 High Impact News Detected

Event:
{event.get('event')}

Country:
{country}

Date:
{event.get('date')}

⚠️ Hindari entry besar menjelang news.
Tunggu market kasih arah yang jelas.

⚠️ Not Financial Advice
Trading memiliki risiko tinggi.
"""

                for uid in users.keys():
                    try:
                        await context.bot.send_message(chat_id=int(uid), text=text)
                    except:
                        pass

    except Exception as e:
        print("NEWS ERROR:", e)

# ===========================
# RUN APP
# ==============================
# RUN APP
# ==============================
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("news", news_command))
app.add_handler(CommandHandler("fomc", fomc_command))
app.add_handler(CommandHandler("premium", premium))
app.add_handler(CommandHandler("unpremium", unpremium))
app.add_handler(CommandHandler("cekuser", cekuser))
app.add_handler(CommandHandler("broadcast", broadcast))
app.add_handler(CommandHandler("risk", risk_command))
app.add_handler(CommandHandler("edukasi", edukasi_command))
app.add_handler(CommandHandler("marketnews", marketnews_command))
app.add_handler(CallbackQueryHandler(button))

app.job_queue.run_repeating(
    auto_broadcast,
    interval=7200,
    first=300
)

from datetime import time as dt_time

app.job_queue.run_daily(
    auto_news_alert,
    time=dt_time(hour=0, minute=30)
)

print("CAPITAL ELITE PROJECT BOT ONLINE...")
app.run_polling()

