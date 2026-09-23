import logging
import os
import re
import requests
import subprocess
import tempfile
import time
import uuid
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def _translate_to_english(text: str) -> str:
    """Translate a Vietnamese image prompt to English using the local Ollama LLM."""
    try:
        # Import here to avoid circular dependencies at module load time.
        import json
        from config.settings import settings

        url = settings.OLLAMA_BASE_URL.rstrip("/") + "/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if settings.OLLAMA_API_KEY:
            headers["Authorization"] = f"Bearer {settings.OLLAMA_API_KEY}"

        payload = {
            "model": settings.OLLAMA_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Translate the user's image description into a short, "
                        "vivid English image-generation prompt. Keep it under 30 words. "
                        "Reply with ONLY the English prompt, no explanation, no quotes, no markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Translate to English:\n\n{text}",
                },
            ],
            "temperature": 0.2,
            "max_tokens": 80,
        }

        r = requests.post(url, json=payload, headers=headers, timeout=(5, 30))
        if r.status_code == 200:
            data = r.json()
            if "choices" in data and len(data["choices"]) > 0:
                translated = data["choices"][0]["message"]["content"].strip()
                # Strip common wrapper characters and explanations.
                translated = re.sub(r"^[^a-zA-Z0-9]*", "", translated)
                translated = re.sub(r"[^a-zA-Z0-9\s\-_.,:;!?()]+$", "", translated)
                translated = translated.strip().strip('"').strip("'")
                if translated and len(translated) > 3:
                    logger.info(f"Translated image prompt: '{text[:60]}' -> '{translated[:80]}'")
                    return translated
        else:
            logger.warning(f"Translation LLM returned {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.warning(f"Failed to translate prompt to English: {e}")
    return text


class ImageGenerationService:
    """
    Generate images for the bot.

    Primary: Pollinations.ai (free, fast text-to-image).  It returns a public
    image URL that Zalo's sendPhoto API can consume directly.

    Fallback: Antigravity CLI (agy) if available and quota allows.  agy saves
    images locally, so local paths are returned as a fallback.
    """

    AGY_TIMEOUT_SECONDS = 90
    POLLINATIONS_BASE = "https://image.pollinations.ai/prompt"

    def __init__(self):
        self._agy_binary = self._resolve_agy_binary()

    def _resolve_agy_binary(self) -> str:
        """Find the agy binary in PATH or common install locations."""
        candidates = ["agy"]
        home = os.path.expanduser("~")
        candidates.extend([
            os.path.join(home, ".local", "bin", "agy"),
            "/usr/local/bin/agy",
            "/usr/bin/agy",
        ])
        for candidate in candidates:
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        return "agy"

    def is_agy_available(self) -> bool:
        """Check whether the agy binary is executable."""
        try:
            result = subprocess.run(
                [self._agy_binary, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            return result.returncode == 0 and bool(result.stdout.strip())
        except Exception as e:
            logger.debug(f"agy is not available: {e}")
            return False

    def generate_image(
        self,
        description: str,
    ) -> Tuple[bool, str]:
        """
        Generate an image from a text description.

        Returns (success, message_or_url_or_path).  On success the second value
        is either a public image URL (Pollinations.ai) or a local file path
        (agy fallback) that can be passed to Zalo sendPhoto.
        """
        # 1. Primary: fast Pollinations.ai public URL
        success, result = self._generate_with_pollinations(description)
        if success:
            return True, result

        logger.warning(f"Pollinations.ai failed ({result}), trying agy fallback")

        # 2. Fallback: agy (Antigravity CLI) -> local file path
        if self.is_agy_available():
            output_path = os.path.join(
                tempfile.gettempdir(),
                f"bot_image_{uuid.uuid4().hex[:12]}.png",
            )
            return self._generate_with_agy(description, output_path)

        return False, f"Pollinations.ai: {result}; agy not available"

    def _generate_with_pollinations(
        self,
        description: str,
    ) -> Tuple[bool, str]:
        """Free primary: Pollinations.ai returns a public image URL.

        We do not verify the URL with a HEAD request because Pollinations.ai
        sometimes rejects HEAD (returns 500) or takes too long to render.  The
        generated URL is public and Zalo's sendPhoto will fetch it directly.

        Pollinations.ai works best with English prompts, so we translate the
        description before building the URL.
        """
        logger.info(f"Original image prompt: {description[:80]}...")
        english_description = _translate_to_english(description)
        logger.info(f"Generating image URL with Pollinations.ai for: {english_description[:80]}...")
        try:
            encoded = requests.utils.quote(english_description)
            url = (
                f"{self.POLLINATIONS_BASE}/{encoded}"
                f"?width=1024&height=1024&nologo=true"
                f"&seed={uuid.uuid4().int % 1000000}"
            )

            logger.info(f"Pollinations.ai image URL ready: {url[:120]}...")
            return True, url

        except Exception as e:
            logger.exception("Pollinations.ai failed")
            return False, str(e)

    def _generate_with_agy(
        self,
        description: str,
        output_path: str,
    ) -> Tuple[bool, str]:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        prompt = (
            f"Create an image matching the following description and save it "
            f"as a PNG file at exactly this path: {output_path}\n\n"
            f"Description: {description}"
        )

        logger.info(f"Generating image with agy for: {description[:80]}...")
        start = time.time()
        try:
            result = subprocess.run(
                [
                    self._agy_binary,
                    "--dangerously-skip-permissions",
                    f"--print={prompt}",
                ],
                capture_output=True,
                text=True,
                timeout=self.AGY_TIMEOUT_SECONDS,
                env=os.environ.copy(),
                check=False,
            )
            elapsed = time.time() - start
            logger.info(f"agy finished in {elapsed:.1f}s, returncode={result.returncode}")

            combined_output = (result.stdout or "") + "\n" + (result.stderr or "")
            if result.stdout:
                logger.info(f"agy stdout: {result.stdout[:500]}")
            if result.stderr:
                logger.warning(f"agy stderr: {result.stderr[:500]}")

            quota_phrases = [
                "rate limits",
                "quota exhaustion",
                "image generation is currently unavailable",
                "quota",
                "rate limit",
            ]
            if any(phrase in combined_output.lower() for phrase in quota_phrases):
                return False, "agy quota exhausted"

            if result.returncode != 0:
                return False, f"agy exit {result.returncode}: {combined_output[:500]}"

            if os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
                return True, output_path

            paths = re.findall(r"\[([^\]]+)\]\(file://([^)]+)\)", result.stdout)
            if paths:
                _, fallback_path = paths[-1]
                if os.path.isfile(fallback_path):
                    return True, fallback_path

            return False, "agy did not produce an image file"

        except subprocess.TimeoutExpired:
            return False, f"agy timed out after {self.AGY_TIMEOUT_SECONDS}s"
        except Exception as e:
            logger.exception("Unexpected error running agy")
            return False, f"agy error: {e}"


image_generation_service = ImageGenerationService()
