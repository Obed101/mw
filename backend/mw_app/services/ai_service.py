import google.generativeai as genai
import json
import logging
import os
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

class AIServiceError(Exception):
    """Base class for AI service errors"""
    pass

class AIService:
    def __init__(self, api_key=None, model_name="gemini-1.5-flash"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise AIServiceError("GEMINI_API_KEY not found in environment")
        
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(model_name)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    def generate_text(self, prompt: str) -> str:
        """Generate text using Gemini model with retry logic"""
        try:
            logger.info(f"Generating text for prompt: {prompt[:50]}...")
            response = self.model.generate_content(prompt)
            if not response.text:
                raise AIServiceError("Empty response from AI")
            return response.text.strip()
        except Exception as e:
            logger.error(f"AI text generation error: {str(e)}")
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    def generate_json(self, prompt: str) -> dict:
        """Generate structured JSON using Gemini model with retry logic"""
        try:
            logger.info(f"Generating JSON for prompt: {prompt[:50]}...")
            # Instruct Gemini to return only valid JSON
            json_prompt = f"{prompt}\n\nIMPORTANT: Return ONLY valid JSON. No markdown formatting, no code blocks, no preamble."
            response = self.model.generate_content(json_prompt)
            
            text = response.text.strip()
            # Clean markdown code blocks if present
            if text.startswith("```"):
                lines = text.splitlines()
                if lines[0].startswith("```json"):
                    text = "\n".join(lines[1:-1])
                else:
                    text = "\n".join(lines[1:-1])
            
            try:
                data = json.loads(text)
                return data
            except json.JSONDecodeError as je:
                logger.error(f"Failed to parse AI JSON response: {text}")
                raise AIServiceError(f"Invalid JSON from AI: {str(je)}")
                
        except Exception as e:
            logger.error(f"AI JSON generation error: {str(e)}")
            raise
