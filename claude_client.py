"""
ClearMind Claude API Client
Direct Anthropic SDK wrapper for Claude Haiku 4.5.
"""

import os
import re
from typing import Optional, List, Dict
from collections import Counter

import anthropic
import config


GARBAGE_PATTERNS = [
    "user safety:", "safety:", "content policy", "i cannot",
    "as an ai language model", "classification:",
]

THOUGHT_PATTERNS = [
    r'<think>.*?</think>',
    r'<thinking>.*?</thinking>',
    r'\*\*Thinking\*\*:.*?\n',
]

REPETITION_THRESHOLD = 0.3


def _is_garbage(text: str) -> bool:
    stripped = text.strip().lower()
    if len(stripped.split()) < 4:
        return True
    return any(stripped.startswith(p) for p in GARBAGE_PATTERNS)


def _sanitize_output(text: str) -> str:
    for pattern in THOUGHT_PATTERNS:
        text = re.sub(pattern, '', text, flags=re.DOTALL | re.IGNORECASE)

    text = text.replace('<unk>', '')

    meta_patterns = [
        r"(?:^|\n)\s*Let me re-read",
        r"(?:^|\n)\s*Let's check the word count",
        r"(?:^|\n)\s*Let me count",
    ]
    for pat in meta_patterns:
        match = re.search(pat, text, flags=re.IGNORECASE)
        if match:
            text = text[:match.start()]
            break

    tldr_positions = [m.start() for m in re.finditer(r'TL;?DR', text, re.IGNORECASE)]
    if len(tldr_positions) >= 2:
        text = text[:tldr_positions[1]]

    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


class ClaudeClient:
    """Anthropic SDK wrapper for ClearMind (Claude Haiku 4.5)."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

        if not self.api_key:
            self.api_key = self._load_from_dotenv()

        if not self.api_key:
            raise ValueError(
                "No API key found. Set ANTHROPIC_API_KEY in your .env file."
            )

        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = config.CLAUDE_MODEL

    def _load_from_dotenv(self) -> Optional[str]:
        env_path = os.path.join(os.path.dirname(__file__), '.env')
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('ANTHROPIC_API_KEY='):
                        return line.split('=', 1)[1].strip().strip('"').strip("'")
        return None

    def generate(
        self,
        user_message: str,
        system_prompt: str = "",
        conversation_history: Optional[List[Dict]] = None,
        temperature: float = config.TEMPERATURE,
        max_tokens: int = config.MAX_TOKENS,
    ) -> str:
        messages = []

        if conversation_history:
            for msg in conversation_history:
                role = "assistant" if msg["role"] == "model" else "user"
                messages.append({"role": role, "content": msg["text"]})

        messages.append({"role": "user", "content": user_message})

        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        try:
            response = self.client.messages.create(**kwargs)
            content = response.content[0].text

            if not content or not content.strip():
                raise RuntimeError("Empty response from Claude")

            if _is_garbage(content):
                raise RuntimeError("Garbage response from Claude")

            return _sanitize_output(content)

        except anthropic.APIError as e:
            raise RuntimeError(f"Claude API error: {e}")

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
