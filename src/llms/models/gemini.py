import os
import json
import logging
from google import genai
from google.genai import types
from PIL import Image
from typing import Dict

from .basemodel import BaseModel
from ..tools import search_internet

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class GeminiModel(BaseModel):
    """
    Implementation for Google's Gemini models.
    Handles vision capabilities and agentic tool calling for internet search.
    """

    def __init__(self, config: dict):
        """
        Initializes the Gemini model client.
        """
        super().__init__(config)
        self.model_name = config.get("name", "gemini-1.5-flash")
        self.api_key = config.get("api_key")

        if not self.api_key:
            self.api_key = os.getenv("GOOGLE_API_KEY")

        if not self.api_key:
            logging.error("Google API key not found in config or GOOGLE_API_KEY environment variable.")
            self.client = None
        else:
            try:
                # Configure the client using the new API
                self.client = genai.Client(api_key=self.api_key)
                
                # Define the grounding tool
                self.grounding_tool = types.Tool(
                    google_search=types.GoogleSearch()
                )
                
                # Configure generation settings
                self.config = types.GenerateContentConfig(
                    tools=[self.grounding_tool]
                )
                
                logging.info(f"Initialized GeminiModel client for model '{self.model_name}'")
            except Exception as e:
                logging.error(f"Failed to initialize Gemini client: {e}.", exc_info=True)
                self.client = None

    def generate_analysis(self, prompt: str, image_path: str = None) -> str:
        """
        Generates stock analysis using the Gemini model with Google Search grounding.
        """
        if not self.client:
            error_msg = "GeminiModel client not initialized. Cannot generate analysis."
            logging.error(error_msg)
            return error_msg

        # Prepare the initial message content
        if image_path and os.path.exists(image_path):
            try:
                img = Image.open(image_path)
                # For multimodal content, pass content directly
                contents = [prompt, img]
                logging.info(f"Included chart image from {image_path} in analysis request.")
            except Exception as e:
                logging.error(f"Error processing image {image_path}: {e}", exc_info=True)
                contents = prompt
        else:
            contents = prompt

        try:
            # Generate content with Google Search grounding enabled using new API
            logging.info(f"Sending request to Gemini model '{self.model_name}' with search grounding...")
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=self.config,
            )

            # Log if grounding was used
            if (response.candidates and 
                response.candidates[0].grounding_metadata and 
                response.candidates[0].grounding_metadata.web_search_queries):
                queries = response.candidates[0].grounding_metadata.web_search_queries
                logging.info(f"Model used Google Search with queries: {queries}")
            else:
                logging.info("Model answered from its own knowledge without searching.")

            logging.info("Model provided analysis.")
            return response.text.strip()

        except Exception as e:
            logging.error(f"Error during Gemini API call: {e}", exc_info=True)
            return f"Error generating analysis: {e}"
