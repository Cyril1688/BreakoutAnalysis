import logging
import os
from src.llms.models.gemini import GeminiModel

class MarketBriefingClient:
    """
    Client to get daily market briefing by directly invoking GeminiModel with search capabilities.
    """

    def __init__(self, api_key: str = None):
        import json
        import os
        try:
            if api_key is None:
                # Attempt to load API key from config file
                config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'config', 'config.json')
                if os.path.exists(config_path):
                    with open(config_path, 'r') as f:
                        config_data = json.load(f)
                    # Look for gemini model in models list
                    llms_config = config_data.get('llms', {})
                    models_list = llms_config.get('models', [])
                    gemini_model_config = next((m for m in models_list if m.get('name', '').startswith('gemini-2.5-flash')), None)
                    if gemini_model_config:
                        api_key = gemini_model_config.get('api_key')
                    if not api_key:
                        api_key = llms_config.get('gemini_api_key') or llms_config.get('api_key')
                if not api_key:
                    api_key = os.getenv("GOOGLE_API_KEY")
            if not api_key:
                logging.error("Google API key not provided or found in config or environment variable GOOGLE_API_KEY.")
                self.gemini_model = None
            else:
                config = {"api_key": api_key, "name": "gemini-2.5-flash"}
                self.gemini_model = GeminiModel(config)
                logging.info("Initialized GeminiModel 'gemini-2.5-flash' for MarketBriefingClient.")
        except Exception as e:
            logging.error(f"Failed to initialize GeminiModel in MarketBriefingClient: {e}")
            self.gemini_model = None

    def get_market_briefing(self) -> str:
        """
        Sends a prompt to Gemini to get current market conditions, important events,
        and trading advice for today.

        Returns:
            str: The market briefing summary or error message.
        """
        if not self.gemini_model:
            return "Market briefing unavailable: Gemini model not initialized."

        prompt = self._build_prompt()
        try:
            logging.info("Requesting market briefing from Gemini model...")
            briefing = self.gemini_model.generate_analysis(prompt)
            logging.info("Received market briefing from Gemini model.")
            return briefing
        except Exception as e:
            logging.error(f"Error getting market briefing: {e}")
            return f"Error getting market briefing: {e}"

    def _build_prompt(self) -> str:
        """
        Constructs the prompt for the market briefing.

        Returns:
            str: The prompt string.
        """
        prompt = (
            "You are a financial AI assistant. Provide a daily US Stock market briefing for today using your search capabilities. "
            "You have access to real-time web search through Google Search grounding. "
            "Include the current prices of the following major indices: S&P 500, NASDAQ, Dow Jones Industrial Average, and VIX. "
            "Also include any important scheduled or occured US market events for today such as Federal Reserve meetings, CPI data releases, unemployment data, or other significant economic indicators. "
            "Please Note: Only for the US Market please. "
            "Make this section brief and concise. Only include important and significant events for current day. "
            "If no such important events are scheduled just mention as such."
            "Summarize the general market conditions based on this data. "
            "Present all the information in a concise, clear, and professional manner suitable for a trader starting or ending their day depending on the time of the report."
            "Use markdown formatting to make the output more readable. Use emojis to make it more interesting. No information overload just make it to the point concise and interesting."
            "Use readable formats such as point based or tabular based for better readabilitiy"
        )
        return prompt
