# Setup Guide

This guide walks you through setting up BreakoutAnalysis for the first time.

---

## 1. Install Prerequisites

- **Python 3.10+** — [download](https://python.org)
- **Git** — [download](https://git-scm.com)

```bash
git clone https://github.com/your-username/BreakoutAnalysis.git
cd BreakoutAnalysis
pip install -r requirements.txt
playwright install chromium
```

---

## 2. Create Your Config File

```bash
cp config/config.example.json config/config.json
```

Now edit `config/config.json`. The sections below explain each part.

> ⚠️ **Never commit `config/config.json`** — it's in `.gitignore` for a reason.

---

## 3. Alpaca API (Required for Historical Filtering)

1. Create a free account at [alpaca.markets](https://alpaca.markets)
2. Go to **API Keys** → generate a key for Paper Trading
3. Set in config:
   ```json
   "alpaca": {
       "api_key": "YOUR_KEY",
       "api_secret": "YOUR_SECRET",
       "use_paper": true,
       "data_feed": "iex"
   }
   ```

### Choosing Your Data Feed

| Feed | Plan | Recommendation |
|------|------|---------------|
| `"iex"` | Free | Good for getting started |
| `"sip"` | Algo Trader (~$9/mo) | **Recommended** — consolidated feed from all US exchanges, lower miss rate |

To use SIP, subscribe at [alpaca.markets/data](https://alpaca.markets/data) then change `"data_feed": "sip"`.

> If no Alpaca key is set, the screener still runs — historical quality filtering is simply skipped.

---

## 4. LLM API Key (Required for AI Analysis)

### Option A: Google Gemini (Recommended — free tier available)
1. Get an API key from [Google AI Studio](https://aistudio.google.com/)
2. Set in config under all `gemini-*` model entries:
   ```json
   { "name": "gemini-2.5-flash", "api_key": "YOUR_GEMINI_KEY" }
   ```
3. Set `"current_model": "gemini-2.5-flash"`

### Option B: OpenAI
1. Get an API key from [platform.openai.com](https://platform.openai.com)
2. Set in config under the `gpt-*` model you want to use
3. Set `"current_model": "gpt-4.1-mini"` (or your preferred model)

### Option C: Local Models (Ollama — no API key needed)
- Install [Ollama](https://ollama.ai) and pull `llama3.2-vision` or `deepseek-r1-distill-qwen-7b`
- No API key needed; set `"current_model": "llama-3.2-vision"`

> If no LLM is configured, alerts are sent without AI analysis.

---

## 5. Discord Notifications (Optional)

1. In your Discord server: **Server Settings → Integrations → Webhooks → New Webhook**
2. Copy the webhook URL and set in config:
   ```json
   "discord": {
       "webhook_url": "https://discord.com/api/webhooks/YOUR_STOCK_ALERTS_WEBHOOK",
       "webhook_url_market_report": "https://discord.com/api/webhooks/YOUR_MARKET_REPORT_WEBHOOK"
   }
   ```
   You can use the same webhook for both or create two separate channels.

> If not configured, Discord notifications are skipped silently.

---

## 6. Email Notifications (Optional)

Email uses Gmail OAuth2. This is the most involved setup.

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → Enable the **Gmail API**
3. Create OAuth2 credentials (Desktop App type) → Download as `credentials.json`
4. Place `credentials.json` in the project root
5. Run the OAuth flow:
   ```bash
   python scripts/run_gmail_oauth_flow.py
   ```
6. This generates `token.json` (gitignored)

> If `credentials.json` / `token.json` are missing, email is skipped.

---

## 7. TradingView Chart Screenshots (Optional)

Screenshots require a TradingView account and your chart's URL ID.

1. Open your chart on TradingView — copy the ID from the URL:
   `https://www.tradingview.com/chart/**ABC123XY**/`
2. Set in config:
   ```json
   "tradingview": {
       "chart_id": "ABC123XY",
       "cookies": {
           "sessionid": "...",
           "sessionid_sign": "...",
           "device_t": "..."
       }
   }
   ```
3. To get cookies: open TradingView in Chrome → F12 → Application → Cookies → tradingview.com
   Copy the values for `sessionid`, `sessionid_sign`, and `device_t`

> If cookies aren't set, screenshots are skipped. The screener and alerts still work.

---

## 8. Run It

```bash
python src/tradealerts.py
```

The bot runs in a loop, checking every 15 minutes during market hours. Check the logs for startup messages confirming which integrations are active.

---

## Environment Variables (Docker / CI)

Instead of editing `config/config.json`, you can set these environment variables:

```bash
export ALPACA_API_KEY=your_key
export ALPACA_API_SECRET=your_secret
export ALPACA_DATA_FEED=sip
export GEMINI_API_KEY=your_gemini_key
export DISCORD_WEBHOOK_URL=your_webhook
```

See `src/utils/config_loader.py` for the full list of supported overrides.
