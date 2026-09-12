import re
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")


def local_links(markdown: Path):
    for match in MARKDOWN_LINK.finditer(markdown.read_text(encoding="utf-8")):
        raw_target = match.group(1).strip()
        if raw_target.startswith("<") and raw_target.endswith(">"):
            raw_target = raw_target[1:-1]
        target = urlsplit(raw_target)
        if target.scheme or target.netloc or not target.path:
            continue
        yield unquote(target.path), unquote(target.fragment)


def heading_anchors(markdown: Path):
    anchors = set()
    counts = {}
    for line in markdown.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue
        heading = re.sub(r"<[^>]+>", "", match.group(1)).lower()
        anchor = re.sub(r"[^\w\- ]", "", heading).replace(" ", "-")
        duplicate = counts.get(anchor, 0)
        counts[anchor] = duplicate + 1
        anchors.add(f"{anchor}-{duplicate}" if duplicate else anchor)
    return anchors


def test_local_markdown_links_resolve():
    markdown_files = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
    missing = []
    for markdown in markdown_files:
        for target, fragment in local_links(markdown):
            resolved = (markdown.parent / target).resolve()
            if not resolved.exists():
                missing.append(f"{markdown.relative_to(ROOT)} -> {target}")
            elif fragment and resolved.suffix.lower() == ".md":
                if fragment not in heading_anchors(resolved):
                    missing.append(f"{markdown.relative_to(ROOT)} -> {target}#{fragment}")
    assert not missing, "Missing local Markdown targets:\n" + "\n".join(missing)
