from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path

from .constants import GLOBAL_RELEASE_WORDS, NOISE_TAG_WORDS, SERIES_NAME_MAX_CHARS, VOLUME_TOKEN


def collapse_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        clean = collapse_spaces(data)
        if clean:
            self.parts.append(clean)

    def text(self) -> str:
        return collapse_spaces(" ".join(self.parts))


def html_to_text(value: str) -> str:
    parser = TextExtractor()
    try:
        parser.feed(value)
        return parser.text()
    except Exception:  # noqa: BLE001 - 解析器失败时退回到保守的纯文本清理。
        return collapse_spaces(re.sub(r"<[^>]+>", " ", value))


def contains_cjk(value: str) -> bool:
    return any(
        "\u3400" <= char <= "\u9fff" or "\u3040" <= char <= "\u30ff" or "\uac00" <= char <= "\ud7af" for char in value
    )


def normalize_for_match(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"[\s\-_.,:;~!！?？\"“”‘’'`·・/\\|()[\]{}【】《》（）「」『』]+", "", value)
    return value


def is_noise_tag(value: str, *, position: str) -> bool:
    tag = collapse_spaces(unicodedata.normalize("NFKC", value)).casefold()
    if not tag:
        return True
    if tag in NOISE_TAG_WORDS:
        return True
    if any(word in tag for word in NOISE_TAG_WORDS):
        return True
    if re.fullmatch(r"(v|vol|volume|book)?\s*[0-9０-９]{1,3}", tag, re.IGNORECASE):
        return position == "trailing"
    return re.fullmatch(rf"第?\s*{VOLUME_TOKEN}\s*[卷册集部].*", tag) is not None


def strip_bracket_noise(value: str) -> str:
    left_brackets = "[【（("
    right_brackets = "]】）)"

    changed = True
    text = value.strip()
    while changed:
        changed = False
        leading = re.match(
            rf"^\s*([{re.escape(left_brackets)}])([^]{re.escape(right_brackets)}]{{1,60}})([{re.escape(right_brackets)}])\s*",
            text,
        )
        if leading and is_noise_tag(leading.group(2), position="leading"):
            text = text[leading.end() :].strip()
            changed = True

        trailing = re.search(
            rf"\s*([{re.escape(left_brackets)}])([^]{re.escape(right_brackets)}]{{1,60}})([{re.escape(right_brackets)}])\s*$",
            text,
        )
        if trailing and is_noise_tag(trailing.group(2), position="trailing"):
            text = text[: trailing.start()].strip()
            changed = True

    return text


def strip_release_words(value: str) -> str:
    text = value
    text = re.sub(
        r"\b(?:ln|light\s*novel|lightnovel)\b(?=\s*(?:第|vol|volume|book|v|\d|$))",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    for word in sorted(GLOBAL_RELEASE_WORDS, key=len, reverse=True):
        if contains_cjk(word):
            text = re.sub(re.escape(word), " ", text, flags=re.IGNORECASE)
        else:
            text = re.sub(rf"\b{re.escape(word)}\b", " ", text, flags=re.IGNORECASE)
    return collapse_spaces(text)


def clean_file_stem(file_name: str) -> str:
    stem = Path(file_name).stem
    text = unicodedata.normalize("NFKC", stem)
    text = text.replace("\u3000", " ").replace("_", " ")
    text = re.sub(r"\bNo\.(?=\d)", "No<<DOT>>", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<=\w)\.(?=\w)", " ", text)
    text = text.replace("No<<DOT>>", "No.")
    text = strip_bracket_noise(text)
    text = strip_release_words(text)
    return collapse_spaces(text.strip(" -_.~"))


def extract_book_lookup_query(file_name: str) -> str:
    stem = Path(file_name).stem
    return clean_file_stem(file_name) or collapse_spaces(stem.strip(" -_.~"))


def weak_file_name_query(file_name: str) -> bool:
    query = normalize_for_match(extract_book_lookup_query(file_name))
    if not query:
        return True
    if query.isdigit():
        return True
    return len(query) <= 3


def identity_query_for_path(path: Path, hint: str | None) -> str:
    file_query = extract_book_lookup_query(path.name)
    if not hint or not weak_file_name_query(path.name):
        return file_query
    lines = re.split(r"[\r\n。！？?]", hint)
    candidates = [collapse_spaces(line) for line in lines if 4 <= len(collapse_spaces(line)) <= 80]
    if candidates:
        return candidates[0]
    return hint[:120] or file_query


def parse_volume_number(value: str) -> int | None:
    path_value = Path(value)
    raw_text = path_value.stem if path_value.suffix else value
    text = unicodedata.normalize("NFKC", raw_text)
    patterns = [
        r"(?:第\s*)?([0-9]{1,3})\s*[卷册集部]",
        r"(?:vol(?:ume)?|book|v)\.?\s*([0-9]{1,3})",
        r"[\(（]\s*([0-9]{1,3})\s*[\)）]",
        r"(?<!No\.)[\s._\-–—~～]+([0-9]{1,3})(?:\s+.+)?$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            try:
                return int(match.group(1).lstrip("0") or "0")
            except ValueError:
                return None
    return None


def title_has_volume(value: str, volume_number: int | None) -> bool:
    if volume_number is None:
        return False
    text = unicodedata.normalize("NFKC", value)
    number = str(volume_number)
    padded = f"{volume_number:02d}"
    patterns = [
        rf"(?:第\s*)0*{number}\s*[卷册集部]",
        rf"(?:vol(?:ume)?|book|v)\.?\s*0*{number}\b",
        rf"[\(（]\s*0*{number}\s*[\)）]",
        rf"[\s._\-–—~～]+(?:{number}|{padded})(?:\s|$)",
    ]
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def extract_series_guess(file_name: str) -> str:
    stem = Path(file_name).stem
    text = extract_book_lookup_query(file_name)

    volume_patterns = [
        rf"^(?P<title>.+?)[\s._\-–—~～]*(?:第\s*{VOLUME_TOKEN}\s*[卷册集部].*)$",
        rf"^(?P<title>.+?)[\s._\-–—~～]*(?:[卷册集部]\s*{VOLUME_TOKEN}.*)$",
        r"^(?P<title>.+?)[\s._\-–—~～]*(?:(?:vol(?:ume)?|book|v)\.?\s*[0-9０-９]{1,3}.*)$",
        r"^(?P<title>.+?)[\s._\-–—~～]+(?:[0-9０-９]{1,3})(?:\s+.+)?$",
    ]

    for pattern in volume_patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = collapse_spaces(match.group("title").strip(" -_.~"))
            if candidate:
                text = candidate
                break

    text = strip_bracket_noise(text)
    text = collapse_spaces(text.strip(" -_.~"))
    return text or collapse_spaces(stem.strip(" -_.~")) or "未命名系列"


def safe_folder_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", value)
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    text = re.sub(r"_+", "_", text)
    if not text:
        text = "未命名系列"
    reserved_stem = text.partition(".")[0].casefold()
    if reserved_stem in {
        "con",
        "prn",
        "aux",
        "nul",
        "clock$",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
    }:
        text = f"_{text}"
    return text[:SERIES_NAME_MAX_CHARS].rstrip(" .")


def score_title(query: str, candidate: str) -> float:
    normalized_query = normalize_for_match(query)
    normalized_candidate = normalize_for_match(candidate)
    if not normalized_query or not normalized_candidate:
        return 0.0
    if normalized_query == normalized_candidate:
        return 1.0
    ratio = SequenceMatcher(None, normalized_query, normalized_candidate).ratio()
    if normalized_query in normalized_candidate or normalized_candidate in normalized_query:
        containment = min(len(normalized_query), len(normalized_candidate)) / max(
            len(normalized_query), len(normalized_candidate)
        )
        ratio = max(ratio, 0.78 + containment * 0.2)
    return min(ratio, 1.0)


def acceptance_threshold(query: str) -> float:
    length = len(normalize_for_match(query))
    if length <= 3:
        return 0.92
    if length <= 6:
        return 0.84
    return 0.74
