"""삼성전자·SK하이닉스 심층 리포트용 실시간 데이터 + 기술적 지표 산출.
설치 스킬(technical-analysis / trading-analysis) 방법론 적용:
- 추세(이평 구조), 모멘텀(RSI·MACD, 다이버전스 주의), 변동성(BB·ATR), 수급(거래량)
- 지지/저항은 '구역(zone)'으로, 단정이 아닌 확률적으로 해석
산출: reports/ 에 JSON + 차트 PNG. 콘솔에 핵심 수치 출력.
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ta import rsi, macd, atr, f  # noqa: E402  공유 지표(중복 제거)
# 한글 라벨 깨짐(tofu) 방지 — Windows 기본 한글 폰트. 없으면 무시.
for _f in ("Malgun Gothic", "AppleGothic", "NanumGothic"):
    try:
        plt.rcParams["font.family"] = _f
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False

OUT = Path(__file__).resolve().parent.parent / "reports"
OUT.mkdir(exist_ok=True)
KST = timezone(timedelta(hours=9))

TARGETS = [
    {"ticker": "005930.KS", "name": "삼성전자"},
    {"ticker": "000660.KS", "name": "SK하이닉스"},
]
CONTEXT = [
    {"ticker": "^KS11", "name": "코스피"},
    {"ticker": "KRW=X", "name": "원/달러"},
    {"ticker": "NVDA", "name": "엔비디아"},
    {"ticker": "^SOX", "name": "필라델피아 반도체"},
]


def analyze(ticker, name):
    df = yf.Ticker(ticker).history(period="1y", auto_adjust=False)
    if len(df) < 60:
        print(f"[warn] {ticker}: 데이터 부족({len(df)})")
        return None
    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]
    last, prev = c.iloc[-1], c.iloc[-2]
    sma = {p: c.rolling(p).mean().iloc[-1] for p in (20, 60, 120, 200)}
    r = rsi(c)
    ml, ms, mh = macd(c)
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std()
    bb_up, bb_dn = mid + 2 * sd, mid - 2 * sd
    pctb = (last - bb_dn.iloc[-1]) / (bb_up.iloc[-1] - bb_dn.iloc[-1]) if (bb_up.iloc[-1] - bb_dn.iloc[-1]) else None
    a = atr(h, l, c)
    hi52, lo52 = c.tail(252).max(), c.tail(252).min()
    rng_pos = (last - lo52) / (hi52 - lo52) if hi52 > lo52 else None
    vol_ann = c.pct_change().tail(20).std() * (252 ** 0.5) * 100
    vavg20 = v.tail(20).mean()
    # 최근 60거래일 스윙 고/저 → 지지/저항 구역
    win = df.tail(60)
    res_zone = win["High"].max()
    sup_zone = win["Low"].min()
    # MACD 히스토그램 추세(최근 5일 기울기)
    mh5 = mh.tail(5).values
    res = {
        "ticker": ticker, "name": name,
        "asof": str(df.index[-1].date()),
        "close": f(last), "prev": f(prev),
        "change_pct": f((last / prev - 1) * 100),
        "sma20": f(sma[20]), "sma60": f(sma[60]), "sma120": f(sma[120]), "sma200": f(sma[200]),
        "rsi14": f(r.iloc[-1]), "rsi_prev": f(r.iloc[-2]),
        "macd": f(ml.iloc[-1]), "macd_signal": f(ms.iloc[-1]), "macd_hist": f(mh.iloc[-1]),
        "macd_hist_rising": bool(len(mh5) >= 2 and mh5[-1] > mh5[0]),
        "bb_pctb": f(pctb), "bb_up": f(bb_up.iloc[-1]), "bb_dn": f(bb_dn.iloc[-1]),
        "atr14": f(a.iloc[-1]), "atr_pct": f(a.iloc[-1] / last * 100),
        "hi52": f(hi52), "lo52": f(lo52), "range_pos": f(rng_pos),
        "vol_ann_pct": f(vol_ann),
        "vol_last": f(v.iloc[-1]), "vol_avg20": f(vavg20),
        "vol_ratio": f(v.iloc[-1] / vavg20) if vavg20 else None,
        "ret_20d": f((last / c.iloc[-21] - 1) * 100) if len(c) > 21 else None,
        "ret_60d": f((last / c.iloc[-61] - 1) * 100) if len(c) > 61 else None,
        "sup_zone": f(sup_zone), "res_zone": f(res_zone),
    }
    # 추세 구조 판정(이평 정배열/역배열)
    s = [sma[20], sma[60], sma[120]]
    if all(f(x) for x in s):
        if last > sma[20] > sma[60] > sma[120]:
            res["trend"] = "정배열(상승추세)"
        elif last < sma[20] < sma[60] < sma[120]:
            res["trend"] = "역배열(하락추세)"
        else:
            res["trend"] = "혼조(추세 불명확)"
    else:
        res["trend"] = "데이터부족"
    # 차트: 가격+이평 / RSI·MACD
    fig, ax = plt.subplots(2, 1, figsize=(10, 7), height_ratios=[2.2, 1], sharex=True)
    ax[0].plot(c.index, c, label="종가", lw=1.3)
    for p, col in [(20, "#e0a13a"), (60, "#3a82e0"), (120, "#9a3ae0")]:
        ax[0].plot(c.index, c.rolling(p).mean(), label=f"SMA{p}", lw=0.9, color=col)
    ax[0].fill_between(c.index, bb_dn, bb_up, color="#888", alpha=0.08, label="볼린저밴드")
    ax[0].set_title(f"{name} ({ticker}) — 1Y")
    ax[0].legend(fontsize=7, loc="upper left"); ax[0].grid(alpha=0.2)
    ax[1].plot(r.index, r, color="#c0392b", lw=0.9, label="RSI14")
    ax[1].axhline(70, color="#aaa", ls="--", lw=0.6); ax[1].axhline(30, color="#aaa", ls="--", lw=0.6)
    ax[1].set_ylim(0, 100); ax[1].legend(fontsize=7, loc="upper left"); ax[1].grid(alpha=0.2)
    plt.tight_layout()
    png = OUT / f"{ticker.replace('.', '_')}_chart.png"
    plt.savefig(png, dpi=130); plt.close()
    res["chart"] = str(png.name)
    return res


def main():
    now = datetime.now(KST)
    out = {"generated_at_kst": now.strftime("%Y-%m-%d %H:%M"), "targets": [], "context": []}
    for t in TARGETS:
        r = analyze(t["ticker"], t["name"])
        if r:
            out["targets"].append(r)
    for t in CONTEXT:
        try:
            df = yf.Ticker(t["ticker"]).history(period="3mo", auto_adjust=False)
            c = df["Close"]
            out["context"].append({
                "ticker": t["ticker"], "name": t["name"],
                "close": f(c.iloc[-1]), "change_pct": f((c.iloc[-1] / c.iloc[-2] - 1) * 100),
                "ret_20d": f((c.iloc[-1] / c.iloc[-21] - 1) * 100) if len(c) > 21 else None,
            })
        except Exception as e:
            print(f"[warn] context {t['ticker']}: {e}")
    p = OUT / "samsung_skhynix_data.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\nsaved {p}")


if __name__ == "__main__":
    main()
