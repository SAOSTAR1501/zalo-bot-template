import logging
import os
import re
import subprocess
import tempfile
import time
import uuid
from typing import Optional, Tuple
from config.settings import settings

logger = logging.getLogger(__name__)


class AgyImageService:
    """
    Generate images using the locally installed Antigravity CLI (agy).

    Requires `agy` to be installed on the server and authenticated with a
    Google account.  The CLI is invoked in headless print mode and asked to
    save the generated image to a known local path.  This service then
    returns the local file path so the bot can upload it to Zalo.
    """

    DEFAULT_TIMEOUT_SECONDS = 180

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
        # Fallback: let subprocess search PATH
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
        Generate an image from a text description using agy.

        Returns (success, message_or_path).  On success the second value is
        the absolute path to the generated image file.
        """
        if not self.is_available():
            return False, "❌ Antigravity CLI (agy) chưa được cài đặt hoặc chưa xác thực trên server."

        if output_path is None:
            output_path = os.path.join(
                tempfile.gettempdir(),
                f"agy_image_{uuid.uuid4().hex[:12]}.png",
            )
        output_path = os.path.abspath(output_path)

        # Ensure parent directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        prompt = (
            f"Create an image matching the following description and save it "
            f"as a PNG file at exactly this path: {output_path}\n\n"
            f"Description: {description}"
        )

        logger.info(f"Generating image with agy for: {description[:80]}...")
        env = os.environ.copy()
        # Allow callers to override agy credentials via environment if needed.
        # agy normally uses the logged-in Google session; GEMINI_API_KEY is only
        # relevant for the deprecated npm gemini-cli package.

        start = time.time()
        try:
            result = subprocess.run(
                [self._binary, "--dangerously-skip-permissions", f"--print={prompt}"],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
                check=False,
            )
            elapsed = time.time() - start
            logger.info(f"agy finished in {elapsed:.1f}s, returncode={result.returncode}")

            if result.stdout:
                logger.info(f"agy stdout: {result.stdout[:500]}")
            if result.stderr:
                logger.warning(f"agy stderr: {result.stderr[:500]}")

            if result.returncode != 0:
                return False, f"❌ Agy generation failed:\n{result.stderr or result.stdout}"

            # The CLI sometimes prints the saved path as a markdown link.
            # Verify the file exists as the source of truth.
            if os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
                return True, output_path

            # Fallback: try to extract any file path from stdout
            paths = re.findall(r"\[([^\]]+)\]\(file://([^)]+)\)", result.stdout)
            if paths:
                _, fallback_path = paths[-1]
                if os.path.isfile(fallback_path):
                    return True, fallback_path

            return False, "❌ Agy did not produce an image file at the expected path."

        except subprocess.TimeoutExpired:
            return False, f"❌ Agy timed out after {self.timeout}s."
        except Exception as e:
            logger.exception("Unexpected error running agy")
            return False, f"❌ Unexpected error: {e}"


agy_image_service = AgyImageService()
