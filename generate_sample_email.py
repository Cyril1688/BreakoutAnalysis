import json
import os
from datetime import datetime

# Assuming the markdown_to_html and create_html_email_body functions are in src/email/send_email.py
# We need to import them or copy them here for this script to run independently.
# For simplicity, I'll copy the relevant functions here.

import markdown2

def markdown_to_html(text):
    """Converts markdown to HTML using the markdown2 library."""
    if not isinstance(text, str):
        return ""
    return markdown2.markdown(text, extras=["fenced-code-blocks", "tables"])

def create_html_email_body(notification_list):
    """Creates a single, well-formatted HTML email body for a list of notifications."""
    
    styles = """
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol";
            margin: 0;
            padding: 0;
            background-color: #f8f9fa; /* Light gray background */
            color: #343a40; /* Dark gray text */
            line-height: 1.6;
        }
        .main-container {
            max-width: 700px;
            margin: 20px auto;
            padding: 30px;
            background-color: #ffffff; /* White content background */
            border-radius: 12px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.08);
        }
        h1 {
            text-align: center;
            color: #212529; /* Darker heading */
            font-size: 2.2em;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #e9ecef; /* Lighter border */
        }
        h2 {
            color: #007bff; /* Primary blue for sections */
            font-size: 1.6em;
            margin-top: 35px;
            margin-bottom: 15px;
            padding-bottom: 8px;
            border-bottom: 1px solid #e9ecef;
        }
        h3 {
            color: #495057; /* Slightly lighter heading */
            font-size: 1.2em;
            margin-top: 25px;
            margin-bottom: 10px;
        }
        .date {
            text-align: center;
            margin-bottom: 30px;
            font-style: italic;
            color: #6c757d; /* Muted date color */
            font-size: 0.95em;
        }
        /* Market Briefing Styles */
        .market-briefing-container {
            background-color: #e0f7fa; /* Light cyan */
            border-left: 5px solid #00bcd4; /* Cyan accent */
            padding: 25px;
            margin-bottom: 30px;
            border-radius: 8px;
        }
        .market-briefing-container h2 {
            margin-top: 0;
            color: #007bff; /* Consistent blue */
            border-bottom: none;
            padding-bottom: 0;
        }
        .market-briefing-container p {
            line-height: 1.7;
            white-space: pre-wrap;
            font-size: 1.05em;
        }
        /* Stock Card Styles */
        .stock-card {
            border: 1px solid #dee2e6; /* Light gray border */
            border-radius: 10px;
            margin-bottom: 30px;
            padding: 25px;
            background-color: #ffffff;
            transition: all 0.3s ease;
            box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        }
        .stock-card:hover {
            box-shadow: 0 6px 20px rgba(0,0,0,0.12);
            transform: translateY(-3px);
        }
        .stock-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 1px solid #e9ecef;
        }
        .stock-header h3 {
            margin: 0;
            color: #212529;
            font-size: 1.6em;
            font-weight: 600;
        }
        .stock-header .ticker {
            font-weight: bold;
            font-size: 1.8em;
            color: #007bff;
            background-color: #e9f5ff;
            padding: 5px 12px;
            border-radius: 5px;
        }
        .data-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 20px;
        }
        .data-section {
            padding: 15px;
            border-radius: 8px;
            background-color: #f1f3f5; /* Lighter gray for data sections */
            border: 1px solid #e9ecef;
        }
        .section-title {
            font-weight: 600;
            color: #495057;
            margin-bottom: 10px;
            font-size: 1.15em;
        }
        .analysis-section .section-title {
            margin-top: 20px;
        }
        .analysis-content {
            white-space: pre-wrap;
            font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, Courier, monospace; /* Monospace for code/analysis */
            background-color: #fdfdfe;
            border: 1px solid #ced4da;
            padding: 18px;
            border-radius: 8px;
            margin-top: 12px;
            font-size: 0.95em;
            line-height: 1.5;
        }
        .disclaimer {
            margin-top: 50px;
            padding-top: 20px;
            border-top: 1px solid #e9ecef;
            font-size: 0.85em;
            color: #6c757d;
            text-align: center;
        }
        .discord-invite {
            margin-top: 35px;
            padding: 25px;
            border-top: 1px solid #e9ecef;
            text-align: center;
            background-color: #f0f8ff; /* Very light blue */
            border-radius: 10px;
            border: 1px solid #cfe2ff;
        }
        .discord-invite p {
            margin-bottom: 15px;
            font-size: 1.05em;
            color: #343a40;
        }
        .discord-invite p:last-child {
            margin-bottom: 0;
        }
        .discord-invite strong {
            font-size: 1.15em;
            color: #212529;
        }
        .discord-invite a {
            font-size: 1.3em;
            color: #7289da; /* Discord brand color */
            text-decoration: none;
            font-weight: bold;
            transition: color 0.2s ease;
        }
        .discord-invite a:hover {
            color: #5b6eae;
        }
        .discord-invite .small-text {
            font-size: 0.9em;
            color: #7f8c8d;
        }
        .unsubscribe-info {
            margin-top: 20px;
            font-size: 0.8em;
            color: #7f8c8d;
            text-align: center;
        }
    </style>
    """
    
    html_content = f"<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'><title>Trading Report</title>{styles}</head><body><div class='main-container'>"
    
    # Add main title and date
    title = "Daily Trading Report"
    if len(notification_list) == 1 and 'content' in notification_list[0]:
        title = notification_list[0].get('title', title)
    
    html_content += f"<h1>{title}</h1><p class='date'>{datetime.now().strftime('%B %d, %Y')}</p>"

    # Process each notification
    for item in notification_list:
        if 'content' in item: # This is a market briefing
            html_content += f"""
            <div class="market-briefing-container">
                <h2>Market Overview</h2>
                <p>{markdown_to_html(item.get('content', 'N/A'))}</p>
            </div>
            """
        elif 'ticker' in item: # This is a stock alert
            ticker = item.get('ticker', 'N/A')
            company_name = item.get('company_name', 'N/A')
            
            html_content += f"""
            <div class="stock-card">
                <div class="stock-header">
                    <h3>{company_name}</h3>
                    <span class="ticker">{ticker}</span>
                </div>
                <div class="data-grid">
                    <div class="data-section">
                        <div class="section-title">📊 Core Data</div>
                        {markdown_to_html(item.get('core_data_str', 'N/A'))}
                    </div>
                    <div class="data-section">
                        <div class="section-title">📈 Technicals</div>
                        {markdown_to_html(item.get('technicals_str', 'N/A'))}
                    </div>
                </div>
                <div class="analysis-section">
                    <div class="section-title">🤖 AI Insights</div>
                    <div class="analysis-content">{markdown_to_html(item.get('llm_analysis_str', 'N/A'))}</div>
                </div>
            </div>
            """

    # Add disclaimer and close tags
    html_content += """
        <div class="disclaimer">
            <p>This report is for informational purposes only and does not constitute investment advice. Trading stocks involves risk. Always perform your own due diligence.</p>
        </div>
        <div class="discord-invite">
            <p><strong>Want more real-time updates, custom recommendations, and knowledge on how to use these alerts effectively?</strong></p>
            <p><a href="https://discord.com/invite/4KCanDzc3m">Join our Discord Channel!</a></p>
        </div>
        <div class="unsubscribe-info">
            <p>To stop receiving these reports, please reply to this email with "Unsubscribe"</p>
        </div>
    </div></body></html>
    """
    
    return html_content


def generate_sample_email():
    sample_market_briefing = {
        "title": "Market Briefing - 07:15 AM PST",
        "content": """
### 🇺🇸 US Stock Market Briefing: July 31, 2025 📈

**Current Index Prices (as of market open/early trading):**
* S&P 500: 6,427.02 (up 1.01%) ⬆️
* NASDAQ Composite: 21,457.48 (up 1.55%) ⬆️
* Dow Jones Industrial Average: 44,665.82 (up 0.46%) ⬆️
* VIX: 14.93 (as of July 2025)

**Important US Market Events for Today:**
* **Federal Reserve Meeting (Yesterday's Outcome):** The Federal Reserve decided to keep interest rates unchanged at yesterday's FOMC meeting. Fed Chair Jerome Powell indicated that the Fed is not ready to cut rates yet and that there is no decision to cut rates at the September meeting either.
* **PCE Price Index (June):** The Personal Consumption Expenditures (PCE) price index for June is expected to be released today at 8:30 AM ET. Economists anticipate inflation to tick higher, with a forecast of a 2.5% year-over-year increase.
* **Weekly Initial Jobless Claims:** Investors are awaiting key reports on Weekly Initial Jobless Claims
* **Challenger Job Cuts (July):** The Challenger Job Cuts report for July has been released, showing 62,075K job cuts.
* **ADP Employment Report (July):** US private businesses added 104,000 jobs in July 2025, surpassing the expected 75,000 and marking the strongest gain since March.
* **Earnings Reports:**
    * **Occurred (Post-market yesterday):** Microsoft (MSFT) and Meta (META) both reported blockbuster quarterly results, exceeding Wall Street expectations. Microsoft jumped nearly 9%, and Meta rallied 11% in premarket trading following their reports.
    * **Scheduled (After market close today):** Tech heavyweights Apple (AAPL) and Amazon (AMZN) will report their results after the bell. Mastercard (MA) also reported Q2 earnings this morning, exceeding analyst forecasts.
* **Trade Developments:** President Trump announced a 15% tariff deal with South Korea and has stood firm on not extending trade negotiations with lagging partners like India, which could face a 50% tariff from August 1. He also imposed a 50% tariff on copper imports, exempting refined metals.

**General Market Conditions:**
The US stock market is showing a strong positive sentiment today, with major indices opening significantly higher. This rally is primarily fueled by better-than-expected quarterly results from tech giants Microsoft and Meta, signaling that their investments in Artificial Intelligence are paying off. While the Federal Reserve decided to keep interest rates unchanged and Fed Chair Powell tempered expectations for a September rate cut, the positive earnings news and optimism around AI are currently driving market momentum. However, investors are also closely watching upcoming inflation data (PCE) and potential impacts from new trade tariffs.
"""
    }

    sample_stock_alert = {
        "ticker": "MSFT",
        "company_name": "Microsoft Corp.",
        "core_data_str": """
* **Price:** $450.00 (+8.9%)
* **Volume:** 120M (vs Avg 70M)
* **Market Cap:** $3.35T
* **Sector:** Technology
""",
        "technicals_str": """
* **RSI:** 72 (Overbought)
* **MACD:** Bullish Crossover
* **50-Day MA:** $410.00
* **200-Day MA:** $380.00
""",
        "llm_analysis_str": """
Microsoft's strong earnings report, driven by cloud and AI growth, has led to a significant premarket rally. The stock is now trading above key moving averages, indicating strong bullish momentum. However, the high RSI suggests it might be overbought in the short term, potentially leading to a minor pullback before further gains. Investors should watch for continued AI adoption and future guidance.
"""
    }

    notification_list = [sample_market_briefing, sample_stock_alert]
    
    html_output = create_html_email_body(notification_list)
    
    output_file = "sample_email_report.html"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html_output)
    print(f"Sample email report generated at {output_file}")

if __name__ == "__main__":
    generate_sample_email()
