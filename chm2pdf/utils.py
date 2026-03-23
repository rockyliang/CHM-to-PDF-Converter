"""Encoding detection, path normalization, and shared helpers."""

from __future__ import annotations

import codecs
import html as html_mod
import posixpath
import re
from pathlib import Path
from typing import Callable

# Shared log function type used across all modules.
LogFn = Callable[[str], None]

HTML_TOPIC_EXTS = {".htm", ".html", ".xhtml"}


# ---------------------------------------------------------------------------
# Character-encoding detection
# ---------------------------------------------------------------------------

def sniff_declared_encoding(raw: bytes) -> str | None:
    """Detect encoding from BOM or HTML meta charset declaration."""
    if raw.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if raw.startswith(codecs.BOM_UTF16_LE):
        return "utf-16-le"
    if raw.startswith(codecs.BOM_UTF16_BE):
        return "utf-16-be"

    head = raw[:4096]
    for enc in ("ascii", "latin-1"):
        try:
            probe = head.decode(enc, errors="ignore")
            break
        except Exception:
            continue
    else:
        probe = ""

    patterns = [
        r"""<meta[^>]+charset\s*=\s*["']?\s*([^"'>\s;/]+)""",
        r"""<meta[^>]+content\s*=\s*["'][^"']*charset\s*=\s*([^"'>\s;]+)""",
    ]
    for pattern in patterns:
        match = re.search(pattern, probe, flags=re.I)
        if match:
            enc_name = match.group(1).strip().lower()
            alias_map = {
                "gb2312": "gb18030",
                "gbk": "gb18030",
                "x-gbk": "gb18030",
                "chinese": "gb18030",
                "big5-hkscs": "big5hkscs",
                "unicode": "utf-8",
            }
            return alias_map.get(enc_name, enc_name)
    return None


def load_text(path: Path) -> str:
    """Read a file, trying declared encoding first then a fallback chain."""
    raw = path.read_bytes()
    declared = sniff_declared_encoding(raw)
    candidates: list[str] = []
    if declared:
        candidates.append(declared)
        if declared.lower() in {
            "utf-16", "utf-16le", "utf-16be", "utf-16-le", "utf-16-be",
        }:
            candidates.extend(["utf-16", "utf-16-le", "utf-16-be"])
    candidates.extend([
        "utf-8", "utf-8-sig",
        "gb18030", "big5", "big5hkscs", "cp950", "cp936",
        "cp1252", "latin-1",
    ])

    seen: set[str] = set()
    ordered: list[str] = []
    for enc in candidates:
        if enc and enc.lower() not in seen:
            seen.add(enc.lower())
            ordered.append(enc)

    for enc in ordered:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue

    return raw.decode("utf-8", errors="replace")


def save_text(path: Path, content: str) -> None:
    """Write UTF-8 text with Unix line endings."""
    path.write_text(content, encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------
# CJK language detection from encoding
# ---------------------------------------------------------------------------

# Mapping from encoding names to BCP-47 language tags.
_ENCODING_TO_LANG: dict[str, str] = {
    # Simplified Chinese
    "gb2312": "zh-CN",
    "gbk": "zh-CN",
    "gb18030": "zh-CN",
    "x-gbk": "zh-CN",
    "chinese": "zh-CN",
    "cp936": "zh-CN",
    # Traditional Chinese
    "big5": "zh-TW",
    "big5hkscs": "zh-TW",
    "cp950": "zh-TW",
    # Japanese
    "shift_jis": "ja",
    "shift-jis": "ja",
    "sjis": "ja",
    "euc-jp": "ja",
    "euc_jp": "ja",
    "iso-2022-jp": "ja",
    "cp932": "ja",
    # Korean
    "euc-kr": "ko",
    "euc_kr": "ko",
    "cp949": "ko",
    "uhc": "ko",
    "johab": "ko",
}


def detect_cjk_language(encodings: list[str]) -> str:
    """Determine the primary CJK language from a list of detected encodings.

    Returns a BCP-47 language tag (e.g. ``'zh-CN'``, ``'zh-TW'``, ``'ja'``,
    ``'ko'``) or an empty string if no CJK language was detected.

    The most frequently occurring CJK encoding wins.
    """
    from collections import Counter
    lang_counts: Counter[str] = Counter()
    for enc in encodings:
        lang = _ENCODING_TO_LANG.get(enc.lower().replace("-", "_"), "")
        if not lang:
            # Try without hyphens/underscores
            lang = _ENCODING_TO_LANG.get(enc.lower().replace("_", "-"), "")
        if lang:
            lang_counts[lang] += 1
    if not lang_counts:
        return ""
    return lang_counts.most_common(1)[0][0]


# ---------------------------------------------------------------------------
# Path / URL helpers
# ---------------------------------------------------------------------------

def slugify(value: str) -> str:
    """Create a valid HTML anchor ID from arbitrary text."""
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip())
    value = value.strip("-")
    return value or "section"


def is_external_url(url: str) -> bool:
    """Return True for http(s), mailto, javascript, data, fragment-only, etc."""
    lowered = url.strip().lower()
    return (
        lowered.startswith("http://")
        or lowered.startswith("https://")
        or lowered.startswith("mailto:")
        or lowered.startswith("javascript:")
        or lowered.startswith("data:")
        or lowered.startswith("#")
        or lowered.startswith("about:")
    )


def normalize_chm_local_path(value: str) -> str:
    """Normalize a CHM-internal file reference to a canonical forward-slash path."""
    value = value.strip().replace("\\", "/")
    value = re.sub(r"^(ms-its:|mk:@msitstore:)", "", value, flags=re.I)
    if "::/" in value:
        value = value.split("::/", 1)[1]
    elif "::" in value:
        value = value.split("::", 1)[1].lstrip("/")
    value = value.lstrip("/")
    return posixpath.normpath(value)


def split_url_and_fragment(url: str) -> tuple[str, str]:
    """Split 'page.html#anchor' into ('page.html', 'anchor')."""
    if "#" in url:
        base, frag = url.split("#", 1)
        return base, frag
    return url, ""


def rewrite_url(
    url: str,
    topic_dir_rel: str,
    topic_anchor_map: dict[str, str],
) -> str:
    """Map a CHM-internal URL to its PDF anchor reference."""
    if is_external_url(url):
        return url
    base, fragment = split_url_and_fragment(url)
    if not base:
        return url
    resolved = posixpath.normpath(posixpath.join(topic_dir_rel, base)) if topic_dir_rel else posixpath.normpath(base)
    norm = normalize_chm_local_path(resolved)
    if norm in topic_anchor_map:
        anchor = topic_anchor_map[norm]
        return f"#{anchor}" if not fragment else f"#{anchor}"
    return url


# Regex for rewriting href/src/background/poster attributes in raw HTML.
ATTR_URL_RE = re.compile(
    r"\b(href|src|background|poster)\s*=\s*([\"'])(.*?)\2",
    re.I | re.S,
)


def rewrite_fragment_urls(
    fragment_html: str,
    topic_dir_rel: str,
    topic_anchor_map: dict[str, str],
) -> str:
    """Rewrite all internal URLs in a raw HTML fragment."""
    def _replace(m: re.Match) -> str:
        attr, quote, url = m.group(1), m.group(2), m.group(3)
        new_url = rewrite_url(url, topic_dir_rel, topic_anchor_map)
        return f'{attr}={quote}{new_url}{quote}'
    return ATTR_URL_RE.sub(_replace, fragment_html)
