"""
ClearMind API Client
Wraps the OpenRouter API (OpenAI-compatible) for generating responses.
Uses free models to keep the project accessible.
"""

import os
import json
import requests
from typing import Optional, List, Dict

import config

GARBAGE_PATTERNS = [
    "user safety:", "safety:", "content policy", "i cannot",
    "as an ai language model", "classification:",
]


def _is_garbage(text: str) -> bool:
    stripped = text.strip().lower()
    if len(stripped.split()) < 4:
        return True
    return any(stripped.startswith(p) for p in GARBAGE_PATTERNS)


class GeminiClient:
    """OpenRouter API wrapper for ClearMind (keeps class name for compatibility)."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")

        if not self.api_key:
            self.api_key = self._load_from_dotenv()

        if not self.api_key:
            raise ValueError(
                "No API key found. Set OPENROUTER_API_KEY in your .env file."
            )

        self.model = config.MODEL
        self.fallback_models = getattr(config, "FALLBACK_MODELS", [])
        self.api_url = config.API_URL

    def _load_from_dotenv(self) -> Optional[str]:
        env_path = os.path.join(os.path.dirname(__file__), '.env')
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('OPENROUTER_API_KEY='):
                        return line.split('=', 1)[1].strip().strip('"').strip("'")
        return None

    def _call_api(self, messages: list, model: str,
                  temperature: float, max_tokens: int) -> str:
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            response = requests.post(
                self.api_url,
                json=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                    "HTTP-Referer": "http://localhost:5000",
                    "X-Title": "ClearMind",
                },
                timeout=60,
            )
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"API request failed: {e}")

        if response.status_code != 200:
            raise RuntimeError(
                f"API error {response.status_code}: {response.text[:500]}"
            )

        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
            if not content or not content.strip():
                raise RuntimeError("Empty response from model")
            return content
        except (KeyError, IndexError) as e:
            raise RuntimeError(
                f"Unexpected response format: {e}\n"
                f"Response: {json.dumps(data, indent=2)[:500]}"
            )

    def generate(
        self,
        user_message: str,
        system_prompt: str = "",
        conversation_history: Optional[List[Dict]] = None,
        temperature: float = config.TEMPERATURE,
        max_tokens: int = config.MAX_TOKENS,
    ) -> str:
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if conversation_history:
            for msg in conversation_history:
                role = "assistant" if msg["role"] == "model" else "user"
                messages.append({"role": role, "content": msg["text"]})

        messages.append({"role": "user", "content": user_message})

        models_to_try = [self.model] + self.fallback_models
        last_error = None

        for model in models_to_try:
            try:
                content = self._call_api(messages, model, temperature, max_tokens)
                if not _is_garbage(content):
                    return content
            except RuntimeError as e:
                last_error = e
                continue

        if last_error:
            raise last_error
        raise RuntimeError("All models returned unusable responses")

    def simplify(self, text: str, simplify_prompt: str) -> str:
        return self.generate(
            user_message=simplify_prompt,
            system_prompt=(
                "You are a text simplification assistant. "
                "Rewrite the given text to be easier to read. "
                "Keep all facts. Use simple words and short sentences."
            ),
            temperature=0.3,
            max_tokens=config.MAX_TOKENS,
        )
