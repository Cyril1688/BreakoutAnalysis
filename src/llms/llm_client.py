import json
import os
import logging
from typing import Dict, Optional, Type # Remove List
# Remove DDGS import

# Dynamically import available model classes
# Add new model classes here as they are implemented
from .models.basemodel import BaseModel

# 惰性导入：模型依赖的 SDK（openai、google-genai、ollama 等）可能未安装
# 在 GitHub Actions 中运行时不安装完整依赖，也仍然可以工作（跳过 LLM 分析）
def _lazy_import_model(model_name: str):
    """Try to import a model class, return None if dependencies missing."""
    try:
        if model_name == "deepseek-r1-distill-qwen-7b":
            from .models.deepseek_r1 import DeepSeekR1Model
            return DeepSeekR1Model
        elif model_name in ("llama-3.2-vision",):
            from .models.llama3_2_vision import Llama3_2VisionModel
            return Llama3_2VisionModel
        elif model_name in ("gpt-4o", "gpt-4o-mini", "gpt-4.1-mini", "o4-mini"):
            from .models.gpt_unified import GPTUnified
            return GPTUnified
        elif model_name in ("gemini-2.0", "gemini-pro-vision", "gemini-2.5-flash", "gemini-2.5-pro"):
            from .models.gemini import GeminiModel
            return GeminiModel
    except ImportError as e:
        logging.warning(f"Model '{model_name}' dependencies not installed: {e}")
    return None

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Map model names (from config.json) to their corresponding classes
# Uses lazy import so missing dependencies don't crash the whole app
MODEL_CLASS_MAP: Dict[str, Type[BaseModel]] = {}

# Populate via lazy import
_MODEL_NAMES = [
    "deepseek-r1-distill-qwen-7b",
    "llama-3.2-vision",
    "gpt-4o", "gpt-4o-mini", "gpt-4.1-mini", "o4-mini",
    "gemini-2.0", "gemini-pro-vision", "gemini-2.5-flash", "gemini-2.5-pro",
]
for _name in _MODEL_NAMES:
    _cls = _lazy_import_model(_name)
    if _cls:
        MODEL_CLASS_MAP[_name] = _cls

class LLMClient:
    """
    Client layer for interacting with different LLM models for stock analysis.
    Loads configuration, selects the appropriate model, constructs prompts,
    and retrieves analysis results.
    """

    def __init__(self, config_path: str = 'config/config.json'):
        """
        Initializes the LLMClient.

        Args:
            config_path (str): Path to the main configuration file.
        """
        self.config_path = config_path
        self.config: Optional[Dict] = None
        self.llm_config: Optional[Dict] = None
        self.model: Optional[BaseModel] = None
        self.prompt_template: Optional[str] = None

        try:
            self._load_config()
            self._initialize_model()
            self._load_prompt()
            logging.info("LLMClient initialized successfully.")
        except Exception as e:
            logging.error(f"Failed to initialize LLMClient: {e}", exc_info=True)
            # Ensure partial initialization doesn't cause issues
            self.model = None
            self.prompt_template = None

    def _load_config(self):
        """Loads the main configuration file."""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
            self.llm_config = self.config.get('llms')
            if not self.llm_config:
                raise ValueError("LLM configuration ('llms') missing in config file.")
            logging.info(f"Loaded configuration from {self.config_path}")
        except FileNotFoundError:
            logging.error(f"Configuration file not found at {self.config_path}")
            raise
        except json.JSONDecodeError:
            logging.error(f"Error decoding JSON from {self.config_path}")
            raise
        except Exception as e:
            logging.error(f"Error loading configuration: {e}")
            raise

    def _initialize_model(self):
        """Initializes the specific LLM model based on the configuration."""
        if not self.llm_config:
            raise ValueError("LLM configuration not loaded.")

        current_model_name = self.llm_config.get('current_model', 'gpt-4o-mini')  # Default to gpt-4o-mini if not specified
        if not current_model_name:
            raise ValueError("'current_model' not specified in LLM configuration.")

        models_list = self.llm_config.get('models', [])
        model_config = next((m for m in models_list if m.get('name') == current_model_name), None)

        if not model_config:
            raise ValueError(f"Configuration for model '{current_model_name}' not found in 'models' list.")

        model_class = MODEL_CLASS_MAP.get(current_model_name)
        if not model_class:
            raise ValueError(f"No implementation class found for model '{current_model_name}'. Check MODEL_CLASS_MAP.")

        try:
            self.model = model_class(model_config)
            logging.info(f"Instantiated model: {current_model_name}")
        except Exception as e:
            logging.error(f"Failed to instantiate model '{current_model_name}': {e}")
            raise

    def _load_prompt(self):
        """Loads the prompt template file."""
        if not self.llm_config or not self.model:
             raise ValueError("LLM configuration or model not initialized before loading prompt.")

        prompt_file_name = self.llm_config.get('prompt_file')
        if not prompt_file_name:
            raise ValueError("'prompt_file' not specified in LLM configuration.")

        # Assume prompt file is relative to the 'src/llms' directory or project root
        # Let's try relative to the config file's directory first, then project root
        config_dir = os.path.dirname(self.config_path) # e.g., 'config'
        project_root = os.path.dirname(config_dir) # e.g., '.'
        llms_dir = os.path.join(project_root, 'src', 'llms') # e.g., './src/llms'

        # Construct potential paths - adjust if prompt location is different
        potential_paths = [
            os.path.join(llms_dir, prompt_file_name),
            os.path.join(project_root, prompt_file_name), # If prompt is at root
        ]

        prompt_file_path = None
        for path in potential_paths:
            if os.path.exists(path):
                prompt_file_path = path
                break

        if not prompt_file_path:
             raise FileNotFoundError(f"Prompt file '{prompt_file_name}' not found in expected locations: {potential_paths}")

        try:
            self.prompt_template = self.model.load_prompt_template(prompt_file_path)
            logging.info(f"Loaded prompt template from {prompt_file_path}")
        except Exception as e:
            logging.error(f"Failed to load prompt template from {prompt_file_path}: {e}")
            raise # Re-raise after logging

    def analyze_stock(self, stock_data: dict) -> Optional[str]:
        """
        Analyzes the given stock data using the configured LLM.

        Args:
            stock_data (dict): A dictionary containing the data for a single stock.
                              May include 'chart_image_path' for vision models.

        Returns:
            Optional[str]: The analysis result string from the LLM, or None if an error occurs.
        """
        if not self.model or not self.prompt_template:
            logging.error("LLMClient is not properly initialized. Cannot analyze stock.")
            return None

        try:
            logging.info(f"Constructing prompt for stock: {stock_data.get('Ticker', 'N/A')}")
            final_prompt = self.model.construct_prompt(self.prompt_template, stock_data)

            # Get chart image path if provided
            chart_image_path = stock_data.get('chart_image_path')
            
            logging.info(f"Requesting analysis from model: {self.model.__class__.__name__}")
            analysis_result = self.model.generate_analysis(final_prompt, chart_image_path)
            logging.info(f"Received analysis for stock: {stock_data.get('Ticker', 'N/A')}")
            return analysis_result

        except Exception as e:
            logging.error(f"Error during stock analysis for {stock_data.get('Ticker', 'N/A')}: {e}", exc_info=True)
            return None # Return None on error

# Note: This class is intended to be imported and used by other modules
# (e.g., tradealerts.py). To test it independently, you would typically
# create a separate test script (e.g., in the 'testscripts' directory)
# that imports LLMClient, or run it as a module from the project root:
# python -m src.llms.llm_client
# (You would need to add the `if __name__ == '__main__':` block back temporarily
# for the `-m` flag execution to run the test code).
