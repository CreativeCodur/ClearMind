"""
ClearMind Response Formatter
Structures AI responses for maximum cognitive accessibility:
  - TL;DR-first layout for ADHD and combined modes
  - Chunked paragraphs to reduce visual overload
  - Progressive disclosure via collapsible sections (frontend renders)

Research basis:
  - W3C COGA (2021): progressive disclosure, small content blocks,
    summaries, and "not present excessive information at once."
  - Gunawardana et al. (2025): "Participant feedback specifically favored
    progressive disclosure and clearer orientation."
  - Giri et al. (2026) P16: working memory difficulties make dense text
    inaccessible — chunking directly addresses this.
  - Goodman et al. (2022): "several rewrite choices rather than one
    imposed answer" — formatting should clarify, not restrict.
"""

import re
from typing import List, Optional

import config
import markdown
from readability import split_sentences


def format_response(text: str, mode: str) -> str:
    """Apply mode-specific formatting to an AI response.

    Pipeline:
      1. Extract or detect existing TL;DR
      2. Chunk the body into digestible blocks
      3. Assemble final output with markers for the frontend

    Args:
        text: Raw AI response text.
        mode: ClearMind mode.

    Returns:
        Formatted text with structural markers.
    """
    # Step 1: Handle TL;DR
    tldr, body = extract_tldr(text)

    if config.TLDR_ENABLED.get(mode, False) and not tldr:
        # Generate a TL;DR from the first sentence
        sentences = split_sentences(body)
        if sentences:
            tldr = sentences[0]

    # Step 2: Chunk the body
    chunk_size = config.CHUNK_SIZES.get(mode, 10)
    chunks = chunk_text(body, chunk_size)

    # Step 3: Assemble
    parts = []

    if tldr:
        parts.append(f"[TLDR]{tldr}[/TLDR]")
        parts.append("")  # blank line separator

    for i, chunk in enumerate(chunks):
        parts.append(f"[CHUNK]{chunk}[/CHUNK]")

    return "\n".join(parts)


def extract_tldr(text: str) -> tuple:
    """Extract TL;DR from text if present.

    Looks for patterns like:
      - "TL;DR: ..."
      - "TLDR: ..."
      - "In short: ..."
      - "Summary: ..."

    Returns:
        (tldr_text, remaining_body) — tldr_text is None if not found.
    """
    raw = text.strip()
    prefix_match = re.match(
        r'^(?:TL;?DR|TLDR|In short|Summary)\s*[:\-]?\s*(.*)',
        raw,
        re.IGNORECASE | re.DOTALL,
    )

    if prefix_match:
        remainder = prefix_match.group(1).strip()

        # If there is an explicit paragraph break, separate TL;DR from body.
        if '\n\n' in remainder:
            tldr, body = remainder.split('\n\n', 1)
            return tldr.strip(), body.strip()

        # If the next line starts a new sentence, use the first line as TL;DR.
        if '\n' in remainder:
            first, rest = remainder.split('\n', 1)
            if rest.strip() and re.match(r'^[A-Z]', rest.strip()):
                return first.strip(), rest.strip()

        # Otherwise, use the first sentence as TL;DR and keep the rest as body.
        sentences = split_sentences(remainder)
        if sentences:
            tldr = sentences[0].strip()
            body = remainder[len(tldr):].strip()
            return tldr, body

    return None, text


def chunk_text(text: str, sentences_per_chunk: int) -> List[str]:
    """Split text into chunks of N sentences each.

    Preserves existing paragraph breaks where possible. If the text
    already has short paragraphs, those are kept as-is.

    Args:
        text: Body text to chunk.
        sentences_per_chunk: Target sentences per chunk.

    Returns:
        List of chunk strings.
    """
    if not text.strip():
        return [text]

    # First, respect existing paragraph breaks
    paragraphs = re.split(r'\n\s*\n', text.strip())

    chunks = []
    for para in paragraphs:
        sentences = split_sentences(para)

        if len(sentences) <= sentences_per_chunk:
            # Paragraph is already small enough
            chunks.append(para.strip())
        else:
            # Split this paragraph into smaller chunks
            for i in range(0, len(sentences), sentences_per_chunk):
                chunk_sents = sentences[i:i + sentences_per_chunk]
                chunks.append(' '.join(chunk_sents))

    return chunks


def strip_format_markers(text: str) -> str:
    """Remove [TLDR], [CHUNK] markers — returns plain text.

    Useful for readability analysis which should operate on raw text.
    """
    text = re.sub(r'\[/?TLDR\]', '', text)
    text = re.sub(r'\[/?CHUNK\]', '', text)
    return text.strip()


def convert_markdown(text: str) -> str:
    """Convert markdown source into HTML."""
    return markdown.markdown(
        text,
        extensions=['extra', 'sane_lists', 'nl2br'],
        output_format='html5',
    )


def to_html(formatted_text: str, mode: str) -> str:
    """Convert formatted text with markers into HTML for the frontend.

    This is called server-side before sending to the client.

    Args:
        formatted_text: Text with [TLDR] and [CHUNK] markers.
        mode: ClearMind mode (affects CSS classes).

    Returns:
        HTML string ready for insertion into the chat UI.
    """
    html_parts = []

    # Process TL;DR
    tldr_match = re.search(r'\[TLDR\](.*?)\[/TLDR\]', formatted_text, re.DOTALL)
    if tldr_match:
        tldr_text = tldr_match.group(1).strip()
        tldr_html = convert_markdown(tldr_text)
        html_parts.append(
            f'<div class="clearmind-tldr">'
            f'<strong>TL;DR:</strong> {tldr_html}'
            f'</div>'
        )

    # Process chunks
    chunk_matches = re.findall(r'\[CHUNK\](.*?)\[/CHUNK\]', formatted_text, re.DOTALL)
    for i, chunk in enumerate(chunk_matches):
        chunk = chunk.strip()
        if not chunk:
            continue
        chunk_html = convert_markdown(chunk)
        html_parts.append(
            f'<div class="clearmind-chunk" data-chunk="{i}">'
            f'{chunk_html}'
            f'</div>'
        )

    # If no markers found, return as plain paragraph
    if not html_parts:
        return f'<div class="clearmind-chunk">{formatted_text}</div>'

    return '\n'.join(html_parts)
