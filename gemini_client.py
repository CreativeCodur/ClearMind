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

# Patterns that indicate the model leaked its chain-of-thought
# or internal reasoning (common with Gemini flash models)
THOUGHT_PATTERNS = [
    r'<think>.*?</think>',        # explicit think tags
    r'<thinking>.*?</thinking>',  # alternative think tags
    r'\*\*Thinking\*\*:.*?\n',    # markdown-style thinking
    r'(?:^|\n)(?:Step \d+:|Reasoning:).*?(?=\n[A-Z]|\Z)',  # reasoning prefixes
]

# Minimum unique-phrase ratio before we flag as repetition loop
REPETITION_THRESHOLD = 0.3


def _is_garbage(text: str) -> bool:
    stripped = text.strip().lower()
    if len(stripped.split()) < 4:
        return True
    return any(stripped.startswith(p) for p in GARBAGE_PATTERNS)


def _sanitize_output(text: str) -> str:
    """Clean model output of thought-process leaks and repetition loops.

    Addresses multiple observed failure modes from free-tier models:
      1. <think>/<thinking> tag leaks
      2. <unk> token spam (garbage tokens from tokenizer)
      3. Model re-reading its own system prompt / constraints mid-response
      4. Line-level and phrase-level repetition loops

    Research basis:
      - Benchmarking study (Malhotra, 2026): observed models leaking
        chain-of-thought tokens, <unk> spam, and entering repetition
        loops on free-tier API calls.
    """
    import re

    # 1. Strip <unk> tokens — free-tier models emit these as garbage
    text = text.replace('<unk>', '')

    # 2. Strip chain-of-thought / thinking blocks
    for pattern in THOUGHT_PATTERNS:
        text = re.sub(pattern, '', text, flags=re.DOTALL | re.IGNORECASE)

    # 3. Truncate at meta-reasoning leaks
    # The model sometimes finishes its answer, then starts re-reading
    # its constraints or re-deriving the response. Cut at the first sign.
    meta_patterns = [
        r"(?:^|\n)\s*Let me re-read",
        r"(?:^|\n)\s*Let's check the word count",
        r"(?:^|\n)\s*Constraints:\s*\n",
        r"(?:^|\n)\s*Let me count",
        r"(?:^|\n)\s*Wait,?\s+(?:the|I|we|let)",
        r"(?:^|\n)\s*Now let's (?:check|make sure|verify|structure)",
        r"(?:^|\n)\s*(?:Hmm|OK|Okay),?\s+(?:so|let|the|I)",
        r"(?:^|\n)\s*Let me (?:re-?do|re-?write|re-?think|re-?structure|verify)",
        r"(?:^|\n)\s*\d+\.\s+\"[^\"]+\"\s*\(\d+\s*words?\)",  # word-count checking like: 1. "sentence" (6 words)
    ]
    for pat in meta_patterns:
        match = re.search(pat, text, flags=re.IGNORECASE)
        if match:
            text = text[:match.start()]
            break

    # 4. If the response contains a duplicate TL;DR, keep only up to the second one
    tldr_positions = [m.start() for m in re.finditer(r'TL;?DR', text, re.IGNORECASE)]
    if len(tldr_positions) >= 2:
        text = text[:tldr_positions[1]]

    # 5. Detect and truncate repetition loops
    lines = text.split('\n')
    cleaned_lines = []
    seen_lines = {}
    consecutive_repeats = 0

    for line in lines:
        stripped = line.strip().lower()
        if not stripped:
            cleaned_lines.append(line)
            consecutive_repeats = 0
            continue

        if stripped in seen_lines and len(stripped) < 100:
            consecutive_repeats += 1
            if consecutive_repeats >= 3:
                continue
        else:
            consecutive_repeats = 0

        seen_lines[stripped] = True
        cleaned_lines.append(line)

    text = '\n'.join(cleaned_lines)

    # 6. Catch short-phrase repetition within a single line
    words = text.split()
    if len(words) > 20:
        for n in (3, 4, 5):
            trigrams = [' '.join(words[i:i+n]) for i in range(len(words) - n + 1)]
            from collections import Counter
            counts = Counter(trigrams)
            for phrase, count in counts.items():
                if count >= 4:
                    parts = text.split(phrase)
                    if len(parts) > 3:
                        text = phrase.join(parts[:3]) + parts[-1]
                    break

    # 7. Clean up leftover whitespace from all the stripping
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


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
                    content = _sanitize_output(content)
                    if content and not _is_garbage(content):
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
