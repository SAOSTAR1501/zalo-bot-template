import logging
import os
import re
import subprocess
import tempfile
import time
import uuid
from typing import Optional, Tuple
import requests
from config.settings import settings

logger = logging.getLogger(__name__)


class AgyImageService:
    """
    Generate images using the locally installed Antigravity CLI (agy).

    Requires `agy` to be installed on the server and authenticated with a
    Google account.  If agy hits rate limits / quota exhaustion, falls back to
    Pollinations.ai (a free text-to-image service) so the bot can still
    deliver an image.
    """

    DEFAULT_TIMEOUT_SECONDS = 240
    POLLINATIONS_BASE = "https://image.pollinations.ai/prompt"

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.timeout = timeout
        self._binary = self._resolve_binary()

    def _resolve_binary(self) -> str:
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

    def is_available(self) -> bool:
        """Check whether the agy binary is executable."""
        try:
            result = subprocess.run(
                [self._binary, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            return result.returncode == 0 and bool(result.stdout.strip())
        except Exception as e:
            logger.warning(f"agy is not available: {e}")
            return False

    def generate_image(
        self,
        description: str,
        output_path: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Generate an image from a text description.

        First tries agy (Antigravity CLI); if it fails due to quota/rate-limit,
        falls back to Pollinations.ai.

        Returns (success, message_or_path).  On success the second value is
        the absolute path to the generated image file.
        """
        if output_path is None:
            output_path = os.path.join(
                tempfile.gettempdir(),
                f"bot_image_{uuid.uuid4().hex[:12]}.png",
            )
        output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # 1. Try agy first if available
        if self.is_available():
            success, result = self._generate_with_agy(description, output_path)
            if success:
                return True, output_path
            # If agy failed due to quota/rate-limit, log and fall through.
            logger.warning(f"agy failed ({result}), trying Pollinations.ai fallback")

        # 2. Fallback to Pollinations.ai
        return self._generate_with_pollinations(description, output_path)

    def _generate_with_agy(
        self,
        description: str,
        output_path: str,
    ) -> Tuple[bool, str]:
        prompt = (
            f"Create an image matching the following description and save it "
            f"as a PNG file at exactly this path: {output_path}\n\n"
            f"Description: {description}"
        )

        logger.info(f"Generating image with agy for: {description[:80]}...")
        start = time.time()
        try:
            result = subprocess.run(
                [self._binary, "--dangerously-skip-permissions", f"--print={prompt}"],
                capture_output=True,
                text=True,
                timeout=self.timeout,
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

            # Detect quota / rate-limit messages even when returncode is 0
            quota_phrases = [
                "rate limits",
                "quota exhaustion",
                "image generation is currently unavailable",
                "quota",
                "rate limit",
            ]
            lower_output = combined_output.lower()
            if any(phrase in lower_output for phrase in quota_phrases):
                return False, "agy quota exhausted"

            if result.returncode != 0:
                return False, f"agy exited with code {result.returncode}: {combined_output[:500]}"

            if os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
                return True, output_path

            # Try to extract any file path from stdout
            paths = re.findall(r"\[([^\]]+)\]\(file://([^)]+)\)", result.stdout)
            if paths:
                _, fallback_path = paths[-1]
                if os.path.isfile(fallback_path):
                    return True, fallback_path

            return False, "agy did not produce an image file"

        except subprocess.TimeoutExpired:
            return False, f"agy timed out after {self.timeout}s"
        except Exception as e:
            logger.exception("Unexpected error running agy")
            return False, f"agy unexpected error: {e}"

    def _generate_with_pollinations(
        self,
        description: str,
        output_path: str,
    ) -> Tuple[bool, str]:
        """Free fallback: Pollinations.ai text-to-image."""
        logger.info(f"Generating image with Pollinations.ai for: {description[:80]}...")
        try:
            # Build a clean URL-safe prompt
            encoded = requests.utils.quote(description)
            url = f"{self.POLLINATIONS_BASE}/{encoded}?width=1024&height=1024&nologo=true&seed={uuid.uuid4().int % 1000000}"

            r = requests.get(url, timeout=120)
            if r.status_code != 200:
                return False, f"Pollinations.ai returned {r.status_code}"

            if len(r.content) == 0:
                return False, "Pollinations.ai returned empty image"

            with open(output_path, "wb") as f:
                f.write(r.content)

            logger.info(f"Pollinations.ai image saved to {output_path} ({len(r.content)} bytes)")
            return True, output_path

        except Exception as e:
            logger.exception("Pollinations.ai fallback failed")
            return False, f"Pollinations.ai error: {e}"


agy_image_service = AgyImageService()
