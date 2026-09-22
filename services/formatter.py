import re


def clean_mention(text: str) -> str:
    """
    Strips @Bot_Name or @username prefix from the beginning of group message.
    """
    cleaned = re.sub(r"^@(?:Bot\s+[\w\d_]+|[\w\d._-]+)\s*", "", text, flags=re.IGNORECASE).strip()
    return cleaned or text.strip()


def clean_markdown_for_zalo(text: str) -> str:
    """
    Cleans markdown formatting that is not rendered properly in Zalo chat.
    Converts bold/italic/headers/links into clean readable plain text with neat bullets.
    """
    if not text:
        return text

    # 1. Strip bold and italic asterisks/underscores (**text**, *text*, __text__, _text_)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"_(.*?)_", r"\1", text)

    # 2. Strip headers: ### Header -> Header
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)

    # 3. Format markdown links: [Title](url) -> Title (url)
    text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1 (\2)", text)

    # 4. Strip code fences & backticks
    text = re.sub(r"```(?:\w+)?\n?", "", text)
    text = text.replace("```", "").replace("`", "")

    # 5. Format bullet points to neat bullet symbols (•)
    text = re.sub(r"^\s*[-*]\s+", "• ", text, flags=re.MULTILINE)

    # 6. Clean consecutive empty lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
