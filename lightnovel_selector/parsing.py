from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path

from .constants import (
    GLOBAL_RELEASE_WORDS,
    NOISE_TAG_WORDS,
    SERIES_NAME_MAX_CHARS,
    SUPPORTED_EXTENSIONS,
    VOLUME_TOKEN,
)


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


def normalize_language_code(value: str) -> str | None:
    text = collapse_spaces(unicodedata.normalize("NFKC", value)).casefold().replace("_", "-")
    aliases = {
        "chs": "zh-Hans",
        "cn": "zh-Hans",
        "简中": "zh-Hans",
        "简体": "zh-Hans",
        "简体中文": "zh-Hans",
        "zh-cn": "zh-Hans",
        "zh-hans": "zh-Hans",
        "cht": "zh-Hant",
        "繁中": "zh-Hant",
        "繁体": "zh-Hant",
        "繁體": "zh-Hant",
        "繁体中文": "zh-Hant",
        "繁體中文": "zh-Hant",
        "zh-hk": "zh-Hant",
        "zh-mo": "zh-Hant",
        "zh-tw": "zh-Hant",
        "zh-hant": "zh-Hant",
        "日文": "ja",
        "日语": "ja",
        "日語": "ja",
        "日本語": "ja",
        "jp": "ja",
        "jpn": "ja",
        "ja-jp": "ja",
        "英文": "en",
        "英语": "en",
        "英語": "en",
        "english": "en",
        "eng": "en",
        "en-us": "en",
        "en-gb": "en",
        "韩文": "ko",
        "韓文": "ko",
        "韩语": "ko",
        "韓語": "ko",
        "kr": "ko",
        "kor": "ko",
        "ko-kr": "ko",
    }
    if text in aliases:
        return aliases[text]
    if re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})*", text):
        return text
    return None


def infer_language(*values: str | None) -> str | None:
    text = " ".join(value for value in values if value)
    normalized = unicodedata.normalize("NFKC", text)
    explicit_patterns = (
        r"(?<![a-z])(?:zh[-_](?:cn|hans)|chs)(?![a-z])",
        r"简体中文|简体|简中",
        r"(?<![a-z])(?:zh[-_](?:tw|hk|mo|hant)|cht)(?![a-z])",
        r"繁體中文|繁体中文|繁體|繁体|繁中",
        r"(?<![a-z])(?:ja[-_]jp|jpn|jp)(?![a-z])|日本語|日语|日語|日文",
        r"(?<![a-z])(?:en[-_](?:us|gb)|eng)(?![a-z])|英语|英語|英文",
        r"(?<![a-z])(?:ko[-_]kr|kor|kr)(?![a-z])|韩语|韓語|韩文|韓文",
    )
    for pattern in explicit_patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return normalize_language_code(match.group(0))

    kana_count = sum("\u3040" <= char <= "\u30ff" for char in normalized)
    hangul_count = sum("\uac00" <= char <= "\ud7af" for char in normalized)
    han_chars = [char for char in normalized if "\u3400" <= char <= "\u9fff"]
    latin_count = sum(char.isascii() and char.isalpha() for char in normalized)
    if kana_count >= 2:
        return "ja"
    if hangul_count >= 2:
        return "ko"
    if len(han_chars) >= 20:
        traditional_markers = set("體臺灣與為這個來說裡後時點書學國會發現開關")
        simplified_markers = set("体台湾与为这个来说里后时点书学国会发现开关")
        traditional_score = sum(char in traditional_markers for char in han_chars)
        simplified_score = sum(char in simplified_markers for char in han_chars)
        if traditional_score > simplified_score:
            return "zh-Hant"
        if simplified_score > traditional_score:
            return "zh-Hans"
        return "zh"
    if latin_count >= 80 and not han_chars:
        return "en"
    return None


def parse_volume_number(value: str) -> int | None:
    path_value = Path(value)
    raw_text = path_value.stem if path_value.suffix.casefold() in SUPPORTED_EXTENSIONS else value
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
        r"^(?P<title>.+?)[\s._\-–—~～]*[\(（]\s*[0-9０-９]{1,3}\s*[\)）].*$",
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
