"""
src/vision.py — user-uploaded image understanding via Google Gemini (the only
vision provider available to this project; see the provider note below).

The rest of this project runs on Groq's `openai/gpt-oss-120b` (D27), which is
TEXT-ONLY -- it cannot see images. So when a user uploads a photo (a swollen
knee, a surgical incision, exercise form), this module makes one separate call
to a natively-multimodal model to turn that image into a factual text
description, and that description is then prepended to the user's question
before it enters the normal orchestrator pipeline.

Provider note (D18): this is the one place the project calls something other
than Groq. Groq was checked first to keep the stack single-provider, but a
live query of the account's `/v1/models` returned NO vision-capable model at
all (only text, TTS, and Whisper models) -- Llama 4 Scout/Maverick are not
available on this key, and every text model rejects image content outright.
Google AI Studio's free tier does support vision, needs no credit card, and
is used ONLY for this single per-upload call; routing, all four specialists,
and synthesis remain entirely on Groq.

Why a description rather than passing the image to the specialists: every
specialist answer in this system is grounded in its own retrieved corpus
(§7.1). Feeding raw pixels to four agents would bypass that. Converting the
image to text once, up front, keeps the existing grounding/routing/synthesis
architecture completely intact -- the image just becomes richer context on the
question.

Safety posture (this is health-adjacent software, per §7):
* The vision prompt asks ONLY for neutral visual description -- no diagnosis,
  no severity judgement, no treatment advice. Diagnosis stays with the
  grounded specialists and the RED_FLAG gate, exactly as before.
* Description text flows back through the normal router, so a photo described
  as e.g. "redness and yellow drainage at an incision" can still trip
  RED_FLAG's deterministic regex and short-circuit to the safety response.
* Never raises: on any failure (no key, rate limit, unsupported file) it
  returns an error string in the result dict, matching consult()'s convention
  so a broken upload can never crash the app.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Gemini's flash alias -- deliberately the "-latest" alias rather than a
# pinned version, because Google retires specific Gemini versions for new
# users fairly aggressively (verified: `gemini-2.5-flash` already returns
# "no longer available to new users" on a key created 2026-08-02, which would
# have hard-broken a pinned config). The alias tracks whatever current flash
# model the account can actually reach.
VISION_MODEL = "gemini-flash-latest"

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"

MAX_IMAGE_BYTES = 4 * 1024 * 1024  # keep base64 payloads within request limits

_SUPPORTED_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

_VISION_PROMPT = (
    "You are assisting an injury-recovery support team by describing a photo a "
    "patient uploaded. Describe ONLY what is visually observable, factually and "
    "neutrally, in 2-4 sentences.\n"
    "Report if present: body part shown, visible swelling, redness or "
    "discoloration, bruising, wounds/incisions and their appearance (open, "
    "closed, draining, sutured), visible deformity or asymmetry, braces/casts/"
    "crutches, or exercise posture and body position.\n"
    "Do NOT diagnose, do NOT estimate severity, do NOT give medical or training "
    "advice, and do NOT speculate about causes -- a separate grounded clinical "
    "team handles all of that. If the image is unclear or shows nothing "
    "medically or physically relevant, say exactly that."
)


def describe_image(image_bytes: bytes, filename: str = "upload.jpg") -> dict:
    """Describe an uploaded image using a Gemini vision model.

    Returns {"description": str, "error": str | None} and never raises --
    same convention as SpecialistAgent.consult().
    """
    result = {"description": "", "error": None}

    ext = Path(filename).suffix.lower()
    mime = _SUPPORTED_MIME.get(ext)
    if not mime:
        result["error"] = (
            f"Unsupported image type '{ext or filename}'. "
            f"Supported: {', '.join(sorted(_SUPPORTED_MIME))}"
        )
        return result

    if not image_bytes:
        result["error"] = "Empty image file."
        return result

    if len(image_bytes) > MAX_IMAGE_BYTES:
        result["error"] = (
            f"Image is {len(image_bytes) / 1_048_576:.1f} MB; "
            f"max is {MAX_IMAGE_BYTES / 1_048_576:.0f} MB. Please upload a smaller photo."
        )
        return result

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        result["error"] = (
            "GOOGLE_API_KEY not found. Photo upload needs a free Google AI Studio "
            "key (https://aistudio.google.com/apikey) in your .env -- Groq has no "
            "vision model available. Text questions work fine without it."
        )
        return result

    try:
        import requests

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        resp = requests.post(
            f"{GEMINI_ENDPOINT}/{VISION_MODEL}:generateContent",
            params={"key": api_key},
            json={
                "contents": [
                    {
                        "parts": [
                            {"text": _VISION_PROMPT},
                            {"inline_data": {"mime_type": mime, "data": b64}},
                        ]
                    }
                ],
                "generationConfig": {"temperature": 0},
            },
            timeout=90,
        )
        if resp.status_code != 200:
            result["error"] = f"Gemini API {resp.status_code}: {resp.text[:200]}"
            return result
        result["description"] = (
            resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def build_question_with_image(question: str, description: str) -> str:
    """Fold an image description into the user's question so the existing
    text-only router/specialist pipeline can use it unchanged."""
    question = (question or "").strip()
    if not description:
        return question
    prefix = f"[Patient uploaded a photo. Visual description: {description}]"
    return f"{prefix}\n\n{question}" if question else prefix


def main() -> None:
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 2:
        print("Usage: python -m src.vision <path-to-image>")
        return
    path = Path(sys.argv[1])
    out = describe_image(path.read_bytes(), path.name)
    print(f"Error: {out['error']}" if out["error"] else out["description"])


if __name__ == "__main__":
    main()
