"""
ClearMind Configuration
All constants, thresholds, and default settings for the adaptive AI chat interface.

Design rationale:
  - Readability targets based on Rello & Baeza-Yates (2017) and W3C COGA (2021)
  - Spacing values from Rello & Baeza-Yates (2017): +7-14% character spacing
  - Font sizes from Goodman et al. (2022): 18pt minimum for dyslexia
  - Chunk sizes from W3C COGA (2021): small content blocks, progressive disclosure
"""

# ─── API ────────────────────────────────────────────────────────────────────────
# Toggle: "claude" or "openrouter"
API_PROVIDER = "claude"

# OpenRouter (GPT-OSS-20B) settings
MODEL = "openai/gpt-oss-20b"
FALLBACK_MODELS = []
API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Claude settings
CLAUDE_MODEL = "claude-haiku-4-5-20251001"

MAX_TOKENS = 4096
TEMPERATURE = 0.7

# ─── Modes ──────────────────────────────────────────────────────────────────────
MODES = ["dyslexia", "adhd", "combined"]
DEFAULT_MODE = "combined"

# ─── Readability targets ────────────────────────────────────────────────────────
# Flesch-Kincaid Grade Level: lower = easier to read
# Grade 6-8 is plain language (CDC recommendation); we target <=8 for accessibility
READABILITY_TARGETS = {
    "standard":  {"max_fk_grade": 12.0, "min_reading_ease": 50.0},
    "dyslexia":  {"max_fk_grade": 6.0,  "min_reading_ease": 70.0},
    "adhd":      {"max_fk_grade": 8.0,  "min_reading_ease": 60.0},
    "combined":  {"max_fk_grade": 6.0,  "min_reading_ease": 70.0},
}

# Maximum number of simplification passes before returning best attempt
MAX_SIMPLIFY_PASSES = 3

# Per-sentence thresholds
MAX_SENTENCE_WORDS = {
    "standard":  35,
    "dyslexia":  15,
    "adhd":      20,
    "combined":  15,
}

# ─── Formatter settings ─────────────────────────────────────────────────────────
# Chunk = number of sentences per visual block
CHUNK_SIZES = {
    "standard":  10,
    "dyslexia":  3,
    "adhd":      4,
    "combined":  3,
}

# Whether to prepend a TL;DR summary
TLDR_ENABLED = {
    "standard":  False,
    "dyslexia":  True,
    "adhd":      True,
    "combined":  True,
}

# ─── Refocus / drift detection (ADHD) ───────────────────────────────────────────
# Cosine similarity threshold: below this = user has drifted off-topic
DRIFT_THRESHOLD = 0.5
# Number of recent messages to consider as the "topic window"
TOPIC_WINDOW = 5
# Minimum messages before drift detection activates
MIN_MESSAGES_FOR_DRIFT = 1

# ─── Frontend display (CSS values) ──────────────────────────────────────────────
# Based on Rello & Baeza-Yates (2017) and Goodman et al. (2022)
DISPLAY_SETTINGS = {
    "standard": {
        "font_family": "'Segoe UI', Tahoma, Geneva, Verdana, sans-serif",
        "font_size": "16px",
        "line_height": "1.5",
        "letter_spacing": "normal",
        "word_spacing": "normal",
        "max_line_width": "75ch",
    },
    "dyslexia": {
        "font_family": "'OpenDyslexic', 'Comic Sans MS', sans-serif",
        "font_size": "18px",
        "line_height": "2.0",
        "letter_spacing": "0.12em",
        "word_spacing": "0.2em",
        "max_line_width": "60ch",
    },
    "adhd": {
        "font_family": "'Segoe UI', Tahoma, Geneva, Verdana, sans-serif",
        "font_size": "17px",
        "line_height": "1.7",
        "letter_spacing": "0.02em",
        "word_spacing": "normal",
        "max_line_width": "70ch",
    },
    "combined": {
        "font_family": "'OpenDyslexic', 'Comic Sans MS', sans-serif",
        "font_size": "18px",
        "line_height": "2.0",
        "letter_spacing": "0.12em",
        "word_spacing": "0.2em",
        "max_line_width": "60ch",
    },
}

# ─── Flask ──────────────────────────────────────────────────────────────────────
FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5000
DEBUG = True
