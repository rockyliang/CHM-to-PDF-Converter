"""Hierarchical TOC parsing from .hhc files using BeautifulSoup."""

from __future__ import annotations

import html as html_mod
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup

from .utils import LogFn, load_text, normalize_chm_local_path, HTML_TOPIC_EXTS


@dataclass
class TocEntry:
    """A single entry in the CHM table of contents."""
    title: str
    local: str  # normalized CHM-internal path
    level: int  # nesting depth (1 = top-level)
    children: list[TocEntry] = field(default_factory=list)


def _extract_params(obj_tag) -> dict[str, str]:
    """Extract name→value pairs from <param> tags inside an <object>."""
    params: dict[str, str] = {}
    for param in obj_tag.find_all("param"):
        name = (param.get("name") or "").strip().lower()
        value = (param.get("value") or "").strip()
        if name and value:
            params[name] = html_mod.unescape(value)
    return params


def _parse_ul(ul_tag, level: int) -> list[TocEntry]:
    """Recursively parse a <ul> containing <li> > <object> + nested <ul>."""
    entries: list[TocEntry] = []
    if ul_tag is None:
        return entries

    for li in ul_tag.find_all("li", recursive=False):
        obj = li.find("object", recursive=False)
        if obj is None:
            # Some .hhc files have <object> not directly in <li> but nested
            obj = li.find("object")
        if obj is None:
            continue

        params = _extract_params(obj)
        title = params.get("name", "").strip()
        local = params.get("local", "").strip()

        if not title:
            continue

        entry = TocEntry(
            title=title,
            local=normalize_chm_local_path(local) if local else "",
            level=level,
        )

        # Parse nested <ul> for children
        nested_ul = li.find("ul", recursive=False)
        if nested_ul:
            entry.children = _parse_ul(nested_ul, level + 1)

        entries.append(entry)

    return entries


def parse_hhc(hhc_path: Path, log: LogFn | None = None) -> list[TocEntry]:
    """Parse an .hhc file into a hierarchical list of TocEntry objects.

    Falls back to flat parsing if the file doesn't use standard <ul>/<li>
    nesting (some generators produce flat <object> lists).
    """
    text = load_text(hhc_path)
    soup = BeautifulSoup(text, "html.parser")

    # Try hierarchical parsing first (standard .hhc format uses nested <ul>)
    body = soup.find("body") or soup
    top_ul = body.find("ul")
    if top_ul:
        entries = _parse_ul(top_ul, level=1)
        if entries:
            return entries

    # Fallback: flat parsing — just collect all <object> tags in order
    if log:
        log("HHC has no nested <ul> structure; using flat parsing.")
    entries = []
    for obj in soup.find_all("object"):
        params = _extract_params(obj)
        title = params.get("name", "").strip()
        local = params.get("local", "").strip()
        if not title or not local:
            continue
        entries.append(TocEntry(
            title=title,
            local=normalize_chm_local_path(local),
            level=1,
        ))
    return entries


def flatten_toc(entries: list[TocEntry]) -> list[tuple[str, str, int]]:
    """Flatten a hierarchical TOC tree into an ordered list.

    Returns list of (title, normalized_path, level) tuples in reading order.
    Entries without a local path (heading-only nodes) are included for
    bookmark generation but flagged with empty path.
    """
    result: list[tuple[str, str, int]] = []
    seen: set[tuple[str, str]] = set()

    def _walk(items: list[TocEntry]) -> None:
        for entry in items:
            key = (entry.title, entry.local)
            if key not in seen:
                seen.add(key)
                result.append((entry.title, entry.local, entry.level))
            _walk(entry.children)

    _walk(entries)
    return result


def find_hhc(extracted_dir: Path) -> Path | None:
    """Find the first .hhc file in the extracted directory."""
    hhc_files = list(extracted_dir.glob("*.hhc"))
    if not hhc_files:
        # Some CHMs put the .hhc in a subdirectory
        hhc_files = list(extracted_dir.rglob("*.hhc"))
    return hhc_files[0] if hhc_files else None


def generate_fallback_entries(
    extracted_dir: Path,
    log: LogFn | None = None,
) -> list[TocEntry]:
    """Generate TOC entries from all HTML files when no .hhc exists.

    Sorts alphabetically and assigns all entries to level 1.
    """
    if log:
        log("No .hhc file found — generating TOC from all HTML files.")
    entries = []
    for ext in sorted(HTML_TOPIC_EXTS):
        for f in sorted(extracted_dir.rglob(f"*{ext}")):
            rel = f.relative_to(extracted_dir).as_posix()
            title = f.stem.replace("_", " ").replace("-", " ").title()
            entries.append(TocEntry(title=title, local=rel, level=1))
    return entries
