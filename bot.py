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
TD_API_KEY = os.environ.get("TD_API_KEY", "")
USER_FILE = "users.json"
NEWS_SENT_FILE = "news_sent.json"
SIGNAL_LOG_FILE = "signal_log.json"
LAST_SIGNAL_FILE = "last_signal.json"
EXPIRED_REMINDER_FILE = "expired_reminder.json"
PENDING_PAYMENT_FILE = "pending_payment.json"
REALTIME_SIGNAL_FILE = "realtime_signal.json"
REALTIME_SCAN_PAIRS = ["XAUUSD", "BTCUSD", "ETHUSD", "EURUSD", "GBPUSD", "NAS100"]
REALTIME_SCAN_TF = "M5"
REALTIME_SCAN_INTERVAL = 300
MARKET_CACHE = {}
MARKET_CACHE_SECONDS = 0
TRIAL_LIMIT_MARKET = 5
TRIAL_LIMIT_NEWS = 3

# Isi pembayaran lu di sini
PAYMENT_TEXT = "DANA / QRIS: 085778001402"
ADMIN_CONTACT = "@egingroho"

PAIRS = {
    "XAUUSD": {"symbol": "XAUUSD", "screener": "cfd", "exchange": "FOREXCOM", "name": "XAU/USD"},
    "XAGUSD": {"symbol": "SILVER", "screener": "cfd", "exchange": "TVC", "name": "XAG/USD"},
    "BTCUSD": {"symbol": "BTCUSD", "screener": "crypto", "exchange": "BITSTAMP", "name": "BTC/USD"},
    "ETHUSD": {"symbol": "ETHUSD", "screener": "crypto", "exchange": "BITSTAMP", "name": "ETH/USD"},
    "EURUSD": {"symbol": "EURUSD", "screener": "forex", "exchange": "OANDA", "name": "EUR/USD"},
    "GBPUSD": {"symbol": "GBPUSD", "screener": "forex", "exchange": "OANDA", "name": "GBP/USD"},
    "USDJPY": {"symbol": "USDJPY", "screener": "forex", "exchange": "OANDA", "name": "USD/JPY"},
    "AUDUSD": {"symbol": "AUDUSD", "screener": "forex", "exchange": "OANDA", "name": "AUD/USD"},
    "NAS100": {"symbol": "NAS100USD", "screener": "cfd", "exchange": "OANDA", "name": "NAS100"},
    "US30": {"symbol": "US30USD", "screener": "cfd", "exchange": "OANDA", "name": "US30"},
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
    # Realtime mode: market analysis selalu fetch data baru.
    return None


def cache_set(key, value):
    MARKET_CACHE[key] = {
        "ts": pytime.time(),
        "value": value
    }


def td_symbol(pair_key):
    mapping = {
        "XAUUSD": "XAU/USD",
        "XAGUSD": "XAG/USD",
        "BTCUSD": "BTC/USD",
        "ETHUSD": "ETH/USD",
        "EURUSD": "EUR/USD",
        "GBPUSD": "GBP/USD",
        "USDJPY": "USD/JPY",
        "AUDUSD": "AUD/USD",
        "NAS100": "NAS100",
        "US30": "DJI",
    }
    return mapping.get(pair_key, "XAU/USD")



def td_symbol_candidates(pair_key):
    primary = td_symbol(pair_key)
    fallbacks = {
        "XAUUSD": ["XAU/USD", "XAUUSD"],
        "XAGUSD": ["XAG/USD", "XAGUSD"],
        "BTCUSD": ["BTC/USD", "BTCUSD", "BTC/USD:Binance"],
        "ETHUSD": ["ETH/USD", "ETHUSD", "ETH/USD:Binance"],
        "EURUSD": ["EUR/USD", "EURUSD"],
        "GBPUSD": ["GBP/USD", "GBPUSD"],
        "USDJPY": ["USD/JPY", "USDJPY"],
        "AUDUSD": ["AUD/USD", "AUDUSD"],
        "NAS100": ["NAS100", "NDX", "NQ"],
        "US30": ["DJI", "US30", "DJI:INDEX"],
    }
    items = fallbacks.get(pair_key, [primary])
    result = []
    for item in [primary] + items:
        if item not in result:
            result.append(item)
    return result


def yf_symbol(pair_key):
    # Legacy compatibility
    return td_symbol(pair_key)


def td_interval(tf):
    mapping = {
        "M1": "1min",
        "M3": "1min",
        "M5": "5min",
        "M15": "15min",
        "M30": "30min",
        "H1": "1h",
        "H4": "4h",
        "DAILY": "1day",
    }
    return mapping.get(tf, "5min")


def yf_interval(tf):
    # Legacy compatibility
    return td_interval(tf)


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



# ==============================
# TWELVEDATA MARKET DATA
# ==============================
def fetch_twelvedata_candles(pair_key, tf, outputsize=180):
    if not TD_API_KEY:
        raise Exception("TD_API_KEY belum diisi di Railway Variables.")

    symbol_candidates = td_symbol_candidates(pair_key)
    interval = td_interval(tf)

    url = "https://api.twelvedata.com/time_series"
    data = None
    last_error = None

    for symbol in symbol_candidates:
        params = {
            "symbol": symbol,
            "interval": interval,
            "outputsize": outputsize,
            "apikey": TD_API_KEY,
            "format": "JSON",
            "timezone": "Asia/Jakarta"
        }

        r = requests.get(url, params=params, timeout=15)
        data = r.json()

        if data.get("status") == "error":
            last_error = data.get("message", "TwelveData error")
            continue

        if data.get("values"):
            break

    if data is None or data.get("status") == "error":
        raise Exception(last_error or "TwelveData error")

    values = data.get("values")
    if not values:
        raise Exception("TwelveData tidak mengembalikan candle values.")

    candles = []
    for item in values:
        try:
            candles.append({
                "datetime": item.get("datetime"),
                "Open": float(item["open"]),
                "High": float(item["high"]),
                "Low": float(item["low"]),
                "Close": float(item["close"]),
            })
        except Exception:
            continue

    if len(candles) < 30:
        raise Exception("Candle TwelveData belum cukup.")

    candles = list(reversed(candles))
    return candles



def fetch_twelvedata_quote(pair_key):
    """
    Ambil harga live/realtime dari TwelveData quote.
    Ini dipakai untuk Price/Recent agar lebih dekat dengan harga chart berjalan.
    """
    if not TD_API_KEY:
        raise Exception("TD_API_KEY belum diisi di Railway Variables.")

    url = "https://api.twelvedata.com/quote"
    last_error = None

    for symbol in td_symbol_candidates(pair_key):
        params = {
            "symbol": symbol,
            "apikey": TD_API_KEY
        }

        r = requests.get(url, params=params, timeout=12)
        data = r.json()

        if data.get("status") == "error":
            last_error = data.get("message", "TwelveData quote error")
            continue

        for key in ["close", "price", "bid"]:
            val = data.get(key)
            if val not in [None, "", "None"]:
                return float(val)

    raise Exception(last_error or "TwelveData quote tidak mengembalikan harga live.")



def fetch_realtime_market_price(pair_key):
    """
    Universal live price untuk semua market:
    - XAU/XAG/Forex/Indices: coba TradingView live dulu
    - Crypto: coba TradingView live dulu
    - Kalau TradingView kena limit/error: fallback ke TwelveData quote

    Semua pair pakai fungsi ini agar Price/Recent realtime.
    """
    pair = PAIRS.get(pair_key, PAIRS["XAUUSD"])

    # 1) TradingView live price
    try:
        handler = TA_Handler(
            symbol=pair["symbol"],
            screener=pair["screener"],
            exchange=pair["exchange"],
            interval=TIMEFRAMES.get("M1", "1m")
        )
        data = handler.get_analysis()
        price = data.indicators.get("close")
        if price is not None:
            return float(price), "TradingView Live"
    except Exception as e:
        print(f"TRADINGVIEW LIVE PRICE FALLBACK {pair_key}:", e)

    # 2) TwelveData quote fallback
    try:
        price = fetch_twelvedata_quote(pair_key)
        return float(price), "TwelveData Live Quote"
    except Exception as e:
        print(f"TWELVEDATA LIVE PRICE ERROR {pair_key}:", e)

    # 3) Hard fail
    raise Exception(f"Semua live price provider gagal untuk {pair_key}")


def apply_price_offset_to_zone(zone, offset):
    if not zone:
        return None
    return {
        **zone,
        "low": float(zone["low"]) + offset,
        "high": float(zone["high"]) + offset,
        "mid": float(zone["mid"]) + offset,
    }


def candle_col(candles, key):
    return [float(c[key]) for c in candles]


def last_candle(candles):
    return candles[-1]


def candles_tail(candles, n):
    return candles[-n:] if len(candles) >= n else candles




def get_market_analysis(pair_key, tf_key):
    """
    CAPITAL ELITE PRECISION ENTRY ENGINE
    Source: TwelveData live quote + candle.
    Entry hanya keluar kalau ada sweep -> displacement -> MSS -> POI overlap.
    """
    pair = PAIRS[pair_key]
    tf_key = str(tf_key).upper().strip()
    if tf_key not in TIMEFRAMES:
        tf_key = "M5"

    # realtime: jangan pakai cache untuk entry
    cache_key = f"PRECISION_{pair_key}_{tf_key}"
    cached_result = cache_get(cache_key)
    if cached_result:
        return cached_result

    def tail(candles, n):
        return candles[-n:] if len(candles) >= n else candles

    def highs(candles):
        return [float(c["High"]) for c in candles]

    def lows(candles):
        return [float(c["Low"]) for c in candles]

    def price_now(candles):
        return float(candles[-1]["Close"])

    def candle_range(c):
        return abs(float(c["High"]) - float(c["Low"]))

    def body_size(c):
        return abs(float(c["Close"]) - float(c["Open"]))

    def candle_direction(c):
        return "BULLISH" if float(c["Close"]) > float(c["Open"]) else "BEARISH"

    def avg_range(candles, n=20):
        cs = tail(candles, n)
        return sum(candle_range(c) for c in cs) / max(len(cs), 1)

    def swing_high_low(candles, lookback=50):
        cs = tail(candles, lookback)
        return max(highs(cs)), min(lows(cs))

    def structure_bias(candles):
        if len(candles) < 50:
            return "SIDEWAYS"
        hi, lo = swing_high_low(candles, 50)
        eq = (hi + lo) / 2
        first = float(tail(candles, 30)[0]["Close"])
        last = float(candles[-1]["Close"])
        if last > first and last > eq:
            return "BULLISH"
        if last < first and last < eq:
            return "BEARISH"
        return "SIDEWAYS"

    def premium_discount(candles):
        hi, lo = swing_high_low(candles, 60)
        eq = (hi + lo) / 2
        p = price_now(candles)
        if p < eq:
            return "DISCOUNT", eq, hi, lo
        if p > eq:
            return "PREMIUM", eq, hi, lo
        return "EQ", eq, hi, lo

    def find_recent_sweep(candles, lookback=10):
        if len(candles) < 45:
            return None
        for offset in range(1, min(lookback, len(candles)-35) + 1):
            idx = len(candles) - offset
            current = candles[idx]
            prev = candles[idx-31:idx]
            prev_high = max(highs(prev))
            prev_low = min(lows(prev))
            high = float(current["High"])
            low = float(current["Low"])
            close = float(current["Close"])
            open_ = float(current["Open"])
            if low < prev_low and close > prev_low and close > open_:
                return {"type": "SELLSIDE_SWEEP", "price": low, "idx": idx, "direction": "BUY"}
            if high > prev_high and close < prev_high and close < open_:
                return {"type": "BUYSIDE_SWEEP", "price": high, "idx": idx, "direction": "SELL"}
        return None

    def has_displacement_after(candles, direction, start_idx):
        avg = avg_range(candles, 20)
        for i in range(start_idx, len(candles)):
            c = candles[i]
            rng = candle_range(c)
            body = body_size(c)
            cdir = candle_direction(c)
            if direction == "BUY" and cdir == "BULLISH" and rng >= avg * 1.25 and body >= rng * 0.50:
                return True, i
            if direction == "SELL" and cdir == "BEARISH" and rng >= avg * 1.25 and body >= rng * 0.50:
                return True, i
        return False, None

    def mss_after_sweep(candles, direction, sweep_idx):
        if sweep_idx is None or sweep_idx < 10:
            return None
        before = candles[max(0, sweep_idx-20):sweep_idx]
        after = candles[sweep_idx:]
        if len(before) < 5 or len(after) < 2:
            return None
        prev_high = max(highs(before))
        prev_low = min(lows(before))
        for c in after:
            close = float(c["Close"])
            if direction == "BUY" and close > prev_high:
                return "BULLISH_MSS"
            if direction == "SELL" and close < prev_low:
                return "BEARISH_MSS"
        return None

    def find_fvg_after(candles, direction, start_idx):
        avg = avg_range(candles, 20)
        start_idx = max(2, start_idx)
        for i in range(len(candles)-1, start_idx, -1):
            c0 = candles[i-2]
            c2 = candles[i]
            if direction == "BUY":
                low = float(c0["High"])
                high = float(c2["Low"])
                if high > low and (high - low) >= avg * 0.10:
                    return {"type": "FVG", "low": low, "high": high, "mid": (low + high) / 2}
            if direction == "SELL":
                low = float(c2["High"])
                high = float(c0["Low"])
                if high > low and (high - low) >= avg * 0.10:
                    return {"type": "FVG", "low": low, "high": high, "mid": (low + high) / 2}
        return None

    def find_order_block_after(candles, direction, start_idx):
        avg = avg_range(candles, 20)
        start_idx = max(2, start_idx)
        for i in range(len(candles)-3, start_idx, -1):
            c = candles[i]
            nxt = candles[i+1]
            cdir = candle_direction(c)
            ndir = candle_direction(nxt)
            nrng = candle_range(nxt)
            if direction == "BUY" and cdir == "BEARISH" and ndir == "BULLISH" and nrng >= avg * 1.05:
                return {"type": "OB", "low": float(c["Low"]), "high": float(c["Open"]), "mid": (float(c["Low"]) + float(c["Open"])) / 2}
            if direction == "SELL" and cdir == "BULLISH" and ndir == "BEARISH" and nrng >= avg * 1.05:
                return {"type": "OB", "low": float(c["Open"]), "high": float(c["High"]), "mid": (float(c["Open"]) + float(c["High"])) / 2}
        return None

    def ote_zone(candles, direction):
        hi, lo = swing_high_low(candles, 50)
        rng = max(hi - lo, 0.0001)
        if direction == "BUY":
            a = hi - rng * 0.62
            b = hi - rng * 0.79
            return {"type": "OTE", "low": min(a, b), "high": max(a, b), "mid": (a + b) / 2}
        a = lo + rng * 0.62
        b = lo + rng * 0.79
        return {"type": "OTE", "low": min(a, b), "high": max(a, b), "mid": (a + b) / 2}

    def crt_zone(candles, direction):
        """
        CRT / Candle Range Theory:
        - BUY: candle berjalan sweep low candle sebelumnya lalu reclaim.
        - SELL: candle berjalan sweep high candle sebelumnya lalu reject.
        Entry area pakai 50%-79% area candle range sebelumnya.
        """
        if len(candles) < 5:
            return None, None

        ref = candles[-2]   # candle yang sudah close
        last = candles[-1]  # candle terbaru

        ref_high = float(ref["High"])
        ref_low = float(ref["Low"])
        ref_range = max(ref_high - ref_low, 0.0001)
        ref_mid = (ref_high + ref_low) / 2

        last_high = float(last["High"])
        last_low = float(last["Low"])
        last_close = float(last["Close"])

        if direction == "BUY":
            swept = last_low < ref_low
            reclaimed = last_close > ref_low
            if swept and reclaimed:
                z1 = ref_low + ref_range * 0.21
                z2 = ref_mid
                return {"type": "CRT_BUY", "low": min(z1, z2), "high": max(z1, z2), "mid": (z1 + z2) / 2}, "CRT low sweep + reclaim"

        if direction == "SELL":
            swept = last_high > ref_high
            rejected = last_close < ref_high
            if swept and rejected:
                z1 = ref_mid
                z2 = ref_high - ref_range * 0.21
                return {"type": "CRT_SELL", "low": min(z1, z2), "high": max(z1, z2), "mid": (z1 + z2) / 2}, "CRT high sweep + reject"

        return None, None

    def overlap(a, b):
        if not a or not b:
            return None
        low = max(float(a["low"]), float(b["low"]))
        high = min(float(a["high"]), float(b["high"]))
        if high > low:
            return {"type": f"{a.get('type','ZONE')} + {b.get('type','ZONE')}", "low": low, "high": high, "mid": (low + high) / 2}
        return None

    def rr_calc(direction, entry_low, entry_high, sl, tp):
        if direction == "BUY":
            risk = max(entry_high - sl, 0.0001)
            reward = max(tp - entry_high, 0.0001)
        else:
            risk = max(sl - entry_low, 0.0001)
            reward = max(entry_low - tp, 0.0001)
        return reward / risk

    def risk_pips(pair_key, entry_mid, sl):
        diff = abs(entry_mid - sl)
        if pair_key in ["XAUUSD", "XAGUSD"]:
            return diff * 100
        if pair_key in ["BTCUSD", "ETHUSD", "NAS100", "US30"]:
            return diff
        if pair_key == "USDJPY":
            return diff * 100
        return diff * 10000

    try:
        c_m1 = fetch_twelvedata_candles(pair_key, "M1", 180)
        pytime.sleep(0.2)
        c_m5 = fetch_twelvedata_candles(pair_key, "M5", 180)
        pytime.sleep(0.2)
        c_m15 = fetch_twelvedata_candles(pair_key, "M15", 180)
        pytime.sleep(0.2)
        c_h1 = fetch_twelvedata_candles(pair_key, "H1", 180)
        pytime.sleep(0.2)
        c_h4 = fetch_twelvedata_candles(pair_key, "H4", 180)
        pytime.sleep(0.2)
        try:
            live_price, live_source = fetch_realtime_market_price(pair_key)
        except Exception as quote_error:
            print("LIVE PRICE FALLBACK:", quote_error)
            live_price = price_now(c_m5)
            live_source = "Candle Close Fallback"
    except Exception as e:
        return f"""
👑 <b>CAPITAL ELITE PROJECT</b>

📡 <b>TwelveData Sync</b>
Data market belum stabil / API limit.

Detail:
<code>{type(e).__name__}: {str(e)[:160]}</code>

{disclaimer_footer()}
"""

    price = float(live_price)
    candle_price = price_now(c_m5)
    price_offset = price - candle_price

    if tf_key == "M1":
        exec_c = c_m1
    elif tf_key in ["M5", "M3"]:
        exec_c = c_m5
    else:
        exec_c = c_m15

    h4_bias = structure_bias(c_h4)
    h1_bias = structure_bias(c_h1)
    m15_bias = structure_bias(c_m15)
    m5_bias = structure_bias(c_m5)
    location, eq, range_high, range_low = premium_discount(c_h1)

    hour = wib_now().hour
    if 5 <= hour < 14:
        session_tag = "Asia"
        session_ok = False
    elif 14 <= hour < 20:
        session_tag = "London"
        session_ok = True
    else:
        session_tag = "New York"
        session_ok = True

    if h4_bias == "BULLISH" and h1_bias in ["BULLISH", "SIDEWAYS"]:
        direction = "BUY"
    elif h4_bias == "BEARISH" and h1_bias in ["BEARISH", "SIDEWAYS"]:
        direction = "SELL"
    else:
        direction = "BUY" if location == "DISCOUNT" else "SELL"

    sweep = find_recent_sweep(c_m15, lookback=10)
    score = 0
    invalid = []
    reasons = []

    if direction == "BUY":
        if h4_bias == "BULLISH": score += 12; reasons.append("H4 Bullish")
        if h1_bias == "BULLISH": score += 12; reasons.append("H1 Bullish")
        if m15_bias == "BULLISH": score += 8; reasons.append("M15 Bullish")
        if location == "DISCOUNT": score += 10; reasons.append("Discount")
        if not sweep or sweep["direction"] != "BUY":
            invalid.append("Belum ada sell-side sweep valid")
    else:
        if h4_bias == "BEARISH": score += 12; reasons.append("H4 Bearish")
        if h1_bias == "BEARISH": score += 12; reasons.append("H1 Bearish")
        if m15_bias == "BEARISH": score += 8; reasons.append("M15 Bearish")
        if location == "PREMIUM": score += 10; reasons.append("Premium")
        if not sweep or sweep["direction"] != "SELL":
            invalid.append("Belum ada buy-side sweep valid")

    if sweep:
        score += 15
        reasons.append("Liquidity Sweep")
        disp, disp_idx = has_displacement_after(c_m15, direction, sweep["idx"])
        mss = mss_after_sweep(c_m15, direction, sweep["idx"])
    else:
        disp, disp_idx, mss = False, None, None

    if disp:
        score += 15
        reasons.append("Displacement")
    else:
        invalid.append("Belum ada displacement setelah sweep")

    if mss:
        score += 15
        reasons.append("MSS/BOS")
    else:
        invalid.append("Belum ada MSS/BOS setelah sweep")

    start_idx = disp_idx if disp_idx is not None else (sweep["idx"] if sweep else len(exec_c)-20)
    fvg = find_fvg_after(exec_c, direction, max(2, start_idx - 5))
    ob = find_order_block_after(exec_c, direction, max(2, start_idx - 8))
    ote = ote_zone(c_m15, direction)
    crt, crt_reason = crt_zone(exec_c, direction)

    zone = overlap(fvg, ob)
    zone_name = "FVG + OB"
    if not zone:
        zone = overlap(fvg, ote)
        zone_name = "FVG + OTE"
    if not zone:
        zone = overlap(ob, ote)
        zone_name = "OB + OTE"

    if fvg: score += 10; reasons.append("FVG")
    if ob: score += 10; reasons.append("OB")
    if ote: score += 5; reasons.append("OTE")
    if crt:
        score += 15
        reasons.append("CRT")
    else:
        invalid.append("Belum ada CRT sweep/reclaim valid")
    if session_ok: score += 5; reasons.append(session_tag)

    # CRT dipakai sebagai filter tambahan: entry lebih valid kalau POI overlap dengan CRT range.
    crt_overlap = overlap(crt, zone) if crt and zone else None
    if crt_overlap:
        zone = crt_overlap
        zone_name = "CRT + " + zone_name
    elif crt and not zone:
        zone = crt
        zone_name = "CRT Zone"

    if not zone:
        invalid.append("Belum ada overlap FVG/OB/OTE valid")

    atr = avg_range(exec_c, 20)
    if zone:
        zone = apply_price_offset_to_zone(zone, price_offset)

    if zone:
        zone_mid = float(zone["mid"])
        if direction == "BUY" and zone_mid > eq:
            invalid.append("POI BUY tidak di discount zone")
        if direction == "SELL" and zone_mid < eq:
            invalid.append("POI SELL tidak di premium zone")

        max_distance = max(atr * 1.2, 0.60 if pair_key == "XAUUSD" else 0.0008)
        if abs(zone_mid - price) > max_distance:
            invalid.append("POI terlalu jauh dari harga realtime")
        if direction == "BUY" and price > float(zone["high"]) + atr * 1.2:
            invalid.append("Harga sudah terlalu jauh di atas entry zone")
        if direction == "SELL" and price < float(zone["low"]) - atr * 1.2:
            invalid.append("Harga sudah terlalu jauh di bawah entry zone")

    if score < 88:
        invalid.append("Score belum cukup untuk CRT precision entry")

    if invalid:
        invalid_text = "\n".join([f"• {x}" for x in invalid[:5]])
        result = f"""
⚪ <b>CAPITAL ELITE NO TRADE</b>

💰 <b>{pair['name']}</b> | <b>{tf_key}</b> • {session_tag}
📍 Price: <code>{fmt(price)}</code>
⏱️ Update: <b>{wib_now().strftime("%H:%M:%S WIB")}</b>
📡 Price Source: <b>{live_source}</b>

📊 Score: <b>{min(score, 99)}/100</b>
🧭 Bias: <b>{direction}</b>

📈 H4: <b>{h4_bias}</b> | H1: <b>{h1_bias}</b>
📈 M15: <b>{m15_bias}</b> | M5: <b>{m5_bias}</b>

{invalid_text}

Rule:
Entry valid = CRT + POI dekat harga realtime + sweep → displacement → MSS.

{disclaimer_footer()}
"""
        cache_set(cache_key, result)
        return result

    entry_low = float(zone["low"])
    entry_high = float(zone["high"])
    entry_mid = (entry_low + entry_high) / 2

    if direction == "BUY":
        sweep_price_live = float(sweep["price"]) + price_offset
        m15_lows_live = [x + price_offset for x in lows(tail(c_m15, 30))]
        sl = min([sweep_price_live] + m15_lows_live + [entry_low]) - atr * 0.45
        risk = max(entry_high - sl, 0.0001)
        tp1 = entry_high + risk * 1.3
        tp2 = entry_high + risk * 2.0
        m15_highs_live = [x + price_offset for x in highs(tail(c_m15, 50))]
        tp3 = max(m15_highs_live + [entry_high + risk * 2.5])
        label = "🟢 BUY PLAN"
    else:
        sweep_price_live = float(sweep["price"]) + price_offset
        m15_highs_live = [x + price_offset for x in highs(tail(c_m15, 30))]
        sl = max([sweep_price_live] + m15_highs_live + [entry_high]) + atr * 0.45
        risk = max(sl - entry_low, 0.0001)
        tp1 = entry_low - risk * 1.3
        tp2 = entry_low - risk * 2.0
        m15_lows_live = [x + price_offset for x in lows(tail(c_m15, 50))]
        tp3 = min(m15_lows_live + [entry_low - risk * 2.5])
        label = "🔴 SELL PLAN"

    rr = rr_calc(direction, entry_low, entry_high, sl, tp2)
    rpips = risk_pips(pair_key, entry_mid, sl)

    if rr < 1.8:
        result = f"""
⚪ <b>CAPITAL ELITE NO TRADE</b>

💰 <b>{pair['name']}</b> | <b>{tf_key}</b>
📍 Price: <code>{fmt(price)}</code>
📊 Score: <b>{min(score, 99)}/100</b>

RR belum ideal.
⚖️ RR: <b>1:{rr:.2f}</b>

{disclaimer_footer()}
"""
        cache_set(cache_key, result)
        return result

    grade = "ELITE S+" if score >= 95 else "A+" if score >= 90 else "A"
    reason_text = " | ".join(reasons[:7])

    result_text = f"""
🎯 <b>CAPITAL ELITE CRT ENTRY</b>

💰 <b>{pair['name']}</b> | <b>{tf_key}</b>
{label}
📊 Score: <b>{min(score, 99)}/100</b> | <b>{grade}</b>
⏱️ Update: <b>{wib_now().strftime("%H:%M:%S WIB")}</b>
📡 Price Source: <b>{live_source}</b>

📍 Entry: <code>{fmt(entry_low)} - {fmt(entry_high)}</code>
📌 Recent: <code>{fmt(price)}</code>
🧩 POI: <b>{zone_name}</b>

🛑 SL: <code>{fmt(sl)}</code>
📏 Risk: <b>{rpips:.0f} pips</b>
⚖️ RR: <b>1:{rr:.2f}</b>

🎯 TP1: <code>{fmt(tp1)}</code>
🎯 TP2: <code>{fmt(tp2)}</code>
🎯 TP3: <code>{fmt(tp3)}</code>

✅ {reason_text}

⚠️ Entry hanya saat harga masuk zone + rejection M1/M5.
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
        [InlineKeyboardButton("📊 Market Analysis", callback_data="menu_market")],
        [InlineKeyboardButton("🎯 Sniper Scanner", callback_data="sniper_menu")],
        [InlineKeyboardButton("📰 News Desk", callback_data="menu_news")],
        [InlineKeyboardButton("👤 Account", callback_data="account")],
        [InlineKeyboardButton("💎 Premium", callback_data="upgrade")],
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

    if data in ["menu_market", "menu_pairs"]:
        if not can_use_market(user_id):
            await q.edit_message_text(
                "🔒 <b>FREE TRIAL MARKET HABIS</b>\n\nUpgrade premium untuk akses unlimited.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 Upgrade Premium", callback_data="upgrade")]]),
                parse_mode="HTML"
            )
            return
        keyboard = [
            [InlineKeyboardButton("🥇 Metals", callback_data="cat_metals"), InlineKeyboardButton("₿ Crypto", callback_data="cat_crypto")],
            [InlineKeyboardButton("💱 Forex", callback_data="cat_forex"), InlineKeyboardButton("📈 Indices", callback_data="cat_indices")],
            [InlineKeyboardButton("⬅️ Back", callback_data="back_start")]
        ]
        await q.edit_message_text("📊 <b>CAPITAL ELITE MARKET ANALYSIS</b>\n\nPilih kategori market:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data.startswith("cat_"):
        category = data.replace("cat_", "")
        if category == "metals":
            title = "🥇 Metals"
            keyboard = [[InlineKeyboardButton("🥇 XAU/USD", callback_data="pair_XAUUSD"), InlineKeyboardButton("🥈 XAG/USD", callback_data="pair_XAGUSD")],[InlineKeyboardButton("⬅️ Back", callback_data="menu_market")]]
        elif category == "crypto":
            title = "₿ Crypto"
            keyboard = [[InlineKeyboardButton("₿ BTC/USD", callback_data="pair_BTCUSD"), InlineKeyboardButton("♦ ETH/USD", callback_data="pair_ETHUSD")],[InlineKeyboardButton("⬅️ Back", callback_data="menu_market")]]
        elif category == "forex":
            title = "💱 Forex"
            keyboard = [[InlineKeyboardButton("🇪🇺 EUR/USD", callback_data="pair_EURUSD"), InlineKeyboardButton("🇬🇧 GBP/USD", callback_data="pair_GBPUSD")],[InlineKeyboardButton("🇯🇵 USD/JPY", callback_data="pair_USDJPY"), InlineKeyboardButton("🇦🇺 AUD/USD", callback_data="pair_AUDUSD")],[InlineKeyboardButton("⬅️ Back", callback_data="menu_market")]]
        else:
            title = "📈 Indices"
            keyboard = [[InlineKeyboardButton("📈 NAS100", callback_data="pair_NAS100"), InlineKeyboardButton("🏛️ US30", callback_data="pair_US30")],[InlineKeyboardButton("⬅️ Back", callback_data="menu_market")]]
        await q.edit_message_text(f"{title}\n\nPilih pair/market:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data.startswith("pair_"):
        pair_key = data.replace("pair_", "")
        keyboard = [
            [InlineKeyboardButton("M1", callback_data=f"tf_{pair_key}_M1"), InlineKeyboardButton("M5", callback_data=f"tf_{pair_key}_M5"), InlineKeyboardButton("M15", callback_data=f"tf_{pair_key}_M15")],
            [InlineKeyboardButton("M30", callback_data=f"tf_{pair_key}_M30"), InlineKeyboardButton("H1", callback_data=f"tf_{pair_key}_H1"), InlineKeyboardButton("H4", callback_data=f"tf_{pair_key}_H4")],
            [InlineKeyboardButton("DAILY", callback_data=f"tf_{pair_key}_DAILY")],
            [InlineKeyboardButton("⬅️ Back", callback_data="menu_market")]
        ]
        await q.edit_message_text(f"💰 <b>{PAIRS[pair_key]['name']}</b>\n\nPilih timeframe analisa:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data.startswith("tf_"):
        if not can_use_market(user_id):
            await q.edit_message_text("🔒 <b>FREE TRIAL MARKET HABIS</b>\n\nUpgrade premium untuk akses unlimited.", parse_mode="HTML")
            return
        parts = data.split("_")
        pair_key, tf_key = parts[1], parts[2]
        await q.edit_message_text(f"🔍 <b>Scanning {PAIRS[pair_key]['name']}</b>\nTF: <b>{tf_key}</b>\n\nFetching realtime quote + validating SMC/ICT/WCO...", parse_mode="HTML")
        try:
            hasil = get_market_analysis(pair_key, tf_key)
            add_market_usage(user_id)
            user = get_user(user_id)
            if not user["premium"]:
                hasil += f"\n\n🆓 Sisa trial market: {TRIAL_LIMIT_MARKET - user['market_used']} analisa"
        except Exception as e:
            hasil = f"""👑 <b>CAPITAL ELITE PROJECT</b>\n\n📡 <b>Market Data Sync</b>\nSistem sedang validasi data market terbaru.\n\nDetail:\n<code>{type(e).__name__}: {str(e)[:160]}</code>\n\n🔄 Coba klik ulang 30-60 detik lagi.\n\n⚠️ <b>Not Financial Advice</b>\nTrading memiliki risiko tinggi."""
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data=f"tf_{pair_key}_{tf_key}")],
            [InlineKeyboardButton("⏱️ Ganti TF", callback_data=f"pair_{pair_key}"), InlineKeyboardButton("📊 Market", callback_data="menu_market")],
            [InlineKeyboardButton("🏠 Home", callback_data="back_start")]
        ]
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
            [InlineKeyboardButton("🥇 XAU", callback_data="sniper_XAUUSD"), InlineKeyboardButton("🥈 XAG", callback_data="sniper_XAGUSD")],
            [InlineKeyboardButton("₿ BTC", callback_data="sniper_BTCUSD"), InlineKeyboardButton("♦ ETH", callback_data="sniper_ETHUSD")],
            [InlineKeyboardButton("🇪🇺 EUR", callback_data="sniper_EURUSD"), InlineKeyboardButton("🇬🇧 GBP", callback_data="sniper_GBPUSD")],
            [InlineKeyboardButton("🇯🇵 JPY", callback_data="sniper_USDJPY"), InlineKeyboardButton("🇦🇺 AUD", callback_data="sniper_AUDUSD")],
            [InlineKeyboardButton("📈 NAS100", callback_data="sniper_NAS100"), InlineKeyboardButton("🏛️ US30", callback_data="sniper_US30")],
            [InlineKeyboardButton("⬅️ Back", callback_data="back_start")]
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
            text = format_news_result_message(events[:5])
            text += "\nGunakan command manual jika data belum kebaca:\n<code>/news cpi actual=3.2 forecast=3.4 previous=3.5</code>"
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
<s>Rp 499.000</s> 🔥 <b>Rp 299.000</b>

👑 <b>VIP ACCESS — 90 HARI</b>
<b>Rp 399.000</b>

♾️ <b>LIFETIME ACCESS</b>
<b>Rp 1.999.000</b>

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
    m = re.search(r"Score:\s*</b>\s*<b>(\d+)/100", text)
    if not m:
        m = re.search(r"Score:\s*<b>(\d+)/100", text)
    if not m:
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
    if "NO TRADE" in text or "NO SETUP" in text:
        return "NO SETUP"
    if "STRONG BUY" in text or "BUY PLAN" in text or "🟢" in text:
        return "BUY"
    if "STRONG SELL" in text or "SELL PLAN" in text or "🔴" in text:
        return "SELL"
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




async def realtime_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Lu bukan admin.")
        return

    db = load_json_file(REALTIME_SIGNAL_FILE, {})
    pairs = ", ".join(REALTIME_SCAN_PAIRS)

    text = f"""
📡 <b>REALTIME SCANNER STATUS</b>

Status: <b>ACTIVE</b>
Interval: <b>{REALTIME_SCAN_INTERVAL} detik</b>
TF: <b>{REALTIME_SCAN_TF}</b>
Pairs: <code>{pairs}</code>

Last Signals:
"""
    if not db:
        text += "\nBelum ada signal realtime."
    else:
        for pair, data in db.items():
            text += f"\n• {pair} — Score {data.get('score','-')} — {data.get('time','-')}"

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




# ==============================
# REALTIME AUTO SCANNER
# ==============================
def parse_signal_score(text):
    m = re.search(r"Score:\s*</b>\s*<b>(\d+)/100", str(text))
    if not m:
        m = re.search(r"Score:\s*<b>(\d+)/100", str(text))
    if not m:
        m = re.search(r"Score:\s*(\d+)/100", str(text), re.I)
    if not m:
        return 0
    try:
        return int(m.group(1))
    except Exception:
        return 0


def parse_signal_direction(text):
    clean = str(text)
    if "STRONG BUY" in clean or "BUY PLAN" in clean or "🟢" in clean:
        return "BUY"
    if "STRONG SELL" in clean or "SELL PLAN" in clean or "🔴" in clean:
        return "SELL"
    return "WAIT"


def parse_signal_entry(text):
    clean = re.sub(r"<[^>]+>", "", str(text))
    m = re.search(r"Entry:\s*([0-9.]+)\s*-\s*([0-9.]+)", clean, re.I)
    if not m:
        return "NA"
    try:
        a = float(m.group(1))
        b = float(m.group(2))
        return str(round((a + b) / 2, 2))
    except Exception:
        return "NA"


def should_broadcast_realtime(pair_key, tf_key, analysis_text, cooldown_minutes=90):
    if "NO TRADE" in str(analysis_text):
        return False

    score = parse_signal_score(analysis_text)
    if score < 94:
        return False

    direction = parse_signal_direction(analysis_text)
    entry = parse_signal_entry(analysis_text)
    key = f"{pair_key}_{tf_key}_{direction}_{entry}"

    db = load_json_file(REALTIME_SIGNAL_FILE, {})
    now = wib_now()
    last = db.get(pair_key)

    if last:
        try:
            last_time = datetime.strptime(last.get("time"), "%Y-%m-%d %H:%M:%S")
            if last.get("key") == key and (now - last_time).total_seconds() < cooldown_minutes * 60:
                return False
        except Exception:
            pass

    db[pair_key] = {
        "key": key,
        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "score": score
    }

    # keep db small
    save_json_file(REALTIME_SIGNAL_FILE, db)
    return True


async def realtime_auto_scanner(context):
    try:
        if has_high_impact_news_risk():
            print("REALTIME SCANNER: pause karena high impact news risk")
            return

        users = load_users()
        targets = premium_users(users)
        if not targets:
            print("REALTIME SCANNER: tidak ada premium user")
            return

        for pair_key in REALTIME_SCAN_PAIRS:
            try:
                analysis = get_market_analysis(pair_key, REALTIME_SCAN_TF)

                if should_broadcast_realtime(pair_key, REALTIME_SCAN_TF, analysis):
                    msg = f"""🚨 <b>CAPITAL ELITE REALTIME SIGNAL</b>
<code>{PAIRS[pair_key]['name']} • {REALTIME_SCAN_TF} • Auto Scanner</code>

{analysis}
"""
                    log_signal(pair_key, REALTIME_SCAN_TF, analysis)

                    for uid in targets:
                        try:
                            await context.bot.send_message(
                                chat_id=int(uid),
                                text=msg,
                                parse_mode="HTML"
                            )
                        except Exception:
                            pass

                    print(f"REALTIME SIGNAL SENT: {pair_key}")

                pytime.sleep(1.2)

            except Exception as e:
                print(f"REALTIME SCANNER ERROR {pair_key}:", e)

    except Exception as e:
        print("REALTIME AUTO SCANNER ERROR:", e)


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

# ==============================
# NEWS RESULT ENGINE
# ==============================
def extract_news_values(raw_text):
    """
    Coba ambil Actual / Forecast / Previous dari teks Forex Factory.
    Karena HTML FF bisa berubah, parser dibuat fleksibel.
    """
    raw = re.sub(r"\s+", " ", str(raw_text)).strip()

    def find_value(label_patterns):
        for pat in label_patterns:
            m = re.search(pat, raw, flags=re.I)
            if m:
                return m.group(1).strip()
        return None

    actual = find_value([
        r"Actual\s*[: ]\s*([+-]?\d+(?:\.\d+)?%?[KMB]?)",
        r"Act(?:ual)?\s*([+-]?\d+(?:\.\d+)?%?[KMB]?)"
    ])
    forecast = find_value([
        r"Forecast\s*[: ]\s*([+-]?\d+(?:\.\d+)?%?[KMB]?)",
        r"Fore(?:cast)?\s*([+-]?\d+(?:\.\d+)?%?[KMB]?)"
    ])
    previous = find_value([
        r"Previous\s*[: ]\s*([+-]?\d+(?:\.\d+)?%?[KMB]?)",
        r"Prev(?:ious)?\s*([+-]?\d+(?:\.\d+)?%?[KMB]?)"
    ])

    # fallback: ambil angka yang muncul, biasanya FF raw kadang urutan actual forecast previous
    nums = re.findall(r"[+-]?\d+(?:\.\d+)?%?[KMB]?", raw, flags=re.I)
    if actual is None and len(nums) >= 1:
        actual = nums[-3] if len(nums) >= 3 else nums[0]
    if forecast is None and len(nums) >= 2:
        forecast = nums[-2]
    if previous is None and len(nums) >= 3:
        previous = nums[-1]

    return actual, forecast, previous


def detect_news_type(raw_text):
    raw = str(raw_text).lower()

    if "core cpi" in raw:
        return "core_cpi"
    if "cpi" in raw or "consumer price index" in raw:
        return "cpi"
    if "core pce" in raw:
        return "core_pce"
    if "pce" in raw:
        return "pce"
    if "ppi" in raw:
        return "ppi"
    if "non-farm" in raw or "nonfarm" in raw or "nfp" in raw:
        return "nfp"
    if "unemployment" in raw:
        return "unemployment"
    if "average hourly earnings" in raw or "earnings" in raw:
        return "earnings"
    if "federal funds" in raw or "interest rate" in raw or "rate decision" in raw:
        return "rate"
    if "fomc" in raw or "powell" in raw:
        return "fomc"
    if "pmi" in raw or "ism" in raw:
        return "pmi"
    if "retail sales" in raw:
        return "retail_sales"
    if "gdp" in raw:
        return "gdp"
    return "general"


def news_to_float(value):
    if value is None:
        return None
    s = str(value).strip().upper().replace(",", "").replace("%", "")
    multiplier = 1
    if s.endswith("K"):
        multiplier = 1000
        s = s[:-1]
    elif s.endswith("M"):
        multiplier = 1000000
        s = s[:-1]
    elif s.endswith("B"):
        multiplier = 1000000000
        s = s[:-1]
    try:
        return float(s) * multiplier
    except Exception:
        return None


def evaluate_news_impact(raw_text):
    """
    Return bias USD dan arah XAU dari Actual vs Forecast.
    Prinsip umum:
    - Inflasi/tenaga kerja/PMI/GDP/retail lebih tinggi dari forecast = USD bullish = XAU bearish.
    - Unemployment lebih tinggi = USD bearish = XAU bullish.
    - Rate/FOMC perlu interpretasi manual, kalau angka ada: rate lebih tinggi = USD bullish.
    """
    actual, forecast, previous = extract_news_values(raw_text)
    news_type = detect_news_type(raw_text)

    actual_num = news_to_float(actual)
    forecast_num = news_to_float(forecast)

    usd_bias = "NEUTRAL"
    xau_direction = "WAIT"
    confidence = 55
    reason = "Data belum lengkap / belum ada actual yang jelas. Tunggu rilis dan reaksi candle."

    if actual_num is not None and forecast_num is not None:
        diff = actual_num - forecast_num

        positive_usd_types = [
            "cpi", "core_cpi", "pce", "core_pce", "ppi", "nfp", "earnings",
            "rate", "pmi", "retail_sales", "gdp", "general"
        ]

        if news_type == "unemployment":
            if diff > 0:
                usd_bias = "BEARISH"
                xau_direction = "BULLISH / BUY BIAS"
                reason = "Unemployment lebih tinggi dari forecast → ekonomi melemah → USD cenderung melemah → XAU berpotensi naik."
                confidence = 82
            elif diff < 0:
                usd_bias = "BULLISH"
                xau_direction = "BEARISH / SELL BIAS"
                reason = "Unemployment lebih rendah dari forecast → tenaga kerja kuat → USD cenderung menguat → XAU berpotensi turun."
                confidence = 82
            else:
                reason = "Actual sama dengan forecast → tunggu reaksi market."

        elif news_type in positive_usd_types:
            if diff > 0:
                usd_bias = "BULLISH"
                xau_direction = "BEARISH / SELL BIAS"
                reason = "Actual lebih tinggi dari forecast → USD cenderung menguat → XAU berpotensi tertekan."
                confidence = 84
            elif diff < 0:
                usd_bias = "BEARISH"
                xau_direction = "BULLISH / BUY BIAS"
                reason = "Actual lebih rendah dari forecast → USD cenderung melemah → XAU berpotensi naik."
                confidence = 84
            else:
                reason = "Actual sama dengan forecast → potensi market choppy, tunggu candle confirmation."

        if abs(diff) > 0:
            try:
                base = abs(forecast_num) if abs(forecast_num) > 0 else 1
                surprise = abs(diff) / base
                if surprise >= 0.10:
                    confidence = min(confidence + 8, 95)
                elif surprise >= 0.05:
                    confidence = min(confidence + 4, 90)
            except Exception:
                pass

    if news_type in ["fomc"] and actual_num is None:
        usd_bias = "WAIT"
        xau_direction = "WAIT FOR STATEMENT"
        confidence = 65
        reason = "FOMC/Powell perlu baca tone statement. Tunggu 1-2 candle M5 setelah rilis."

    return {
        "type": news_type,
        "actual": actual or "-",
        "forecast": forecast or "-",
        "previous": previous or "-",
        "usd_bias": usd_bias,
        "xau_direction": xau_direction,
        "confidence": confidence,
        "reason": reason
    }


def format_news_result_message(events):
    today = wib_now().strftime("%d %b %Y")
    text = f"""📰 <b>CAPITAL ELITE NEWS RESULT</b>
<code>{today} • Auto Impact</code>
"""

    for ev in events[:4]:
        raw_event = str(ev.get("raw", "-"))
        clean_event = clean_ff_event_text(raw_event)
        wib_time = convert_ff_time_to_wib(raw_event)
        impact = evaluate_news_impact(raw_event)

        text += f"""
━━━━━━━━━━━━━━
🇺🇸 <b>USD NEWS</b> • {wib_time}
📌 {clean_event[:140]}

Actual: <b>{impact['actual']}</b>
Forecast: <b>{impact['forecast']}</b>
Previous: <b>{impact['previous']}</b>

💵 USD Bias: <b>{impact['usd_bias']}</b>
🥇 XAUUSD: <b>{impact['xau_direction']}</b>
📊 Confidence: <b>{impact['confidence']}%</b>

{impact['reason']}
"""

    text += f"""
━━━━━━━━━━━━━━
⚠️ <b>Execution Rule</b>
Jangan entry di detik rilis.
Tunggu 1-2 candle M5 close + spread normal.

⚠️ <b>Not Financial Advice</b>
Trading memiliki risiko tinggi.
"""
    return text


async def auto_news_alert(context):
    try:
        events = parse_forex_factory_today()

        if not events:
            print("FOREX FACTORY: Tidak ada news USD penting / gagal dibaca")
            return

        users = load_users()
        targets = list(users.keys())

        sent_db = load_json_file(NEWS_SENT_FILE, {})
        today_key = wib_now().strftime("%Y-%m-%d")
        sent_today = set(sent_db.get(today_key, []))

        important_terms = [
            "cpi", "core cpi", "consumer price index", "nfp", "non-farm", "nonfarm",
            "fomc", "federal funds rate", "interest rate", "powell", "pce", "core pce",
            "ppi", "unemployment", "average hourly earnings", "pmi", "ism", "gdp",
            "retail sales"
        ]

        selected_events = []
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
            print("FOREX FACTORY: news penting sudah pernah dikirim / belum ada actual baru")
            return

        message = format_news_result_message([ev for key, ev in selected_events[:4]])

        for key, ev in selected_events[:4]:
            sent_today.add(key)

        sent_db[today_key] = list(sent_today)
        sorted_days = sorted(sent_db.keys())[-7:]
        sent_db = {d: sent_db[d] for d in sorted_days}
        save_json_file(NEWS_SENT_FILE, sent_db)

        for uid in targets:
            try:
                await context.bot.send_message(
                    chat_id=int(uid),
                    text=message,
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
app.add_handler(CommandHandler("realtime", realtime_status_command))
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

# Realtime auto scanner every 60 seconds
app.job_queue.run_repeating(
    realtime_auto_scanner,
    interval=REALTIME_SCAN_INTERVAL,
    first=30
)

print("CAPITAL ELITE PROJECT BOT ONLINE...")
app.run_polling()

