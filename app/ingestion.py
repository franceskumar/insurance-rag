"""Bounded document extraction and section-aware, overlapping chunks."""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from pypdf import PdfReader

MAX_BYTES = 15 * 1024 * 1024
MAX_TEXT = 2_000_000
MAX_PAGES = 500
SUPPORTED = {".pdf", ".txt", ".md", ".docx"}


class DocumentError(ValueError):
    pass


@dataclass(frozen=True)
class Passage:
    page: int
    section: str
    text: str


def clean(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.replace("\x00", "")).strip()


def _split(text: str, size: int = 1050, overlap: int = 180) -> list[str]:
    """Split at a nearby sentence/word boundary without losing long paragraphs."""
    output = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = max(text.rfind(". ", start + size // 2, end),
                           text.rfind("\n", start + size // 2, end))
            if boundary > start:
                end = boundary + 1
            else:
                boundary = text.rfind(" ", start + size // 2, end)
                if boundary > start:
                    end = boundary
        part = text[start:end].strip()
        if part:
            output.append(part)
        if end == len(text):
            break
        next_start = max(start + 1, end - overlap)
        word_boundary = text.find(" ", next_start, end)
        start = word_boundary + 1 if word_boundary >= 0 else next_start
    return output


def _sections(text: str, page: int, default: str = "Document") -> list[Passage]:
    result = []
    section = default
    buffer: list[str] = []

    def flush():
        body = clean("\n".join(buffer))
        if body:
            result.extend(Passage(page, section, part) for part in _split(body))
        buffer.clear()

    for line in text.splitlines():
        heading = re.match(r"^\s*#{1,6}\s+(.+?)\s*#*\s*$", line)
        if heading:
            flush()
            section = heading.group(1)
        else:
            buffer.append(line)
    flush()
    return result


def extract(filename: str, content: bytes) -> tuple[str, list[Passage], int]:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED:
        raise DocumentError("Choose a PDF, DOCX, Markdown, or UTF-8 text file.")
    if not content:
        raise DocumentError("This file is empty.")
    if len(content) > MAX_BYTES:
        raise DocumentError("The maximum file size is 15 MB.")
    title = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    try:
        if suffix == ".pdf":
            reader = PdfReader(io.BytesIO(content))
            if reader.is_encrypted:
                raise DocumentError("Remove the PDF password before uploading.")
            page_count = len(reader.pages)
            if page_count > MAX_PAGES:
                raise DocumentError("Please split documents longer than 500 pages.")
            pages: list[str] = []
            text_length = 0
            for page in reader.pages:
                text = page.extract_text() or ""
                text_length += len(text)
                if text_length > MAX_TEXT:
                    raise DocumentError("The extracted text exceeds the 2 million character limit.")
                pages.append(text)
            passages = [p for i, page in enumerate(pages, 1) for p in _sections(page, i, "Policy text")]
        elif suffix == ".docx":
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                info = archive.getinfo("word/document.xml")
                if info.file_size > 10 * MAX_TEXT:
                    raise DocumentError("This Word document is too large to extract.")
                xml = ElementTree.fromstring(archive.read(info))
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            lines = []
            for para in xml.findall(".//w:body//w:p", ns):
                text = "".join(node.text or "" for node in para.findall(".//w:t", ns))
                style = para.find("w:pPr/w:pStyle", ns)
                if style is not None and "heading" in style.get(f"{{{ns['w']}}}val", "").lower():
                    text = "## " + text
                lines.append(text)
            text = "\n\n".join(lines)
            if len(text) > MAX_TEXT:
                raise DocumentError("The extracted text exceeds the 2 million character limit.")
            passages = _sections(text, 1)
            page_count = 1  # DOCX has no reliable physical page boundaries.
        else:
            text = content.decode("utf-8-sig")
            if len(text) > MAX_TEXT:
                raise DocumentError("The extracted text exceeds the 2 million character limit.")
            if "\x00" in text:
                raise DocumentError("This file does not appear to contain plain text.")
            heading = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
            if heading:
                title = heading.group(1).strip()
            passages = _sections(text, 1)
            page_count = 1
    except DocumentError:
        raise
    except Exception as exc:
        raise DocumentError("Could not read this file. Check that it is a valid, unencrypted document.") from exc
    if not passages or sum(len(p.text.strip()) for p in passages) < 30:
        raise DocumentError("No readable text found. Scanned PDFs need OCR before uploading.")
    return title[:180], passages, page_count


def infer_category(filename: str, title: str) -> str:
    terms = (filename + " " + title).lower()
    for category, keywords in {
        "Health": ("health", "medical"),
        "Motor": ("motor", "auto", "vehicle", "car insurance"),
        "Life": ("life", "term plan"),
        "Home": ("home", "property", "house"),
        "Claims": ("claim",),
    }.items():
        if any(word in terms for word in keywords):
            return category
    return "General"
