import json
import logging
import os
from groq import Groq
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

class AIServiceError(Exception):
    """Base class for AI service errors"""
    pass

class AIService:
    def __init__(self, api_key=None, model_name="openai/gpt-oss-20b"):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise AIServiceError("GROQ_API_KEY not found in environment")

        self.model_name = model_name
        self.client = Groq(api_key=self.api_key)

    def _call_groq(self, messages: list, temperature: float = 0.7) -> str:
        """Send a chat completion request to the Groq API and return the response text."""
        completion = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=temperature,
            max_completion_tokens=2048,
            top_p=1,
            stream=False,
            stop=None,
        )

        choices = completion.choices
        if not choices:
            raise AIServiceError("Empty response from Groq API (no choices)")

        text = choices[0].message.content
        if not text:
            raise AIServiceError("Empty response from Groq API (no content)")

        return text.strip()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    def generate_text(self, prompt: str) -> str:
        """Generate text using Groq chat completion with retry logic"""
        try:
            logger.info(f"Generating text for prompt: {prompt[:50]}...")
            messages = [{"role": "user", "content": prompt}]
            return self._call_groq(messages)
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
        """Generate structured JSON using Groq chat completion with retry logic"""
        try:
            logger.info(f"Generating JSON for prompt: {prompt[:50]}...")
            # Instruct the model to return only valid JSON
            json_prompt = f"{prompt}\n\nIMPORTANT: Return ONLY valid JSON. No markdown formatting, no code blocks, no preamble."
            messages = [{"role": "user", "content": json_prompt}]
            text = self._call_groq(messages, temperature=0.3)

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
