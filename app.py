"""
ClearMind Flask Server
Main application server that orchestrates the full adaptive pipeline:

  User message
    -> Mode-specific system prompt (prompts.py)
    -> Gemini API call (gemini_client.py)
    -> Readability check + iterative simplification (readability.py)
    -> Topic drift detection (refocus.py, ADHD/combined only)
    -> Response formatting with TL;DR + chunking (formatter.py)
    -> HTML response to frontend

Research basis (full pipeline justification):
  - Glazko et al. (2025): current AI places "the burden of adaptation
    onto 'power users' themselves." This pipeline removes that burden
    by adapting automatically.
  - Silverman et al. (2025): "There is a gap between technology
    development and user experience as it relates to disability needs."
    This pipeline is designed to close that gap for ADHD and dyslexia.
"""

import os
import logging
import secrets
import html
from flask import Flask, request, jsonify, send_from_directory, session
from flask_cors import CORS

import config
from prompts import get_system_prompt
from readability import (
    analyze_readability,
    build_simplify_prompt,
    needs_simplification,
    get_readability_summary,
)
from refocus import DriftDetector
from formatter import format_response, strip_format_markers, to_html
from gemini_client import GeminiClient
from database import (
    authenticate_user,
    create_user,
    get_prompts,
    initialize_database,
    save_prompt,
)

# ─── Setup ──────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("clearmind")

app = Flask(__name__, static_folder="static")
app.config.update(
    SECRET_KEY=os.environ.get("FLASK_SECRET_KEY", secrets.token_urlsafe(32)),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
CORS(app)
initialize_database()

# Initialize Gemini client (will fail fast if no API key)
try:
    gemini = GeminiClient()
    logger.info("Gemini client initialized successfully.")
except ValueError as e:
    logger.warning(f"Gemini client not initialized: {e}")
    gemini = None

# Per-session drift detectors (keyed by session ID)
drift_detectors = {}

# Per-session conversation history
conversations = {}


# ─── Pipeline ───────────────────────────────────────────────────────────────────

def process_message(user_message: str, mode: str, session_id: str) -> dict:
    """Run the full ClearMind pipeline on a user message.

    Args:
        user_message: What the user typed.
        mode: One of 'standard', 'dyslexia', 'adhd', 'combined'.
        session_id: Unique session identifier.

    Returns:
        Dict with 'html', 'readability', 'drift', and 'raw' keys.
    """
    if gemini is None:
        return {
            "html": '<div class="clearmind-chunk">Error: No API key configured. '
                    'Set GEMINI_API_KEY in your .env file.</div>',
            "readability": None,
            "drift": None,
            "raw": "",
        }

    # --- Step 1: Get system prompt for this mode ---
    system_prompt = get_system_prompt(mode)

    # --- Step 2: Get conversation history ---
    history = conversations.get(session_id, [])

    # --- Step 3: Call Gemini ---
    logger.info(f"[{session_id}] Mode={mode}, sending to Gemini...")
    try:
        raw_response = gemini.generate(
            user_message=user_message,
            system_prompt=system_prompt,
            conversation_history=history[-10:],
        )
    except RuntimeError as e:
        error_str = str(e)
        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
            return {
                "html": '<div class="clearmind-chunk">The API is temporarily '
                        'rate-limited. Please wait a minute and try again.</div>',
                "readability": None,
                "drift": None,
                "raw": "",
            }
        return {
            "html": f'<div class="clearmind-chunk">API error: {html.escape(error_str[:200])}</div>',
            "readability": None,
            "drift": None,
            "raw": "",
        }
    logger.info(f"[{session_id}] Got response ({len(raw_response)} chars)")

    # --- Step 4: Readability check + iterative simplification ---
    current_text = raw_response
    report = analyze_readability(current_text, mode)
    pass_num = 0

    while needs_simplification(report) and pass_num < config.MAX_SIMPLIFY_PASSES and report.total_words >= 30:
        pass_num += 1
        logger.info(
            f"[{session_id}] Readability FAIL (pass {pass_num}): "
            f"grade={report.fk_grade}, ease={report.reading_ease}"
        )
        simplify_prompt = build_simplify_prompt(current_text, report, mode)
        try:
            current_text = gemini.simplify(current_text, simplify_prompt)
        except RuntimeError:
            logger.warning(f"[{session_id}] Simplification pass {pass_num} failed, using best effort")
            break
        report = analyze_readability(current_text, mode)

    logger.info(
        f"[{session_id}] Readability final: "
        f"grade={report.fk_grade}, ease={report.reading_ease}, "
        f"pass={'YES' if report.passes_overall else 'NO (best effort)'}"
    )

    # --- Step 5: Topic drift detection (ADHD and combined only) ---
    drift_info = None
    if mode in ("adhd", "combined"):
        if session_id not in drift_detectors:
            drift_detectors[session_id] = DriftDetector()

        detector = drift_detectors[session_id]
        detector.add_message(user_message)
        drift_result = detector.check_drift()

        if drift_result.is_drifting:
            drift_info = {
                "is_drifting": True,
                "similarity": drift_result.similarity,
                "message": drift_result.refocus_message,
            }
            logger.info(
                f"[{session_id}] Drift detected (sim={drift_result.similarity})"
            )
        else:
            drift_info = {
                "is_drifting": False,
                "similarity": drift_result.similarity,
            }

    # --- Step 6: Format response ---
    formatted = format_response(current_text, mode)
    html = to_html(formatted, mode)

    # Prepend drift notice if detected
    if drift_info and drift_info.get("is_drifting"):
        drift_html = (
            f'<div class="clearmind-drift-notice">'
            f'{drift_info["message"]}'
            f'</div>'
        )
        html = drift_html + html

    # --- Step 7: Update conversation history ---
    if session_id not in conversations:
        conversations[session_id] = []
    conversations[session_id].append({"role": "user", "text": user_message})
    conversations[session_id].append({"role": "model", "text": current_text})

    # Readability summary for debug/display
    readability_info = {
        "fk_grade": report.fk_grade,
        "reading_ease": report.reading_ease,
        "passes": report.passes_overall,
        "simplification_passes": pass_num,
        "avg_sentence_length": report.avg_sentence_length,
        "complex_word_ratio": report.complex_word_ratio,
    }

    return {
        "html": html,
        "readability": readability_info,
        "drift": drift_info,
        "raw": current_text,
    }


# ─── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the main chat interface."""
    return send_from_directory(".", "index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    """Main chat endpoint.

    Expects JSON:
        {
            "message": "user's message",
            "mode": "standard|dyslexia|adhd|combined",
            "session_id": "unique-id"
        }

    Returns JSON:
        {
            "html": "formatted HTML response",
            "readability": {...metrics...},
            "drift": {...or null...},
            "raw": "plain text response"
        }
    """
    data = request.get_json(silent=True)
    if not data or "message" not in data:
        return jsonify({"error": "Missing 'message' field"}), 400

    user_message = data["message"]
    mode = data.get("mode", config.DEFAULT_MODE)
    session_id = data.get("session_id", "default")

    if not isinstance(user_message, str) or not user_message.strip():
        return jsonify({"error": "'message' must be a non-empty string"}), 400
    if len(user_message) > 10000:
        return jsonify({"error": "'message' must be 10,000 characters or less"}), 400
    if not isinstance(mode, str) or not isinstance(session_id, str):
        return jsonify({"error": "'mode' and 'session_id' must be strings"}), 400
    if len(session_id) > 200:
        return jsonify({"error": "'session_id' must be 200 characters or less"}), 400
    if mode not in config.MODES:
        return jsonify({"error": f"Invalid mode: {mode}"}), 400

    user_id = session.get("user_id")
    if user_id is not None:
        save_prompt(user_id, session_id, user_message)

    result = process_message(user_message, mode, session_id)
    return jsonify(result)


@app.route("/api/reset", methods=["POST"])
def reset_session():
    """Reset conversation history and drift detector for a session."""
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id", "default")
    if not isinstance(session_id, str) or len(session_id) > 200:
        return jsonify({"error": "'session_id' must be a string of 200 characters or less"}), 400

    conversations.pop(session_id, None)
    drift_detectors.pop(session_id, None)

    return jsonify({"status": "reset", "session_id": session_id})


@app.route("/api/settings", methods=["GET"])
def get_settings():
    """Return display settings for all modes (used by frontend CSS)."""
    return jsonify(config.DISPLAY_SETTINGS)


def current_user() -> dict | None:
    """Return the safe account fields stored in the signed session."""
    user_id = session.get("user_id")
    if user_id is None:
        return None
    return {"id": user_id, "name": session.get("user_name"), "email": session.get("user_email")}


@app.route("/api/auth/signup", methods=["POST"])
def signup():
    data = request.get_json(silent=True) or {}
    name, email, password = data.get("name"), data.get("email"), data.get("password")
    if not all(isinstance(value, str) for value in (name, email, password)):
        return jsonify({"error": "Name, email, and password must be strings."}), 400
    try:
        user = create_user(name, email, password)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    session.clear()
    session.update(user_id=user["id"], user_name=user["name"], user_email=user["email"])
    return jsonify({"user": user}), 201


@app.route("/api/auth/signin", methods=["POST"])
def signin():
    data = request.get_json(silent=True) or {}
    email, password = data.get("email"), data.get("password")
    if not isinstance(email, str) or not isinstance(password, str):
        return jsonify({"error": "Email and password must be strings."}), 400
    user = authenticate_user(email, password)
    if user is None:
        return jsonify({"error": "Email or password is incorrect."}), 401
    session.clear()
    session.update(user_id=user["id"], user_name=user["name"], user_email=user["email"])
    return jsonify({"user": user})


@app.route("/api/auth/signout", methods=["POST"])
def signout():
    session.clear()
    return jsonify({"status": "signed_out"})


@app.route("/api/auth/me", methods=["GET"])
def account():
    return jsonify({"user": current_user()})


@app.route("/api/history", methods=["GET"])
def prompt_history():
    user = current_user()
    if user is None:
        return jsonify({"error": "Sign in to view saved prompt history."}), 401
    return jsonify({"prompts": get_prompts(user["id"])})


# ─── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=config.DEBUG,
    )
