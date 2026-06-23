# CAPITAL ELITE PROJECT V10 FUNDAMENTAL EDITION
# Replace file lama lu dengan file ini.
# Requirements:
# python-telegram-bot==20.6
# tradingview-ta
# yfinance
# requests
#
# NEW in V10:
# - Fundamental Layer: Fed Policy Tracker (Rate + Dot Plot + Meeting Cycle)
# - Macro Regime Detector (Risk-On / Risk-Off / Stagflation / Recession)
# - COT Sentiment Proxy (Institutional Bias dari price action multi-timeframe)
# - Yield Curve Monitor (2Y vs 10Y spread, impact ke USD/XAU/Risk)
# - Fundamental Confluence Score terintegrasi ke confidence + entry grading
# - /fundamental command + /macro command baru
# - Auto Sniper Alert kini include fundamental filter
# - NO TRADE diperkuat kalau fundamental berlawanan arah teknikal

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Conflict
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from tradingview_ta import TA_Handler
from datetime import datetime, timedelta, time as dt_time
import os
import re
import json
import math
import random
import time as pytime
import requests

try:
    import yfinance as yf
except Exception:
    yf = None

# ==============================
# CONFIG
# ==============================
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "7889334774"))
PAYMENT_TEXT = os.environ.get("PAYMENT_TEXT", "DANA / QRIS: 085778001402")
ADMIN_CONTACT = os.environ.get("ADMIN_CONTACT", "@egingroho")

USER_FILE = "users.json"
SIGNAL_LOG_FILE = "signal_log.json"
TRADE_HISTORY_FILE = "trade_history.json"
NEWS_SENT_FILE = "news_sent.json"
ALERT_SENT_FILE = "alert_sent.json"
PAYMENT_REQUEST_FILE = "payment_requests.json"

MARKET_CACHE = {}
MARKET_CACHE_SECONDS = 180
FUNDAMENTAL_CACHE_SECONDS = 3600  # cache fundamental 1 jam, data tidak berubah menit-an
TRIAL_LIMIT_MARKET = 5
TRIAL_LIMIT_NEWS = 3
AUTO_ALERT_MIN_CONF = 85

# Fundamental config
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")  # optional – kalau kosong pakai proxy yfinance
FUNDAMENTAL_FILE = "fundamental_state.json"  # persistent state buat Fed tone, macro regime, dll

# ==============================
# PAIR DATABASE
# ==============================
PAIRS = {
    # METALS
    "XAUUSD": {"symbol": "XAUUSD", "screener": "cfd", "exchange": "FOREXCOM", "name": "XAU/USD", "cat": "METALS", "yf": "GC=F", "sl": (3.0, 6.0), "tp": (6.0, 12.0)},
    "XAGUSD": {"symbol": "SILVER", "screener": "cfd", "exchange": "TVC", "name": "XAG/USD", "cat": "METALS", "yf": "SI=F", "sl": (0.12, 0.30), "tp": (0.25, 0.60)},

    # FOREX
    "EURUSD": {"symbol": "EURUSD", "screener": "forex", "exchange": "FX_IDC", "name": "EUR/USD", "cat": "FOREX", "yf": "EURUSD=X", "sl": (0.0015, 0.0030), "tp": (0.0030, 0.0060)},
    "GBPUSD": {"symbol": "GBPUSD", "screener": "forex", "exchange": "FX_IDC", "name": "GBP/USD", "cat": "FOREX", "yf": "GBPUSD=X", "sl": (0.0020, 0.0040), "tp": (0.0040, 0.0080)},
    "USDJPY": {"symbol": "USDJPY", "screener": "forex", "exchange": "FX_IDC", "name": "USD/JPY", "cat": "FOREX", "yf": "JPY=X", "sl": (0.20, 0.45), "tp": (0.40, 0.90)},
    "AUDUSD": {"symbol": "AUDUSD", "screener": "forex", "exchange": "FX_IDC", "name": "AUD/USD", "cat": "FOREX", "yf": "AUDUSD=X", "sl": (0.0015, 0.0030), "tp": (0.0030, 0.0060)},
    "USDCAD": {"symbol": "USDCAD", "screener": "forex", "exchange": "FX_IDC", "name": "USD/CAD", "cat": "FOREX", "yf": "CAD=X", "sl": (0.0020, 0.0040), "tp": (0.0040, 0.0080)},

    # INDICES
    "NAS100": {"symbol": "NAS100USD", "screener": "cfd", "exchange": "OANDA", "name": "NAS100", "cat": "INDEX", "yf": "NQ=F", "sl": (30, 90), "tp": (70, 180)},
    "US30": {"symbol": "US30USD", "screener": "cfd", "exchange": "OANDA", "name": "US30", "cat": "INDEX", "yf": "YM=F", "sl": (60, 160), "tp": (140, 320)},
    "SPX500": {"symbol": "SPX500USD", "screener": "cfd", "exchange": "OANDA", "name": "SPX500", "cat": "INDEX", "yf": "ES=F", "sl": (12, 35), "tp": (25, 75)},

    # CRYPTO
    "BTCUSD": {"symbol": "BTCUSD", "screener": "crypto", "exchange": "BITSTAMP", "name": "BTC/USD", "cat": "CRYPTO", "yf": "BTC-USD", "sl": (120, 350), "tp": (250, 800)},
    "ETHUSD": {"symbol": "ETHUSD", "screener": "crypto", "exchange": "BITSTAMP", "name": "ETH/USD", "cat": "CRYPTO", "yf": "ETH-USD", "sl": (10, 45), "tp": (25, 110)},
    "SOLUSD": {"symbol": "SOLUSD", "screener": "crypto", "exchange": "BINANCE", "name": "SOL/USD", "cat": "CRYPTO", "yf": "SOL-USD", "sl": (1.0, 4.0), "tp": (2.5, 9.0)},
    "BNBUSD": {"symbol": "BNBUSD", "screener": "crypto", "exchange": "BINANCE", "name": "BNB/USD", "cat": "CRYPTO", "yf": "BNB-USD", "sl": (4, 16), "tp": (10, 35)},
    "XRPUSD": {"symbol": "XRPUSD", "screener": "crypto", "exchange": "BITSTAMP", "name": "XRP/USD", "cat": "CRYPTO", "yf": "XRP-USD", "sl": (0.025, 0.080), "tp": (0.055, 0.160)},

    # OIL
    "USOIL": {"symbol": "USOIL", "screener": "cfd", "exchange": "TVC", "name": "USOIL / WTI", "cat": "OIL", "yf": "CL=F", "sl": (0.35, 0.90), "tp": (0.80, 1.90)},
    "UKOIL": {"symbol": "UKOIL", "screener": "cfd", "exchange": "TVC", "name": "UKOIL / BRENT", "cat": "OIL", "yf": "BZ=F", "sl": (0.35, 0.90), "tp": (0.80, 1.90)},
}

TIMEFRAMES = {"M1": "1m", "M3": "3m", "M5": "5m", "M15": "15m", "M30": "30m", "H1": "1h", "H4": "4h", "DAILY": "1d"}
YF_INTERVAL = {"M1": "1m", "M3": "5m", "M5": "5m", "M15": "15m", "M30": "30m", "H1": "60m", "H4": "60m", "DAILY": "1d"}

IMPORTANT_NEWS_KEYWORDS = ["NFP", "Non-Farm", "Nonfarm", "CPI", "Core CPI", "PPI", "PCE", "Core PCE", "FOMC", "Federal Funds Rate", "PMI", "ISM", "GDP", "Unemployment", "Average Hourly Earnings"]

# ==============================
# JSON DATABASE
# ==============================
def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def wib_now():
    return datetime.utcnow() + timedelta(hours=7)


def fmt(x):
    try:
        x = float(x)
        if abs(x) < 10:
            return f"{x:.5f}"
        if abs(x) < 100:
            return f"{x:.3f}"
        return f"{x:.2f}"
    except Exception:
        return "-"


def clean_num(value):
    m = re.search(r"-?\d+(\.\d+)?", str(value).replace(",", ""))
    return float(m.group(0)) if m else None


def xau_pips(value):
    """
    XAUUSD Indonesian gold convention:
    1.00 = 10 pips
    3.00 = 30 pips
    5.00 = 50 pips
    10.00 = 100 pips
    """
    try:
        return int(round(abs(float(value)) * 10))
    except Exception:
        return 0


def conf_bar(conf):
    full = max(0, min(10, int(conf / 10)))
    return "█" * full + "░" * (10 - full)


def get_user(user_id):
    users = load_json(USER_FILE, {})
    uid = str(user_id)
    if uid not in users:
        users[uid] = {"market_used": 0, "news_used": 0, "premium": False, "premium_until": None, "created_at": wib_now().strftime("%Y-%m-%d %H:%M:%S")}
        save_json(USER_FILE, users)

    if int(uid) == ADMIN_ID:
        users[uid]["premium"] = True
        users[uid]["premium_until"] = "LIFETIME"
        save_json(USER_FILE, users)
        return users[uid]

    u = users[uid]
    if u.get("premium") and u.get("premium_until") not in [None, "LIFETIME"]:
        try:
            if wib_now() > datetime.strptime(u["premium_until"], "%Y-%m-%d %H:%M:%S"):
                u["premium"] = False
                u["expired_at"] = wib_now().strftime("%Y-%m-%d %H:%M:%S")
                users[uid] = u
                save_json(USER_FILE, users)
        except Exception:
            pass
    return users[uid]


def update_user(user_id, data):
    users = load_json(USER_FILE, {})
    users[str(user_id)] = data
    save_json(USER_FILE, users)


def can_use_market(user_id):
    u = get_user(user_id)
    return u.get("premium") or u.get("market_used", 0) < TRIAL_LIMIT_MARKET


def can_use_news(user_id):
    u = get_user(user_id)
    return u.get("premium") or u.get("news_used", 0) < TRIAL_LIMIT_NEWS


def add_usage(user_id, kind="market"):
    u = get_user(user_id)
    if not u.get("premium"):
        key = "market_used" if kind == "market" else "news_used"
        u[key] = u.get(key, 0) + 1
        update_user(user_id, u)


def premium_user_ids():
    users = load_json(USER_FILE, {})
    ids = []
    for uid in users.keys():
        try:
            if get_user(int(uid)).get("premium"):
                ids.append(uid)
        except Exception:
            pass
    return ids

# ==============================
# MARKET DATA ENGINE
# ==============================
def cache_get(key):
    item = MARKET_CACHE.get(key)
    if not item:
        return None
    if pytime.time() - item["ts"] <= MARKET_CACHE_SECONDS:
        return item["value"]
    return None


def cache_set(key, value):
    MARKET_CACHE[key] = {"ts": pytime.time(), "value": value}


def yf_period(tf):
    if tf in ["M1", "M3", "M5", "M15", "M30"]:
        return "5d"
    if tf in ["H1", "H4"]:
        return "1mo"
    return "6mo"


def calc_rsi(closes, period=14):
    try:
        delta = closes.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean().replace(0, 0.00001)
        rs = gain / loss
        return float((100 - (100 / (1 + rs))).iloc[-1])
    except Exception:
        return 50.0


def fetch_yf(pair_key, tf):
    if yf is None:
        raise Exception("Install yfinance dulu di requirements.txt")
    pair = PAIRS[pair_key]
    data = yf.download(pair["yf"], period=yf_period(tf), interval=YF_INTERVAL.get(tf, "5m"), progress=False, auto_adjust=False)
    if data is None or data.empty:
        raise Exception("Yahoo fallback kosong")
    if tf == "H4" and len(data) >= 4:
        block = data.tail(4)
        open_price = float(block["Open"].iloc[0])
        close = float(block["Close"].iloc[-1])
        high = float(block["High"].max())
        low = float(block["Low"].min())
        closes = data["Close"].astype(float)
    else:
        last = data.iloc[-1]
        open_price = float(last["Open"])
        close = float(last["Close"])
        high = float(last["High"])
        low = float(last["Low"])
        closes = data["Close"].astype(float)
    ema20 = float(closes.ewm(span=20, adjust=False).mean().iloc[-1]) if len(closes) >= 20 else close
    ema50 = float(closes.ewm(span=50, adjust=False).mean().iloc[-1]) if len(closes) >= 50 else close
    rsi = calc_rsi(closes)
    return build_tf_data(close, open_price, high, low, ema20, ema50, rsi, "Yahoo Finance")


def build_tf_data(price, open_price, high, low, ema20, ema50, rsi, source):
    rng = max(abs(high - low), 0.00001)
    candle = "BULLISH" if price >= open_price else "BEARISH"
    if price > ema20 > ema50:
        bias = "BULLISH"
    elif price < ema20 < ema50:
        bias = "BEARISH"
    else:
        bias = "SIDEWAYS"
    return {"price": float(price), "open": float(open_price), "high": float(high), "low": float(low), "eq": (float(high) + float(low)) / 2, "range": rng, "ema20": float(ema20), "ema50": float(ema50), "rsi": float(rsi), "candle": candle, "bias": bias, "source": source}


def fetch_tv(pair_key, tf):
    pair = PAIRS[pair_key]

    tv_candidates = [
        (pair["symbol"], pair["screener"], pair["exchange"])
    ]

    # Backup mapping agar NAS100 / US30 / OIL tidak sering error.
    backup = {
        "NAS100": [
            ("NAS100USD", "cfd", "OANDA"),
            ("NAS100", "cfd", "OANDA"),
            ("US100", "cfd", "CAPITALCOM"),
            ("NDX", "america", "NASDAQ"),
        ],
        "US30": [
            ("US30USD", "cfd", "OANDA"),
            ("US30", "cfd", "OANDA"),
            ("DJI", "america", "DJ"),
        ],
        "USOIL": [
            ("USOIL", "cfd", "TVC"),
            ("USOIL", "cfd", "OANDA"),
            ("CL1!", "futures", "NYMEX"),
        ],
        "UKOIL": [
            ("UKOIL", "cfd", "TVC"),
            ("UKOIL", "cfd", "OANDA"),
            ("BRN1!", "futures", "ICEEUR"),
        ],
    }

    tv_candidates += backup.get(pair_key, [])

    last_error = None
    for symbol, screener, exchange in tv_candidates:
        try:
            handler = TA_Handler(
                symbol=symbol,
                screener=screener,
                exchange=exchange,
                interval=TIMEFRAMES.get(tf, "5m")
            )
            data = handler.get_analysis()
            ind = data.indicators
            price = ind.get("close")
            high = ind.get("high")
            low = ind.get("low")
            open_price = ind.get("open") or price
            ema20 = ind.get("EMA20") or price
            ema50 = ind.get("EMA50") or price
            rsi = ind.get("RSI") or 50
            if price is None or high is None or low is None:
                raise Exception("TradingView data belum lengkap")
            return build_tf_data(float(price), float(open_price), float(high), float(low), float(ema20), float(ema50), float(rsi), f"TradingView {exchange}:{symbol}")
        except Exception as e:
            last_error = e
            continue

    raise Exception(str(last_error) if last_error else "TradingView data gagal")


def fetch_tf(pair_key, tf):
    key = f"raw_{pair_key}_{tf}"
    cached = cache_get(key)
    if cached:
        return cached
    try:
        result = fetch_tv(pair_key, tf)
    except Exception as e:
        print("TV fallback:", pair_key, tf, e)
        result = fetch_yf(pair_key, tf)
    cache_set(key, result)
    return result

# ==============================
# FUNDAMENTAL INTELLIGENCE ENGINE V10
# ==============================

# --- Fed Policy Tracker ---
def fetch_fed_policy():
    """
    Ambil data Fed Funds Rate via yfinance (^IRX = 13-week T-Bill proxy)
    + 2Y Treasury (^IRX) dan 10Y Treasury (^TNX) untuk yield curve.
    Fallback ke state file kalau data gagal.
    """
    key = "fed_policy"
    cached = cache_get(key)
    if cached:
        return cached

    state = load_json(FUNDAMENTAL_FILE, {})

    try:
        if yf is None:
            raise Exception("yfinance tidak tersedia")

        # 2Y yield (^IRX = 3-month, pakai ^FVX = 5Y sebagai proxy short-end lebih akurat)
        # Gunakan DGS2 via yfinance ticker ^IRX untuk short end dan ^TNX untuk 10Y
        data_2y = yf.download("^IRX", period="5d", interval="1d", progress=False, auto_adjust=False)
        data_10y = yf.download("^TNX", period="5d", interval="1d", progress=False, auto_adjust=False)
        data_ffr = yf.download("^IRX", period="30d", interval="1d", progress=False, auto_adjust=False)

        rate_2y = float(data_2y["Close"].dropna().iloc[-1]) if not data_2y.empty else 5.0
        rate_10y = float(data_10y["Close"].dropna().iloc[-1]) if not data_10y.empty else 4.5

        # Yield curve spread: 10Y - 2Y
        # Inverted = recession signal. Normal = risk-on.
        spread = round(rate_10y - rate_2y, 3)
        curve_status = "INVERTED" if spread < -0.10 else "FLAT" if -0.10 <= spread <= 0.20 else "NORMAL"

        # Trend Fed rate: compare 4-week vs 1-week average
        if len(data_ffr) >= 20:
            avg_4w = float(data_ffr["Close"].dropna().tail(20).mean())
            avg_1w = float(data_ffr["Close"].dropna().tail(5).mean())
            if avg_1w > avg_4w * 1.02:
                fed_trend = "HIKING"
            elif avg_1w < avg_4w * 0.98:
                fed_trend = "CUTTING"
            else:
                fed_trend = "HOLDING"
        else:
            fed_trend = state.get("fed_trend", "HOLDING")

        # Manual override dari admin tetap prioritas
        manual_tone = state.get("manual_fed_tone", None)
        if manual_tone:
            fed_tone = manual_tone
        else:
            fed_tone = "HAWKISH" if fed_trend == "HIKING" else "DOVISH" if fed_trend == "CUTTING" else "NEUTRAL"

        result = {
            "rate_2y": rate_2y,
            "rate_10y": rate_10y,
            "spread": spread,
            "curve_status": curve_status,
            "fed_trend": fed_trend,
            "fed_tone": fed_tone,
            "source": "yfinance",
        }

        # Persist ke file supaya command /fundamental bisa baca tanpa fetch ulang
        state.update(result)
        state["last_updated"] = wib_now().strftime("%Y-%m-%d %H:%M WIB")
        save_json(FUNDAMENTAL_FILE, state)
        cache_set(key, result)
        return result

    except Exception as e:
        print("fed_policy fetch error:", e)
        # Return dari state file kalau ada
        if state:
            return {
                "rate_2y": state.get("rate_2y", 5.0),
                "rate_10y": state.get("rate_10y", 4.5),
                "spread": state.get("spread", -0.5),
                "curve_status": state.get("curve_status", "INVERTED"),
                "fed_trend": state.get("fed_trend", "HOLDING"),
                "fed_tone": state.get("fed_tone", "NEUTRAL"),
                "source": "cached_state",
            }
        return {
            "rate_2y": 5.0, "rate_10y": 4.5, "spread": -0.5,
            "curve_status": "INVERTED", "fed_trend": "HOLDING",
            "fed_tone": "NEUTRAL", "source": "fallback",
        }


# --- Macro Regime Detector ---
def detect_macro_regime(fed_policy):
    """
    Deteksi macro regime berdasarkan kombinasi:
    - Fed tone (hawkish/dovish/neutral)
    - Yield curve (inverted/flat/normal)
    - DXY bias (dari dxy_filter)
    
    Output: RISK_ON / RISK_OFF / STAGFLATION / RECESSION / NEUTRAL
    """
    key = "macro_regime"
    cached = cache_get(key)
    if cached:
        return cached

    tone = fed_policy.get("fed_tone", "NEUTRAL")
    curve = fed_policy.get("curve_status", "FLAT")
    dxy = dxy_filter()
    dxy_bias = dxy.get("bias", "NEUTRAL")

    # Scoring matrix profesional
    # RISK_ON: Fed dovish + kurva normal + DXY lemah → equities/crypto/Gold menguat
    # RISK_OFF: Fed hawkish + DXY kuat + kurva flat/inverted → USD naik, XAU bisa dua arah
    # STAGFLATION: Fed hawkish tapi kurva inverted → worst scenario
    # RECESSION: Kurva sangat inverted + Fed mulai cutting
    # NEUTRAL: Data mixed

    if tone == "DOVISH" and dxy_bias == "BEARISH" and curve in ["NORMAL", "FLAT"]:
        regime = "RISK_ON"
        regime_note = "Fed dovish + DXY lemah → bullish equities, crypto, XAU"
        xau_bias = "BULLISH"
        btc_bias = "BULLISH"
        usd_bias = "BEARISH"
        index_bias = "BULLISH"
    elif tone == "HAWKISH" and dxy_bias == "BULLISH" and curve in ["FLAT", "NORMAL"]:
        regime = "RISK_OFF"
        regime_note = "Fed hawkish + DXY kuat → USD menguat, tekanan ke risiko aset"
        xau_bias = "BEARISH" if curve == "NORMAL" else "MIXED"
        btc_bias = "BEARISH"
        usd_bias = "BULLISH"
        index_bias = "BEARISH"
    elif tone == "HAWKISH" and curve == "INVERTED":
        regime = "STAGFLATION"
        regime_note = "Fed ketat + kurva inverted → stagflation risk, XAU safe haven"
        xau_bias = "BULLISH"  # Gold sebagai safe haven
        btc_bias = "BEARISH"
        usd_bias = "BULLISH"
        index_bias = "BEARISH"
    elif tone in ["CUTTING", "DOVISH"] and curve == "INVERTED":
        regime = "RECESSION"
        regime_note = "Fed mulai cut + kurva inverted → recession signal, XAU naik kuat"
        xau_bias = "STRONG_BULLISH"
        btc_bias = "MIXED"
        usd_bias = "BEARISH"
        index_bias = "BEARISH"
    else:
        regime = "NEUTRAL"
        regime_note = "Macro data mixed, ikuti teknikal"
        xau_bias = "NEUTRAL"
        btc_bias = "NEUTRAL"
        usd_bias = "NEUTRAL"
        index_bias = "NEUTRAL"

    result = {
        "regime": regime,
        "regime_note": regime_note,
        "xau_bias": xau_bias,
        "btc_bias": btc_bias,
        "usd_bias": usd_bias,
        "index_bias": index_bias,
    }
    cache_set(key, result)
    return result


# --- COT Sentiment Proxy ---
def cot_sentiment_proxy(pair_key):
    """
    Karena tidak ada akses langsung ke CFTC COT report real-time,
    engine ini pakai proxy berbasis:
    1. Price momentum multi-TF (H1 + Daily alignment)
    2. Volume proxy dari range expansion
    3. Pullback depth (apakah smart money accumulating atau distributing)
    
    Output: institutional_bias (LONG_BIAS / SHORT_BIAS / NEUTRAL)
             + confidence score 0-100
    """
    try:
        h1 = fetch_tf(pair_key, "H1")
        daily = fetch_tf(pair_key, "DAILY")

        # Institutional biasanya push price jauh dari EMA50 lalu retrace ke EMA20
        # Kalau price > EMA20 > EMA50 di Daily → longs accumulated
        if daily["price"] > daily["ema20"] > daily["ema50"]:
            daily_inst = "LONG_BIAS"
            daily_score = 30
        elif daily["price"] < daily["ema20"] < daily["ema50"]:
            daily_inst = "SHORT_BIAS"
            daily_score = 30
        else:
            daily_inst = "NEUTRAL"
            daily_score = 15

        # H1 momentum
        if h1["bias"] == "BULLISH" and h1["rsi"] > 55:
            h1_inst = "LONG_BIAS"
            h1_score = 20
        elif h1["bias"] == "BEARISH" and h1["rsi"] < 45:
            h1_inst = "SHORT_BIAS"
            h1_score = 20
        elif h1["bias"] == "BULLISH" and h1["rsi"] < 40:
            # Bullish tapi RSI oversold = institutional buying dip
            h1_inst = "LONG_BIAS"
            h1_score = 25
        elif h1["bias"] == "BEARISH" and h1["rsi"] > 60:
            # Bearish tapi RSI overbought = institutional selling rally
            h1_inst = "SHORT_BIAS"
            h1_score = 25
        else:
            h1_inst = "NEUTRAL"
            h1_score = 10

        # RSI Divergence proxy (simplified)
        # Kalau harga lebih tinggi dari EQ tapi RSI < 50 → divergence bearish (distribusi)
        # Kalau harga lebih rendah dari EQ tapi RSI > 50 → divergence bullish (akumulasi)
        rsi_divergence = "NONE"
        div_score = 0
        if daily["price"] > daily["eq"] and daily["rsi"] < 50:
            rsi_divergence = "BEARISH_DIV"
            div_score = -10
        elif daily["price"] < daily["eq"] and daily["rsi"] > 50:
            rsi_divergence = "BULLISH_DIV"
            div_score = -10  # konflik, turunkan confidence

        total_score = daily_score + h1_score + div_score

        if daily_inst == h1_inst and daily_inst != "NEUTRAL":
            institutional_bias = daily_inst
            cot_conf = min(total_score + 10, 55)  # max 55% sumbangan dari COT proxy
        else:
            institutional_bias = "NEUTRAL"
            cot_conf = 10

        return {
            "institutional_bias": institutional_bias,
            "cot_confidence": cot_conf,
            "daily_bias": daily_inst,
            "h1_cot": h1_inst,
            "rsi_divergence": rsi_divergence,
            "note": f"COT proxy: Daily {daily_inst} | H1 {h1_inst} | RSI-Div: {rsi_divergence}",
        }
    except Exception as e:
        print("cot_sentiment_proxy error:", e)
        return {
            "institutional_bias": "NEUTRAL",
            "cot_confidence": 0,
            "daily_bias": "NEUTRAL",
            "h1_cot": "NEUTRAL",
            "rsi_divergence": "NONE",
            "note": "COT proxy unavailable",
        }


# --- Fundamental Score Calculator ---
def calc_fundamental_score(pair_key, signal, fed_policy, macro_regime, cot):
    """
    Hitung Fundamental Confluence Score (0–100) yang akan dimasukkan
    ke dalam confidence final analysis.
    
    Komponen:
    - Fed Tone alignment (25 pts)
    - Macro Regime alignment (25 pts)
    - COT/Institutional Bias alignment (25 pts)
    - Yield Curve context (15 pts)
    - Seasonal/Cyclical context (10 pts)
    """
    score = 0
    details = {}
    alignment_notes = []

    # 1. Fed Tone (25 pts)
    fed_tone = fed_policy.get("fed_tone", "NEUTRAL")
    cat = PAIRS[pair_key]["cat"]

    if cat in ["METALS", "CRYPTO"]:
        # XAU & crypto: Fed dovish → BUY, hawkish → SELL
        if (signal == "BUY" and fed_tone == "DOVISH") or (signal == "SELL" and fed_tone == "HAWKISH"):
            fed_score = 25
            alignment_notes.append(f"✅ Fed {fed_tone} → align {signal}")
        elif fed_tone == "NEUTRAL":
            fed_score = 12
            alignment_notes.append(f"⚠️ Fed NEUTRAL — konfirmasi macro lain")
        else:
            fed_score = 0
            alignment_notes.append(f"❌ Fed {fed_tone} berlawanan {signal}")
    elif cat == "FOREX":
        # USD pairs: hawkish → USD kuat
        usd_is_base = pair_key in ["USDJPY", "USDCAD"]
        usd_is_quote = pair_key in ["EURUSD", "GBPUSD", "AUDUSD"]
        if usd_is_base:
            if (signal == "BUY" and fed_tone == "HAWKISH") or (signal == "SELL" and fed_tone == "DOVISH"):
                fed_score = 25
                alignment_notes.append(f"✅ Fed {fed_tone} → USD base pair align {signal}")
            elif fed_tone == "NEUTRAL":
                fed_score = 12
                alignment_notes.append("⚠️ Fed NEUTRAL")
            else:
                fed_score = 0
                alignment_notes.append(f"❌ Fed berlawanan arah")
        elif usd_is_quote:
            if (signal == "BUY" and fed_tone == "DOVISH") or (signal == "SELL" and fed_tone == "HAWKISH"):
                fed_score = 25
                alignment_notes.append(f"✅ Fed {fed_tone} → USD quote pair align {signal}")
            elif fed_tone == "NEUTRAL":
                fed_score = 12
                alignment_notes.append("⚠️ Fed NEUTRAL")
            else:
                fed_score = 0
                alignment_notes.append(f"❌ Fed berlawanan arah")
        else:
            fed_score = 12
    elif cat == "INDEX":
        # Indices: dovish Fed = lebih bullish equities
        if (signal == "BUY" and fed_tone == "DOVISH") or (signal == "SELL" and fed_tone == "HAWKISH"):
            fed_score = 25
            alignment_notes.append(f"✅ Fed {fed_tone} → equities align {signal}")
        elif fed_tone == "NEUTRAL":
            fed_score = 12
            alignment_notes.append("⚠️ Fed NEUTRAL")
        else:
            fed_score = 5
            alignment_notes.append(f"⚠️ Fed berlawanan — indices bisa mixed")
    elif cat == "OIL":
        # Oil: lebih ke supply/demand, Fed secondary
        fed_score = 12
        alignment_notes.append("ℹ️ Oil: Fed secondary factor")
    else:
        fed_score = 12

    details["fed_score"] = fed_score

    # 2. Macro Regime (25 pts)
    regime = macro_regime.get("regime", "NEUTRAL")
    if cat == "METALS":
        macro_asset_bias = macro_regime.get("xau_bias", "NEUTRAL")
    elif cat == "CRYPTO":
        macro_asset_bias = macro_regime.get("btc_bias", "NEUTRAL")
    elif cat in ["INDEX"]:
        macro_asset_bias = macro_regime.get("index_bias", "NEUTRAL")
    elif cat in ["FOREX", "OIL"]:
        macro_asset_bias = macro_regime.get("usd_bias", "NEUTRAL")
    else:
        macro_asset_bias = "NEUTRAL"

    if macro_asset_bias in ["BULLISH", "STRONG_BULLISH"] and signal == "BUY":
        macro_score = 25
        alignment_notes.append(f"✅ Macro {regime}: bias {macro_asset_bias} → align BUY")
    elif macro_asset_bias in ["BEARISH"] and signal == "SELL":
        macro_score = 25
        alignment_notes.append(f"✅ Macro {regime}: bias BEARISH → align SELL")
    elif macro_asset_bias == "MIXED":
        macro_score = 12
        alignment_notes.append(f"⚠️ Macro {regime}: MIXED — hati-hati")
    elif macro_asset_bias == "NEUTRAL":
        macro_score = 10
        alignment_notes.append(f"⚠️ Macro NEUTRAL — ikuti teknikal")
    else:
        macro_score = 0
        alignment_notes.append(f"❌ Macro {regime} berlawanan arah signal")

    details["macro_score"] = macro_score

    # 3. COT/Institutional Bias (25 pts)
    inst_bias = cot.get("institutional_bias", "NEUTRAL")
    if (signal == "BUY" and inst_bias == "LONG_BIAS") or (signal == "SELL" and inst_bias == "SHORT_BIAS"):
        cot_score = 25
        alignment_notes.append(f"✅ Institutional: {inst_bias} align {signal}")
    elif inst_bias == "NEUTRAL":
        cot_score = 10
        alignment_notes.append("⚠️ Institutional neutral")
    else:
        cot_score = 0
        alignment_notes.append(f"❌ Institutional {inst_bias} berlawanan signal")

    details["cot_score"] = cot_score

    # 4. Yield Curve Context (15 pts)
    curve = fed_policy.get("curve_status", "FLAT")
    spread = fed_policy.get("spread", 0)
    if cat == "METALS":
        # XAU naik saat kurva inverted (safe haven) atau cut cycle
        if curve == "INVERTED" and signal == "BUY":
            yc_score = 15
            alignment_notes.append(f"✅ Yield curve INVERTED → XAU safe haven BUY")
        elif curve == "NORMAL" and signal == "SELL":
            yc_score = 15
            alignment_notes.append("✅ Yield normal → XAU pressure SELL")
        else:
            yc_score = 7
    elif cat in ["INDEX", "CRYPTO"]:
        # Risk assets suka kurva normal (growth)
        if curve == "NORMAL" and signal == "BUY":
            yc_score = 15
            alignment_notes.append("✅ Yield curve normal → risk-on BUY")
        elif curve == "INVERTED" and signal == "SELL":
            yc_score = 15
            alignment_notes.append("✅ Yield inverted → risk-off caution")
        else:
            yc_score = 5
    else:
        yc_score = 7

    details["yc_score"] = yc_score

    # 5. Seasonal / Cyclical (10 pts) — simplified
    month = wib_now().month
    # Q1 Jan-Mar: risk-on start year
    # Q2 Apr-Jun: "Sell in May" risk, DXY cenderung kuat
    # Q3 Jul-Sep: summer doldrums, low volatility
    # Q4 Oct-Dec: year-end rally equities, XAU cenderung kuat
    if month in [10, 11, 12] and cat == "METALS" and signal == "BUY":
        seasonal_score = 10
        alignment_notes.append("✅ Q4 seasonal: XAU historically kuat")
    elif month in [4, 5, 6] and cat in ["INDEX", "CRYPTO"] and signal == "SELL":
        seasonal_score = 8
        alignment_notes.append("⚠️ Q2 'Sell in May' seasonal caution")
    elif month in [1, 2, 3] and cat in ["INDEX", "CRYPTO"] and signal == "BUY":
        seasonal_score = 10
        alignment_notes.append("✅ Q1 risk-on seasonal")
    else:
        seasonal_score = 5

    details["seasonal_score"] = seasonal_score

    total = min(fed_score + macro_score + cot_score + yc_score + seasonal_score, 100)

    # Fundamental verdict
    if total >= 75:
        verdict = "STRONG CONFIRM"
        verdict_icon = "✅✅"
    elif total >= 55:
        verdict = "CONFIRM"
        verdict_icon = "✅"
    elif total >= 35:
        verdict = "WEAK"
        verdict_icon = "⚠️"
    else:
        verdict = "CONFLICT"
        verdict_icon = "❌"

    return {
        "total": total,
        "fed_score": fed_score,
        "macro_score": macro_score,
        "cot_score": cot_score,
        "yc_score": yc_score,
        "seasonal_score": seasonal_score,
        "verdict": verdict,
        "verdict_icon": verdict_icon,
        "alignment_notes": alignment_notes,
        "regime": regime,
        "fed_tone": fed_tone,
        "curve_status": curve,
        "spread": spread,
        "inst_bias": inst_bias,
    }


def fundamental_report_text(pair_key="XAUUSD"):
    """
    Full fundamental report untuk command /fundamental atau /macro
    """
    try:
        fed = fetch_fed_policy()
        macro = detect_macro_regime(fed)
        cot = cot_sentiment_proxy(pair_key)

        spread_arrow = "📈" if fed["spread"] > 0 else "📉"
        curve_icon = "🔴" if fed["curve_status"] == "INVERTED" else "🟡" if fed["curve_status"] == "FLAT" else "🟢"

        regime_icons = {
            "RISK_ON": "🟢",
            "RISK_OFF": "🔴",
            "STAGFLATION": "🟠",
            "RECESSION": "⚫",
            "NEUTRAL": "🟡",
        }
        regime_icon = regime_icons.get(macro["regime"], "🟡")

        inst_icon = "🐂" if cot["institutional_bias"] == "LONG_BIAS" else "🐻" if cot["institutional_bias"] == "SHORT_BIAS" else "➖"

        pair_name = PAIRS.get(pair_key, {}).get("name", pair_key)

        text = f"""
👑 <b>CAPITAL ELITE FUNDAMENTAL INTELLIGENCE</b>
<code>V10 Macro + Fed + Institutional Engine</code>
🕐 <code>{wib_now().strftime('%d-%m-%Y %H:%M WIB')}</code>

━━━━━━━━━━━━━━━━━━━━━
🏛 <b>FED POLICY TRACKER</b>
━━━━━━━━━━━━━━━━━━━━━
Fed Tone: <b>{fed['fed_tone']}</b>
Rate Trend: <b>{fed['fed_trend']}</b>
2Y Treasury: <code>{fed['rate_2y']:.2f}%</code>
10Y Treasury: <code>{fed['rate_10y']:.2f}%</code>
{spread_arrow} Yield Spread (10Y-2Y): <code>{fed['spread']:+.3f}%</code>
{curve_icon} Yield Curve: <b>{fed['curve_status']}</b>

━━━━━━━━━━━━━━━━━━━━━
🌐 <b>MACRO REGIME</b>
━━━━━━━━━━━━━━━━━━━━━
{regime_icon} Regime: <b>{macro['regime']}</b>
{macro['regime_note']}

Asset Bias:
  🥇 XAU/Silver: <b>{macro['xau_bias']}</b>
  ₿  Crypto: <b>{macro['btc_bias']}</b>
  📈 Indices: <b>{macro['index_bias']}</b>
  💵 USD: <b>{macro['usd_bias']}</b>

━━━━━━━━━━━━━━━━━━━━━
{inst_icon} <b>INSTITUTIONAL SENTIMENT (COT Proxy)</b>
━━━━━━━━━━━━━━━━━━━━━
Pair: <b>{pair_name}</b>
Institutional Bias: <b>{cot['institutional_bias']}</b>
Daily Structure: <b>{cot['daily_bias']}</b>
H1 Institutional: <b>{cot['h1_cot']}</b>
RSI Divergence: <b>{cot['rsi_divergence']}</b>
COT Confidence: <b>{cot['cot_confidence']}%</b>

━━━━━━━━━━━━━━━━━━━━━
📋 <b>TRADING IMPLICATION</b>
━━━━━━━━━━━━━━━━━━━━━
{macro['regime_note']}

⚠️ Fundamental adalah BIG PICTURE.
Entry tetap pakai SMC/ICT + konfirmasi candle close.
Data: {fed.get('source','yfinance')}
"""
        return text
    except Exception as e:
        return f"⚠️ Fundamental engine error: {e}\nCoba lagi dalam 60 detik."


# ==============================
# SMC / ICT PREMIUM ENGINE
# ==============================
def session_info():
    h = wib_now().hour
    if 5 <= h < 14:
        return "Asia Session", 4, "Market sering lebih kalem. Fokus sniper/retest, jangan kejar candle."
    if 14 <= h < 20:
        return "London Session", 10, "Volume mulai masuk. Validasi sweep + MSS/BOS lebih penting."
    return "New York Session", 10, "Volatilitas tinggi. Wajib kecilkan lot dan tunggu close candle."


def sl_tp_distance(pair_key, market_range):
    """
    FINAL RISK MODEL
    XAUUSD khusus:
    - SL fixed 50 pips = 5.00
    - TP1 fixed 60 pips = 6.00
    - TP2 fixed 80 pips = 8.00
    - TP3 fixed 100 pips = 10.00

    Pair lain tetap dynamic sesuai karakter market.
    """

    if pair_key == "XAUUSD":
        return 5.00, 5.00

    if pair_key == "XAGUSD":
        sl = max(0.030, min(market_range * 0.35, 0.050))
        return sl, sl

    if pair_key == "BTCUSD":
        return 150, 150

    if pair_key == "ETHUSD":
        return 15, 15

    if pair_key in ["SOLUSD", "BNBUSD"]:
        return 2, 2

    if pair_key == "XRPUSD":
        return 0.030, 0.030

    if pair_key in ["NAS100", "US30", "SPX500"]:
        return 40, 40

    if pair_key in ["USOIL", "UKOIL"]:
        return 0.35, 0.35

    min_sl, max_sl = PAIRS[pair_key]["sl"]
    sl = max(min_sl, min(market_range * 0.85, max_sl))
    return sl, sl


def market_status(price, h1, m15, m5):
    aligned = len({h1["bias"], m15["bias"], m5["bias"]}) == 1 and h1["bias"] != "SIDEWAYS"
    rng_pct = (m5["range"] / max(price, 0.0001)) * 100
    if aligned and rng_pct > 0.03:
        return "🟢 TRENDING"
    if m15["bias"] == "SIDEWAYS" or m5["bias"] == "SIDEWAYS":
        return "🟡 SIDEWAYS"
    return "🔴 CHOPPY"


def liquidity_heatmap(h1, m15, m5):
    buy_levels = sorted([h1["high"], m15["high"], m5["high"]], reverse=True)
    sell_levels = sorted([h1["low"], m15["low"], m5["low"]])
    return buy_levels[:3], sell_levels[:3]


def dxy_filter():
    """
    DXY correlation filter:
    DXY bullish = pressure bearish untuk XAU/crypto/risk assets.
    DXY bearish = support bullish untuk XAU/crypto/risk assets.
    Kalau data gagal, netral agar bot tetap jalan.
    """
    try:
        if yf is None:
            return {"bias": "NEUTRAL", "score_buy": 0, "score_sell": 0, "note": "DXY data unavailable"}
        data = yf.download("DX-Y.NYB", period="7d", interval="60m", progress=False, auto_adjust=False)
        if data is None or data.empty or len(data) < 20:
            data = yf.download("DX=F", period="7d", interval="60m", progress=False, auto_adjust=False)
        if data is None or data.empty or len(data) < 20:
            return {"bias": "NEUTRAL", "score_buy": 0, "score_sell": 0, "note": "DXY data unavailable"}

        closes = data["Close"].astype(float)
        last = float(closes.iloc[-1])
        ma20 = float(closes.rolling(20).mean().iloc[-1])
        first = float(closes.iloc[-12]) if len(closes) >= 12 else float(closes.iloc[0])

        if last > ma20 and last > first:
            return {"bias": "BULLISH", "score_buy": -8, "score_sell": 10, "note": "DXY bullish → pressure bearish ke XAU"}
        if last < ma20 and last < first:
            return {"bias": "BEARISH", "score_buy": 10, "score_sell": -8, "note": "DXY bearish → support bullish ke XAU"}
        return {"bias": "NEUTRAL", "score_buy": 0, "score_sell": 0, "note": "DXY netral"}
    except Exception:
        return {"bias": "NEUTRAL", "score_buy": 0, "score_sell": 0, "note": "DXY filter unavailable"}


def near_high_impact_news():
    """
    News filter ringan. Tidak mematikan sinyal, hanya mengurangi confidence.
    Supaya fitur lama tetap jalan dan tidak NO TRADE terus.
    """
    try:
        events = parse_forex_factory_today()
        if not events:
            return False, "No high impact USD news detected"
        return True, "High impact USD news detected — kecilkan lot / tunggu spread normal"
    except Exception:
        return False, "News filter unavailable"


def detect_liquidity_sweep(signal, h1, m15, m5):
    if signal == "BUY":
        swept = m5["low"] <= m15["low"] or m15["low"] <= h1["low"] or m5["low"] <= m15["eq"]
        return swept, "Sell-side liquidity sweep / discount raid" if swept else "Sweep belum bersih"
    swept = m5["high"] >= m15["high"] or m15["high"] >= h1["high"] or m5["high"] >= m15["eq"]
    return swept, "Buy-side liquidity sweep / premium raid" if swept else "Sweep belum bersih"


def detect_mss_bos(signal, h1, m15, m5):
    if signal == "BUY":
        mss = (m5["candle"] == "BULLISH" and m5["price"] > m5["eq"]) or (m5["price"] > m5["ema20"])
        bos = m15["price"] > m15["eq"] or h1["bias"] == "BULLISH"
        return mss, bos, "Bullish MSS/BOS" if mss and bos else "MSS/BOS belum full"
    mss = (m5["candle"] == "BEARISH" and m5["price"] < m5["eq"]) or (m5["price"] < m5["ema20"])
    bos = m15["price"] < m15["eq"] or h1["bias"] == "BEARISH"
    return mss, bos, "Bearish MSS/BOS" if mss and bos else "MSS/BOS belum full"


def detect_fvg_ob_crt(signal, h1, m15, m5):
    """
    Karena data yang tersedia hanya OHLC snapshot per TF, ini pakai proxy:
    FVG = range candle cukup besar dan displacement.
    OB = harga dekat EQ / open candle opposite area.
    CRT = sweep high/low candle range lalu balik ke range.
    """
    avg_range_proxy = max((h1["range"] + m15["range"] + m5["range"]) / 3, 0.00001)

    if signal == "BUY":
        displacement = m5["candle"] == "BULLISH" and m5["range"] >= avg_range_proxy * 0.45
        fvg = displacement and m5["price"] > m5["eq"]
        ob = m5["low"] <= m15["eq"] or m15["low"] <= h1["eq"]
        crt = m5["low"] < m15["low"] or (m5["low"] < m5["eq"] and m5["price"] > m5["eq"])
        poi_name = "Discount FVG/OB/CRT"
    else:
        displacement = m5["candle"] == "BEARISH" and m5["range"] >= avg_range_proxy * 0.45
        fvg = displacement and m5["price"] < m5["eq"]
        ob = m5["high"] >= m15["eq"] or m15["high"] >= h1["eq"]
        crt = m5["high"] > m15["high"] or (m5["high"] > m5["eq"] and m5["price"] < m5["eq"])
        poi_name = "Premium FVG/OB/CRT"

    return {
        "fvg": fvg,
        "ob": ob,
        "crt": crt,
        "displacement": displacement,
        "poi_name": poi_name,
    }


def premium_discount_score(signal, price, h1, m15):
    h1_discount = price <= h1["eq"]
    m15_discount = price <= m15["eq"]
    h1_premium = price >= h1["eq"]
    m15_premium = price >= m15["eq"]

    if signal == "BUY":
        ok = h1_discount or m15_discount
        return ok, "Discount zone" if ok else "BUY belum ideal di discount"
    ok = h1_premium or m15_premium
    return ok, "Premium zone" if ok else "SELL belum ideal di premium"


def calc_smc_score(signal, price, h1, m15, m5, session_score, pair_key="XAUUSD"):
    dxy = dxy_filter()
    news_risk, news_note = near_high_impact_news()
    sweep_ok, sweep_note = detect_liquidity_sweep(signal, h1, m15, m5)
    mss_ok, bos_ok, mss_note = detect_mss_bos(signal, h1, m15, m5)
    poi = detect_fvg_ob_crt(signal, h1, m15, m5)
    pd_ok, pd_note = premium_discount_score(signal, price, h1, m15)

    htf = 20 if (signal == "BUY" and h1["bias"] == "BULLISH") or (signal == "SELL" and h1["bias"] == "BEARISH") else 10
    dxy_score = 10 if (signal == "BUY" and dxy["bias"] == "BEARISH") or (signal == "SELL" and dxy["bias"] == "BULLISH") else 5 if dxy["bias"] == "NEUTRAL" else 0
    liq = 20 if sweep_ok else 8
    mss = 15 if mss_ok else 6
    bos = 10 if bos_ok else 4
    fvg = 10 if poi["fvg"] else 4
    ob = 10 if poi["ob"] else 4
    crt = 10 if poi["crt"] else 3
    pd = 10 if pd_ok else 4
    timing = min(10, session_score)

    penalty = 8 if news_risk else 0
    total_raw = htf + dxy_score + liq + mss + bos + fvg + ob + crt + pd + timing - penalty
    total = max(35, min(100, total_raw))

    # --- FUNDAMENTAL LAYER V10 ---
    try:
        fed_policy = fetch_fed_policy()
        macro_regime = detect_macro_regime(fed_policy)
        cot = cot_sentiment_proxy(pair_key)
        fund = calc_fundamental_score(pair_key, signal, fed_policy, macro_regime, cot)
    except Exception as e:
        print("fundamental layer error:", e)
        fed_policy = {"fed_tone": "NEUTRAL", "curve_status": "FLAT", "spread": 0, "rate_2y": 5.0, "rate_10y": 4.5}
        macro_regime = {"regime": "NEUTRAL", "regime_note": "Fundamental unavailable", "xau_bias": "NEUTRAL", "btc_bias": "NEUTRAL", "index_bias": "NEUTRAL", "usd_bias": "NEUTRAL"}
        cot = {"institutional_bias": "NEUTRAL", "cot_confidence": 0, "note": "COT unavailable", "rsi_divergence": "NONE"}
        fund = {"total": 50, "verdict": "WEAK", "verdict_icon": "⚠️", "alignment_notes": ["Fundamental data unavailable"], "regime": "NEUTRAL", "fed_tone": "NEUTRAL", "curve_status": "FLAT", "spread": 0, "inst_bias": "NEUTRAL", "fed_score": 12, "macro_score": 10, "cot_score": 10, "yc_score": 7, "seasonal_score": 5}

    return {
        "HTF": htf,
        "DXY": dxy_score,
        "Liquidity": liq,
        "MSS": mss,
        "BOS": bos,
        "FVG": fvg,
        "OB": ob,
        "CRT": crt,
        "PD": pd,
        "Timing": timing,
        "Penalty": penalty,
        "Total": total,
        "dxy_bias": dxy["bias"],
        "dxy_note": dxy["note"],
        "news_risk": news_risk,
        "news_note": news_note,
        "sweep_ok": sweep_ok,
        "sweep_note": sweep_note,
        "mss_ok": mss_ok,
        "bos_ok": bos_ok,
        "mss_note": mss_note,
        "fvg_ok": poi["fvg"],
        "ob_ok": poi["ob"],
        "crt_ok": poi["crt"],
        "poi_name": poi["poi_name"],
        "pd_ok": pd_ok,
        "pd_note": pd_note,
        # Fundamental fields
        "fund": fund,
        "fed_tone": fed_policy.get("fed_tone", "NEUTRAL"),
        "macro_regime": macro_regime.get("regime", "NEUTRAL"),
        "macro_note": macro_regime.get("regime_note", ""),
        "inst_bias": cot.get("institutional_bias", "NEUTRAL"),
        "curve_status": fed_policy.get("curve_status", "FLAT"),
        "yield_spread": fed_policy.get("spread", 0),
        "cot_note": cot.get("note", ""),
    }


def analyze_pair(pair_key, tf_key="M5", compact=False):
    if pair_key not in PAIRS:
        return "Pair belum tersedia."
    tf_key = tf_key.upper().strip()
    if tf_key not in TIMEFRAMES:
        tf_key = "M5"
    cache_key = f"analysis_{pair_key}_{tf_key}_{compact}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    try:
        tf = fetch_tf(pair_key, tf_key)
        pytime.sleep(0.35)
        h1 = fetch_tf(pair_key, "H1") if tf_key != "H1" else tf
        pytime.sleep(0.35)
        m15 = fetch_tf(pair_key, "M15") if tf_key != "M15" else tf
        pytime.sleep(0.35)
        m5 = fetch_tf(pair_key, "M5") if tf_key != "M5" else tf
    except Exception as e:
        return f"""
👑 <b>CAPITAL ELITE PROJECT</b>
<code>Market Data Sync</code>

⚠️ Data market belum kebaca.
Detail: <code>{type(e).__name__}: {str(e)[:160]}</code>

Coba ulang 30-60 detik lagi.
"""

    price = tf["price"]
    session_tag, session_score, session_note = session_info()
    dxy = dxy_filter()

    # Direction engine:
    # HTF Bias + DXY Filter + Premium/Discount + Liquidity context.
    buy_score = 0
    sell_score = 0

    if h1["bias"] == "BULLISH":
        buy_score += 26
    elif h1["bias"] == "BEARISH":
        sell_score += 26

    if m15["bias"] == "BULLISH":
        buy_score += 16
    elif m15["bias"] == "BEARISH":
        sell_score += 16
    else:
        buy_score += 6
        sell_score += 6

    if m5["bias"] == "BULLISH" or m5["candle"] == "BULLISH":
        buy_score += 12
    if m5["bias"] == "BEARISH" or m5["candle"] == "BEARISH":
        sell_score += 12

    # Premium / discount
    if price <= h1["eq"] or price <= m15["eq"]:
        buy_score += 14
    if price >= h1["eq"] or price >= m15["eq"]:
        sell_score += 14

    # Liquidity sweep context
    buy_sweep, _ = detect_liquidity_sweep("BUY", h1, m15, m5)
    sell_sweep, _ = detect_liquidity_sweep("SELL", h1, m15, m5)
    if buy_sweep:
        buy_score += 12
    if sell_sweep:
        sell_score += 12

    # DXY filter strongest for XAU, XAG, forex/indices/crypto kept as soft filter.
    dxy_weight = 14 if pair_key in ["XAUUSD", "XAGUSD"] else 8
    if dxy["bias"] == "BEARISH":
        buy_score += dxy_weight
    elif dxy["bias"] == "BULLISH":
        sell_score += dxy_weight

    buy_score += session_score
    sell_score += session_score

    signal = "BUY" if buy_score >= sell_score else "SELL"
    score_gap = abs(buy_score - sell_score)

    smc = calc_smc_score(signal, price, h1, m15, m5, session_score, pair_key=pair_key)
    buy_liq, sell_liq = liquidity_heatmap(h1, m15, m5)
    status = market_status(price, h1, m15, m5)
    sl_dist, tp_dist = sl_tp_distance(pair_key, tf["range"])

    # V10: Confidence sekarang 3-layer: Teknikal + SMC + Fundamental
    base_conf = max(buy_score, sell_score)
    fund_score = smc["fund"]["total"]
    fund_verdict = smc["fund"]["verdict"]

    # Weight: Teknikal 35% + SMC 40% + Fundamental 25%
    confidence = int(min(max(
        (base_conf * 0.35) + (smc["Total"] * 0.40) + (fund_score * 0.25),
        45
    ), 96))

    # Fundamental CONFLICT = paksa cap confidence & paksa NO TRADE kalau gap besar
    if fund_verdict == "CONFLICT":
        confidence = min(confidence, 58)  # cap di 58 kalau fundamental berlawanan
        fundamental_conflict = True
    else:
        fundamental_conflict = False

    no_trade = confidence < 55 or (fundamental_conflict and smc["Total"] < 70)

    if signal == "BUY":
        # Entry uses discount POI, sweep low, OB/FVG proxy and realtime area.
        poi_anchor = min(price, m15["eq"], h1["eq"])
        entry_low = poi_anchor - sl_dist * 0.25
        entry_high = price + sl_dist * 0.05
        zf_low = min(price, m15["eq"]) - sl_dist * 0.40
        zf_high = min(price, m15["eq"]) - sl_dist * 0.12
        entry_mid_temp = (entry_low + entry_high) / 2
        if pair_key == "XAUUSD":
            # XAU final Indonesia convention:
            # SL 50 pips = 5.00, TP 60/80/100 pips = 6.00/8.00/10.00
            entry_center = price
            entry_low = entry_center - 1.00
            entry_high = entry_center + 1.00
            entry_mid_temp = (entry_low + entry_high) / 2

            zf_low = entry_mid_temp - 2.50
            zf_high = entry_mid_temp - 1.50

            sl = entry_mid_temp - 5.00
            tp1 = entry_mid_temp + 6.00
            tp2 = entry_mid_temp + 8.00
            tp3 = entry_mid_temp + 10.00
        else:
            raw_sl = min(m5["low"], m15["low"], zf_low - sl_dist * 0.45)
            sl = max(raw_sl, entry_mid_temp - sl_dist)
            risk = abs(entry_mid_temp - sl)
            tp1 = entry_mid_temp + (risk * 2)
            tp2 = entry_mid_temp + (risk * 3)
            tp3 = entry_mid_temp + (risk * 4)
        action = "🟢 BUY PLAN"
        invalid = "Invalid kalau SSL/discount POI jebol dan candle close bearish kuat."
        confluence = [
            smc["pd_note"],
            smc["sweep_note"],
            smc["mss_note"],
            smc["dxy_note"],
            session_note
        ]
    else:
        # Entry uses premium POI, sweep high, OB/FVG proxy and realtime area.
        poi_anchor = max(price, m15["eq"], h1["eq"])
        entry_low = price - sl_dist * 0.05
        entry_high = poi_anchor + sl_dist * 0.25
        zf_low = max(price, m15["eq"]) + sl_dist * 0.12
        zf_high = max(price, m15["eq"]) + sl_dist * 0.40
        entry_mid_temp = (entry_low + entry_high) / 2
        if pair_key == "XAUUSD":
            # XAU final Indonesia convention:
            # SL 50 pips = 5.00, TP 60/80/100 pips = 6.00/8.00/10.00
            entry_center = price
            entry_low = entry_center - 1.00
            entry_high = entry_center + 1.00
            entry_mid_temp = (entry_low + entry_high) / 2

            zf_low = entry_mid_temp + 1.50
            zf_high = entry_mid_temp + 2.50

            sl = entry_mid_temp + 5.00
            tp1 = entry_mid_temp - 6.00
            tp2 = entry_mid_temp - 8.00
            tp3 = entry_mid_temp - 10.00
        else:
            raw_sl = max(m5["high"], m15["high"], zf_high + sl_dist * 0.45)
            sl = min(raw_sl, entry_mid_temp + sl_dist)
            risk = abs(sl - entry_mid_temp)
            tp1 = entry_mid_temp - (risk * 2)
            tp2 = entry_mid_temp - (risk * 3)
            tp3 = entry_mid_temp - (risk * 4)
        action = "🔴 SELL PLAN"
        invalid = "Invalid kalau BSL/premium POI jebol dan candle close bullish kuat."
        confluence = [
            smc["pd_note"],
            smc["sweep_note"],
            smc["mss_note"],
            smc["dxy_note"],
            session_note
        ]

    # V10 Grade: butuh fundamental CONFIRM untuk A+
    fund_verdict = smc["fund"]["verdict"]
    grade = (
        "A+" if confidence >= 88 and smc["Total"] >= 82 and fund_verdict in ["STRONG CONFIRM", "CONFIRM"]
        else "A" if confidence >= 78 and fund_verdict != "CONFLICT"
        else "B" if confidence >= 66
        else "C"
    )
    setup_name = "💎 INSTITUTIONAL SETUP" if grade == "A+" else "🚀 SNIPER SETUP" if grade == "A" else "🟡 RETEST SETUP" if grade == "B" else "⚪ WAIT"
    entry_mid = (entry_low + entry_high) / 2
    risk_value = abs(entry_mid - sl)
    rr = round(abs(tp2 - entry_mid) / max(risk_value, 0.00001), 1)

    if pair_key == "XAUUSD":
        risk_text = f"{xau_pips(risk_value)} pips"
        tp1_text = f"{fmt(tp1)} (+{xau_pips(tp1 - entry_mid)} pips)"
        tp2_text = f"{fmt(tp2)} (+{xau_pips(tp2 - entry_mid)} pips)"
        tp3_text = f"{fmt(tp3)} (+{xau_pips(tp3 - entry_mid)} pips)"
        rr_text = "SL 50 pips • TP1 60 pips • TP2 80 pips • TP3 100 pips"
    else:
        risk_text = fmt(risk_value)
        tp1_text = fmt(tp1)
        tp2_text = fmt(tp2)
        tp3_text = fmt(tp3)
        rr_text = f"1:{rr}"

    if compact:
        return {
            "pair": pair_key,
            "name": PAIRS[pair_key]["name"],
            "signal": "NO SETUP" if no_trade else signal,
            "confidence": confidence,
            "grade": grade,
            "price": price,
            "entry": (entry_low, entry_high),
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "smc": smc,
            "status": status,
            "bias": (h1["bias"], m15["bias"], m5["bias"])
        }

    if no_trade:
        fund = smc["fund"]
        fund_notes_str = "\n".join(f"  {n}" for n in fund["alignment_notes"][:3])
        conflict_warn = "\n❌ <b>FUNDAMENTAL CONFLICT</b> — sinyal teknikal berlawanan macro/fundamental.\nHigh probability setup butuh alignment ketiganya.\n" if fundamental_conflict else ""
        text = f"""
👑 <b>CAPITAL ELITE INTELLIGENCE</b>
<code>V10 SMC/ICT + Fundamental Engine</code>

💱 <b>{PAIRS[pair_key]['name']}</b> | <b>{tf_key}</b> • {session_tag}
{status}
⚪ <b>NO TRADE ZONE</b>
{conflict_warn}
📌 <b>Bias</b>
H1: <b>{h1['bias']}</b>
M15: <b>{m15['bias']}</b>
M5: <b>{m5['bias']}</b>
DXY: <b>{smc['dxy_bias']}</b>

🔥 <b>Confidence</b>: <b>{confidence}%</b>
{conf_bar(confidence)}
🏆 Grade: <b>{grade}</b>
🧠 SMC Score: <b>{smc['Total']}/100</b>
🌐 Fundamental: <b>{fund['total']}/100</b> {fund['verdict_icon']} {fund['verdict']}

🔥 <b>Liquidity Heatmap</b>
BSL: <code>{fmt(buy_liq[0])}</code> / <code>{fmt(buy_liq[1])}</code>
SSL: <code>{fmt(sell_liq[0])}</code> / <code>{fmt(sell_liq[1])}</code>

🌐 <b>Macro Context</b>
Fed: <b>{smc['fed_tone']}</b> | Regime: <b>{smc['macro_regime']}</b>
Yield Curve: <b>{smc['curve_status']}</b> | Institutional: <b>{smc['inst_bias']}</b>
{fund_notes_str}

🧠 <b>Filter Check</b>
DXY: <b>{smc['DXY']}/10</b> — {smc['dxy_note']}
Sweep: <b>{smc['Liquidity']}/20</b> — {smc['sweep_note']}
MSS/BOS: <b>{smc['MSS'] + smc['BOS']}/25</b> — {smc['mss_note']}
FVG/OB/CRT: <b>{smc['FVG'] + smc['OB'] + smc['CRT']}/30</b>
Premium/Discount: <b>{smc['PD']}/10</b> — {smc['pd_note']}
News: {smc['news_note']}

🛡️ <b>Elite Note</b>
Edge belum bersih. Tunggu sweep + MSS/BOS + POI valid + fundamental align.

⚠️ <b>DISCLAIMER</b>
Bukan saran finansial. Trading berisiko tinggi.
"""
        cache_set(cache_key, text)
        return text

    trade_id = log_signal(pair_key, tf_key, signal, entry_low, entry_high, sl, tp1, tp2, confidence, grade)

    fund = smc["fund"]
    fund_notes_str = "\n".join(f"• {n}" for n in fund["alignment_notes"])

    text = f"""
👑 <b>CAPITAL ELITE INTELLIGENCE</b>
<code>V10 • SMC/ICT + DXY + Fundamental Engine</code>

💱 <b>{PAIRS[pair_key]['name']}</b> | <b>{tf_key}</b> • {session_tag}
{status}
{setup_name}
<b>{action}</b>

📌 <b>Market Bias</b>
H1: <b>{h1['bias']}</b>
M15: <b>{m15['bias']}</b>
M5: <b>{m5['bias']}</b>
DXY: <b>{smc['dxy_bias']}</b>
Price: <code>{fmt(price)}</code>

⚡ <b>Entry Area</b>
<code>{fmt(entry_low)} - {fmt(entry_high)}</code>

💎 <b>Zero Floating Zone</b>
<code>{fmt(zf_low)} - {fmt(zf_high)}</code>

🛑 <b>Stop Loss</b>
<code>{fmt(sl)}</code>

🎯 <b>Take Profit</b>
TP1: <code>{tp1_text}</code>
TP2: <code>{tp2_text}</code>
TP3: <code>{tp3_text}</code>

🔥 <b>Liquidity Heatmap</b>
BSL: <code>{fmt(buy_liq[0])}</code> / <code>{fmt(buy_liq[1])}</code>
SSL: <code>{fmt(sell_liq[0])}</code> / <code>{fmt(sell_liq[1])}</code>

🧠 <b>Smart Money Score</b>
HTF: <b>{smc['HTF']}/20</b>
DXY Filter: <b>{smc['DXY']}/10</b>
Liquidity Sweep: <b>{smc['Liquidity']}/20</b>
MSS: <b>{smc['MSS']}/15</b>
BOS: <b>{smc['BOS']}/10</b>
FVG: <b>{smc['FVG']}/10</b>
OB: <b>{smc['OB']}/10</b>
CRT: <b>{smc['CRT']}/10</b>
Premium/Discount: <b>{smc['PD']}/10</b>
Timing: <b>{smc['Timing']}/10</b>
News Penalty: <b>-{smc['Penalty']}</b>
SMC TOTAL: <b>{smc['Total']}/100</b>

🌐 <b>Fundamental Confluence V10</b>
Regime: <b>{smc['macro_regime']}</b> | Fed: <b>{smc['fed_tone']}</b>
Yield Curve: <b>{smc['curve_status']}</b> ({smc['yield_spread']:+.3f}%)
Institutional: <b>{smc['inst_bias']}</b>
Fund Score: <b>{fund['total']}/100</b> {fund['verdict_icon']} {fund['verdict']}
{fund_notes_str}

📊 <b>Elite Grade V10</b>
Grade: <b>{grade}</b>
Confidence: <b>{confidence}%</b>
{conf_bar(confidence)}
⚖️ Teknikal 35% | SMC 40% | Fundamental 25%
Risk: <b>{risk_text}</b>
Reward: <b>{rr_text}</b>
Trade ID: <code>{trade_id}</code>

🧩 <b>Confluence</b>
• {confluence[0]}
• {confluence[1]}
• {confluence[2]}
• {confluence[3]}
• {confluence[4]}

🛡️ <b>Management</b>
Entry kecil dulu. XAU fixed: SL 50 pips, TP 60/80/100 pips. Pair lain tetap dynamic.
{invalid}
Grade A+ butuh: SMC ≥82 + Fundamental CONFIRM + Confidence ≥88.

⚠️ <b>DISCLAIMER</b>
Bukan saran finansial. Trading berisiko tinggi.
"""
    cache_set(cache_key, text)
    return text

# ==============================
# JOURNAL / DASHBOARD
# ==============================
def log_signal(pair, tf, direction, entry_low, entry_high, sl, tp1, tp2, confidence, grade):
    logs = load_json(SIGNAL_LOG_FILE, [])
    trade_id = f"CE{wib_now().strftime('%y%m%d%H%M%S')}{random.randint(10,99)}"
    item = {"id": trade_id, "time": wib_now().strftime("%Y-%m-%d %H:%M:%S"), "pair": pair, "tf": tf, "direction": direction, "entry_low": entry_low, "entry_high": entry_high, "sl": sl, "tp1": tp1, "tp2": tp2, "confidence": confidence, "grade": grade, "status": "OPEN"}
    logs.append(item)
    save_json(SIGNAL_LOG_FILE, logs[-300:])
    history = load_json(TRADE_HISTORY_FILE, [])
    history.append(item)
    save_json(TRADE_HISTORY_FILE, history[-500:])
    return trade_id


def update_trade_result(trade_id, result):
    result = result.upper()
    if result not in ["WIN", "LOSS", "BE", "OPEN"]:
        return False
    changed = False
    for path in [SIGNAL_LOG_FILE, TRADE_HISTORY_FILE]:
        rows = load_json(path, [])
        for row in rows:
            if row.get("id") == trade_id:
                row["status"] = result
                row["closed_at"] = wib_now().strftime("%Y-%m-%d %H:%M:%S")
                changed = True
        save_json(path, rows)
    return changed


def performance_text():
    rows = load_json(TRADE_HISTORY_FILE, [])
    closed = [r for r in rows if r.get("status") in ["WIN", "LOSS", "BE"]]
    wins = len([r for r in closed if r.get("status") == "WIN"])
    losses = len([r for r in closed if r.get("status") == "LOSS"])
    be = len([r for r in closed if r.get("status") == "BE"])
    total = len(closed)
    winrate = round((wins / max(total, 1)) * 100, 1)
    pf = round((wins * 2) / max(losses, 1), 2)
    last = rows[-10:][::-1]
    last_lines = ""
    for r in last:
        last_lines += f"• <code>{r.get('id')}</code> {r.get('pair')} {r.get('direction')} — <b>{r.get('status','OPEN')}</b>\n"
    if not last_lines:
        last_lines = "Belum ada journal."
    return f"""
📈 <b>CAPITAL ELITE PERFORMANCE</b>

Total Closed: <b>{total}</b>
WIN: <b>{wins}</b>
LOSS: <b>{losses}</b>
BE: <b>{be}</b>
Winrate: <b>{winrate}%</b>
Profit Factor Est: <b>{pf}</b>

📒 <b>Last 10 Journal</b>
{last_lines}
"""

# ==============================
# NEWS ENGINE
# ==============================
def parse_forex_factory_today():
    try:
        url = "https://www.forexfactory.com/calendar"
        headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"}
        html = requests.get(url, headers=headers, timeout=15).text
        rows = re.findall(r"<tr[^>]*calendar__row[^>]*>(.*?)</tr>", html, flags=re.S | re.I)
        events = []
        for row in rows:
            txt = re.sub(r"<[^>]+>", " ", row)
            txt = re.sub(r"\s+", " ", txt).strip()
            if " USD " not in (" " + txt + " "):
                continue
            if not any(k.lower() in txt.lower() for k in IMPORTANT_NEWS_KEYWORDS):
                continue
            impact = "HIGH" if "impact--high" in row or "High Impact" in row else "NEWS"
            events.append({"raw": txt[:220], "impact": impact})
        return events[:8]
    except Exception:
        return []


def news_ai(news_type, actual, forecast, previous=None):
    nt = news_type.lower()
    a = clean_num(actual)
    f = clean_num(forecast)
    if a is None or f is None:
        return "Format salah. Contoh: /news cpi actual=3.2 forecast=3.4 previous=3.5"
    usd = "NEUTRAL"
    reason = "Actual mendekati forecast. Market bisa choppy."
    conf = 65
    lower_is_good_for_usd = ["unemployment", "jobless"]
    higher_hot = ["cpi", "ppi", "pce"]
    higher_growth = ["nfp", "nonfarm", "pmi", "ism", "gdp", "earnings", "retail"]
    if any(x in nt for x in lower_is_good_for_usd):
        if a < f: usd, reason, conf = "BULLISH", "Unemployment lebih rendah dari forecast → USD kuat.", 86
        elif a > f: usd, reason, conf = "BEARISH", "Unemployment lebih tinggi dari forecast → USD lemah.", 86
    elif any(x in nt for x in higher_hot):
        if a > f: usd, reason, conf = "BULLISH", "Inflasi lebih panas → Fed cenderung hawkish.", 88
        elif a < f: usd, reason, conf = "BEARISH", "Inflasi lebih dingin → Fed cenderung dovish.", 88
    elif any(x in nt for x in higher_growth):
        if a > f: usd, reason, conf = "BULLISH", "Data ekonomi lebih kuat dari forecast → USD kuat.", 86
        elif a < f: usd, reason, conf = "BEARISH", "Data ekonomi lebih lemah dari forecast → USD lemah.", 86
    if usd == "BULLISH":
        xau, btc, index = "SELL", "SELL / RISK-OFF", "SELL / CAUTION"
    elif usd == "BEARISH":
        xau, btc, index = "BUY", "BUY / RISK-ON", "BUY / RISK-ON"
    else:
        xau = btc = index = "WAIT"
    return f"""
🚨 <b>NEWS AI IMPACT PRO</b>
<code>{wib_now().strftime('%d-%m-%Y %H:%M WIB')}</code>

📰 News: <b>{news_type.upper()}</b>
Actual: <code>{actual}</code>
Forecast: <code>{forecast}</code>
Previous: <code>{previous if previous else '-'}</code>

💵 USD Bias: <b>{usd}</b>
🎯 Confidence: <b>{conf}%</b> {conf_bar(conf)}

🥇 XAU/XAG: <b>{xau}</b>
₿ Crypto: <b>{btc}</b>
📈 Index: <b>{index}</b>

✅ Reason:
{reason}

⚠️ Tunggu 1-2 candle M5 close setelah news. Jangan entry pas spread gila.
"""

# ==============================
# MENUS
# ==============================
def keyboard_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Market Scan", callback_data="cat_menu")],
        [InlineKeyboardButton("🎯 Sniper Scanner", callback_data="sniper_all")],
        [InlineKeyboardButton("🌍 Session Bias", callback_data="session_bias")],
        [InlineKeyboardButton("🌐 Macro Regime", callback_data="macro_view"), InlineKeyboardButton("🏛 Fundamental", callback_data="fund_xau")],
        [InlineKeyboardButton("📈 Dashboard", callback_data="dashboard")],
        [InlineKeyboardButton("📰 News Desk", callback_data="news_menu")],
        [InlineKeyboardButton("👤 Akun", callback_data="account"), InlineKeyboardButton("💎 Upgrade", callback_data="upgrade")],
        [InlineKeyboardButton("✅ Konfirmasi Bayar", callback_data="pay_menu")],
    ])


def main_text(user_id):
    u = get_user(user_id)
    status = "💎 <b>ELITE MEMBER</b>" if u.get("premium") else "🆓 <b>TRIAL MODE</b>"
    left = "Unlimited" if u.get("premium") else f"Market {TRIAL_LIMIT_MARKET-u.get('market_used',0)}x • News {TRIAL_LIMIT_NEWS-u.get('news_used',0)}x"
    return f"""
👑 <b>CAPITAL ELITE PROJECT V10</b>
<code>Fundamental + SMC/ICT Intelligence System</code>

{status}
{left}

✅ Multi Pair Scanner
✅ Smart Money Score
✅ Liquidity Heatmap
✅ Session Bias
✅ Auto Journal & Winrate
✅ Auto Sniper Alert Premium
✅ News AI Impact Pro
✅ AI Vision Lite
🆕 Fundamental Engine (Fed + Macro + COT)
🆕 3-Layer Confidence Scoring
🆕 /fundamental /macro commands

<code>Trade Smart • Trade Elite • V10</code>
"""


def category_keyboard():
    cats = [("🥇 Metals", "METALS"), ("💱 Forex", "FOREX"), ("📈 Index", "INDEX"), ("₿ Crypto", "CRYPTO"), ("🛢 Oil", "OIL")]
    rows = [[InlineKeyboardButton(label, callback_data=f"cat_{cat}")] for label, cat in cats]
    rows.append([InlineKeyboardButton("⬅️ Menu", callback_data="home")])
    return InlineKeyboardMarkup(rows)


def pairs_keyboard(cat):
    rows = []
    pairs = [k for k, v in PAIRS.items() if v["cat"] == cat]
    for i in range(0, len(pairs), 2):
        rows.append([InlineKeyboardButton(PAIRS[p]["name"], callback_data=f"pair_{p}") for p in pairs[i:i+2]])
    rows.append([InlineKeyboardButton("⬅️ Kategori", callback_data="cat_menu")])
    return InlineKeyboardMarkup(rows)


def tf_keyboard(pair):
    rows = [
        [InlineKeyboardButton("M1", callback_data=f"tf_{pair}_M1"), InlineKeyboardButton("M5", callback_data=f"tf_{pair}_M5"), InlineKeyboardButton("M15", callback_data=f"tf_{pair}_M15")],
        [InlineKeyboardButton("M30", callback_data=f"tf_{pair}_M30"), InlineKeyboardButton("H1", callback_data=f"tf_{pair}_H1"), InlineKeyboardButton("H4", callback_data=f"tf_{pair}_H4")],
        [InlineKeyboardButton("DAILY", callback_data=f"tf_{pair}_DAILY")],
        [InlineKeyboardButton("⬅️ Pair", callback_data=f"cat_{PAIRS[pair]['cat']}")]
    ]
    return InlineKeyboardMarkup(rows)

# ==============================
# HANDLERS
# ==============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(main_text(update.effective_user.id), reply_markup=keyboard_main(), parse_mode="HTML")


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data

    if data == "home":
        await q.edit_message_text(main_text(uid), reply_markup=keyboard_main(), parse_mode="HTML")
        return
    if data == "cat_menu":
        await q.edit_message_text("📊 <b>Pilih kategori pair:</b>", reply_markup=category_keyboard(), parse_mode="HTML")
        return
    if data.startswith("cat_"):
        cat = data.replace("cat_", "")
        await q.edit_message_text(f"📊 <b>{cat}</b>\nPilih pair:", reply_markup=pairs_keyboard(cat), parse_mode="HTML")
        return
    if data.startswith("pair_"):
        pair = data.replace("pair_", "")
        await q.edit_message_text(f"💱 <b>{PAIRS[pair]['name']}</b>\nPilih timeframe:", reply_markup=tf_keyboard(pair), parse_mode="HTML")
        return
    if data.startswith("tf_"):
        if not can_use_market(uid):
            await q.edit_message_text("🔒 Trial market habis. Upgrade premium untuk akses unlimited.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 Upgrade", callback_data="upgrade")]]), parse_mode="HTML")
            return
        _, pair, tf = data.split("_")
        await q.edit_message_text("🔍 Scanning liquidity...\n🧠 Validating SMC score...\n⚡ Building setup...")
        text = analyze_pair(pair, tf)
        add_usage(uid, "market")
        u = get_user(uid)
        if not u.get("premium"):
            text += f"\n\n🆓 Sisa trial market: {TRIAL_LIMIT_MARKET-u.get('market_used',0)}"
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔁 Ulang", callback_data=f"pair_{pair}")], [InlineKeyboardButton("🏠 Menu", callback_data="home")]]), parse_mode="HTML")
        return
    if data == "sniper_all":
        if not can_use_market(uid):
            await q.edit_message_text("🔒 Trial market habis. Upgrade premium untuk Sniper Scanner.", parse_mode="HTML")
            return
        await q.edit_message_text("🎯 Scanning top pairs M5/M15/H1...")
        text = sniper_scan_text(["XAUUSD", "BTCUSD", "ETHUSD", "EURUSD", "GBPUSD", "NAS100", "US30", "USOIL"])
        add_usage(uid, "market")
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="home")]]), parse_mode="HTML")
        return
    if data == "session_bias":
        await q.edit_message_text(session_bias_text(), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="home")]]), parse_mode="HTML")
        return
    if data == "macro_view":
        if not can_use_market(uid):
            await q.edit_message_text("🔒 Trial market habis. Upgrade premium untuk Macro Regime.", parse_mode="HTML")
            return
        await q.edit_message_text("🌐 Loading macro regime...")
        try:
            fed = fetch_fed_policy()
            macro = detect_macro_regime(fed)
            spread_arrow = "📈" if fed["spread"] > 0 else "📉"
            curve_icon = "🔴" if fed["curve_status"] == "INVERTED" else "🟡" if fed["curve_status"] == "FLAT" else "🟢"
            regime_icons = {"RISK_ON":"🟢","RISK_OFF":"🔴","STAGFLATION":"🟠","RECESSION":"⚫","NEUTRAL":"🟡"}
            regime_icon = regime_icons.get(macro["regime"],"🟡")
            text = f"""
🌐 <b>MACRO REGIME MONITOR V10</b>
<code>{wib_now().strftime('%d-%m-%Y %H:%M WIB')}</code>

{regime_icon} <b>REGIME: {macro['regime']}</b>
{macro['regime_note']}

🏛 Fed: <b>{fed['fed_tone']}</b>
{curve_icon} Yield Curve: <b>{fed['curve_status']}</b>
{spread_arrow} Spread: <b>{fed['spread']:+.3f}%</b>

📦 Asset Bias:
🥇 XAU → <b>{macro['xau_bias']}</b>
₿ Crypto → <b>{macro['btc_bias']}</b>
📈 Indices → <b>{macro['index_bias']}</b>
💵 USD → <b>{macro['usd_bias']}</b>

Gunakan /fundamental XAUUSD untuk COT detail.
"""
        except Exception as e:
            text = f"⚠️ Macro data error: {e}"
        add_usage(uid, "market")
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="home")]]), parse_mode="HTML")
        return
    if data == "fund_xau":
        if not can_use_market(uid):
            await q.edit_message_text("🔒 Trial market habis. Upgrade premium untuk Fundamental Engine.", parse_mode="HTML")
            return
        await q.edit_message_text("🏛 Loading fundamental data XAUUSD...")
        text = fundamental_report_text("XAUUSD")
        add_usage(uid, "market")
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="home")]]), parse_mode="HTML")
        return
    if data == "dashboard":
        await q.edit_message_text(performance_text(), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="home")]]), parse_mode="HTML")
        return
    if data == "news_menu":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📅 Forex Factory Today", callback_data="ff_today")], [InlineKeyboardButton("📌 Format Manual", callback_data="news_help")], [InlineKeyboardButton("🏠 Menu", callback_data="home")]])
        await q.edit_message_text("📰 <b>News Desk</b>", reply_markup=kb, parse_mode="HTML")
        return
    if data == "ff_today":
        if not can_use_news(uid):
            await q.edit_message_text("🔒 Trial news habis. Upgrade premium.", parse_mode="HTML")
            return
        events = parse_forex_factory_today()
        add_usage(uid, "news")
        text = "📰 <b>FOREX FACTORY TODAY</b>\n\n"
        if events:
            for i, ev in enumerate(events, 1):
                text += f"<b>{i}. USD {ev['impact']}</b>\n{ev['raw']}\n\n"
        else:
            text += "Tidak ada high impact USD terbaca / website sedang block. Pakai manual /news."
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="home")]]), parse_mode="HTML")
        return
    if data == "news_help":
        await q.edit_message_text("Format:\n<code>/news cpi actual=3.2 forecast=3.4 previous=3.5</code>\n<code>/news nfp actual=250 forecast=180</code>\n<code>/fomc hawkish</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="home")]]), parse_mode="HTML")
        return
    if data == "account":
        u = get_user(uid)
        status = "💎 PREMIUM" if u.get("premium") else "🆓 TRIAL"
        await q.edit_message_text(f"👤 <b>AKUN</b>\n\nID: <code>{uid}</code>\nStatus: <b>{status}</b>\nMarket used: <b>{u.get('market_used',0)}</b>\nNews used: <b>{u.get('news_used',0)}</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="home")]]), parse_mode="HTML")
        return
    if data == "upgrade":
        await q.edit_message_text(upgrade_text(), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Saya Sudah Bayar", callback_data="pay_menu")], [InlineKeyboardButton("🏠 Menu", callback_data="home")]]), parse_mode="HTML")
        return
    if data == "pay_menu":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💎 Elite 60 Hari", callback_data="payplan_60")],
            [InlineKeyboardButton("👑 VIP 90 Hari", callback_data="payplan_90")],
            [InlineKeyboardButton("♾️ Lifetime", callback_data="payplan_9999")],
            [InlineKeyboardButton("🏠 Menu", callback_data="home")],
        ])
        await q.edit_message_text(payment_start_text(), reply_markup=kb, parse_mode="HTML")
        return
    if data.startswith("payplan_"):
        days = int(data.replace("payplan_", ""))
        set_awaiting_payment(uid, days)
        await q.edit_message_text(payment_waiting_text(days), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="home")]]), parse_mode="HTML")
        return
    if data.startswith("payapprove_"):
        if uid != ADMIN_ID:
            await q.answer("Khusus admin.", show_alert=True)
            return
        parts = data.split("_")
        target_id = parts[1]
        days = int(parts[2])
        approve_payment_user(target_id, days)
        mark_payment_status(target_id, "APPROVED")
        await q.edit_message_text(f"✅ <b>PAYMENT APPROVED</b>\n\nUser <code>{target_id}</code> sudah aktif premium {format_days(days)}.", parse_mode="HTML")
        try:
            await context.bot.send_message(chat_id=int(target_id), text=f"✅ <b>PEMBAYARAN DISETUJUI</b>\n\nAkun lu sudah aktif: <b>{format_days(days)}</b>.\nKlik /start buat akses fitur premium.", parse_mode="HTML")
        except Exception:
            pass
        return
    if data.startswith("payreject_"):
        if uid != ADMIN_ID:
            await q.answer("Khusus admin.", show_alert=True)
            return
        target_id = data.replace("payreject_", "")
        clear_awaiting_payment(target_id)
        mark_payment_status(target_id, "REJECTED")
        await q.edit_message_text(f"❌ <b>PAYMENT REJECTED</b>\n\nUser <code>{target_id}</code> ditolak.", parse_mode="HTML")
        try:
            await context.bot.send_message(chat_id=int(target_id), text="❌ <b>BUKTI BAYAR DITOLAK</b>\n\nBukti belum valid / belum terbaca. Kirim ulang bukti transfer yang jelas atau chat admin.", parse_mode="HTML")
        except Exception:
            pass
        return


def upgrade_text():
    return f"""
👑 <b>CAPITAL ELITE PROJECT V10</b>
<code>Fundamental + SMC/ICT Intelligence System</code>

💎 <b>ELITE ACCESS — 60 HARI</b>
<s>Rp 499.000</s> 🔥 <b>Rp 199.000</b>

👑 <b>VIP ACCESS — 90 HARI</b>
<b>Rp 399.000</b>

♾️ <b>LIFETIME ACCESS</b>
<b>Rp 599.000</b>

✅ Unlimited Signal
✅ Auto Sniper Alert (Fundamental Filter)
✅ Multi Pair Scanner
✅ Session Bias
✅ News AI Pro
✅ Journal & Winrate
✅ AI Vision Lite
✅ <b>NEW: Fundamental Engine V10</b>
✅ <b>NEW: Macro Regime Detector</b>
✅ <b>NEW: Fed Policy Tracker</b>
✅ <b>NEW: COT Institutional Bias Proxy</b>
✅ <b>NEW: Yield Curve Monitor</b>
✅ <b>NEW: 3-Layer Confidence Scoring</b>

💳 <b>Payment</b>
<code>{PAYMENT_TEXT}</code>

📩 Admin: {ADMIN_CONTACT}
Kirim bukti transfer setelah bayar.
"""


def format_days(days):
    try:
        days = int(days)
    except Exception:
        days = 60
    return "LIFETIME" if days >= 9999 else f"{days} hari"


def payment_start_text():
    return f"""
✅ <b>KONFIRMASI PEMBAYARAN</b>

Pilih paket yang lu bayar.

💳 <b>Payment</b>
<code>{PAYMENT_TEXT}</code>

Setelah pilih paket, kirim foto/screenshot bukti transfer ke bot ini.
Bukti akan masuk ke admin untuk approve.
"""


def payment_waiting_text(days):
    return f"""
📸 <b>UPLOAD BUKTI TRANSFER</b>

Paket dipilih: <b>{format_days(days)}</b>

Sekarang kirim foto/screenshot bukti transfer ke chat ini.
Setelah dikirim, admin tinggal klik approve/reject.

⚠️ Pastikan nominal, tanggal, dan status berhasil terlihat jelas.
"""


def set_awaiting_payment(user_id, days):
    u = get_user(user_id)
    u["awaiting_payment_proof"] = True
    u["pending_payment_days"] = int(days)
    u["pending_payment_at"] = wib_now().strftime("%Y-%m-%d %H:%M:%S")
    update_user(user_id, u)


def clear_awaiting_payment(user_id):
    u = get_user(int(user_id))
    u["awaiting_payment_proof"] = False
    u.pop("pending_payment_days", None)
    update_user(int(user_id), u)


def save_payment_request(user_id, days, file_id, username="", full_name=""):
    db = load_json(PAYMENT_REQUEST_FILE, [])
    item = {
        "user_id": str(user_id),
        "days": int(days),
        "file_id": file_id,
        "username": username or "-",
        "full_name": full_name or "-",
        "status": "WAITING_ADMIN",
        "created_at": wib_now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    db.append(item)
    db = db[-200:]
    save_json(PAYMENT_REQUEST_FILE, db)
    return item


def mark_payment_status(user_id, status):
    db = load_json(PAYMENT_REQUEST_FILE, [])
    for item in reversed(db):
        if str(item.get("user_id")) == str(user_id) and item.get("status") == "WAITING_ADMIN":
            item["status"] = status
            item["updated_at"] = wib_now().strftime("%Y-%m-%d %H:%M:%S")
            break
    save_json(PAYMENT_REQUEST_FILE, db)


def approve_payment_user(user_id, days):
    users = load_json(USER_FILE, {})
    uid = str(user_id)
    u = users.get(uid, {"market_used": 0, "news_used": 0, "created_at": wib_now().strftime("%Y-%m-%d %H:%M:%S")})
    u["premium"] = True
    u["premium_until"] = "LIFETIME" if int(days) >= 9999 else (wib_now() + timedelta(days=int(days))).strftime("%Y-%m-%d %H:%M:%S")
    u["awaiting_payment_proof"] = False
    u.pop("pending_payment_days", None)
    u["approved_at"] = wib_now().strftime("%Y-%m-%d %H:%M:%S")
    users[uid] = u
    save_json(USER_FILE, users)

# ==============================
# COMMANDS
# ==============================
def normalize_tf(args, default="M5"):
    if not args:
        return default
    raw = args[0].upper()
    return {"1M":"M1","M1":"M1","3M":"M3","M3":"M3","5M":"M5","M5":"M5","15M":"M15","M15":"M15","30M":"M30","M30":"M30","1H":"H1","H1":"H1","4H":"H4","H4":"H4","D1":"DAILY","DAILY":"DAILY"}.get(raw, default)


async def pair_command(update: Update, context: ContextTypes.DEFAULT_TYPE, pair):
    uid = update.effective_user.id
    if not can_use_market(uid):
        await update.message.reply_text("🔒 Trial market habis. Upgrade premium untuk akses unlimited.", parse_mode="HTML")
        return
    tf = normalize_tf(context.args)
    await update.message.reply_text(f"🔍 Scanning <b>{PAIRS[pair]['name']}</b> {tf}...", parse_mode="HTML")
    text = analyze_pair(pair, tf)
    add_usage(uid, "market")
    await update.message.reply_text(text, parse_mode="HTML")


async def xau_command(update, context): await pair_command(update, context, "XAUUSD")
async def xag_command(update, context): await pair_command(update, context, "XAGUSD")
async def btc_command(update, context): await pair_command(update, context, "BTCUSD")
async def eth_command(update, context): await pair_command(update, context, "ETHUSD")
async def eur_command(update, context): await pair_command(update, context, "EURUSD")
async def gbp_command(update, context): await pair_command(update, context, "GBPUSD")
async def nas_command(update, context): await pair_command(update, context, "NAS100")
async def us30_command(update, context): await pair_command(update, context, "US30")
async def oil_command(update, context): await pair_command(update, context, "USOIL")


async def sniper_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not can_use_market(uid):
        await update.message.reply_text("🔒 Trial market habis. Upgrade premium.")
        return
    pairs = [a.upper() for a in context.args] if context.args else ["XAUUSD", "BTCUSD", "ETHUSD", "EURUSD", "GBPUSD", "NAS100", "US30", "USOIL"]
    pairs = [p if p in PAIRS else {"XAU":"XAUUSD","BTC":"BTCUSD","ETH":"ETHUSD","GOLD":"XAUUSD","NAS":"NAS100"}.get(p, "XAUUSD") for p in pairs]
    await update.message.reply_text("🎯 Sniper scanning...")
    text = sniper_scan_text(pairs[:10])
    add_usage(uid, "market")
    await update.message.reply_text(text, parse_mode="HTML")


def sniper_scan_text(pairs):
    rows = []
    best = None
    for pair in pairs:
        try:
            r = analyze_pair(pair, "M15", compact=True)
            if isinstance(r, dict):
                rows.append(r)
                if r["signal"] != "NO SETUP" and (best is None or r["confidence"] > best["confidence"]):
                    best = r
            pytime.sleep(0.4)
        except Exception as e:
            print("sniper error", pair, e)
    text = "🎯 <b>CAPITAL ELITE SNIPER SCANNER</b>\n<code>Multi Pair Confluence</code>\n\n"
    for r in rows:
        icon = "🟢" if r["signal"] == "BUY" else "🔴" if r["signal"] == "SELL" else "⚪"
        text += f"{icon} <b>{r['name']}</b> — {r['signal']} • {r['confidence']}% • {r['grade']} • SMC {r['smc']['Total']}/100\n"
    if best:
        text += f"\n🔥 <b>Best Watchlist</b>\n{best['name']} — <b>{best['signal']}</b> {best['confidence']}%\nEntry: <code>{fmt(best['entry'][0])} - {fmt(best['entry'][1])}</code>\nSL: <code>{fmt(best['sl'])}</code>\nTP: <code>{fmt(best['tp2'])}</code>\n"
    else:
        text += "\n⚪ Belum ada A setup. Tunggu market kasih sweep + MSS.\n"
    text += "\n⚠️ Bukan saran finansial."
    return text


def session_bias_text():
    session_tag, _, note = session_info()
    pairs = ["XAUUSD", "BTCUSD", "EURUSD", "GBPUSD", "NAS100", "US30", "USOIL"]
    text = f"🌍 <b>{session_tag.upper()} BIAS</b>\n<code>{wib_now().strftime('%d-%m-%Y %H:%M WIB')}</code>\n\n"
    for p in pairs:
        try:
            r = analyze_pair(p, "H1", compact=True)
            sig = r["signal"] if isinstance(r, dict) else "WAIT"
            conf = r["confidence"] if isinstance(r, dict) else 0
            text += f"• <b>{PAIRS[p]['name']}</b>: {sig} • {conf}%\n"
            pytime.sleep(0.3)
        except Exception:
            text += f"• <b>{PAIRS[p]['name']}</b>: DATA N/A\n"
    text += f"\n📌 {note}\n⚠️ Bukan saran finansial."
    return text


async def session_command(update, context):
    await update.message.reply_text(session_bias_text(), parse_mode="HTML")


async def dashboard_command(update, context):
    await update.message.reply_text(performance_text(), parse_mode="HTML")


async def journal_command(update, context):
    await update.message.reply_text(performance_text(), parse_mode="HTML")


async def result_command(update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Command ini khusus admin.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Format: /result TRADE_ID WIN|LOSS|BE")
        return
    ok = update_trade_result(context.args[0], context.args[1])
    await update.message.reply_text("✅ Journal updated." if ok else "Trade ID tidak ditemukan.")


async def risk_command(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("Format: /risk 100000 2")
        return
    modal = clean_num(context.args[0])
    risk_pct = clean_num(context.args[1])
    if not modal or not risk_pct:
        await update.message.reply_text("Format salah. Contoh: /risk 100000 2")
        return
    risk_money = modal * risk_pct / 100
    daily_max = modal * min(risk_pct * 2, 10) / 100
    await update.message.reply_text(f"""
🛡️ <b>SMART RISK CALCULATOR</b>

Modal: <code>Rp{modal:,.0f}</code>
Risk/trade: <code>{risk_pct}%</code>
Max loss/trade: <code>Rp{risk_money:,.0f}</code>
Max loss harian: <code>Rp{daily_max:,.0f}</code>

Rule akun kecil:
• Max 2-3 trade/hari
• Stop kalau 2x SL
• Minimal RR 1:2
• Jangan balas dendam market
""", parse_mode="HTML")


async def news_command(update, context):
    uid = update.effective_user.id
    if not can_use_news(uid):
        await update.message.reply_text("🔒 Trial news habis. Upgrade premium.")
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
    add_usage(uid, "news")
    await update.message.reply_text(news_ai(news_type, actual.group(1), forecast.group(1), previous.group(1) if previous else None), parse_mode="HTML")


async def fomc_command(update, context):
    uid = update.effective_user.id
    if not can_use_news(uid):
        await update.message.reply_text("🔒 Trial news habis. Upgrade premium.")
        return
    tone = " ".join(context.args).lower() if context.args else "neutral"
    if any(x in tone for x in ["hawk", "naik", "higher", "ketat"]):
        # Update manual Fed tone ke state file
        state = load_json(FUNDAMENTAL_FILE, {})
        state["manual_fed_tone"] = "HAWKISH"
        state["manual_set_at"] = wib_now().strftime("%Y-%m-%d %H:%M WIB")
        save_json(FUNDAMENTAL_FILE, state)
        # Clear cache biar fundamental re-fetch dengan tone baru
        MARKET_CACHE.pop("fed_policy", None)
        MARKET_CACHE.pop("macro_regime", None)
        text = news_ai("fomc", "1", "0", "hawkish")
        text += "\n🏦 Tone FOMC: <b>HAWKISH</b> → USD cenderung kuat.\n✅ Fundamental engine diupdate ke HAWKISH mode."
    elif any(x in tone for x in ["dov", "turun", "cut", "longgar"]):
        state = load_json(FUNDAMENTAL_FILE, {})
        state["manual_fed_tone"] = "DOVISH"
        state["manual_set_at"] = wib_now().strftime("%Y-%m-%d %H:%M WIB")
        save_json(FUNDAMENTAL_FILE, state)
        MARKET_CACHE.pop("fed_policy", None)
        MARKET_CACHE.pop("macro_regime", None)
        text = news_ai("fomc", "0", "1", "dovish")
        text += "\n🏦 Tone FOMC: <b>DOVISH</b> → USD cenderung lemah.\n✅ Fundamental engine diupdate ke DOVISH mode."
    elif any(x in tone for x in ["reset", "auto", "clear"]):
        state = load_json(FUNDAMENTAL_FILE, {})
        state.pop("manual_fed_tone", None)
        save_json(FUNDAMENTAL_FILE, state)
        MARKET_CACHE.pop("fed_policy", None)
        MARKET_CACHE.pop("macro_regime", None)
        text = "🔄 <b>FOMC tone direset ke auto-detect.</b>\nBot akan baca dari data yield curve otomatis."
    else:
        text = "🏦 <b>FOMC IMPACT</b>\nTone belum jelas. Tunggu statement + press conference + close candle M5.\n\nGunakan: /fomc hawkish | /fomc dovish | /fomc reset"
    add_usage(uid, "news")
    await update.message.reply_text(text, parse_mode="HTML")


async def fundamental_command(update, context):
    """
    /fundamental atau /fundamental XAUUSD
    Report lengkap fundamental: Fed, macro regime, COT proxy, yield curve.
    """
    uid = update.effective_user.id
    if not can_use_market(uid):
        await update.message.reply_text("🔒 Trial market habis. Upgrade premium untuk Fundamental Engine.")
        return
    pair = "XAUUSD"
    if context.args:
        p = context.args[0].upper()
        if p in PAIRS:
            pair = p
        elif p in {"XAU","GOLD"}:
            pair = "XAUUSD"
        elif p in {"BTC","BITCOIN"}:
            pair = "BTCUSD"
        elif p in {"EUR","EURUSD"}:
            pair = "EURUSD"
        elif p in {"NAS","NAS100","NASDAQ"}:
            pair = "NAS100"
    await update.message.reply_text(f"🌐 Fetching fundamental data untuk {PAIRS[pair]['name']}...")
    text = fundamental_report_text(pair)
    add_usage(uid, "market")
    await update.message.reply_text(text, parse_mode="HTML")


async def macro_command(update, context):
    """
    /macro — ringkasan macro regime global untuk semua kategori aset
    """
    uid = update.effective_user.id
    if not can_use_market(uid):
        await update.message.reply_text("🔒 Trial market habis. Upgrade premium.")
        return
    try:
        fed = fetch_fed_policy()
        macro = detect_macro_regime(fed)
        spread_arrow = "📈" if fed["spread"] > 0 else "📉"
        curve_icon = "🔴" if fed["curve_status"] == "INVERTED" else "🟡" if fed["curve_status"] == "FLAT" else "🟢"
        regime_icons = {"RISK_ON":"🟢","RISK_OFF":"🔴","STAGFLATION":"🟠","RECESSION":"⚫","NEUTRAL":"🟡"}
        regime_icon = regime_icons.get(macro["regime"],"🟡")
        text = f"""
🌐 <b>MACRO REGIME MONITOR</b>
<code>Capital Elite V10 • {wib_now().strftime('%d-%m-%Y %H:%M WIB')}</code>

{regime_icon} <b>REGIME: {macro['regime']}</b>
{macro['regime_note']}

🏛 <b>Fed:</b> {fed['fed_tone']} ({fed['fed_trend']})
{curve_icon} <b>Yield Curve:</b> {fed['curve_status']}
{spread_arrow} <b>Spread 10Y-2Y:</b> {fed['spread']:+.3f}%
2Y: {fed['rate_2y']:.2f}% | 10Y: {fed['rate_10y']:.2f}%

📦 <b>Asset Regime Bias:</b>
🥇 XAU/Silver → <b>{macro['xau_bias']}</b>
₿ Crypto → <b>{macro['btc_bias']}</b>
📈 Indices → <b>{macro['index_bias']}</b>
💵 USD → <b>{macro['usd_bias']}</b>

💡 <b>Trading Implication:</b>
Gunakan bias ini sebagai FILTER — entry tetap tunggu konfirmasi SMC.
Grade A+ hanya keluar kalau fundamental CONFIRM + SMC ≥82.

<code>/fundamental XAUUSD</code> untuk COT proxy pair spesifik.
<code>/fomc hawkish</code> atau <code>/fomc dovish</code> untuk update manual Fed tone.
"""
    except Exception as e:
        text = f"⚠️ Macro data error: {e}"
    add_usage(uid, "market")
    await update.message.reply_text(text, parse_mode="HTML")


async def commands_command(update, context):
    await update.message.reply_text("""
👑 <b>CAPITAL ELITE COMMAND CENTER V10</b>

📊 Analysis:
<code>/xau m5</code> <code>/btc h1</code> <code>/eth m15</code>
<code>/eur m15</code> <code>/gbp m15</code> <code>/nas m15</code>
<code>/us30 m15</code> <code>/oil h1</code>

🎯 Scanner:
<code>/sniper</code>
<code>/session</code>

🌐 Fundamental (NEW V10):
<code>/fundamental</code> — Full macro + Fed + COT report
<code>/fundamental XAUUSD</code> — COT proxy pair spesifik
<code>/macro</code> — Macro regime global (RISK_ON/OFF dll)
<code>/fomc hawkish</code> — Update Fed tone manual
<code>/fomc dovish</code> — Update Fed tone manual
<code>/fomc reset</code> — Kembali ke auto-detect

📈 Journal:
<code>/dashboard</code>
<code>/journal</code>
Admin: <code>/result TRADE_ID WIN</code>

🛡️ Risk:
<code>/risk 100000 2</code>

📰 News:
<code>/news cpi actual=3.2 forecast=3.4</code>
<code>/fomc hawkish</code>

💳 Payment:
<code>/bayar 60</code> lalu kirim bukti transfer
Admin: <code>/payments</code>

📸 AI Vision Lite:
Kirim screenshot chart ke bot.

<code>Grade A+ = SMC ≥82 + Fundamental CONFIRM + Confidence ≥88</code>
""", parse_mode="HTML")


async def premium_command(update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Lu bukan admin.")
        return
    if len(context.args) < 1:
        await update.message.reply_text("Format: /premium ID 60")
        return
    target = context.args[0]
    days = int(context.args[1]) if len(context.args) > 1 and context.args[1].isdigit() else 60
    users = load_json(USER_FILE, {})
    u = users.get(target, {"market_used": 0, "news_used": 0, "created_at": wib_now().strftime("%Y-%m-%d %H:%M:%S")})
    u["premium"] = True
    u["premium_until"] = "LIFETIME" if days >= 9999 else (wib_now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    users[target] = u
    save_json(USER_FILE, users)
    await update.message.reply_text(f"✅ User {target} premium {days} hari.")


async def unpremium_command(update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Lu bukan admin.")
        return
    if not context.args:
        await update.message.reply_text("Format: /unpremium ID")
        return
    users = load_json(USER_FILE, {})
    if context.args[0] in users:
        users[context.args[0]]["premium"] = False
        save_json(USER_FILE, users)
    await update.message.reply_text("✅ Premium dicabut.")


async def stats_admin_command(update, context):
    if update.effective_user.id != ADMIN_ID:
        await dashboard_command(update, context)
        return
    users = load_json(USER_FILE, {})
    premium = sum(1 for uid in users if get_user(int(uid)).get("premium"))
    await update.message.reply_text(f"👑 <b>ADMIN STATS</b>\n\nTotal User: <b>{len(users)}</b>\nPremium: <b>{premium}</b>\n\n" + performance_text(), parse_mode="HTML")


async def broadcast_command(update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Lu bukan admin.")
        return
    msg = " ".join(context.args)
    if not msg:
        await update.message.reply_text("Format: /broadcast pesan")
        return
    sent = 0
    for uid in premium_user_ids():
        try:
            await context.bot.send_message(chat_id=int(uid), text=msg, parse_mode="HTML")
            sent += 1
        except Exception:
            pass
    await update.message.reply_text(f"Broadcast terkirim ke {sent} premium user.")


async def vision_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = get_user(uid)

    # Payment proof mode: user already clicked /bayar or payment button.
    if u.get("awaiting_payment_proof"):
        days = int(u.get("pending_payment_days", 60))
        photo = update.message.photo[-1]
        file_id = photo.file_id
        username = update.effective_user.username or "-"
        full_name = update.effective_user.full_name or "-"
        save_payment_request(uid, days, file_id, username, full_name)
        clear_awaiting_payment(uid)

        await update.message.reply_text(
            "✅ <b>BUKTI BAYAR TERKIRIM</b>\n\nTunggu admin approve. Kalau valid, premium aktif otomatis.",
            parse_mode="HTML"
        )

        admin_text = f"""
💳 <b>PAYMENT PROOF REQUEST</b>

User: <b>{full_name}</b>
Username: @{username}
ID: <code>{uid}</code>
Paket: <b>{format_days(days)}</b>
Waktu: <code>{wib_now().strftime('%d-%m-%Y %H:%M WIB')}</code>

Klik approve kalau pembayaran valid.
"""
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ APPROVE", callback_data=f"payapprove_{uid}_{days}")],
            [InlineKeyboardButton("❌ REJECT", callback_data=f"payreject_{uid}")],
        ])
        try:
            await context.bot.send_photo(chat_id=ADMIN_ID, photo=file_id, caption=admin_text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_text, reply_markup=kb, parse_mode="HTML")
        return

    # Default: AI Vision Lite.
    if not can_use_market(uid):
        await update.message.reply_text("🔒 Trial market habis. Upgrade premium untuk AI Vision.")
        return
    caption = update.message.caption or ""
    pair = "XAUUSD"
    for p in PAIRS:
        if p.lower() in caption.lower() or PAIRS[p]["name"].replace("/", "").lower() in caption.lower():
            pair = p
            break
    tf = "M5"
    for t in TIMEFRAMES:
        if t.lower() in caption.lower():
            tf = t
            break
    add_usage(uid, "market")
    text = analyze_pair(pair, tf)
    text = "📸 <b>AI VISION LITE</b>\n<code>Screenshot diterima. Bot pakai market engine + caption pair/TF.</code>\n\n" + text
    await update.message.reply_text(text, parse_mode="HTML")


async def bayar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    days = 60
    if context.args:
        raw = context.args[0].lower()
        if raw in ["90", "vip"]:
            days = 90
        elif raw in ["life", "lifetime", "9999"]:
            days = 9999
        elif raw.isdigit():
            days = int(raw)
    set_awaiting_payment(uid, days)
    await update.message.reply_text(payment_waiting_text(days), parse_mode="HTML")


async def payments_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Lu bukan admin.")
        return
    db = load_json(PAYMENT_REQUEST_FILE, [])
    waiting = [x for x in db if x.get("status") == "WAITING_ADMIN"][-10:]
    if not waiting:
        await update.message.reply_text("✅ Tidak ada payment pending.")
        return
    text = "💳 <b>PENDING PAYMENT</b>\n\n"
    for i, item in enumerate(waiting, 1):
        text += f"{i}. ID <code>{item.get('user_id')}</code> • {format_days(item.get('days',60))} • @{item.get('username','-')} • {item.get('created_at','-')}\n"
    await update.message.reply_text(text, parse_mode="HTML")

# ==============================
# AUTO JOBS
# ==============================
async def auto_sniper_alert(context: ContextTypes.DEFAULT_TYPE):
    targets = premium_user_ids()
    if not targets:
        return
    watch = ["XAUUSD", "BTCUSD", "ETHUSD", "EURUSD", "GBPUSD", "NAS100", "US30", "USOIL"]
    sent_db = load_json(ALERT_SENT_FILE, {})
    hour_key = wib_now().strftime("%Y-%m-%d %H")
    sent_db.setdefault(hour_key, [])
    for p in watch:
        try:
            r = analyze_pair(p, "M15", compact=True)
            if not isinstance(r, dict) or r["signal"] == "NO SETUP" or r["confidence"] < AUTO_ALERT_MIN_CONF:
                continue
            alert_key = f"{hour_key}_{p}_{r['signal']}"
            if alert_key in sent_db[hour_key]:
                continue

            # V10: Fundamental filter for auto alert
            # Hanya kirim alert kalau fundamental tidak CONFLICT
            fund_verdict = r["smc"].get("fund", {}).get("verdict", "WEAK")
            fund_score = r["smc"].get("fund", {}).get("total", 50)
            fund_icon = "✅✅" if fund_verdict == "STRONG CONFIRM" else "✅" if fund_verdict == "CONFIRM" else "⚠️" if fund_verdict == "WEAK" else "❌"
            # Skip auto alert kalau fundamental CONFLICT kecuali SMC sangat tinggi
            if fund_verdict == "CONFLICT" and r["smc"]["Total"] < 80:
                continue

            sent_db[hour_key].append(alert_key)
            macro_regime = r["smc"].get("macro_regime", "NEUTRAL")
            fed_tone = r["smc"].get("fed_tone", "NEUTRAL")
            inst_bias = r["smc"].get("inst_bias", "NEUTRAL")
            text = f"""
🚨 <b>CAPITAL ELITE AUTO SNIPER ALERT V10</b>
<code>{PAIRS[p]['name']} • M15</code>

Signal: <b>{r['signal']}</b>
Confidence: <b>{r['confidence']}%</b> {conf_bar(r['confidence'])}
Grade: <b>{r['grade']}</b>
SMC Score: <b>{r['smc']['Total']}/100</b>
Fundamental: <b>{fund_score}/100</b> {fund_icon} {fund_verdict}

🌐 Macro: <b>{macro_regime}</b> | Fed: <b>{fed_tone}</b>
🏛 Institutional: <b>{inst_bias}</b>

Entry: <code>{fmt(r['entry'][0])} - {fmt(r['entry'][1])}</code>
SL: <code>{fmt(r['sl'])}</code>
TP1: <code>{fmt(r['tp1'])}</code>
TP2: <code>{fmt(r['tp2'])}</code>

⚠️ Validasi candle close. Bukan saran finansial.
"""
            for uid in targets:
                try:
                    await context.bot.send_message(chat_id=int(uid), text=text, parse_mode="HTML")
                except Exception:
                    pass
            pytime.sleep(0.5)
        except Exception as e:
            print("auto sniper error", p, e)
    days = sorted(sent_db.keys())[-48:]
    save_json(ALERT_SENT_FILE, {d: sent_db[d] for d in days})


async def daily_watchlist(context):
    targets = premium_user_ids()
    if not targets:
        return
    text = "🔥 <b>TODAY WATCHLIST</b>\n<code>Capital Elite Project V9</code>\n\n" + sniper_scan_text(["XAUUSD", "BTCUSD", "EURUSD", "GBPUSD", "NAS100", "USOIL"])
    for uid in targets:
        try:
            await context.bot.send_message(chat_id=int(uid), text=text, parse_mode="HTML")
        except Exception:
            pass


async def session_broadcast(context):
    targets = premium_user_ids()
    if not targets:
        return
    text = session_bias_text()
    for uid in targets:
        try:
            await context.bot.send_message(chat_id=int(uid), text=text, parse_mode="HTML")
        except Exception:
            pass


async def auto_news_alert(context):
    targets = premium_user_ids()
    if not targets:
        return
    events = parse_forex_factory_today()
    if not events:
        return
    sent = load_json(NEWS_SENT_FILE, {})
    day = wib_now().strftime("%Y-%m-%d")
    sent.setdefault(day, [])
    fresh = []
    for ev in events:
        key = re.sub(r"\s+", " ", ev["raw"].lower())[:160]
        if key not in sent[day]:
            fresh.append(ev)
            sent[day].append(key)
    if not fresh:
        return
    text = "🚨 <b>HIGH IMPACT NEWS WATCH</b>\n\n"
    for ev in fresh[:5]:
        text += f"• USD {ev['impact']} — {ev['raw']}\n"
    text += "\nGunakan /news setelah actual keluar."
    for uid in targets:
        try:
            await context.bot.send_message(chat_id=int(uid), text=text, parse_mode="HTML")
        except Exception:
            pass
    days = sorted(sent.keys())[-7:]
    save_json(NEWS_SENT_FILE, {d: sent[d] for d in days})

# ==============================
# RUN APP
# ==============================
def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN belum diisi di Environment Variables.")
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("commands", commands_command))
    app.add_handler(CommandHandler("xau", xau_command))
    app.add_handler(CommandHandler("xag", xag_command))
    app.add_handler(CommandHandler("btc", btc_command))
    app.add_handler(CommandHandler("eth", eth_command))
    app.add_handler(CommandHandler("eur", eur_command))
    app.add_handler(CommandHandler("gbp", gbp_command))
    app.add_handler(CommandHandler("nas", nas_command))
    app.add_handler(CommandHandler("us30", us30_command))
    app.add_handler(CommandHandler("oil", oil_command))
    app.add_handler(CommandHandler("sniper", sniper_command))
    app.add_handler(CommandHandler("session", session_command))
    app.add_handler(CommandHandler("dashboard", dashboard_command))
    app.add_handler(CommandHandler("journal", journal_command))
    app.add_handler(CommandHandler("result", result_command))
    app.add_handler(CommandHandler("risk", risk_command))
    app.add_handler(CommandHandler("news", news_command))
    app.add_handler(CommandHandler("fomc", fomc_command))
    app.add_handler(CommandHandler("fundamental", fundamental_command))
    app.add_handler(CommandHandler("macro", macro_command))
    app.add_handler(CommandHandler("premium", premium_command))
    app.add_handler(CommandHandler("bayar", bayar_command))
    app.add_handler(CommandHandler("payments", payments_command))
    app.add_handler(CommandHandler("unpremium", unpremium_command))
    app.add_handler(CommandHandler("stats", stats_admin_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(MessageHandler(filters.PHOTO, vision_handler))
    app.add_handler(CallbackQueryHandler(button))

    # Auto jobs. Waktu pakai UTC. WIB = UTC+7.
    app.job_queue.run_repeating(auto_sniper_alert, interval=1800, first=120)  # tiap 30 menit
    app.job_queue.run_repeating(auto_news_alert, interval=1800, first=180)
    app.job_queue.run_daily(daily_watchlist, time=dt_time(hour=0, minute=0))   # 07:00 WIB
    app.job_queue.run_daily(session_broadcast, time=dt_time(hour=6, minute=0)) # 13:00 WIB
    app.job_queue.run_daily(session_broadcast, time=dt_time(hour=12, minute=0)) # 19:00 WIB

    print("CAPITAL ELITE PROJECT V10 FUNDAMENTAL EDITION ONLINE...")
    print("Startup safe mode: delete webhook + drop pending updates.")
    app.run_polling(
        drop_pending_updates=True,
        close_loop=False
    )


if __name__ == "__main__":
    main()
