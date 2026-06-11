from tradingview_ta import TA_Handler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from datetime import datetime, timedelta
import json
import os
import re
import requests
import time as pytime

try:
    import yfinance as yf
except Exception:
    yf = None

# ==============================
# CONFIG
# ==============================
import os

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ADMIN_ID = 7889334774  # ganti kalau ID admin lu beda
FMP_API_KEY = os.environ.get("FMP_API_KEY", "")
USER_FILE = "users.json"
NEWS_SENT_FILE = "news_sent.json"
SIGNAL_LOG_FILE = "signal_log.json"
LAST_SIGNAL_FILE = "last_signal.json"
EXPIRED_REMINDER_FILE = "expired_reminder.json"
PENDING_PAYMENT_FILE = "pending_payment.json"
MARKET_CACHE = {}
MARKET_CACHE_SECONDS = 300
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

def load_json_file(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json_file(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def get_news_key(raw_text):
    raw_text = str(raw_text)
    compact = re.sub(r"\s+", " ", raw_text).strip().lower()
    return compact[:180]


def log_signal(asset, tf, result_text):
    logs = load_json_file(SIGNAL_LOG_FILE, [])
    logs.append({
        "asset": asset,
        "tf": tf,
        "time": wib_now().strftime("%Y-%m-%d %H:%M:%S"),
        "preview": re.sub(r"<[^>]+>", "", result_text)[:250]
    })
    logs = logs[-100:]
    save_json_file(SIGNAL_LOG_FILE, logs)

def extract_signal_key(signal_text):
    """
    Bikin fingerprint sinyal supaya auto signal tidak spam setup yang sama.
    """
    clean = re.sub(r"<[^>]+>", "", str(signal_text))
    direction = "BUY" if "BUY SETUP" in clean or "STRONG BUY" in clean else "SELL" if "SELL SETUP" in clean or "STRONG SELL" in clean else "UNKNOWN"

    entry_match = re.search(r"Entry:\s*([0-9.]+)\s*-\s*([0-9.]+)", clean, re.I)
    if entry_match:
        try:
            mid = (float(entry_match.group(1)) + float(entry_match.group(2))) / 2
            entry_bucket = round(mid, 1)
        except Exception:
            entry_bucket = "NA"
    else:
        recent_match = re.search(r"Recent Entry:\s*([0-9.]+)", clean, re.I)
        entry_bucket = recent_match.group(1) if recent_match else "NA"

    return f"{direction}_{entry_bucket}"


def should_send_auto_signal(asset, signal_text, cooldown_minutes=90):
    last_db = load_json_file(LAST_SIGNAL_FILE, {})
    key = extract_signal_key(signal_text)
    now = wib_now()

    last = last_db.get(asset)
    if last:
        try:
            last_time = datetime.strptime(last.get("time"), "%Y-%m-%d %H:%M:%S")
            same_key = last.get("key") == key
            still_cooldown = (now - last_time).total_seconds() < cooldown_minutes * 60
            if same_key and still_cooldown:
                return False
        except Exception:
            pass

    last_db[asset] = {
        "key": key,
        "time": now.strftime("%Y-%m-%d %H:%M:%S")
    }
    save_json_file(LAST_SIGNAL_FILE, last_db)
    return True


def has_high_impact_news_risk():
    """
    Simple guard: kalau Forex Factory kebaca ada CPI/NFP/FOMC/Rate/Powell hari ini,
    auto signal dipause. Manual analysis tetap bisa dipakai user.
    """
    try:
        events = parse_forex_factory_today()
        if not events:
            return False

        risk_terms = [
            "cpi", "core cpi", "consumer price index", "nfp", "non-farm", "nonfarm",
            "fomc", "federal funds rate", "interest rate", "powell"
        ]

        for ev in events:
            raw = str(ev.get("raw", "")).lower()
            if any(term in raw for term in risk_terms):
                return True
        return False
    except Exception:
        return False


def premium_expire_text(uid, days_left, premium_until):
    return f"""
⏳ <b>CAPITAL ELITE REMINDER</b>

Premium lu akan habis dalam <b>{days_left} hari</b>.

Expired:
<code>{premium_until}</code>

💎 Perpanjang akses:
{ADMIN_CONTACT}

⚠️ <b>Not Financial Advice</b>
Trading memiliki risiko tinggi.
"""



def get_user(user_id):
    users = load_users()
    uid = str(user_id)

    if uid not in users:
        users[uid] = {
            "market_used": 0,
            "news_used": 0,
            "premium": False,
            "premium_until": None,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        save_users(users)

    # Admin otomatis premium
    if int(uid) == ADMIN_ID:
        users[uid]["premium"] = True
        users[uid]["premium_until"] = "LIFETIME"
        save_users(users)
        return users[uid]

    # Auto-expire premium membership
    if users[uid].get("premium") and users[uid].get("premium_until") not in [None, "LIFETIME"]:
        try:
            expire_dt = datetime.strptime(users[uid]["premium_until"], "%Y-%m-%d %H:%M:%S")
            if datetime.now() > expire_dt:
                users[uid]["premium"] = False
                users[uid]["expired_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                save_users(users)
        except Exception:
            pass

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

def disclaimer_footer():
    return """
━━━━━━━━━━━━━━
⚠️ <b>Not Financial Advice</b>
Trading memiliki risiko tinggi.
Gunakan Stop Loss.
Kelola risiko dan modal dengan bijak.
━━━━━━━━━━━━━━
"""


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


def wib_now():
    return datetime.utcnow() + timedelta(hours=7)

def convert_ff_time_to_wib(raw_text):
    """
    Convert jam Forex Factory seperti 7:30am / 8:30pm ke WIB.
    Catatan: Forex Factory default sering tampil ET/New York.
    ET ke WIB:
    - Saat EDT (umumnya Mar-Nov): +11 jam
    - Saat EST (umumnya Nov-Mar): +12 jam
    Agar aman untuk mayoritas periode market aktif, default pakai +11 jam.
    """
    try:
        raw_text = str(raw_text).lower()
        match = re.search(r"(\d{1,2}):(\d{2})\s*(am|pm)", raw_text)
        if not match:
            return "WIB N/A"

        hour = int(match.group(1))
        minute = int(match.group(2))
        ampm = match.group(3)

        if ampm == "pm" and hour != 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0

        ff_time = datetime.utcnow().replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0
        )

        # Default Forex Factory ET/EDT -> WIB kira-kira +11 jam
        wib_time = ff_time + timedelta(hours=11)
        return wib_time.strftime("%H:%M WIB")

    except Exception:
        return "WIB N/A"


def clean_ff_event_text(raw_text):
    """
    Bersihin teks event Forex Factory biar tidak dobel jam.
    """
    raw_text = str(raw_text)
    raw_text = re.sub(r"\b\d{1,2}:\d{2}\s*(am|pm)\b", "", raw_text, flags=re.I)
    raw_text = re.sub(r"\s+", " ", raw_text).strip()
    return raw_text



def is_trade_signal_text(text):
    bad_words = ["DEBUG ERROR", "NO SETUP", "Market Engine", "ERROR"]
    return all(b not in text for b in bad_words)


def premium_users(users):
    result = []
    for uid, data in users.items():
        try:
            u = get_user(int(uid))
            if u.get("premium"):
                result.append(uid)
        except Exception:
            pass
    return result


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
# MARKET DATA FALLBACK + CACHE
# ==============================
def cache_get(key):
    item = MARKET_CACHE.get(key)
    if not item:
        return None
    age = pytime.time() - item.get("ts", 0)
    if age <= MARKET_CACHE_SECONDS:
        return item.get("value")
    return None


def cache_set(key, value):
    MARKET_CACHE[key] = {
        "ts": pytime.time(),
        "value": value
    }


def yf_symbol(pair_key):
    mapping = {
        "XAUUSD": "GC=F",
        "XAGUSD": "SI=F",
        "BTCUSD": "BTC-USD",
        "ETHUSD": "ETH-USD",
    }
    return mapping.get(pair_key, "GC=F")


def yf_interval(tf):
    mapping = {
        "M1": "1m",
        "M3": "5m",
        "M5": "5m",
        "M15": "15m",
        "M30": "30m",
        "H1": "60m",
        "H4": "60m",
        "DAILY": "1d",
    }
    return mapping.get(tf, "5m")


def yf_period(tf):
    if tf in ["M1", "M3", "M5", "M15", "M30"]:
        return "5d"
    if tf in ["H1", "H4"]:
        return "1mo"
    return "6mo"


def fetch_yfinance_data(pair_key, tf):
    if yf is None:
        raise Exception("Yahoo Finance fallback belum tersedia. Tambahkan yfinance di requirements.txt")

    symbol = yf_symbol(pair_key)
    interval = yf_interval(tf)
    period = yf_period(tf)

    data = yf.download(
        symbol,
        period=period,
        interval=interval,
        progress=False,
        auto_adjust=False
    )

    if data is None or data.empty:
        raise Exception("Yahoo Finance tidak mengembalikan data.")

    # Untuk H4, data 60m dipadatkan 4 candle terakhir sebagai proxy.
    if tf == "H4" and len(data) >= 4:
        block = data.tail(4)
        close = float(block["Close"].iloc[-1])
        open_price = float(block["Open"].iloc[0])
        high = float(block["High"].max())
        low = float(block["Low"].min())
    else:
        last = data.iloc[-1]
        close = float(last["Close"])
        open_price = float(last["Open"])
        high = float(last["High"])
        low = float(last["Low"])

    closes = data["Close"].astype(float)
    ema20 = float(closes.ewm(span=20, adjust=False).mean().iloc[-1]) if len(closes) >= 20 else close
    ema50 = float(closes.ewm(span=50, adjust=False).mean().iloc[-1]) if len(closes) >= 50 else close

    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, 0.0001)
    rsi_series = 100 - (100 / (1 + rs))
    rsi = float(rsi_series.iloc[-1]) if len(rsi_series.dropna()) else 50.0

    if close > ema20 > ema50:
        rec = "BUY"
        bias = "BULLISH"
    elif close < ema20 < ema50:
        rec = "SELL"
        bias = "BEARISH"
    else:
        rec = "NEUTRAL"
        bias = "SIDEWAYS"

    eq = (high + low) / 2
    rng = max(abs(high - low), 0.0001)
    candle = "BULLISH" if close > open_price else "BEARISH"

    return {
        "price": close,
        "open": open_price,
        "high": high,
        "low": low,
        "eq": eq,
        "range": rng,
        "bias": bias,
        "candle": candle,
        "rsi": rsi,
        "rec": rec,
        "ema20": ema20,
        "ema50": ema50,
        "source": "Yahoo Finance Fallback"
    }


# ==============================
# MARKET ANALYSIS: CAPITAL ELITE SMC ENGINE
# ==============================
def get_market_analysis(pair_key, tf_key):
    pair = PAIRS[pair_key]
    tf_key = str(tf_key).upper().strip()
    if tf_key not in TIMEFRAMES:
        tf_key = "M5"

    cache_key = f"{pair_key}_{tf_key}"
    cached_result = cache_get(cache_key)
    if cached_result:
        return cached_result

    def fetch_tf(tf):
        tv_interval = TIMEFRAMES.get(tf, "5m")

        try:
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
                raise Exception("Data TradingView belum lengkap.")

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
                "rsi": rsi, "rec": rec, "ema20": ema20, "ema50": ema50,
                "source": "TradingView"
            }

        except Exception as tv_error:
            print("TRADINGVIEW 429/FALLBACK:", tv_error)
            return fetch_yfinance_data(pair_key, tf)

    try:
        tf_data = fetch_tf(tf_key)
        pytime.sleep(1.2)
        h1 = fetch_tf("H1") if tf_key != "H1" else tf_data
        pytime.sleep(1.2)
        m15 = fetch_tf("M15") if tf_key != "M15" else tf_data
        pytime.sleep(1.2)
        m5 = fetch_tf("M5") if tf_key != "M5" else tf_data
    except Exception as e:
        return f"""
👑 <b>CAPITAL ELITE PROJECT</b>
<code>Market Intelligence System</code>

📡 <b>Market Data Sync</b>
Sistem sedang validasi data market terbaru.

Detail:
<code>{type(e).__name__}: {str(e)[:180]}</code>

🔄 Coba klik ulang 30-60 detik lagi.
⚠️ Not Financial Advice
"""

    price = tf_data["price"]
    market_range = tf_data["range"]
    h1_bias = h1["bias"]
    m15_bias = m15["bias"]
    m5_bias = m5["bias"]
    data_source = tf_data.get("source", "Market Data")

    wib_now = datetime.utcnow() + timedelta(hours=7)
    hour = wib_now.hour
    if 5 <= hour < 14:
        session_tag = "Asia Session"
        session_score = 4
        session_note = "Volatilitas biasanya lebih kalem. Utamakan sniper/retest."
    elif 14 <= hour < 20:
        session_tag = "London Session"
        session_score = 10
        session_note = "Volume mulai naik. Setup valid lebih enak dieksekusi."
    else:
        session_tag = "New York Session"
        session_score = 10
        session_note = "Volatilitas tinggi. Wajib jaga lot dan disiplin SL."

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
    raw_score = buy_score if signal == "BUY" else sell_score
    confidence = min(max(raw_score, 45), 96)
    score_gap = abs(buy_score - sell_score)
    true_no_setup = confidence < 60 or score_gap < 8

    if confidence >= 88:
        grade = "A+"
        setup_type = "💎 INSTITUTIONAL SETUP"
        risk_level = "LOW"
    elif confidence >= 78:
        grade = "A"
        setup_type = "🚀 SNIPER SETUP"
        risk_level = "MEDIUM"
    elif confidence >= 65:
        grade = "B"
        setup_type = "🟡 RETEST SETUP"
        risk_level = "MEDIUM-HIGH"
    else:
        grade = "C"
        setup_type = "⚪ WAIT / NO SETUP"
        risk_level = "HIGH"

    if pair_key == "XAUUSD":
        sl_dist = max(3.0, min(market_range * 0.85, 6.0))
    elif pair_key == "XAGUSD":
        sl_dist = max(0.12, min(market_range * 0.85, 0.28))
    elif pair_key == "BTCUSD":
        sl_dist = max(120, min(market_range * 0.85, 350))
    else:
        sl_dist = max(10, min(market_range * 0.85, 40))

    if signal == "BUY":
        aggressive_low = price - (sl_dist * 0.15)
        aggressive_high = price + (sl_dist * 0.08)
        sniper_low = min(price, m15["eq"]) - (sl_dist * 0.35)
        sniper_high = min(price, m15["eq"]) - (sl_dist * 0.10)
        sl = min(m5["low"], m15["low"], sniper_low - (sl_dist * 0.55))
        tp1 = price + (sl_dist * 1.1)
        tp2 = price + (sl_dist * 2.0)
        tp3 = price + (sl_dist * 3.0)
        signal_label = "🟢 BUY PLAN"
        action_bias = "BUY ONLY"
        poi_label = "Discount POI"
        sweep_label = "Sell-side liquidity sweep"
        mss_label = "Bullish trigger / recovery"
        invalid_text = "Invalid kalau low POI jebol kuat dan candle close bearish."
    else:
        aggressive_low = price - (sl_dist * 0.08)
        aggressive_high = price + (sl_dist * 0.15)
        sniper_low = max(price, m15["eq"]) + (sl_dist * 0.10)
        sniper_high = max(price, m15["eq"]) + (sl_dist * 0.35)
        sl = max(m5["high"], m15["high"], sniper_high + (sl_dist * 0.55))
        tp1 = price - (sl_dist * 1.1)
        tp2 = price - (sl_dist * 2.0)
        tp3 = price - (sl_dist * 3.0)
        signal_label = "🔴 SELL PLAN"
        action_bias = "SELL ONLY"
        poi_label = "Premium POI"
        sweep_label = "Buy-side liquidity sweep"
        mss_label = "Bearish trigger / rejection"
        invalid_text = "Invalid kalau high POI jebol kuat dan candle close bullish."

    confidence_bar = conf_bar(confidence)
    entry_mid = (aggressive_low + aggressive_high) / 2
    recent_entry = fmt(price)
    rr = round(abs(tp2 - entry_mid) / max(abs(entry_mid - sl), 0.0001), 1)

    if true_no_setup:
        return f"""
👑 <b>CAPITAL ELITE INTELLIGENCE</b>
<code>SMC Signal Desk</code>

💱 <b>{pair['name']}</b> | <b>{tf_key}</b> • {session_tag}
⚪ <b>NO TRADE ZONE</b>

📊 <b>Market Status</b>
H1: <b>{h1_bias}</b>
M15: <b>{m15_bias}</b>
M5: <b>{m5_bias}</b>

⭐ <b>Setup Grade</b>: <b>{grade}</b>
🔥 <b>Confidence</b>: <b>{confidence}%</b>
{confidence_bar}
⚠️ <b>Risk Level</b>: <b>{risk_level}</b>

🧠 <b>Elite Note</b>
Market belum kasih edge bersih. Jangan maksa entry kalau confluence belum kuat.

🛡️ <b>Small Account Rule</b>
Better miss than MC. Tunggu setup lebih clean.

{disclaimer_footer()}
"""

    result_text = f"""
🎯 <b>CAPITAL ELITE SIGNAL</b>

💰 <b>{pair['name']}</b> | <b>{tf_key}</b> • {session_tag}
📡 <code>{data_source}</code>

<b>{signal_label}</b>
📊 Score: <b>{confidence}/100</b> | RR 1:{rr}

📍 Entry: <code>{fmt(aggressive_low)} - {fmt(aggressive_high)}</code>
💎 Sniper: <code>{fmt(sniper_low)} - {fmt(sniper_high)}</code>
📌 Recent Entry: <code>{recent_entry}</code>

🛑 SL: <code>{fmt(sl)}</code>
🎯 TP1: <code>{fmt(tp1)}</code>
🎯 TP2: <code>{fmt(tp2)}</code>
🎯 TP3: <code>{fmt(tp3)}</code>

📈 H1: <b>{h1_bias}</b> | M15: <b>{m15_bias}</b>
📈 M5: <b>{m5_bias}</b>

🏆 Grade: <b>{grade}</b>
🔥 Confidence: <b>{confidence}%</b>
🧭 Bias: <b>{action_bias}</b>

⚠️ Tunggu candle konfirmasi sebelum entry.
{disclaimer_footer()}
"""

    cache_set(cache_key, result_text)
    return result_text

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
<code>AI-Powered Trading Intelligence System</code>

{status_line}
{access_line}

📊 <b>Market Scan</b>
Aggressive • Sniper • SL • TP

🧠 <b>SMC Engine</b>
HTF Bias • Liquidity • POI • MSS

📰 <b>News Desk</b>
CPI • NFP • FOMC • PMI

🟢 <b>Engine Online</b>
Pilih fitur di bawah dan ikuti setup dengan disiplin.

<code>Trade Smart • Trade Elite</code>
"""

    keyboard = [
        [InlineKeyboardButton("📊 Scan Market", callback_data="menu_pairs")],
        [InlineKeyboardButton("🎯 Sniper Scanner", callback_data="sniper_menu")],
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
            hasil = f"""
👑 <b>CAPITAL ELITE PROJECT</b>

📡 <b>Market Data Sync</b>
Sistem sedang validasi data market terbaru.

Detail:
<code>{type(e).__name__}: {str(e)[:160]}</code>

🔄 Coba klik ulang 30-60 detik lagi.

⚠️ <b>Not Financial Advice</b>
Trading memiliki risiko tinggi.
"""
        keyboard = [[InlineKeyboardButton("🔁 Analisa Lagi", callback_data=f"pair_{pair_key}")], [InlineKeyboardButton("🏠 Menu Utama", callback_data="back_start")]]
        await q.edit_message_text(hasil, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data == "sniper_menu":
        if not can_use_market(user_id):
            await q.edit_message_text(
                "🔒 <b>TRIAL MARKET HABIS</b>\n\nUpgrade premium untuk akses Sniper Scanner.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 Upgrade Premium", callback_data="upgrade")]]),
                parse_mode="HTML"
            )
            return
        keyboard = [
            [InlineKeyboardButton("🎯 Scan XAUUSD", callback_data="sniper_XAUUSD")],
            [InlineKeyboardButton("🎯 Scan BTCUSD", callback_data="sniper_BTCUSD")],
            [InlineKeyboardButton("🎯 Scan ETHUSD", callback_data="sniper_ETHUSD")],
            [InlineKeyboardButton("⬅️ Kembali", callback_data="back_start")]
        ]
        await q.edit_message_text(
            "🎯 <b>CAPITAL ELITE SNIPER SCANNER</b>\n\nScan multi-timeframe M1 • M5 • M15 • H1 untuk cari confluence.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )

    elif data.startswith("sniper_"):
        pair_key = data.replace("sniper_", "")
        await q.edit_message_text(
            f"🎯 <b>Scanning {PAIRS[pair_key]['name']}</b>\n\nM1 • M5 • M15 • H1\nMohon tunggu sebentar...",
            parse_mode="HTML"
        )

        scan_tfs = ["M1", "M5", "M15", "H1"]
        results = []
        buy_count = 0
        sell_count = 0
        total_conf = 0

        for tf in scan_tfs:
            hasil = get_market_analysis(pair_key, tf)
            direction = extract_direction_from_text(hasil)
            conf = extract_confidence_from_text(hasil)
            total_conf += conf

            if direction == "BUY":
                buy_count += 1
                icon = "🟢 BUY"
            elif direction == "SELL":
                sell_count += 1
                icon = "🔴 SELL"
            elif direction == "NO SETUP":
                icon = "⚪ NO SETUP"
            else:
                icon = "🟡 MIXED"

            results.append((tf, icon, conf))
            pytime.sleep(1.2)

        if buy_count > sell_count:
            final_bias = "🟢 BUY DOMINANT"
            action = "Cari buy setelah retracement / validasi M5."
        elif sell_count > buy_count:
            final_bias = "🔴 SELL DOMINANT"
            action = "Cari sell setelah pullback / validasi M5."
        else:
            final_bias = "🟡 MIXED / WAIT"
            action = "Market belum satu arah. Jangan maksa entry."

        avg_conf = int(total_conf / max(len(scan_tfs), 1))
        confluence = max(buy_count, sell_count)

        if confluence >= 3 and avg_conf >= 75:
            grade = "A+ SNIPER WATCH"
        elif confluence >= 3:
            grade = "A SETUP WATCH"
        elif confluence == 2:
            grade = "B WAIT CONFIRMATION"
        else:
            grade = "C NO TRADE"

        lines = ""
        for tf, icon, conf in results:
            lines += f"{tf:<4} : <b>{icon}</b> • {conf}%\n"

        add_market_usage(user_id)
        user = get_user(user_id)
        trial_note = ""
        if not user["premium"]:
            trial_note = f"\n\n🆓 Sisa trial market: {TRIAL_LIMIT_MARKET - user['market_used']} analisa"

        text = f"""
🎯 <b>CAPITAL ELITE SNIPER PRO</b>

💰 <b>{PAIRS[pair_key]['name']}</b> | <b>{grade}</b>
{final_bias}
📊 Score: <b>{avg_conf}/100</b> | Confluence <b>{confluence}/4</b>

{lines}📌 Action: {action}

⚠️ Tunggu candle konfirmasi.

━━━━━━━━━━━━━━
⚠️ <b>Not Financial Advice</b>
Trading memiliki risiko tinggi.
Gunakan Stop Loss.
Kelola risiko dan modal dengan bijak.
━━━━━━━━━━━━━━
{trial_note}
"""
        await q.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="back_start")]]),
            parse_mode="HTML"
        )


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
<code>Trading Intelligence System</code>

⚜ <b>MEMBERSHIP PLANS</b>

💎 <b>ELITE ACCESS — 60 HARI</b>
<s>Rp 499.000</s> 🔥 <b>Rp 150.000</b>

👑 <b>VIP ACCESS — 90 HARI</b>
<b>Rp 250.000</b>

♾️ <b>LIFETIME ACCESS</b>
<b>Rp 499.000</b>

✅ Premium Signal
✅ Auto Signal Broadcast
✅ Morning Briefing WIB
✅ High Impact News Alert
✅ Risk Calculator
✅ Elite Mindset Broadcast
✅ Admin Support

💳 <b>Payment</b>
<code>{PAYMENT_TEXT}</code>

🎁 <b>Mau akses gratis?</b>
Hubungi Admin — S&K berlaku.

📩 <b>Admin</b>
{ADMIN_CONTACT}

⚡ Setelah bayar, kirim bukti transfer.

Klik /pay untuk ajukan aktivasi otomatis ke admin.
"""
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="back_start")]]), parse_mode="HTML")

    elif data == "back_start":
        text, keyboard = main_menu(user_id)
        await q.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")



# ==============================
# SELF ANALYSIS COMMANDS
# ==============================
def normalize_command_tf(args, default="M5"):
    if not args:
        return default
    tf = str(args[0]).upper().strip()
    aliases = {
        "1M": "M1", "M1": "M1",
        "3M": "M3", "M3": "M3",
        "5M": "M5", "M5": "M5",
        "15M": "M15", "M15": "M15",
        "30M": "M30", "M30": "M30",
        "1H": "H1", "H1": "H1",
        "4H": "H4", "H4": "H4",
        "D1": "DAILY", "1D": "DAILY", "DAILY": "DAILY"
    }
    return aliases.get(tf, default)


async def manual_analysis_command(update: Update, context: ContextTypes.DEFAULT_TYPE, pair_key: str):
    user_id = update.effective_user.id

    if not can_use_market(user_id):
        await update.message.reply_text(
            "🔒 <b>TRIAL MARKET HABIS</b>\n\nUpgrade premium untuk akses unlimited.\n\n💬 Chat Admin: " + ADMIN_CONTACT,
            parse_mode="HTML"
        )
        return

    tf_key = normalize_command_tf(context.args, "M5")

    await update.message.reply_text(
        f"🔍 <b>CAPITAL ELITE SCANNING</b>\n\nPair: <b>{PAIRS[pair_key]['name']}</b>\nTimeframe: <b>{tf_key}</b>\n\n⚡ Validating market structure...",
        parse_mode="HTML"
    )

    hasil = get_market_analysis(pair_key, tf_key)
    add_market_usage(user_id)

    user = get_user(user_id)
    if not user["premium"]:
        hasil += f"\n\n🆓 Sisa trial market: {TRIAL_LIMIT_MARKET - user['market_used']} analisa"

    await update.message.reply_text(hasil, parse_mode="HTML")


async def xau_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await manual_analysis_command(update, context, "XAUUSD")


async def xag_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await manual_analysis_command(update, context, "XAGUSD")


async def btc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await manual_analysis_command(update, context, "BTCUSD")


async def eth_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await manual_analysis_command(update, context, "ETHUSD")


def extract_confidence_from_text(text):
    m = re.search(r"Confidence\s*</b>\s*<b>(\d+)%", text)
    if not m:
        m = re.search(r"Confidence\s*[: ]+\s*(\d+)%", text, re.I)
    if not m:
        return 0
    try:
        return int(m.group(1))
    except Exception:
        return 0


def extract_direction_from_text(text):
    if "BUY SETUP" in text or "🟢" in text:
        return "BUY"
    if "SELL SETUP" in text or "🔴" in text:
        return "SELL"
    if "NO SETUP" in text:
        return "NO SETUP"
    return "MIXED"


async def sniper_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not can_use_market(user_id):
        await update.message.reply_text(
            "🔒 <b>TRIAL MARKET HABIS</b>\n\nUpgrade premium untuk akses Sniper Scanner.\n\n💬 Chat Admin: " + ADMIN_CONTACT,
            parse_mode="HTML"
        )
        return

    pair_key = "XAUUSD"
    if context.args:
        raw_pair = str(context.args[0]).upper().strip()
        pair_alias = {
            "XAU": "XAUUSD", "GOLD": "XAUUSD", "XAUUSD": "XAUUSD",
            "XAG": "XAGUSD", "SILVER": "XAGUSD", "XAGUSD": "XAGUSD",
            "BTC": "BTCUSD", "BTCUSD": "BTCUSD",
            "ETH": "ETHUSD", "ETHUSD": "ETHUSD"
        }
        pair_key = pair_alias.get(raw_pair, "XAUUSD")

    await update.message.reply_text(
        f"🎯 <b>CAPITAL ELITE SNIPER SCANNER</b>\n\nScanning <b>{PAIRS[pair_key]['name']}</b> across M1 • M5 • M15 • H1...\n\nMohon tunggu sebentar.",
        parse_mode="HTML"
    )

    scan_tfs = ["M1", "M5", "M15", "H1"]
    results = []
    buy_count = 0
    sell_count = 0
    total_conf = 0

    for tf in scan_tfs:
        hasil = get_market_analysis(pair_key, tf)
        direction = extract_direction_from_text(hasil)
        conf = extract_confidence_from_text(hasil)
        total_conf += conf

        if direction == "BUY":
            buy_count += 1
            icon = "🟢 BUY"
        elif direction == "SELL":
            sell_count += 1
            icon = "🔴 SELL"
        elif direction == "NO SETUP":
            icon = "⚪ NO SETUP"
        else:
            icon = "🟡 MIXED"

        results.append((tf, icon, conf))
        pytime.sleep(1.2)

    if buy_count > sell_count:
        final_bias = "🟢 BUY DOMINANT"
        action = "Cari buy setelah retracement / validasi M5."
    elif sell_count > buy_count:
        final_bias = "🔴 SELL DOMINANT"
        action = "Cari sell setelah pullback / validasi M5."
    else:
        final_bias = "🟡 MIXED / WAIT"
        action = "Market belum satu arah. Jangan maksa entry."

    avg_conf = int(total_conf / max(len(scan_tfs), 1))
    confluence = max(buy_count, sell_count)

    if confluence >= 3 and avg_conf >= 75:
        grade = "A+ SNIPER WATCH"
    elif confluence >= 3:
        grade = "A SETUP WATCH"
    elif confluence == 2:
        grade = "B WAIT CONFIRMATION"
    else:
        grade = "C NO TRADE"

    lines = ""
    for tf, icon, conf in results:
        lines += f"{tf:<4} : <b>{icon}</b> • {conf}%\n"

    add_market_usage(user_id)
    user = get_user(user_id)
    trial_note = ""
    if not user["premium"]:
        trial_note = f"\n\n🆓 Sisa trial market: {TRIAL_LIMIT_MARKET - user['market_used']} analisa"

    text = f"""
🎯 <b>CAPITAL ELITE SNIPER PRO</b>

💰 <b>{PAIRS[pair_key]['name']}</b> | <b>{grade}</b>
{final_bias}
📊 Score: <b>{avg_conf}/100</b> | Confluence <b>{confluence}/4</b>

{lines}📌 Action: {action}

⚠️ Tunggu candle konfirmasi.

━━━━━━━━━━━━━━
⚠️ <b>Not Financial Advice</b>
Trading memiliki risiko tinggi.
Gunakan Stop Loss.
Kelola risiko dan modal dengan bijak.
━━━━━━━━━━━━━━
{trial_note}
"""
    await update.message.reply_text(text, parse_mode="HTML")


async def commands_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
👑 <b>CAPITAL ELITE COMMAND CENTER</b>

📊 <b>Manual Analysis</b>
<code>/xau m5</code> — Analisa XAUUSD
<code>/btc h1</code> — Analisa BTCUSD
<code>/eth m15</code> — Analisa ETHUSD
<code>/xag m5</code> — Analisa XAGUSD

🎯 <b>Sniper Scanner</b>
<code>/sniper</code> — Scan XAUUSD
<code>/sniper btc</code> — Scan BTCUSD
<code>/sniper eth</code> — Scan ETHUSD

🛡️ <b>Risk Calculator</b>
<code>/risk 100000 5</code>

📰 <b>News</b>
<code>/news cpi actual=3.2 forecast=3.4</code>
<code>/fomc hawkish</code>

💎 <b>Membership</b>
Klik menu Upgrade di /start.
"""
    await update.message.reply_text(text, parse_mode="HTML")


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



def activate_premium_user(target_id, days=60):
    users = load_users()
    target_id = str(target_id)
    until = datetime.now() + timedelta(days=days)

    if target_id not in users:
        users[target_id] = {
            "market_used": 0,
            "news_used": 0,
            "premium": True,
            "premium_until": until.strftime("%Y-%m-%d %H:%M:%S"),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    else:
        users[target_id]["premium"] = True
        users[target_id]["premium_until"] = until.strftime("%Y-%m-%d %H:%M:%S")

    save_users(users)
    return until


async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Lu bukan admin.")
        return

    if len(context.args) < 1:
        await update.message.reply_text("Format: /approve ID_TELEGRAM\nContoh: /approve 123456789")
        return

    target_id = str(context.args[0])
    days = 60

    if len(context.args) >= 2:
        try:
            days = int(context.args[1])
        except Exception:
            days = 60

    until = activate_premium_user(target_id, days)

    pending = load_json_file(PENDING_PAYMENT_FILE, {})
    if target_id in pending:
        pending[target_id]["status"] = "approved"
        pending[target_id]["approved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_json_file(PENDING_PAYMENT_FILE, pending)

    admin_text = f"""
✅ <b>PAYMENT APPROVED</b>

User: <code>{target_id}</code>
Durasi: <b>{days} hari</b>
Expired: <code>{until.strftime('%Y-%m-%d %H:%M:%S')}</code>
"""
    await update.message.reply_text(admin_text, parse_mode="HTML")

    try:
        user_text = f"""
👑 <b>CAPITAL ELITE PROJECT</b>

✅ <b>Premium lu sudah aktif</b>

Durasi: <b>{days} hari</b>
Expired: <code>{until.strftime('%d %b %Y %H:%M WIB')}</code>

Akses:
✅ Manual Analysis
✅ Sniper Scanner
✅ Auto Signal
✅ News Alert
✅ Risk Calculator

Trade smart. Manage your risk.

⚠️ <b>Not Financial Advice</b>
Trading memiliki risiko tinggi.
"""
        await context.bot.send_message(chat_id=int(target_id), text=user_text, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"Premium aktif, tapi gagal kirim notif user: {e}")


async def request_payment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.full_name or "-"
    username = update.effective_user.username or "-"

    pending = load_json_file(PENDING_PAYMENT_FILE, {})
    pending[user_id] = {
        "name": user_name,
        "username": username,
        "status": "waiting_approval",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_json_file(PENDING_PAYMENT_FILE, pending)

    text = f"""
💎 <b>CAPITAL ELITE PREMIUM REQUEST</b>

ID lu:
<code>{user_id}</code>

Status:
⏳ Menunggu approval admin

Setelah transfer, kirim bukti pembayaran ke:
{ADMIN_CONTACT}

Admin akan aktifkan premium dengan:
<code>/approve {user_id}</code>

⚠️ <b>Not Financial Advice</b>
Trading memiliki risiko tinggi.
"""
    await update.message.reply_text(text, parse_mode="HTML")

    try:
        admin_msg = f"""
🧾 <b>NEW PAYMENT REQUEST</b>

Name: <b>{user_name}</b>
Username: @{username}
ID: <code>{user_id}</code>

Approve:
<code>/approve {user_id}</code>

Custom 90 hari:
<code>/approve {user_id} 90</code>
"""
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="HTML")
    except Exception:
        pass


async def pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Lu bukan admin.")
        return

    pending = load_json_file(PENDING_PAYMENT_FILE, {})
    rows = []
    for uid, data in pending.items():
        if data.get("status") == "waiting_approval":
            rows.append(f"• <code>{uid}</code> — {data.get('name','-')} (@{data.get('username','-')})")

    if not rows:
        await update.message.reply_text("Tidak ada pending payment.")
        return

    text = "🧾 <b>PENDING PAYMENT</b>\n\n" + "\n".join(rows[:80]) + "\n\nApprove pakai:\n<code>/approve ID</code>"
    await update.message.reply_text(text, parse_mode="HTML")



async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Lu bukan admin.")
        return
    if len(context.args) < 1:
        await update.message.reply_text("Format: /premium ID_TELEGRAM\nContoh: /premium 123456789\n\nDefault premium: 60 hari\nCustom: /premium 123456789 90")
        return

    target_id = context.args[0]
    days = 60
    if len(context.args) >= 2:
        try:
            days = int(context.args[1])
        except Exception:
            days = 60

    until = datetime.now() + timedelta(days=days)
    users = load_users()
    if target_id not in users:
        users[target_id] = {
            "market_used": 0,
            "news_used": 0,
            "premium": True,
            "premium_until": until.strftime("%Y-%m-%d %H:%M:%S"),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    else:
        users[target_id]["premium"] = True
        users[target_id]["premium_until"] = until.strftime("%Y-%m-%d %H:%M:%S")
    save_users(users)

    await update.message.reply_text(
        f"👑 CAPITAL ELITE PROJECT\n\nUser {target_id} sudah PREMIUM selama {days} hari.\nExpired: {until.strftime('%d-%m-%Y %H:%M')}"
    )


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


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Lu bukan admin.")
        return

    users = load_users()
    total = len(users)
    premium_count = 0
    trial_count = 0
    expired_count = 0

    for uid in list(users.keys()):
        u = get_user(int(uid))
        if u.get("premium"):
            premium_count += 1
        else:
            trial_count += 1
            if u.get("expired_at"):
                expired_count += 1

    logs = load_json_file(SIGNAL_LOG_FILE, [])
    news_sent = load_json_file(NEWS_SENT_FILE, {})
    today_key = wib_now().strftime("%Y-%m-%d")
    news_today = len(news_sent.get(today_key, []))

    text = f"""
👑 <b>CAPITAL ELITE ADMIN DASHBOARD</b>

👥 Total User: <b>{total}</b>
💎 Premium Aktif: <b>{premium_count}</b>
🆓 Trial/Free: <b>{trial_count}</b>
⌛ Expired: <b>{expired_count}</b>

🚨 Signal Log: <b>{len(logs)}</b>
📰 News Sent Today: <b>{news_today}</b>

📊 Market Trial Limit: <b>{TRIAL_LIMIT_MARKET}</b>
📰 News Trial Limit: <b>{TRIAL_LIMIT_NEWS}</b>

⚙️ Engine: <b>ONLINE</b>
🕘 Server Mode: <b>WIB Schedule</b>
"""
    await update.message.reply_text(text, parse_mode="HTML")



async def listpremium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Lu bukan admin.")
        return

    users = load_users()
    lines = []
    for uid in list(users.keys()):
        u = get_user(int(uid))
        if u.get("premium"):
            until = u.get("premium_until", "LIFETIME")
            lines.append(f"• <code>{uid}</code> — {until}")

    if not lines:
        text = "Belum ada user premium aktif."
    else:
        text = "💎 <b>PREMIUM ACTIVE LIST</b>\n\n" + "\n".join(lines[:80])

    await update.message.reply_text(text, parse_mode="HTML")


async def resettrial_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Lu bukan admin.")
        return

    if len(context.args) < 1:
        await update.message.reply_text("Format: /resettrial ID_TELEGRAM")
        return

    uid = str(context.args[0])
    users = load_users()

    if uid not in users:
        users[uid] = {
            "market_used": 0,
            "news_used": 0,
            "premium": False,
            "premium_until": None,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    else:
        users[uid]["market_used"] = 0
        users[uid]["news_used"] = 0

    save_users(users)
    await update.message.reply_text(f"Trial user {uid} sudah direset.")


async def expired_reminder_job(context):
    try:
        users = load_users()
        reminder_db = load_json_file(EXPIRED_REMINDER_FILE, {})
        today_key = wib_now().strftime("%Y-%m-%d")

        for uid in list(users.keys()):
            u = get_user(int(uid))
            if not u.get("premium"):
                continue

            premium_until = u.get("premium_until")
            if premium_until in [None, "LIFETIME"]:
                continue

            try:
                exp = datetime.strptime(premium_until, "%Y-%m-%d %H:%M:%S")
                days_left = (exp.date() - wib_now().date()).days
            except Exception:
                continue

            if days_left in [3, 1, 0]:
                key = f"{uid}_{today_key}_{days_left}"
                if reminder_db.get(key):
                    continue

                try:
                    await context.bot.send_message(
                        chat_id=int(uid),
                        text=premium_expire_text(uid, days_left, premium_until),
                        parse_mode="HTML"
                    )
                    reminder_db[key] = True
                except Exception:
                    pass

        # keep db small
        if len(reminder_db) > 500:
            reminder_db = dict(list(reminder_db.items())[-300:])

        save_json_file(EXPIRED_REMINDER_FILE, reminder_db)

    except Exception as e:
        print("EXPIRED REMINDER ERROR:", e)



async def auto_signal_broadcast(context):
    try:
        users = load_users()
        targets = premium_users(users)
        if not targets:
            print("AUTO SIGNAL: tidak ada premium user")
            return

        if has_high_impact_news_risk():
            print("AUTO SIGNAL: paused karena ada high impact USD news risk")
            return

        signal_text = get_market_analysis("XAUUSD", "M15")
        if not is_trade_signal_text(signal_text):
            print("AUTO SIGNAL: no setup / error, tidak dibroadcast")
            return

        if not should_send_auto_signal("XAUUSD", signal_text, cooldown_minutes=90):
            print("AUTO SIGNAL: duplicate setup, skip broadcast")
            return

        log_signal("XAUUSD", "M15", signal_text)

        header = """
🚨 <b>CAPITAL ELITE AUTO SIGNAL</b>
<code>XAUUSD Priority Alert • Auto Broadcast</code>

"""
        text = header + signal_text + """

📌 <b>Auto Signal Note</b>
Signal otomatis hanya dikirim saat engine membaca setup yang layak dipantau.
Gunakan lot kecil dan tetap validasi chart sebelum entry.
"""
        for uid in targets:
            try:
                await context.bot.send_message(chat_id=int(uid), text=text, parse_mode="HTML")
            except Exception:
                pass

    except Exception as e:
        print("AUTO SIGNAL ERROR:", e)


async def morning_briefing(context):
    try:
        users = load_users()
        targets = premium_users(users)
        if not targets:
            print("MORNING BRIEFING: tidak ada premium user")
            return

        today = wib_now().strftime("%d %b %Y")
        xau = get_market_analysis("XAUUSD", "H1")
        btc = get_market_analysis("BTCUSD", "H1")
        events = parse_forex_factory_today()

        news_lines = "Tidak ada high impact USD yang terbaca. Tetap cek kalender manual."
        if events:
            news_lines = ""
            for ev in events[:4]:
                raw_event = str(ev.get("raw", "-"))
                wib_time = convert_ff_time_to_wib(raw_event)
                clean_event = clean_ff_event_text(raw_event)
                news_lines += f"• USD {ev.get('impact', 'NEWS')} — {wib_time} — {clean_event[:90]}\n"

        text = f"""
🌅 <b>CAPITAL ELITE MORNING BRIEFING</b>
<code>{today} • WIB Session Plan</code>

🥇 <b>XAUUSD Focus</b>
Lihat bias H1 dan tunggu validasi M15/M5 sebelum entry.

₿ <b>BTCUSD Focus</b>
Pantau risk sentiment dan reaksi terhadap USD news.

📰 <b>News Watch</b>
{news_lines}
🛡️ <b>Elite Rule</b>
Jangan overlot di awal hari. Tunggu setup, bukan kejar market.

⚠️ <b>Not Financial Advice</b>
Trading memiliki risiko tinggi.
"""
        for uid in targets:
            try:
                await context.bot.send_message(chat_id=int(uid), text=text, parse_mode="HTML")
            except Exception:
                pass

    except Exception as e:
        print("MORNING BRIEFING ERROR:", e)


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
            raw_event = str(ev.get("raw", "-"))
            wib_time = convert_ff_time_to_wib(raw_event)
            clean_event = clean_ff_event_text(raw_event)
            news_lines += f"• USD {ev.get('impact', 'NEWS')} — {wib_time} — {clean_event[:90]}\n"
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
        events = parse_forex_factory_today()

        if not events:
            print("FOREX FACTORY: Tidak ada news USD penting / gagal dibaca")
            return

        users = load_users()
        targets = list(users.keys())
        today = wib_now().strftime("%d %b %Y")
        sent_db = load_json_file(NEWS_SENT_FILE, {})
        today_key = wib_now().strftime("%Y-%m-%d")
        sent_today = set(sent_db.get(today_key, []))

        selected_events = []
        important_terms = [
            "cpi", "core cpi", "consumer price index", "nfp", "non-farm", "nonfarm",
            "fomc", "federal funds rate", "interest rate", "powell", "pce", "core pce",
            "ppi", "unemployment", "average hourly earnings", "pmi", "ism", "gdp"
        ]

        for ev in events:
            raw = str(ev.get("raw", ""))
            raw_l = raw.lower()
            if not any(k in raw_l for k in important_terms):
                continue
            key = get_news_key(raw)
            if key in sent_today:
                continue
            selected_events.append((key, ev))

        if not selected_events:
            print("FOREX FACTORY: news penting sudah pernah dikirim hari ini")
            return

        text = f"""
📰 <b>CAPITAL ELITE NEWS INTELLIGENCE</b>
<code>{today} • High Impact USD Watch</code>

🔥 <b>HIGH IMPACT NEWS DETECTED</b>

📊 <b>USD News Watch</b>
"""

        for key, ev in selected_events[:5]:
            raw_event = str(ev.get("raw", "-"))
            wib_time = convert_ff_time_to_wib(raw_event)
            clean_event = clean_ff_event_text(raw_event)

            text += f"""
• <b>USD {ev.get('impact', 'NEWS')}</b>
🕘 <b>{wib_time}</b>
📌 {clean_event[:160]}
"""
            sent_today.add(key)

        text += """
⚠️ <b>Market Focus</b>
XAUUSD • BTCUSD • ETHUSD • USD Index

🚫 <b>No Trade Zone</b>
Hindari entry besar menjelang news.
Tunggu spread normal dan candle close setelah news.

🕘 <b>Timezone</b>
Jam rilis sudah dikonversi ke estimasi WIB.
Tetap validasi kalender ekonomi sebelum news besar.

🧠 <b>Elite Note</b>
Jangan nebak news. Tunggu market kasih arah.

⚠️ <b>Not Financial Advice</b>
Trading memiliki risiko tinggi.
"""

        sent_db[today_key] = list(sent_today)
        # keep only latest 7 days
        sorted_days = sorted(sent_db.keys())[-7:]
        sent_db = {d: sent_db[d] for d in sorted_days}
        save_json_file(NEWS_SENT_FILE, sent_db)

        for uid in targets:
            try:
                await context.bot.send_message(
                    chat_id=int(uid),
                    text=text,
                    parse_mode="HTML"
                )
            except Exception:
                pass

    except Exception as e:
        print("FOREX FACTORY NEWS ERROR:", e)


async def new_york_session_alert(context):
    try:
        users = load_users()
        targets = premium_users(users)
        if not targets:
            print("NY SESSION: tidak ada premium user")
            return

        text = """
🔥 <b>CAPITAL ELITE NEW YORK SESSION</b>
<code>19:00 WIB • XAUUSD Volatility Watch</code>

🇺🇸 <b>New York Session mulai aktif</b>

Pantau:
✅ Liquidity sweep
✅ Reaksi area H1/M15
✅ Spread & news USD
✅ Jangan overlot di candle impulsif

📌 <b>Elite Rule</b>
Kalau market sudah terbang duluan, jangan dikejar.
Tunggu retrace atau setup baru.

⚠️ <b>Not Financial Advice</b>
Trading memiliki risiko tinggi.
"""
        for uid in targets:
            try:
                await context.bot.send_message(chat_id=int(uid), text=text, parse_mode="HTML")
            except Exception:
                pass

    except Exception as e:
        print("NY SESSION ERROR:", e)

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
app.add_handler(CommandHandler("approve", approve_command))
app.add_handler(CommandHandler("pay", request_payment_command))
app.add_handler(CommandHandler("pending", pending_command))
app.add_handler(CommandHandler("unpremium", unpremium))
app.add_handler(CommandHandler("cekuser", cekuser))
app.add_handler(CommandHandler("broadcast", broadcast))
app.add_handler(CommandHandler("risk", risk_command))
app.add_handler(CommandHandler("edukasi", edukasi_command))
app.add_handler(CommandHandler("marketnews", marketnews_command))
app.add_handler(CommandHandler("stats", stats_command))
app.add_handler(CommandHandler("listpremium", listpremium_command))
app.add_handler(CommandHandler("resettrial", resettrial_command))
app.add_handler(CommandHandler("commands", commands_command))
app.add_handler(CommandHandler("xau", xau_command))
app.add_handler(CommandHandler("xag", xag_command))
app.add_handler(CommandHandler("btc", btc_command))
app.add_handler(CommandHandler("eth", eth_command))
app.add_handler(CommandHandler("sniper", sniper_command))
app.add_handler(CallbackQueryHandler(button))

app.job_queue.run_repeating(
    auto_broadcast,
    interval=7200,
    first=300
)

# Cek news otomatis tiap 30 menit
app.job_queue.run_repeating(
    auto_news_alert,
    interval=1800,
    first=60
)

# Auto signal XAUUSD untuk premium setiap 3 jam
app.job_queue.run_repeating(
    auto_signal_broadcast,
    interval=10800,
    first=900
)

from datetime import time as dt_time

# Morning briefing 07:00 WIB = 00:00 UTC
app.job_queue.run_daily(
    morning_briefing,
    time=dt_time(hour=0, minute=0)
)

# New York session alert 19:00 WIB = 12:00 UTC
app.job_queue.run_daily(
    new_york_session_alert,
    time=dt_time(hour=12, minute=0)
)

# Reminder premium expired 09:00 WIB = 02:00 UTC
app.job_queue.run_daily(
    expired_reminder_job,
    time=dt_time(hour=2, minute=0)
)

print("CAPITAL ELITE PROJECT BOT ONLINE...")
app.run_polling()

