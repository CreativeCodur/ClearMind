"""
ClearMind Topic Drift Detection & Refocus
Detects when a user with ADHD has drifted off their original topic
and gently offers to redirect them.

Research basis:
  - Giri et al. (2026) P17: "[I was] overwhelmed by where to start and
    that overwhelm turns into confirmation of that deeply held belief
    that you're a piece of shit." — Task initiation and sustained focus
    are core ADHD challenges.
  - Giri et al. (2026) P12: "Neurodivergent people are not very good at
    staying on schedule with our basic human needs." — Difficulty
    maintaining focus on the original task.
  - W3C COGA (2021): "The interface should avoid unnecessary interruptions
    and should not present excessive information at once."
  - Glazko et al. (2025): Users need AI that proactively supports focus
    rather than requiring users to self-regulate.

Method:
  Uses TF-IDF cosine similarity to compare the user's latest message
  against their recent conversation history. If similarity drops below
  a threshold, the system flags a potential drift and prepends a gentle
  refocus suggestion to the AI's response.

  This is NOT intrusive — the user can ignore it. Per Tang et al. (2026),
  the system should support user agency, not enforce compliance.
"""

import re
import math
from collections import Counter
from typing import List, Dict, Optional, Tuple

import config


# Common conversational words should not become the subject of a refocus
# notice.  Keep this separate from the TF-IDF tokens: they still help with
# drift detection, but are not useful to show back to the user as a topic.
TOPIC_STOPWORDS = {
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
    'should', 'may', 'might', 'can', 'shall', 'to', 'of', 'in', 'for',
    'on', 'with', 'at', 'by', 'from', 'it', 'its', 'this', 'that', 'these',
    'those', 'i', 'you', 'he', 'she', 'we', 'they', 'me', 'him', 'her',
    'us', 'them', 'my', 'your', 'his', 'our', 'their', 'and', 'but', 'or',
    'not', 'no', 'so', 'if', 'as', 'just', 'about', 'what', 'how', 'when',
    'where', 'why', 'which', 'who', 'whom', 'please', 'help', 'want',
    'need', 'like', 'really', 'also', 'get', 'got', 'make', 'tell', 'give',
}


def tokenize(text: str) -> List[str]:
    """Lowercase and extract alphabetic tokens."""
    return re.findall(r'[a-z]+', text.lower())


def compute_tf(tokens: List[str]) -> Dict[str, float]:
    """Term frequency: count / total tokens."""
    counts = Counter(tokens)
    total = len(tokens) if tokens else 1
    return {word: count / total for word, count in counts.items()}


def compute_idf(documents: List[List[str]]) -> Dict[str, float]:
    """Inverse document frequency across a set of tokenized documents."""
    n_docs = len(documents)
    if n_docs == 0:
        return {}

    # Count how many documents contain each word
    doc_freq = Counter()
    for doc in documents:
        unique_words = set(doc)
        for word in unique_words:
            doc_freq[word] += 1

    return {
        word: math.log((n_docs + 1) / (freq + 1)) + 1
        for word, freq in doc_freq.items()
    }


def tfidf_vector(tokens: List[str], idf: Dict[str, float]) -> Dict[str, float]:
    """Compute TF-IDF vector for a single document."""
    tf = compute_tf(tokens)
    return {word: tf_val * idf.get(word, 1.0) for word, tf_val in tf.items()}


def cosine_similarity(vec_a: Dict[str, float], vec_b: Dict[str, float]) -> float:
    """Cosine similarity between two sparse vectors (dicts)."""
    # Find shared keys
    all_keys = set(vec_a.keys()) | set(vec_b.keys())
    if not all_keys:
        return 0.0

    dot = sum(vec_a.get(k, 0) * vec_b.get(k, 0) for k in all_keys)
    mag_a = math.sqrt(sum(v ** 2 for v in vec_a.values()))
    mag_b = math.sqrt(sum(v ** 2 for v in vec_b.values()))

    if mag_a == 0 or mag_b == 0:
        return 0.0

    return dot / (mag_a * mag_b)


def most_significant_keyword(tokens: List[str], idf: Dict[str, float]) -> Optional[str]:
    """Return the strongest user-mentioned topic keyword.

    Repeated words score higher, while IDF gives more specific words a small
    advantage.  Conversational filler and very short words are excluded so the
    refocus message names the user's actual subject, not a function word.
    """
    candidates = [
        token for token in tokens
        if len(token) > 2 and token not in TOPIC_STOPWORDS
    ]
    if not candidates:
        return None

    counts = Counter(candidates)
    return max(
        counts,
        key=lambda word: (counts[word] * idf.get(word, 1.0), counts[word], len(word)),
    )


class DriftDetector:
    """Tracks conversation history and detects topic drift.

    Usage:
        detector = DriftDetector()

        # After each user message:
        detector.add_message(user_message)
        drift = detector.check_drift()
        if drift.is_drifting:
            # Prepend drift.refocus_message to AI response
    """

    def __init__(self):
        self.messages: List[str] = []
        self.tokenized: List[List[str]] = []

    def add_message(self, message: str) -> None:
        """Add a user message to the conversation history."""
        self.messages.append(message)
        self.tokenized.append(tokenize(message))

    def check_drift(self) -> 'DriftResult':
        """Check if the latest message has drifted from the conversation topic.

        Returns:
            DriftResult with is_drifting flag and optional refocus message.
        """
        n = len(self.messages)

        # Not enough messages to detect drift
        if n < config.MIN_MESSAGES_FOR_DRIFT:
            return DriftResult(is_drifting=False, similarity=1.0)

        # Build the "topic window" = recent messages BEFORE the latest one
        window_start = max(0, n - 1 - config.TOPIC_WINDOW)
        window_docs = self.tokenized[window_start:n - 1]
        latest_doc = self.tokenized[-1]

        if not latest_doc:
            return DriftResult(is_drifting=False, similarity=1.0)

        # Combine window into one document for comparison
        window_combined = []
        for doc in window_docs:
            window_combined.extend(doc)

        if not window_combined:
            return DriftResult(is_drifting=False, similarity=1.0)

        # Compute IDF across both documents
        all_docs = [window_combined, latest_doc]
        idf = compute_idf(all_docs)

        # Compute TF-IDF vectors
        vec_window = tfidf_vector(window_combined, idf)
        vec_latest = tfidf_vector(latest_doc, idf)

        # Cosine similarity
        sim = cosine_similarity(vec_window, vec_latest)

        is_drifting = sim < config.DRIFT_THRESHOLD

        # Build refocus message if drifting
        refocus_msg = None
        if is_drifting:
            # Name one meaningful keyword from the earlier user prompts.
            # A single, specific subject is clearer and less distracting than
            # a list of raw TF-IDF words.
            topic_hint = most_significant_keyword(window_combined, idf)
            if topic_hint is None:
                topic_hint = "that earlier topic"

            # Warm, supportive messages — never clinical or passive-aggressive.
            # Per Giri et al. (2026): neurodivergent users experience
            # rejection sensitive dysphoria; blunt phrasing feels like
            # judgment. Per Barkley (2015) [7]: topic-switching is a
            # natural ADHD behavior, not a mistake to correct.
            import random
            gentle_msgs = [
                (
                    f"No worries at all — just a heads-up that you were "
                    f"exploring {topic_hint} earlier. Want to come back to "
                    f"that, or keep going with this? Either is fine!"
                ),
                (
                    f"Hey, totally okay to switch gears! For reference, "
                    f"you were looking into {topic_hint} before. "
                    f"Happy to help with whatever you need right now."
                ),
                (
                    f"Quick friendly note: your earlier thread was about "
                    f"{topic_hint}. No pressure to go back — just "
                    f"bookmarking it so you don't lose it."
                ),
            ]
            refocus_msg = random.choice(gentle_msgs)

        return DriftResult(
            is_drifting=is_drifting,
            similarity=round(sim, 3),
            refocus_message=refocus_msg,
        )

    def reset(self) -> None:
        """Clear conversation history (e.g., on new topic)."""
        self.messages.clear()
        self.tokenized.clear()

    def get_topic_summary(self) -> str:
        """Return the dominant words from the conversation so far."""
        if not self.tokenized:
            return "(no conversation yet)"

        all_tokens = []
        for doc in self.tokenized:
            all_tokens.extend(doc)

        counts = Counter(all_tokens)
        filtered = {
            word: count for word, count in counts.items()
            if word not in TOPIC_STOPWORDS and len(word) > 2
        }
        top = sorted(filtered.items(), key=lambda x: x[1], reverse=True)[:5]
        return ", ".join(f"{w} ({c})" for w, c in top)


class DriftResult:
    """Result of a drift check."""

    def __init__(
        self,
        is_drifting: bool,
        similarity: float = 1.0,
        refocus_message: Optional[str] = None,
    ):
        self.is_drifting = is_drifting
        self.similarity = similarity
        self.refocus_message = refocus_message

    def __repr__(self):
        return (
            f"DriftResult(drifting={self.is_drifting}, "
            f"sim={self.similarity}, msg={self.refocus_message!r})"
        )
