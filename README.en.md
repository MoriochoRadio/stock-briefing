# 📈 Semiconductor-Focused Stock Market Tracker (Nearly Free to Run)

🇰🇷 [한국어](README.md) · 🇬🇧 English

[![Daily Stock Briefing](https://github.com/MoriochoRadio/stock-briefing/actions/workflows/daily.yml/badge.svg)](https://github.com/MoriochoRadio/stock-briefing/actions/workflows/daily.yml)
[![Korea Intraday](https://github.com/MoriochoRadio/stock-briefing/actions/workflows/intraday_kr.yml/badge.svg)](https://github.com/MoriochoRadio/stock-briefing/actions/workflows/intraday_kr.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Tracks the US and Korean stock markets **all day long**, automatically generating and publishing analysis reports. It focuses on **semiconductors** (centered on Samsung Electronics and SK hynix), covers the Korean market in three slices — **open, midday, and close** — and ties each day back to the preceding **US semiconductor** session.

**Nearly zero-cost operation**: GitHub Actions (execution, free) + Gemini free tier (analysis, with thinking enabled) + GitHub Pages (hosting, free). If you need deeper analysis, you can switch to Claude Opus 4.8 in `config.yaml` (paid, about $3–4/month — **billed separately from a Claude MAX subscription**).

🔗 **Live**: https://moriochoradio.github.io/stock-briefing/

**Tech stack**: Python (yfinance, Google News RSS, pandas/numpy) · Gemini API (2.5 Flash, thinking) / Claude Opus 4.8 (optional) · Astro 5 · Tailwind CSS 4 · TradingView lightweight-charts · Lucide

## Daily Cycle (KST — Korea Standard Time, weekdays)

| Time | Workflow | What happens |
|---|---|---|
| 🌅 **07:10~** | `daily.yml` | Overnight **US market** morning briefing (Tue–Sat, only on US trading days) |
| 🟢 **09:30–11:00** | `intraday_kr.yml` (open) | Korean market **opening** snapshot |
| 🟡 **11:30–14:00** | `intraday_kr.yml` (mid) | **Midday** snapshot |
| 🔴 **15:35~** | `intraday_kr.yml` (close) | Korean market **closing deep-dive report** + **US semiconductor connection analysis** |

> Open and midday runs are light snapshots (quotes, indicator changes, a short read); the close is a full deep-dive report. GitHub cron can be **delayed by up to several hours** under load, so the crons are scheduled densely and each run determines its own phase (open/mid/close) from the **actual KST time it arrives**. If it lands outside a window, is a duplicate, or the market is closed (no candle for today), it skips immediately without calling the LLM. Quotes come from yfinance, with Korean stocks delayed by **roughly 15–20 minutes**.

## Main Screens (Home)

- **Time-of-day-responsive Hero** — sky and sun colors and labels change with pre-open / morning session / afternoon session / close / after-hours, reflecting the latest Korean market quotes (adjusted to KST in real time in the browser)
- **Today's Korean Market Timeline** — open→mid→close snapshots fill in over the day, with Samsung and SK hynix technical indicators (trend, RSI, MACD…) + LLM analysis
- **The Two Semiconductor Giants** — interactive charts for Samsung and SK hynix (price + SMA20/60/120 moving averages)
- **US Semiconductor Connection** — NVIDIA, AMD, Micron, TSMC, Broadcom, ASML + the Philadelphia Semiconductor Index (SOX), with analysis of links to the Korean market (decoupling, HBM demand, etc.)
- **Data-status panel** — surfaces collection time, actual quote dates, watchlist coverage, and possible delay on both Home and Dashboard, so prior-session prices are not presented as current data during holidays or delayed runs
- **Verifiable briefing** — stable evidence IDs are assigned to collected headlines; only citations actually used by the LLM are rendered as clickable entries in the `Article evidence` section
- Plus — today's briefing, key headlines, market mood (Fear & Greed Index), watchlist quote cards, index charts
- **Market Focus** — a three-card observation console immediately below the hero, combining Korean semiconductor indicators, US semiconductor context, and market sentiment. Starred tickers are stored only in the local browser and can be filtered instantly
- **Semiconductor Relative Strength** — normalizes Samsung Electronics and SK hynix to the same 100-point baseline for accurate 1M, 3M, 6M, and 1Y performance comparison
- **Dashboard** (`/dashboard`) — bento grid, sector heatmap · **Archive** — past briefings by date

## How It Works

**Scripts** (`scripts/`)
- `fetch_data.py` — collects yfinance quotes + Google News RSS + CNN Fear & Greed Index → `sentiment/series/news/history.json` and `quality.json` (coverage, as-of dates, sources)
- `generate.py` — writes the morning briefing with the LLM → `briefings/<date>.md`. Engine calls are factored into `run_llm()` (built-in retries and engine fallback, shared with the intraday script); only permitted news evidence IDs are kept and rendered as clickable sources
- `intraday_kr.py` — Korean market open/mid/close + (at close) US semiconductor analysis → `site/src/data/intraday.json`, including snapshot-level coverage, as-of dates, and delay status. If the LLM fails, existing real analysis is preserved (no downgrade)
- `ta.py` — shared technical indicators (RSI, MACD, ATR, SMA, Bollinger Bands, trend detection)
- `deep_report.py` — one-off local deep-dive report (matplotlib chart PNGs; `reports/` is gitignored)

**Workflows** (`.github/workflows/`)
- `daily.yml` — morning briefing at 22:10 UTC (07:10 KST)
- `intraday_kr.yml` — dense cron every 30 minutes. PHASE is auto-determined by the script from the KST time at execution (`auto`) — labels and data stay consistent even when cron is delayed. If nothing is captured, commit/build/deploy are skipped
- Data collection and analysis run independently; only the **Pages deployment job** is serialized in the shared `pages-deploy` queue. The deploy job checks out current `main` immediately before its build, preventing an old workflow SHA from being published, while retaining push retries, one automatic Pages retry, and pip/npm caching

```
GitHub Actions → fetch/generate/intraday (Python) → commit *.json/*.md → Astro build → GitHub Pages deploy
```

> Besides the scheduled (cron) runs, **pushing code to main** rebuilds and redeploys the site (data collection and LLM calls are skipped to save quota).

## Why It's Built This Way — Technical Choices Q&A

**Q. Why a serverless static site + GitHub Actions?**
A. The data changes only 3–4 times a day (morning, open, mid, close), so there's no need for a server that renders on every request. Actions handles cron scheduling, secret management, execution, and deployment (Pages) in one place for free, and the outputs are committed, giving you history tracking too — zero server/DB cost and one less failure point.

**Q. GitHub cron can be hours late — how do you keep things on time?**
A. Instead of trusting the clock, crons are scheduled densely at 30-minute intervals, and each run determines its own phase (open/mid/close) from the **actual KST time it arrives**. Runs outside a window, duplicates, and market holidays are skipped immediately without calling the LLM, so labels and data stay consistent even under delay.

**Q. Why is the default LLM the Gemini free tier?**
A. "Nearly zero-cost operation" is the project's premise, so Gemini 2.5 Flash — which supports thinking (a reasoning budget) even on the free tier — is the default. For deeper analysis, engine calls are abstracted behind `run_llm()` so a one-line change in `config.yaml` switches to Claude Opus.

**Q. Doesn't the site break when the LLM API fails?**
A. `run_llm()` has built-in retries (up to 6) and engine fallback; if it still fails, a data summary is used instead. On fallback, the intraday script **preserves the existing real analysis**, preventing a downgrade where a good result gets overwritten by a bad one.

**Q. Why yfinance, Google News RSS, and the CNN Fear & Greed Index as data sources?**
A. All three are free and require no API key, which fits the zero-cost principle. The roughly 15–20 minute delay on Korean stock quotes is an acceptable trade-off, since this is an analysis report, not a real-time trading tool.

**Q. Why Astro?**
A. For a content-centric static site, Astro's default output is pure HTML with no JS, so it's fast, and the model of adding client scripts only where needed (the TradingView lightweight-charts interactive charts, the Hero's real-time KST adjustment) fits this project exactly.

## Deployment

1. **Create the repo** — GitHub New repository → name it `stock-briefing`, **Public** (unlimited free Actions).
2. **Push the code**:
   ```bash
   cd stock-briefing-web
   git init && git add -A && git commit -m "init"
   git branch -M main
   git remote add origin https://github.com/<username>/stock-briefing.git
   git push -u origin main
   ```
3. **Get a Gemini API key (free, no card required)** — https://aistudio.google.com/apikey  ⚠️ Registering billing removes the free tier.
   > For deeper analysis, get an **Anthropic key** instead (https://console.anthropic.com/, paid, about $3–4/month — separate from a Claude MAX subscription) and set `llm.provider` in `config.yaml` to `"anthropic"`.
4. **Register secrets** — Settings → Secrets and variables → Actions → New repository secret
   - `GEMINI_API_KEY` (default engine: Gemini 2.5 Flash)
   - (Optional) `ANTHROPIC_API_KEY` + `provider: anthropic` in `config.yaml` → Claude Opus 4.8
   - ⚠️ Pushing changes to workflow files (`.github/workflows/`) requires a token with the **`workflow` scope** (`gh auth refresh -s workflow`).
5. **Enable Pages** — Settings → Pages → Source: **GitHub Actions**.
6. **Test run** — Actions tab → "Daily Stock Briefing" or "Korea Intraday Snapshot" (input `phase`) → Run workflow → `https://<username>.github.io/stock-briefing/`.

## Customization

| What to change | Where |
|---|---|
| Watchlist, news keywords, LLM engine (`provider`), model, thinking budget | `config.yaml` |
| Check windows (open/mid/close) | `WINDOWS` in `scripts/intraday_kr.py` (cron in `intraday_kr.yml`, UTC = KST−9h) |
| Morning briefing time | cron in `.github/workflows/daily.yml` |
| Briefing/intraday tone and structure (prompts) | `scripts/generate.py`, `scripts/intraday_kr.py` |
| Korean deep-dive / US analysis tickers | `PRIMARY`/`US_SEMI` in `scripts/intraday_kr.py` |
| Site design | `site/src/` (Astro components, CSS) |

Local preview: `cd site && npm install && npm run dev` · Local deep-dive report: `pip install -r requirements.txt && python scripts/deep_report.py`

## Notes

- Quote cards and charts appear once the workflows have run at least once and data has accumulated.
- If you name the repo `<username>.github.io`, change `BASE_PATH` in `daily.yml` to `"/"`.
- The Gemini free tier is occasionally overloaded (503), so LLM calls retry (up to 6 times) and, if that still fails, fall back safely to a data summary (real analysis resumes automatically on the next run).
- These reports are **informational, not investment advice**. Data sources: Yahoo Finance (yfinance), Google News, CNN Fear & Greed.

## Development (Claude Code)

This repo is developed and maintained with [Claude Code](https://claude.com/claude-code). See `CLAUDE.md` for working rules.
Key rule: **always `git pull --rebase` before pushing** (the bot commits daily and intraday).

## License

[MIT](LICENSE)
