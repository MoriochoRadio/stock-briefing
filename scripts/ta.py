"""공유 기술적 지표 계산 — 인트라데이/심층 리포트가 함께 사용.
일봉 종가 기준. 장중에는 yfinance가 당일 봉을 갱신하므로 last=현재가(지연 시세)로 동작.
"""
import math
import numpy as np
import pandas as pd


def f(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except Exception:
        return None


def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def macd(close, fast=12, slow=26, sig=9):
    ef = close.ewm(span=fast, adjust=False).mean()
    es = close.ewm(span=slow, adjust=False).mean()
    line = ef - es
    signal = line.ewm(span=sig, adjust=False).mean()
    return line, signal, line - signal


def atr(h, l, c, n=14):
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def compute_metrics(df):
    """일봉 DataFrame(Open/High/Low/Close/Volume) → 지표 딕셔너리. 데이터 부족 시 None."""
    if df is None or len(df) < 60:
        return None
    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]
    o = df["Open"]
    last, prev = c.iloc[-1], c.iloc[-2]
    sma = {p: c.rolling(p).mean().iloc[-1] for p in (20, 60, 120, 200)}
    r = rsi(c)
    ml, ms, mh = macd(c)
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std()
    bb_up, bb_dn = mid + 2 * sd, mid - 2 * sd
    band = bb_up.iloc[-1] - bb_dn.iloc[-1]
    pctb = (last - bb_dn.iloc[-1]) / band if band else None
    a = atr(h, l, c)
    hi52, lo52 = c.tail(252).max(), c.tail(252).min()
    rng_pos = (last - lo52) / (hi52 - lo52) if hi52 > lo52 else None
    vavg20 = v.tail(20).mean()
    mh5 = mh.tail(5).values
    today_open = o.iloc[-1]

    # 추세 구조(이평 정/역배열)
    s20, s60, s120 = sma[20], sma[60], sma[120]
    if all(f(x) for x in (s20, s60, s120)):
        if last > s20 > s60 > s120:
            trend = "정배열"
        elif last < s20 < s60 < s120:
            trend = "역배열"
        else:
            trend = "혼조"
    else:
        trend = "데이터부족"

    rsi_now = f(r.iloc[-1])
    rsi_state = ("과매수" if rsi_now and rsi_now >= 70 else
                 "과매도" if rsi_now and rsi_now <= 30 else
                 "강세권" if rsi_now and rsi_now >= 55 else
                 "약세권" if rsi_now and rsi_now <= 45 else "중립")
    macd_hist_now = f(mh.iloc[-1])
    macd_dir = "상승" if macd_hist_now and macd_hist_now > 0 else "하락" if macd_hist_now and macd_hist_now < 0 else "보합"

    return {
        "asof": str(df.index[-1].date()),
        "close": f(last), "prev": f(prev),
        "change_pct": f((last / prev - 1) * 100) if prev else None,
        "open": f(today_open),
        "vs_open_pct": f((last / today_open - 1) * 100) if today_open else None,
        "sma20": f(s20), "sma60": f(s60), "sma120": f(sma[120]), "sma200": f(sma[200]),
        "vs_sma20_pct": f((last / s20 - 1) * 100) if s20 else None,
        "rsi14": rsi_now, "rsi_prev": f(r.iloc[-2]), "rsi_state": rsi_state,
        "macd": f(ml.iloc[-1]), "macd_signal": f(ms.iloc[-1]),
        "macd_hist": macd_hist_now, "macd_dir": macd_dir,
        "macd_hist_rising": bool(len(mh5) >= 2 and mh5[-1] > mh5[0]),
        "bb_pctb": f(pctb), "bb_up": f(bb_up.iloc[-1]), "bb_dn": f(bb_dn.iloc[-1]),
        "atr14": f(a.iloc[-1]), "atr_pct": f(a.iloc[-1] / last * 100) if last else None,
        "hi52": f(hi52), "lo52": f(lo52), "range_pos": f(rng_pos),
        "vol_last": f(v.iloc[-1]), "vol_avg20": f(vavg20),
        "vol_ratio": f(v.iloc[-1] / vavg20) if vavg20 else None,
        "ret_20d": f((last / c.iloc[-21] - 1) * 100) if len(c) > 21 else None,
        "ret_60d": f((last / c.iloc[-61] - 1) * 100) if len(c) > 61 else None,
        "trend": trend,
    }
