"""Convert tracker-specific rich text (Jira ADF, ADO HTML) to plain text, and
back to the minimal ADF Jira needs for posting a comment. Dependency-free."""
import re
from html.parser import HTMLParser


def adf_to_text(node: object) -> str:
    """Flatten an Atlassian Document Format node (Jira description/comment) to text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    t = node.get("type")
    if t == "text":
        return node.get("text", "")
    if t == "hardBreak":
        return "\n"
    children = node.get("content") or []
    inner = "".join(adf_to_text(c) for c in children)
    if t == "listItem":
        return "- " + inner.strip() + "\n"
    if t in ("paragraph", "heading", "codeBlock", "blockquote", "doc"):
        return inner + "\n"
    return inner


class _HTMLText(HTMLParser):
    BREAK_AFTER = {"p", "div", "li", "tr", "br", "h1", "h2", "h3", "h4", "ul", "ol"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag == "br":
            self.parts.append("\n")
        elif tag in ("ul", "ol"):
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.BREAK_AFTER:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(html: str) -> str:
    """Strip ADO/HTML markup to readable plain text."""
    if not html:
        return ""
    p = _HTMLText()
    p.feed(html)
    text = "".join(p.parts)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def text_to_adf(text: str) -> dict:
    """Wrap plain text in the minimal ADF document Jira accepts for a comment."""
    paras = []
    for line in (text or "").split("\n"):
        line = line.rstrip()
        if line:
            paras.append({"type": "paragraph", "content": [{"type": "text", "text": line}]})
    if not paras:
        paras = [{"type": "paragraph", "content": [{"type": "text", "text": " "}]}]
    return {"type": "doc", "version": 1, "content": paras}
