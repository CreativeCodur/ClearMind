"""
ClearMind Readability Engine
Measures and enforces reading-level constraints on AI responses.

This is the core accessibility module. It does not just score text — it
iteratively rewrites responses that exceed the target reading level.

Research basis:
  - Rello & Baeza-Yates (2017): text presentation significantly affects
    readability for people with dyslexia. Simpler sentence structure and
    familiar vocabulary are essential.
  - W3C COGA (2021): "familiar words, short sentences, clear headings,
    summaries, and small content blocks."
  - Giri et al. (2026) P16: "it is too much new information to keep in
    my working memory" — complex text overloads working memory.
  - Panda et al. (2025): "semantic comprehension delays in people with
    dyslexia" — justifies aggressive readability enforcement.

Metrics used:
  1. Flesch-Kincaid Grade Level (primary) — U.S. school grade needed to
     understand the text. Target: <=6 for dyslexia, <=8 for ADHD.
  2. Flesch Reading Ease (secondary) — 0-100 scale, higher = easier.
     Target: >=70 for dyslexia, >=60 for ADHD.
  3. Sentence length analysis — flags individual sentences that exceed
     the per-mode word limit.
  4. Complex word ratio — percentage of words with 3+ syllables.
"""

import re
import math
from dataclasses import dataclass, field
from typing import List, Tuple

import config


# ─── Syllable counter ───────────────────────────────────────────────────────────

def count_syllables(word: str) -> int:
    """Count syllables in a word using a refined heuristic.

    Uses the vowel-cluster method with corrections for silent-e,
    common suffixes (-le, -ed, -es), and guarantees at least 1.
    """
    word = word.lower().strip()
    if not word:
        return 0

    # Remove non-alpha
    word = re.sub(r'[^a-z]', '', word)
    if not word:
        return 0

    # Special short words
    if len(word) <= 2:
        return 1

    count = 0
    vowels = "aeiouy"
    prev_was_vowel = False

    for char in word:
        is_vowel = char in vowels
        if is_vowel and not prev_was_vowel:
            count += 1
        prev_was_vowel = is_vowel

    # Adjustments
    # Silent 'e' at the end
    if word.endswith('e') and not word.endswith(('le', 'ce', 'ge')):
        count -= 1

    # '-ed' ending (usually not a separate syllable unless preceded by t/d)
    if word.endswith('ed') and len(word) > 3:
        if word[-3] not in ('t', 'd'):
            count -= 1

    # '-le' ending IS a syllable (e.g., "table", "simple")
    if word.endswith('le') and len(word) > 2 and word[-3] not in vowels:
        count += 1

    # Guarantee at least 1
    return max(count, 1)


# ─── Sentence splitter ──────────────────────────────────────────────────────────

def split_sentences(text: str) -> List[str]:
    """Split text into sentences. Handles abbreviations and decimals."""
    # Split on sentence-ending punctuation followed by whitespace or end
    raw = re.split(r'(?<=[.!?])\s+', text.strip())
    # Filter empty strings
    return [s.strip() for s in raw if s.strip()]


def get_words(text: str) -> List[str]:
    """Extract words from text (alpha characters only)."""
    return [w for w in re.findall(r"[a-zA-Z']+", text) if len(w) > 0]


# ─── Readability scores ────────────────────────────────────────────────────────

@dataclass
class ReadabilityReport:
    """Complete readability analysis of a text."""
    text: str
    fk_grade: float              # Flesch-Kincaid Grade Level
    reading_ease: float          # Flesch Reading Ease
    avg_sentence_length: float   # words per sentence
    avg_syllables_per_word: float
    complex_word_ratio: float    # fraction of words with 3+ syllables
    total_words: int
    total_sentences: int
    total_syllables: int
    long_sentences: List[Tuple[int, str, int]] = field(default_factory=list)
    # (index, sentence_text, word_count) for sentences exceeding threshold
    passes_grade: bool = False
    passes_ease: bool = False
    passes_overall: bool = False


def analyze_readability(text: str, mode: str = "standard") -> ReadabilityReport:
    """Run full readability analysis on the given text.

    Args:
        text: The text to analyze.
        mode: ClearMind mode — determines thresholds.

    Returns:
        ReadabilityReport with all metrics and pass/fail status.
    """
    sentences = split_sentences(text)
    if not sentences:
        return ReadabilityReport(
            text=text, fk_grade=0, reading_ease=100,
            avg_sentence_length=0, avg_syllables_per_word=0,
            complex_word_ratio=0, total_words=0, total_sentences=0,
            total_syllables=0, passes_grade=True, passes_ease=True,
            passes_overall=True,
        )

    total_sentences = len(sentences)
    all_words = get_words(text)
    total_words = len(all_words) if all_words else 1
    total_syllables = sum(count_syllables(w) for w in all_words)

    # Core metrics
    avg_sentence_length = total_words / max(total_sentences, 1)
    avg_syllables_per_word = total_syllables / max(total_words, 1)

    # Flesch-Kincaid Grade Level
    fk_grade = (
        0.39 * avg_sentence_length
        + 11.8 * avg_syllables_per_word
        - 15.59
    )
    fk_grade = round(max(fk_grade, 0), 2)

    # Flesch Reading Ease
    reading_ease = (
        206.835
        - 1.015 * avg_sentence_length
        - 84.6 * avg_syllables_per_word
    )
    reading_ease = round(min(max(reading_ease, 0), 100), 2)

    # Complex word ratio (3+ syllables)
    complex_words = [w for w in all_words if count_syllables(w) >= 3]
    complex_word_ratio = round(len(complex_words) / max(total_words, 1), 3)

    # Flag long sentences
    max_words = config.MAX_SENTENCE_WORDS.get(mode, 35)
    long_sentences = []
    for i, sent in enumerate(sentences):
        wc = len(get_words(sent))
        if wc > max_words:
            long_sentences.append((i, sent, wc))

    # Pass/fail
    targets = config.READABILITY_TARGETS.get(mode, config.READABILITY_TARGETS["standard"])
    passes_grade = fk_grade <= targets["max_fk_grade"]
    passes_ease = reading_ease >= targets["min_reading_ease"]
    passes_overall = passes_grade and passes_ease

    return ReadabilityReport(
        text=text,
        fk_grade=fk_grade,
        reading_ease=reading_ease,
        avg_sentence_length=round(avg_sentence_length, 1),
        avg_syllables_per_word=round(avg_syllables_per_word, 2),
        complex_word_ratio=complex_word_ratio,
        total_words=total_words,
        total_sentences=total_sentences,
        total_syllables=total_syllables,
        long_sentences=long_sentences,
        passes_grade=passes_grade,
        passes_ease=passes_ease,
        passes_overall=passes_overall,
    )


# ─── Simplification prompt builder ─────────────────────────────────────────────

def build_simplify_prompt(text: str, report: ReadabilityReport, mode: str) -> str:
    """Build a prompt that asks the AI to simplify its own response.

    This is used when the initial response exceeds readability targets.
    The prompt includes the specific metrics that failed so the AI can
    target its simplification.
    """
    targets = config.READABILITY_TARGETS.get(mode, config.READABILITY_TARGETS["standard"])
    max_words = config.MAX_SENTENCE_WORDS.get(mode, 35)

    issues = []
    if not report.passes_grade:
        issues.append(
            f"- Reading level is grade {report.fk_grade} but must be "
            f"grade {targets['max_fk_grade']} or lower."
        )
    if not report.passes_ease:
        issues.append(
            f"- Reading ease score is {report.reading_ease} but must be "
            f"{targets['min_reading_ease']} or higher."
        )
    if report.long_sentences:
        issues.append(
            f"- {len(report.long_sentences)} sentence(s) exceed the "
            f"{max_words}-word limit."
        )
    if report.complex_word_ratio > 0.15:
        issues.append(
            f"- {report.complex_word_ratio:.0%} of words have 3+ syllables. "
            f"Replace complex words with simpler ones."
        )

    issue_text = "\n".join(issues)

    return (
        "The following response is too difficult to read. "
        "Rewrite it to fix these specific problems:\n"
        f"{issue_text}\n\n"
        "Rules for your rewrite:\n"
        f"- Maximum {max_words} words per sentence.\n"
        "- Use common, everyday words.\n"
        "- Replace any word with 3+ syllables with a simpler synonym "
        "  if one exists.\n"
        "- Keep all the important information. Do not remove facts.\n"
        "- Do not add new information.\n"
        "- Do not start with phrases like 'Here is a simpler version.'\n"
        "  Just give the rewritten text.\n\n"
        "Text to rewrite:\n"
        f"{text}"
    )


def needs_simplification(report: ReadabilityReport) -> bool:
    """Check if text needs another simplification pass."""
    return not report.passes_overall


def get_readability_summary(report: ReadabilityReport, mode: str) -> str:
    """Return a human-readable summary of the readability analysis.

    Useful for logging and debugging.
    """
    targets = config.READABILITY_TARGETS.get(mode, config.READABILITY_TARGETS["standard"])
    status = "PASS" if report.passes_overall else "FAIL"

    lines = [
        f"Readability [{status}] (mode: {mode})",
        f"  FK Grade:       {report.fk_grade} (target: <={targets['max_fk_grade']})",
        f"  Reading Ease:   {report.reading_ease} (target: >={targets['min_reading_ease']})",
        f"  Avg sent len:   {report.avg_sentence_length} words",
        f"  Avg syl/word:   {report.avg_syllables_per_word}",
        f"  Complex ratio:  {report.complex_word_ratio:.1%}",
        f"  Total:          {report.total_words} words, {report.total_sentences} sentences",
    ]
    if report.long_sentences:
        lines.append(f"  Long sentences: {len(report.long_sentences)}")
        for idx, sent, wc in report.long_sentences[:3]:
            preview = sent[:60] + "..." if len(sent) > 60 else sent
            lines.append(f"    [{idx}] ({wc} words) {preview}")

    return "\n".join(lines)
