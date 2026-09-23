import re
from typing import Tuple, Optional


# ---------------------------------------------------------------------------
# Mention / reply detection helpers for group chat behaviour
# ---------------------------------------------------------------------------
def is_mentioning_bot(text: str, bot_display_name: Optional[str] = None) -> bool:
    """
    Detect whether the user explicitly mentioned the bot with '@BotName'.
    If bot_display_name is not provided, we accept any leading @SomeName as a bot mention.
    """
    text = (text or "").strip()
    if not text:
        return False
    # Any leading @<word> is treated as a group mention of the bot.
    if re.match(r"^@(?:Bot\s+[\w\d_]+|[\w\d._-]+)\b", text, flags=re.IGNORECASE):
        return True
    # If we know the bot name, also accept mentions anywhere in the message.
    if bot_display_name:
        pattern = re.compile(rf"@{re.escape(bot_display_name)}\b", flags=re.IGNORECASE)
        if pattern.search(text):
            return True
    return False


def clean_mention(text: str, bot_display_name: Optional[str] = None) -> str:
    """
    Strips @Bot_Name or @username prefix from the beginning of group message
    while preserving any inline @username mentions so the bot can still reference them.
    """
    text = (text or "").strip()
    cleaned = re.sub(r"^@(?:Bot\s+[\w\d_]+|[\w\d._-]+)\s*", "", text, flags=re.IGNORECASE).strip()
    # Also remove an inline mention of the bot itself if the whole message is just that.
    if bot_display_name:
        cleaned = re.sub(
            rf"^\s*@{re.escape(bot_display_name)}\s*",
            "",
            cleaned,
            flags=re.IGNORECASE
        ).strip()
    return cleaned or text


def is_reply_to_bot(reply_to_obj: dict, bot_user_id: str = "") -> bool:
    """Check if the user's quoted reply is replying to a message sent by the bot."""
    if not isinstance(reply_to_obj, dict):
        return False
    sender = reply_to_obj.get("from") or {}
    sender_id = sender.get("id", "")
    sender_name = sender.get("display_name", "")
    is_bot = sender.get("is_bot", False)
    if is_bot:
        return True
    if bot_user_id and str(sender_id) == str(bot_user_id):
        return True
    # Fallback heuristic: Zalo bot display names often contain "Bot" or the registered name.
    if "bot" in sender_name.lower():
        return True
    return False


def extract_target_mentions(text: str) -> list:
    """Return all @username / @Display Name style mentions found in text."""
    return re.findall(r"@([\w\d._\- \u00c0-\u1fff]+?)(?:\b|$)", text)


# ---------------------------------------------------------------------------
# Markdown formatting helpers tuned for Zalo Bot Platform
# ---------------------------------------------------------------------------
def clean_markdown_for_zalo(text: str) -> str:
    """
    Cleans markdown formatting to safe Zalo plain text / light markdown.
    Zalo official parse_mode=markdown supports: **bold**, *italic*, ~~strike~~,
    `code`, #headers, lists, blockquote, {color} tags, {big}, {underline}.
    We keep supported syntax and only strip unsupported elements.
    """
    if not text:
        return text

    # Remove triple backticks (code fences) because they render poorly in chat bubbles.
    text = re.sub(r"```(?:\w+)?\n?", "", text)
    text = text.replace("```", "")

    # Convert nested __underline__ to Zalo {underline}...{/underline}
    text = re.sub(r"__(.*?)__", r"{underline}\1{/underline}", text)

    # Keep single backticks as plain text, Zalo `code` keeps raw content anyway.
    text = text.replace("`", "")

    # Normalize headers: keep the text, remove leading hashes.
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)

    # Ensure markdown links become readable: [Title](url) -> Title (url)
    text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1 (\2)", text)

    # Convert common bullet markers to Zalo-friendly '• '
    text = re.sub(r"^\s*[-*]\s+", "• ", text, flags=re.MULTILINE)

    # Tidy up excessive empty lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def zalo_safe_rich_text(text: str) -> str:
    """
    Keep Zalo-supported markdown only. Use this when sending with parse_mode='markdown'.
    Removes unsupported asterisk/underscore variants and keeps **bold**, *italic*, etc.
    """
    if not text:
        return text

    # Keep **bold** and *italic* as-is (supported by Zalo).
    # Remove ___ and __ raw since we already mapped __underline__ above.
    text = re.sub(r"\b__\b", "", text)

    # Keep ~~strike~~, `code` (Zalo supports both).
    # Remove triple backticks.
    text = re.sub(r"```(?:\w+)?\n?", "", text)
    text = text.replace("```", "")

    # Clean headers
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)

    # Clean links
    text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1 (\2)", text)

    # Convert bullets
    text = re.sub(r"^\s*[-*]\s+", "• ", text, flags=re.MULTILINE)

    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_quota_badges(text: str) -> str:
    """
    Strips transient quota badges like (💡 Tin nhắn X/10 miễn phí)
    so LLM does not hallucinate or mimic them into future replies.
    """
    if not text:
        return ""
    cleaned = re.sub(r"\s*\(💡\s*Tin nhắn\s+\d+/\d+\s+miễn phí\)\s*", "", text, flags=re.IGNORECASE)
    return cleaned.strip()


def mention_name_for_zalo(display_name: str) -> str:
    """
    Return a plain-text pseudo-mention that looks like a real Zalo mention.
    Zalo Bot Platform does NOT provide an API for real interactive mentions,
    so this is the best we can do visually.
    """
    name = (display_name or "").strip()
    if not name:
        return ""
    return f"@{name}"
