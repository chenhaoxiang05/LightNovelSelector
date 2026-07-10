from __future__ import annotations

import argparse
import fnmatch
import hashlib
import io
import json
import os
import posixpath
import queue
import re
import shutil
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable
from xml.etree import ElementTree


APP_NAME = "Light Novel Selector"
APP_VERSION = "1.3.0"
USER_AGENT = f"LightNovelSelector/{APP_VERSION} (+local-file-classifier)"
BANGUMI_SEARCH_URL = "https://api.bgm.tv/v0/search/subjects"
BANGUMI_SUBJECT_WEB_URL = "https://bgm.tv/subject/{subject_id}"
BANGUMI_SEARCH_LIMIT = 20
BANGUMI_DETAIL_PAGES = 4
LOCAL_COVER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
METADATA_CACHE_VERSION = 1
METADATA_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30
CONTENT_HINT_MAX_CHARS = 5000
CONTENT_HINT_TEXT_EXTENSIONS = {".txt", ".md", ".html", ".htm"}
METADATA_PRELOAD_WORKERS = 4
FILE_FINGERPRINT_CHUNK_SIZE = 1024 * 1024
REPORT_FILE_NAME = "classification_report.json"
SETTINGS_FILE_NAME = "settings.json"

SUPPORTED_EXTENSIONS = {
    ".txt",
    ".epub",
    ".pdf",
    ".mobi",
    ".azw",
    ".azw3",
    ".fb2",
    ".doc",
    ".docx",
    ".rtf",
    ".md",
    ".html",
    ".htm",
    ".cbz",
    ".cbr",
    ".zip",
    ".rar",
    ".7z",
}

NOISE_TAG_WORDS = {
    "epub",
    "txt",
    "pdf",
    "mobi",
    "azw",
    "azw3",
    "kindle",
    "ocr",
    "web",
    "raw",
    "scan",
    "scans",
    "illustration",
    "illustrations",
    "cover",
    "color",
    "complete",
    "completed",
    "light novel",
    "lightnovel",
    "novel",
    "ln",
    "简体",
    "繁体",
    "简中",
    "繁中",
    "台版",
    "日版",
    "大陆版",
    "轻小说",
    "文库",
    "插图",
    "扫图",
    "校对",
    "自购",
    "录入",
    "整理",
    "完结",
    "全集",
    "全本",
    "连载",
    "汉化",
}

GLOBAL_RELEASE_WORDS = NOISE_TAG_WORDS - {
    "light novel",
    "lightnovel",
    "novel",
    "ln",
    "轻小说",
    "文库",
}

CHINESE_NUMERAL = "零〇一二两三四五六七八九十百千"
VOLUME_TOKEN = rf"[0-9０-９{CHINESE_NUMERAL}]+"


@dataclass(frozen=True)
class ResolveResult:
    series_name: str
    source: str
    confidence: float
    local_guess: str
    metadata_title: str | None = None
    metadata_summary: str | None = None
    metadata_cover_url: str | None = None
    metadata_url: str | None = None


@dataclass(frozen=True)
class BookMetadata:
    title: str
    source: str
    confidence: float
    query: str
    summary: str | None = None
    cover_url: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class CustomRule:
    pattern: str
    series: str


@dataclass(frozen=True)
class AppSettings:
    use_network: bool = True
    recursive: bool = False
    auto_rename: bool = False
    custom_rules: tuple[CustomRule, ...] = ()


def book_metadata_to_dict(metadata: BookMetadata) -> dict:
    return {
        "title": metadata.title,
        "source": metadata.source,
        "confidence": metadata.confidence,
        "query": metadata.query,
        "summary": metadata.summary,
        "cover_url": metadata.cover_url,
        "url": metadata.url,
    }


def book_metadata_from_dict(data: dict) -> BookMetadata | None:
    try:
        return BookMetadata(
            title=str(data["title"]),
            source=str(data.get("source") or "Bangumi"),
            confidence=float(data.get("confidence") or 0.0),
            query=str(data.get("query") or data["title"]),
            summary=data.get("summary"),
            cover_url=data.get("cover_url"),
            url=data.get("url"),
        )
    except (KeyError, TypeError, ValueError):
        return None


def resolve_result_to_dict(result: ResolveResult) -> dict:
    return {
        "series_name": result.series_name,
        "source": result.source,
        "confidence": result.confidence,
        "local_guess": result.local_guess,
        "metadata_title": result.metadata_title,
        "metadata_summary": result.metadata_summary,
        "metadata_cover_url": result.metadata_cover_url,
        "metadata_url": result.metadata_url,
    }


def resolve_result_from_dict(data: dict) -> ResolveResult | None:
    try:
        return ResolveResult(
            series_name=str(data["series_name"]),
            source=str(data.get("source") or "缓存"),
            confidence=float(data.get("confidence") or 0.0),
            local_guess=str(data.get("local_guess") or data["series_name"]),
            metadata_title=data.get("metadata_title"),
            metadata_summary=data.get("metadata_summary"),
            metadata_cover_url=data.get("metadata_cover_url"),
            metadata_url=data.get("metadata_url"),
        )
    except (KeyError, TypeError, ValueError):
        return None


def metadata_cache_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        root = Path(base) / "LightNovelSelector"
    else:
        root = Path.home() / ".lightnovel_selector"
    return root / "metadata_cache.json"


def app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "LightNovelSelector"
    return Path.home() / ".lightnovel_selector"


def settings_path() -> Path:
    return app_data_dir() / SETTINGS_FILE_NAME


def write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def app_settings_from_dict(data: dict) -> AppSettings:
    rules = []
    for item in data.get("custom_rules") or []:
        if not isinstance(item, dict):
            continue
        pattern = collapse_spaces(str(item.get("pattern") or ""))
        series = collapse_spaces(str(item.get("series") or ""))
        if pattern and series:
            rules.append(CustomRule(pattern=pattern, series=series))
    return AppSettings(
        use_network=bool(data.get("use_network", True)),
        recursive=bool(data.get("recursive", False)),
        auto_rename=bool(data.get("auto_rename", False)),
        custom_rules=tuple(rules),
    )


def app_settings_to_dict(settings: AppSettings) -> dict:
    return {
        "use_network": settings.use_network,
        "recursive": settings.recursive,
        "auto_rename": settings.auto_rename,
        "custom_rules": [
            {"pattern": rule.pattern, "series": rule.series}
            for rule in settings.custom_rules
        ],
    }


def load_app_settings(path: Path | None = None) -> AppSettings:
    path = path or settings_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppSettings()
    if not isinstance(raw, dict):
        return AppSettings()
    return app_settings_from_dict(raw)


def save_app_settings(settings: AppSettings, path: Path | None = None) -> None:
    path = path or settings_path()
    write_json_atomic(path, app_settings_to_dict(settings))


def try_save_app_settings(settings: AppSettings, path: Path | None = None) -> OSError | None:
    try:
        save_app_settings(settings, path)
    except OSError as exc:
        return exc
    return None


class PersistentMetadataCache:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or metadata_cache_path()
        self.lock = threading.Lock()
        self.data = self._load()

    def _load(self) -> dict:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        if raw.get("version") != METADATA_CACHE_VERSION:
            return {"version": METADATA_CACHE_VERSION, "entries": {}}
        entries = raw.get("entries")
        if not isinstance(entries, dict):
            entries = {}
        return {"version": METADATA_CACHE_VERSION, "entries": entries}

    def _save(self) -> None:
        try:
            write_json_atomic(self.path, self.data)
        except OSError:
            pass

    def get(self, key: str) -> dict | None:
        with self.lock:
            entry = self.data.get("entries", {}).get(key)
            if not isinstance(entry, dict):
                return None
            try:
                cached_at = float(entry.get("cached_at") or 0)
            except (TypeError, ValueError):
                self.data["entries"].pop(key, None)
                self._save()
                return None
            if time.time() - cached_at > METADATA_CACHE_TTL_SECONDS:
                self.data["entries"].pop(key, None)
                self._save()
                return None
            payload = entry.get("payload")
            return payload if isinstance(payload, dict) else None

    def set(self, key: str, payload: dict) -> None:
        with self.lock:
            self.data.setdefault("entries", {})[key] = {
                "cached_at": time.time(),
                "payload": payload,
            }
            self._save()


_PERSISTENT_METADATA_CACHE: PersistentMetadataCache | None = None
_PERSISTENT_METADATA_CACHE_LOCK = threading.Lock()


def get_persistent_metadata_cache() -> PersistentMetadataCache:
    global _PERSISTENT_METADATA_CACHE
    with _PERSISTENT_METADATA_CACHE_LOCK:
        if _PERSISTENT_METADATA_CACHE is None:
            _PERSISTENT_METADATA_CACHE = PersistentMetadataCache()
        return _PERSISTENT_METADATA_CACHE


@dataclass(frozen=True)
class ClassificationPlan:
    source_path: Path
    series_name: str
    target_dir: Path
    target_path: Path
    resolver_source: str
    confidence: float
    local_guess: str
    metadata_title: str | None = None
    metadata_summary: str | None = None
    metadata_cover_url: str | None = None
    metadata_url: str | None = None
    local_cover_bytes: bytes | None = None
    identity_hint: str | None = None
    identity_query: str | None = None
    rename_to: str | None = None
    series_key: str | None = None
    status: str = "ready"
    note: str = ""
    duplicate_of: Path | None = None

    @property
    def will_move(self) -> bool:
        if self.status != "ready":
            return False
        try:
            return self.source_path.resolve() != self.target_path.resolve()
        except OSError:
            return self.source_path != self.target_path

    @property
    def has_warning(self) -> bool:
        return self.status != "ready" or bool(self.note)


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
    except Exception:
        return collapse_spaces(re.sub(r"<[^>]+>", " ", value))


def contains_cjk(value: str) -> bool:
    return any(
        "\u3400" <= char <= "\u9fff"
        or "\u3040" <= char <= "\u30ff"
        or "\uac00" <= char <= "\ud7af"
        for char in value
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
    if re.fullmatch(rf"第?\s*{VOLUME_TOKEN}\s*[卷册集部].*", tag):
        return True
    return False


def strip_bracket_noise(value: str) -> str:
    left_brackets = "[【（("
    right_brackets = "]】）)"

    changed = True
    text = value.strip()
    while changed:
        changed = False
        leading = re.match(rf"^\s*([{re.escape(left_brackets)}])([^]{re.escape(right_brackets)}]{{1,60}})([{re.escape(right_brackets)}])\s*", text)
        if leading and is_noise_tag(leading.group(2), position="leading"):
            text = text[leading.end() :].strip()
            changed = True

        trailing = re.search(rf"\s*([{re.escape(left_brackets)}])([^]{re.escape(right_brackets)}]{{1,60}})([{re.escape(right_brackets)}])\s*$", text)
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
    return text[:120].rstrip(" .")


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


def http_json(url: str, *, payload: dict | None = None, timeout: float = 10.0) -> dict:
    headers = {"User-Agent": USER_AGENT}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset, errors="replace"))


def http_bytes(url: str, *, timeout: float = 10.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def is_image_zip_member(name: str) -> bool:
    suffix = Path(urllib.parse.unquote(name)).suffix.casefold()
    return suffix in LOCAL_COVER_EXTENSIONS and not name.endswith("/")


def resolve_zip_member(base_path: str, href: str) -> str:
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(base_path), href))
    return joined.lstrip("/")


def read_zip_member(zip_file: zipfile.ZipFile, member_name: str) -> bytes | None:
    names = {name.casefold(): name for name in zip_file.namelist()}
    actual_name = names.get(member_name.casefold())
    if not actual_name:
        return None
    try:
        return zip_file.read(actual_name)
    except (KeyError, RuntimeError, zipfile.BadZipFile):
        return None


def pick_archive_cover_name(names: Iterable[str]) -> str | None:
    images = [name for name in names if is_image_zip_member(name)]
    if not images:
        return None
    preferred_words = ("cover", "front", "folder", "title", "表紙", "封面")

    def sort_key(name: str) -> tuple[int, str]:
        base = posixpath.basename(name).casefold()
        preferred = 0 if any(word.casefold() in base for word in preferred_words) else 1
        return preferred, name.casefold()

    return sorted(images, key=sort_key)[0]


def read_epub_cover_bytes(path: Path) -> bytes | None:
    try:
        with zipfile.ZipFile(path) as epub:
            container_xml = epub.read("META-INF/container.xml")
            container = ElementTree.fromstring(container_xml)
            rootfile_path = None
            for element in container.iter():
                if xml_local_name(element.tag) == "rootfile":
                    rootfile_path = element.attrib.get("full-path")
                    if rootfile_path:
                        break
            if not rootfile_path:
                return None

            opf_root = ElementTree.fromstring(epub.read(rootfile_path))
            cover_id = None
            manifest_items: list[dict[str, str]] = []
            for element in opf_root.iter():
                name = xml_local_name(element.tag)
                if name == "meta" and element.attrib.get("name") == "cover":
                    cover_id = element.attrib.get("content")
                elif name == "item":
                    manifest_items.append(dict(element.attrib))

            cover_href = None
            for item in manifest_items:
                properties = item.get("properties", "")
                if "cover-image" in properties.split():
                    cover_href = item.get("href")
                    break
            if not cover_href and cover_id:
                for item in manifest_items:
                    if item.get("id") == cover_id:
                        cover_href = item.get("href")
                        break
            if cover_href:
                data = read_zip_member(epub, resolve_zip_member(rootfile_path, cover_href))
                if data:
                    return data

            image_hrefs = [
                item.get("href", "")
                for item in manifest_items
                if item.get("media-type", "").startswith("image/")
            ]
            fallback_name = pick_archive_cover_name(resolve_zip_member(rootfile_path, href) for href in image_hrefs)
            if fallback_name:
                return read_zip_member(epub, fallback_name)
    except (OSError, KeyError, RuntimeError, zipfile.BadZipFile, ElementTree.ParseError):
        return None
    return None


def decode_bytes(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "big5", "shift_jis"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def read_epub_identity_hint(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path) as epub:
            container = ElementTree.fromstring(epub.read("META-INF/container.xml"))
            rootfile_path = None
            for element in container.iter():
                if xml_local_name(element.tag) == "rootfile":
                    rootfile_path = element.attrib.get("full-path")
                    break
            if not rootfile_path:
                return None

            opf_root = ElementTree.fromstring(epub.read(rootfile_path))
            titles: list[str] = []
            manifest: dict[str, str] = {}
            spine_ids: list[str] = []
            for element in opf_root.iter():
                name = xml_local_name(element.tag)
                if name == "title" and element.text:
                    titles.append(collapse_spaces(element.text))
                elif name == "item":
                    item_id = element.attrib.get("id")
                    href = element.attrib.get("href")
                    media_type = element.attrib.get("media-type", "")
                    if item_id and href and media_type in {"application/xhtml+xml", "text/html"}:
                        manifest[item_id] = resolve_zip_member(rootfile_path, href)
                elif name == "itemref":
                    item_id = element.attrib.get("idref")
                    if item_id:
                        spine_ids.append(item_id)

            text_parts = titles[:3]
            for item_id in spine_ids[:4]:
                member = manifest.get(item_id)
                if not member:
                    continue
                data = read_zip_member(epub, member)
                if not data:
                    continue
                text = html_to_text(decode_bytes(data))
                if text:
                    text_parts.append(text[:1200])
                if sum(len(part) for part in text_parts) >= CONTENT_HINT_MAX_CHARS:
                    break
            hint = collapse_spaces(" ".join(text_parts))
            return hint[:CONTENT_HINT_MAX_CHARS] or None
    except (OSError, KeyError, RuntimeError, zipfile.BadZipFile, ElementTree.ParseError):
        return None


def read_text_identity_hint(path: Path) -> str | None:
    try:
        with path.open("rb") as file:
            data = file.read(16000)
    except OSError:
        return None
    text = decode_bytes(data)
    if path.suffix.casefold() in {".html", ".htm"}:
        text = html_to_text(text)
    hint = collapse_spaces(text)
    return hint[:CONTENT_HINT_MAX_CHARS] or None


def read_identity_hint(path: Path) -> str | None:
    suffix = path.suffix.casefold()
    if suffix == ".epub":
        return read_epub_identity_hint(path)
    if suffix in CONTENT_HINT_TEXT_EXTENSIONS:
        return read_text_identity_hint(path)
    return None


def read_archive_cover_bytes(path: Path) -> bytes | None:
    try:
        with zipfile.ZipFile(path) as archive:
            cover_name = pick_archive_cover_name(archive.namelist())
            if not cover_name:
                return None
            return archive.read(cover_name)
    except (OSError, KeyError, RuntimeError, zipfile.BadZipFile):
        return None


def read_local_cover_bytes(path: Path) -> bytes | None:
    suffix = path.suffix.casefold()
    if suffix == ".epub":
        return read_epub_cover_bytes(path)
    if suffix in {".cbz", ".zip"}:
        return read_archive_cover_bytes(path)
    return None


def file_fingerprint(path: Path) -> str:
    stat = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(FILE_FINGERPRINT_CHUNK_SIZE), b""):
            digest.update(chunk)
    return f"{stat.st_size}:{digest.hexdigest()}"


def file_quick_signature(path: Path) -> str:
    stat = path.stat()
    digest = hashlib.sha256()
    digest.update(str(stat.st_size).encode("ascii"))
    with path.open("rb") as handle:
        digest.update(handle.read(FILE_FINGERPRINT_CHUNK_SIZE))
        if stat.st_size > FILE_FINGERPRINT_CHUNK_SIZE:
            handle.seek(max(0, stat.st_size - FILE_FINGERPRINT_CHUNK_SIZE))
            digest.update(handle.read(FILE_FINGERPRINT_CHUNK_SIZE))
    return f"{stat.st_size}:{digest.hexdigest()}"


def find_duplicate_files(paths: Iterable[Path]) -> dict[Path, Path]:
    candidates: dict[str, list[Path]] = {}
    duplicates: dict[Path, Path] = {}
    for path in paths:
        try:
            signature = file_quick_signature(path)
        except OSError:
            continue
        candidates.setdefault(signature, []).append(path)

    for group in candidates.values():
        if len(group) < 2:
            continue
        seen: dict[str, Path] = {}
        for path in group:
            try:
                fingerprint = file_fingerprint(path)
            except OSError:
                continue
            first_seen = seen.get(fingerprint)
            if first_seen is None:
                seen[fingerprint] = path
            else:
                duplicates[path] = first_seen
    return duplicates


def match_custom_rule(file_name: str, identity_query: str, rules: Iterable[CustomRule]) -> CustomRule | None:
    candidates = [
        file_name,
        Path(file_name).stem,
        identity_query,
        normalize_for_match(file_name),
        normalize_for_match(identity_query),
    ]
    for rule in rules:
        pattern = rule.pattern
        normalized_pattern = normalize_for_match(pattern)
        for candidate in candidates:
            if fnmatch.fnmatchcase(candidate.casefold(), pattern.casefold()):
                return rule
            if normalized_pattern and fnmatch.fnmatchcase(candidate, normalized_pattern):
                return rule
            if normalized_pattern and normalized_pattern in candidate:
                return rule
    return None


def unique_existing(values: Iterable[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value:
            continue
        clean = collapse_spaces(str(value))
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def flatten_bangumi_value(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return flatten_bangumi_value(value.get("v") or value.get("value") or value.get("name"))
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(flatten_bangumi_value(item))
        return result
    return [str(value)]


def bangumi_title_candidates(item: dict) -> list[str]:
    values: list[str | None] = [item.get("name_cn"), item.get("name")]
    for row in item.get("infobox") or []:
        key = str(row.get("key") or "").casefold()
        if any(label in key for label in ("别名", "alias", "title")):
            values.extend(flatten_bangumi_value(row.get("value")))
    return unique_existing(values)


def bangumi_cover_url(item: dict) -> str | None:
    images = item.get("images") or {}
    return (
        images.get("common")
        or images.get("medium")
        or images.get("large")
        or images.get("small")
        or item.get("image")
    )


def clean_summary(value: str | None) -> str | None:
    if not value:
        return None
    lines = [line.strip() for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line).strip() or None


def bangumi_subject_url(item: dict) -> str | None:
    subject_id = item.get("id")
    return BANGUMI_SUBJECT_WEB_URL.format(subject_id=subject_id) if subject_id else None


def bangumi_metadata_from_item(item: dict, *, confidence: float, query: str) -> BookMetadata:
    title = item.get("name_cn") or item.get("name") or query
    return BookMetadata(
        title=title,
        source="Bangumi",
        confidence=confidence,
        query=query,
        summary=clean_summary(item.get("summary")),
        cover_url=bangumi_cover_url(item),
        url=bangumi_subject_url(item),
    )


def bangumi_search_items(query: str, *, timeout: float, pages: int = 1) -> list[dict]:
    payload = {
        "keyword": query,
        "sort": "match",
        "filter": {"type": [1]},
    }
    items: list[dict] = []
    seen_ids: set[int] = set()
    for page in range(max(1, pages)):
        url = BANGUMI_SEARCH_URL
        if pages > 1:
            url += "?" + urllib.parse.urlencode(
                {"limit": BANGUMI_SEARCH_LIMIT, "offset": page * BANGUMI_SEARCH_LIMIT}
            )
        data = http_json(url, payload=payload, timeout=timeout)
        page_items = data.get("data", [])
        for item in page_items:
            subject_id = item.get("id")
            if isinstance(subject_id, int):
                if subject_id in seen_ids:
                    continue
                seen_ids.add(subject_id)
            items.append(item)
        if len(page_items) < BANGUMI_SEARCH_LIMIT:
            break
    return items


def score_bangumi_item_for_detail(
    item: dict,
    *,
    query: str,
    series_name: str,
    volume_number: int | None,
) -> float:
    candidates = bangumi_title_candidates(item)
    if not candidates:
        return 0.0

    base = max(score_title(query, candidate) for candidate in candidates)
    if series_name:
        base = max(base, max(score_title(series_name, candidate) for candidate in candidates) * 0.92)

    candidate_text = " ".join(candidates)
    has_volume = title_has_volume(candidate_text, volume_number)
    platform = str(item.get("platform") or "")

    if volume_number is not None:
        if has_volume:
            base += 0.28
        else:
            base -= 0.18
    if platform == "小说":
        base += 0.08
    elif platform:
        base -= 0.08

    return max(0.0, min(base, 1.0))


def item_matches_volume(item: dict, volume_number: int | None) -> bool:
    if volume_number is None:
        return False
    return title_has_volume(" ".join(bangumi_title_candidates(item)), volume_number)


def suggest_renamed_filename(
    original_path: Path,
    *,
    series_name: str,
    metadata: BookMetadata | None,
    identity_query: str,
) -> str:
    volume_number = None
    if metadata is not None:
        volume_number = parse_volume_number(metadata.title) or parse_volume_number(metadata.query)
    if volume_number is None:
        volume_number = parse_volume_number(identity_query) or parse_volume_number(original_path.name)

    if series_name and volume_number is not None:
        base = f"{series_name} 第{volume_number:02d}卷"
    elif metadata is not None and metadata.title:
        base = metadata.title
    else:
        base = extract_series_guess(identity_query or original_path.name)

    return safe_folder_name(base) + original_path.suffix


class SeriesResolver:
    def __init__(
        self,
        use_network: bool = True,
        timeout: float = 10.0,
        persistent_cache: PersistentMetadataCache | None = None,
    ) -> None:
        self.use_network = use_network
        self.timeout = timeout
        self._cache: dict[str, ResolveResult] = {}
        self.persistent_cache = persistent_cache if persistent_cache is not None else get_persistent_metadata_cache()
        self.last_network_error: str | None = None

    def resolve(self, file_name: str) -> ResolveResult:
        local_guess = extract_series_guess(file_name)
        cache_key = normalize_for_match(local_guess)
        if cache_key in self._cache:
            return self._cache[cache_key]

        result: ResolveResult | None = None
        if self.use_network:
            persistent_key = "series:" + cache_key
            cached_payload = self.persistent_cache.get(persistent_key)
            result = resolve_result_from_dict(cached_payload) if cached_payload else None
            if result is None:
                result = self._resolve_with_network(local_guess)
                if result is not None:
                    self.persistent_cache.set(persistent_key, resolve_result_to_dict(result))

        if result is None:
            suffix = "（联网失败）" if self.last_network_error else ""
            result = ResolveResult(
                series_name=local_guess,
                source=f"本地规则{suffix}",
                confidence=0.55,
                local_guess=local_guess,
            )

        self._cache[cache_key] = result
        return result

    def resolve_book_metadata(self, file_name: str, series_name: str = "") -> BookMetadata | None:
        return self.resolve_book_metadata_for_query(extract_book_lookup_query(file_name), series_name=series_name)

    def resolve_book_metadata_for_query(self, query: str, series_name: str = "") -> BookMetadata | None:
        if not self.use_network:
            return None

        query = collapse_spaces(query)
        if not query:
            return None
        cache_key = "book:" + normalize_for_match(query)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return BookMetadata(
                title=cached.metadata_title or cached.series_name,
                source=cached.source,
                confidence=cached.confidence,
                query=query,
                summary=cached.metadata_summary,
                cover_url=cached.metadata_cover_url,
                url=cached.metadata_url,
            )
        cached_payload = self.persistent_cache.get(cache_key)
        cached_metadata = book_metadata_from_dict(cached_payload) if cached_payload else None
        if cached_metadata is not None:
            self._cache[cache_key] = ResolveResult(
                series_name=cached_metadata.title,
                source=cached_metadata.source,
                confidence=cached_metadata.confidence,
                local_guess=query,
                metadata_title=cached_metadata.title,
                metadata_summary=cached_metadata.summary,
                metadata_cover_url=cached_metadata.cover_url,
                metadata_url=cached_metadata.url,
            )
            return cached_metadata

        volume_number = parse_volume_number(query)
        try:
            items = bangumi_search_items(query, timeout=self.timeout, pages=BANGUMI_DETAIL_PAGES)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            self.last_network_error = f"resolve_book_metadata: {exc}"
            return None

        candidate_items = [item for item in items if item.get("type") == 1]
        if volume_number is not None:
            exact_volume_items = [item for item in candidate_items if item_matches_volume(item, volume_number)]
            if exact_volume_items:
                candidate_items = exact_volume_items

        best: tuple[float, dict] | None = None
        for item in candidate_items:
            score = score_bangumi_item_for_detail(
                item,
                query=query,
                series_name=series_name,
                volume_number=volume_number,
            )
            if volume_number is not None and item_matches_volume(item, volume_number):
                score = max(score, 0.88)
                if str(item.get("platform") or "") == "小说":
                    score = max(score, 0.96)
            if best is None or score > best[0]:
                best = (score, item)

        if best is None:
            return None
        if volume_number is None and best[0] < acceptance_threshold(query):
            return None
        if volume_number is not None and best[0] < 0.68:
            return None

        metadata = bangumi_metadata_from_item(best[1], confidence=best[0], query=query)
        self.persistent_cache.set(cache_key, book_metadata_to_dict(metadata))
        self._cache[cache_key] = ResolveResult(
            series_name=metadata.title,
            source=metadata.source,
            confidence=metadata.confidence,
            local_guess=query,
            metadata_title=metadata.title,
            metadata_summary=metadata.summary,
            metadata_cover_url=metadata.cover_url,
            metadata_url=metadata.url,
        )
        return metadata

    def _resolve_with_network(self, query: str) -> ResolveResult | None:
        for provider in (self._search_bangumi, self._search_anilist, self._search_jikan):
            try:
                result = provider(query)
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                self.last_network_error = f"{provider.__name__}: {exc}"
                result = None
            if result is not None:
                return result
        return None

    def _search_bangumi(self, query: str) -> ResolveResult | None:
        items = bangumi_search_items(query, timeout=self.timeout)
        best: tuple[float, str, dict] | None = None

        for item in items:
            if item.get("type") != 1:
                continue
            candidates = bangumi_title_candidates(item)
            for candidate in candidates:
                score = score_title(query, candidate)
                if str(item.get("platform") or "") == "小说":
                    score = min(1.0, score + 0.02)
                if best is None or score > best[0]:
                    best = (score, candidate, item)

        if best is None or best[0] < acceptance_threshold(query):
            return None

        item = best[2]
        display_title = item.get("name_cn") or item.get("name") or best[1]
        return ResolveResult(
            series_name=safe_folder_name(display_title),
            source="Bangumi",
            confidence=best[0],
            local_guess=query,
            metadata_title=display_title,
            metadata_summary=clean_summary(item.get("summary")),
            metadata_cover_url=bangumi_cover_url(item),
            metadata_url=bangumi_subject_url(item),
        )

    def _search_anilist(self, query: str) -> ResolveResult | None:
        graphql = """
        query ($search: String) {
          Page(page: 1, perPage: 8) {
            media(search: $search, type: MANGA, format_in: [NOVEL]) {
              id
              format
              title {
                romaji
                english
                native
              }
              synonyms
            }
          }
        }
        """
        data = http_json(
            "https://graphql.anilist.co",
            payload={"query": graphql, "variables": {"search": query}},
            timeout=self.timeout,
        )
        media_items = data.get("data", {}).get("Page", {}).get("media", [])
        best: tuple[float, str, dict] | None = None
        for item in media_items:
            titles = item.get("title") or {}
            candidates = unique_existing(
                [
                    titles.get("english"),
                    titles.get("romaji"),
                    titles.get("native"),
                    *(item.get("synonyms") or []),
                ]
            )
            for candidate in candidates:
                score = score_title(query, candidate)
                if best is None or score > best[0]:
                    best = (score, candidate, item)

        if best is None or best[0] < acceptance_threshold(query):
            return None

        titles = best[2].get("title") or {}
        canonical = titles.get("english") or titles.get("romaji") or titles.get("native") or best[1]
        return ResolveResult(
            series_name=safe_folder_name(canonical),
            source="AniList",
            confidence=best[0],
            local_guess=query,
        )

    def _search_jikan(self, query: str) -> ResolveResult | None:
        url = "https://api.jikan.moe/v4/manga?" + urllib.parse.urlencode(
            {"q": query, "limit": 8, "type": "lightnovel"}
        )
        data = http_json(url, timeout=self.timeout)
        best: tuple[float, str, dict] | None = None
        for item in data.get("data", []):
            title_values = [
                item.get("title_english"),
                item.get("title"),
                item.get("title_japanese"),
            ]
            for title in item.get("titles") or []:
                title_values.append(title.get("title"))
            candidates = unique_existing(title_values)
            for candidate in candidates:
                score = score_title(query, candidate)
                if best is None or score > best[0]:
                    best = (score, candidate, item)

        if best is None or best[0] < acceptance_threshold(query):
            return None

        canonical = best[2].get("title_english") or best[2].get("title") or best[1]
        return ResolveResult(
            series_name=safe_folder_name(canonical),
            source="Jikan",
            confidence=best[0],
            local_guess=query,
        )


def find_novel_files(root: Path, recursive: bool = False) -> list[Path]:
    iterator = root.rglob("*") if recursive else root.iterdir()
    files = [
        path
        for path in iterator
        if path.is_file() and path.suffix.casefold() in SUPPORTED_EXTENSIONS
    ]
    return sorted(files, key=lambda item: item.name.casefold())


def unique_target_path(target_path: Path, reserved: set[Path]) -> Path:
    normalized = target_path.resolve() if target_path.exists() else target_path.absolute()
    if not target_path.exists() and normalized not in reserved:
        reserved.add(normalized)
        return target_path

    stem = target_path.stem
    suffix = target_path.suffix
    parent = target_path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        normalized_candidate = candidate.resolve() if candidate.exists() else candidate.absolute()
        if not candidate.exists() and normalized_candidate not in reserved:
            reserved.add(normalized_candidate)
            return candidate
        counter += 1


def classification_plan_to_report_item(
    plan: ClassificationPlan,
    *,
    actual_target_path: Path | None = None,
) -> dict:
    return {
        "source_path": str(plan.source_path),
        "target_path": str(plan.target_path),
        "actual_target_path": str(actual_target_path) if actual_target_path else None,
        "series_name": plan.series_name,
        "resolver_source": plan.resolver_source,
        "confidence": round(plan.confidence, 4),
        "status": plan.status,
        "operation": "moved" if actual_target_path else "skipped",
        "note": plan.note,
        "duplicate_of": str(plan.duplicate_of) if plan.duplicate_of else None,
        "rename_to": plan.rename_to,
        "metadata_title": plan.metadata_title,
        "metadata_url": plan.metadata_url,
    }


def write_classification_report(
    plans: list[ClassificationPlan],
    report_path: Path,
    *,
    moved: int,
    skipped: int,
    actual_targets: dict[Path, Path] | None = None,
) -> None:
    actual_targets = actual_targets or {}
    report = {
        "app": APP_NAME,
        "version": APP_VERSION,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "summary": {
            "total": len(plans),
            "moved": moved,
            "skipped": skipped,
            "duplicates": sum(1 for plan in plans if plan.status == "duplicate"),
            "errors": sum(1 for plan in plans if plan.status == "error"),
        },
        "items": [
            classification_plan_to_report_item(plan, actual_target_path=actual_targets.get(plan.source_path))
            for plan in plans
        ],
    }
    write_json_atomic(report_path, report)


def build_classification_plan(
    root: Path,
    *,
    recursive: bool = False,
    use_network: bool = True,
    auto_rename: bool = False,
    custom_rules: Iterable[CustomRule] | None = None,
    progress: Callable[[str], None] | None = None,
) -> list[ClassificationPlan]:
    root = root.expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"大文件夹不存在：{root}")
    if not root.is_dir():
        raise NotADirectoryError(f"不是文件夹：{root}")

    files = find_novel_files(root, recursive=recursive)
    duplicates = find_duplicate_files(files)
    rules = tuple(custom_rules or ())
    resolver = SeriesResolver(use_network=use_network)
    plans: list[ClassificationPlan] = []
    reserved_targets: set[Path] = set()

    for index, path in enumerate(files, start=1):
        if progress:
            progress(f"[{index}/{len(files)}] 识别：{path.name}")
        duplicate_of = duplicates.get(path)
        if duplicate_of is not None:
            local_guess = extract_series_guess(path.name)
            folder_name = safe_folder_name(local_guess)
            plans.append(
                ClassificationPlan(
                    source_path=path,
                    series_name=folder_name,
                    target_dir=root / folder_name,
                    target_path=path,
                    resolver_source="重复文件检测",
                    confidence=1.0,
                    local_guess=local_guess,
                    identity_query=extract_book_lookup_query(path.name),
                    series_key=folder_name,
                    status="duplicate",
                    note=f"与 {duplicate_of.name} 内容重复，默认跳过。",
                    duplicate_of=duplicate_of,
                )
            )
            continue

        try:
            identity_hint = read_identity_hint(path)
            identity_query = identity_query_for_path(path, identity_hint)
            custom_rule = match_custom_rule(path.name, identity_query, rules)
            if custom_rule is not None:
                result = ResolveResult(
                    series_name=safe_folder_name(custom_rule.series),
                    source="自定义规则",
                    confidence=1.0,
                    local_guess=identity_query,
                )
            else:
                result = resolver.resolve(identity_query)
            folder_name = safe_folder_name(result.series_name)
            target_dir = root / folder_name
            metadata = None
            rename_to = None
            target_name = path.name
            if auto_rename and use_network:
                metadata = resolver.resolve_book_metadata_for_query(identity_query, series_name=folder_name)
                rename_to = suggest_renamed_filename(
                    path,
                    series_name=folder_name,
                    metadata=metadata,
                    identity_query=identity_query,
                )
                target_name = rename_to
            proposed_target_path = target_dir / target_name
            try:
                already_classified = path.resolve() == proposed_target_path.resolve()
            except OSError:
                already_classified = path.absolute() == proposed_target_path.absolute()
            if already_classified:
                target_path = path
                status = "unchanged"
                note = "文件已在正确的系列目录中，无需移动。"
            else:
                target_path = unique_target_path(proposed_target_path, reserved_targets)
                status = "ready"
                note = ""
            plans.append(
                ClassificationPlan(
                    source_path=path,
                    series_name=folder_name,
                    target_dir=target_dir,
                    target_path=target_path,
                    resolver_source=result.source,
                    confidence=result.confidence,
                    local_guess=result.local_guess,
                    metadata_title=(metadata.title if metadata else result.metadata_title),
                    metadata_summary=(metadata.summary if metadata else result.metadata_summary),
                    metadata_cover_url=(metadata.cover_url if metadata else result.metadata_cover_url),
                    metadata_url=(metadata.url if metadata else result.metadata_url),
                    local_cover_bytes=read_local_cover_bytes(path),
                    identity_hint=identity_hint,
                    identity_query=identity_query,
                    rename_to=rename_to,
                    series_key=folder_name,
                    status=status,
                    note=note,
                )
            )
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            local_guess = extract_series_guess(path.name)
            folder_name = safe_folder_name(local_guess)
            plans.append(
                ClassificationPlan(
                    source_path=path,
                    series_name=folder_name,
                    target_dir=root / folder_name,
                    target_path=path,
                    resolver_source="文件读取失败",
                    confidence=0.0,
                    local_guess=local_guess,
                    identity_query=extract_book_lookup_query(path.name),
                    series_key=folder_name,
                    status="error",
                    note=str(exc),
                )
            )

    return plans


def execute_classification_plan(
    plans: list[ClassificationPlan],
    *,
    progress: Callable[[str], None] | None = None,
    progress_count: Callable[[int, int], None] | None = None,
    report_path: Path | None = None,
) -> tuple[int, int]:
    moved = 0
    skipped = 0
    actual_targets: dict[Path, Path] = {}
    if report_path is not None:
        write_classification_report(plans, report_path, moved=0, skipped=0, actual_targets=actual_targets)
    try:
        for index, plan in enumerate(plans, start=1):
            if not plan.will_move:
                skipped += 1
                if progress_count:
                    progress_count(index, len(plans))
                continue
            if progress:
                progress(f"[{index}/{len(plans)}] 移动：{plan.source_path.name} -> {plan.target_dir.name}")
            plan.target_dir.mkdir(parents=True, exist_ok=True)
            final_target = unique_target_path(plan.target_path, set()) if plan.target_path.exists() else plan.target_path
            shutil.move(str(plan.source_path), str(final_target))
            actual_targets[plan.source_path] = final_target
            moved += 1
            if progress_count:
                progress_count(index, len(plans))
    except Exception:
        if report_path is not None:
            write_classification_report(plans, report_path, moved=moved, skipped=skipped, actual_targets=actual_targets)
        raise
    if report_path is not None:
        write_classification_report(plans, report_path, moved=moved, skipped=skipped, actual_targets=actual_targets)
    return moved, skipped


def undo_classification_report(
    report_path: Path,
    *,
    progress: Callable[[str], None] | None = None,
    progress_count: Callable[[int, int], None] | None = None,
) -> tuple[int, int]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError("撤销报告格式无效：根节点必须是对象。")
    items = report.get("items") or []
    if not isinstance(items, list):
        raise ValueError("撤销报告格式无效：items 必须是数组。")
    moved_items = [
        item
        for item in reversed(items)
        if isinstance(item, dict) and item.get("operation") == "moved"
    ]
    restored = 0
    skipped = 0
    for index, item in enumerate(moved_items, start=1):
        source_path = Path(str(item.get("source_path") or ""))
        target_path = Path(str(item.get("actual_target_path") or item.get("target_path") or ""))
        if not target_path.exists() or source_path.exists():
            skipped += 1
            if progress_count:
                progress_count(index, len(moved_items))
            continue
        if progress:
            progress(f"撤销：{target_path.name} -> {source_path}")
        source_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target_path), str(source_path))
        restored += 1
        try:
            if not any(target_path.parent.iterdir()):
                target_path.parent.rmdir()
        except OSError:
            pass
        if progress_count:
            progress_count(index, len(moved_items))
    return restored, skipped


def plan_status_label(status: str) -> str:
    return {
        "ready": "可执行",
        "duplicate": "重复",
        "error": "错误",
        "moved": "已移动",
        "unchanged": "无需移动",
    }.get(status, status)


def count_plan_statuses(plans: Iterable[ClassificationPlan]) -> dict[str, int]:
    counts = {"total": 0, "ready": 0, "duplicate": 0, "error": 0}
    for plan in plans:
        counts["total"] += 1
        if plan.status in counts:
            counts[plan.status] += 1
    return counts


def print_plan(plans: list[ClassificationPlan]) -> None:
    if not plans:
        print("没有找到可分类的小说文件。")
        return
    for plan in plans:
        marker = "MOVE" if plan.will_move else "SKIP"
        note = f"\t{plan.note}" if plan.note else ""
        print(
            f"{marker}\t{plan.source_path.name}\t=>\t{plan.target_dir.name}\\{plan.target_path.name}"
            f"\t[{plan.resolver_source}, {plan.confidence:.0%}]{note}"
        )


def run_cli(args: argparse.Namespace) -> int:
    root = Path(args.folder)
    settings = load_app_settings()
    plans = build_classification_plan(
        root,
        recursive=args.recursive,
        use_network=not args.no_network,
        auto_rename=args.auto_rename,
        custom_rules=settings.custom_rules,
        progress=None if args.quiet else print,
    )
    print_plan(plans)
    if args.dry_run:
        return 0
    report_path = root / REPORT_FILE_NAME
    moved, skipped = execute_classification_plan(
        plans,
        progress=None if args.quiet else print,
        report_path=report_path,
    )
    print(f"完成：移动 {moved} 个文件，跳过 {skipped} 个文件。")
    print(f"报告：{report_path}")
    return 0


def launch_gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk
    from tkinter.scrolledtext import ScrolledText

    try:
        from PIL import Image, ImageTk
    except ImportError:
        Image = None
        ImageTk = None

    COLORS = {
        "bg": "#090b10",
        "panel": "#171b24",
        "sidebar": "#0d1016",
        "sidebar_active": "#1c2733",
        "card": "#121720",
        "card_alt": "#171e29",
        "card_hover": "#1d2835",
        "border": "#303b4a",
        "separator": "#242d3a",
        "muted": "#a6b1c0",
        "text": "#f4f7fb",
        "accent": "#4cc9f0",
        "accent_soft": "#123543",
        "accent_dark": "#22afd8",
        "violet": "#b197fc",
        "violet_soft": "#2b2242",
        "file": "#f6ad3c",
        "file_soft": "#3a2a12",
        "warning": "#f6ad3c",
        "warning_soft": "#3a2a12",
        "danger": "#ff6b7a",
        "danger_soft": "#3d1820",
        "ok": "#45d69a",
        "ok_soft": "#15392d",
        "button_text": "#071116",
        "button_secondary": "#202936",
        "button_secondary_hover": "#2b3747",
    }

    FONT_FAMILY = "Segoe UI"
    HERO_FONT = ("Segoe UI", 23, "bold")
    TITLE_FONT = ("Segoe UI", 13, "bold")
    BODY_FONT = ("Segoe UI", 9)
    CAPTION_FONT = ("Segoe UI", 8)
    REDUCED_MOTION = os.environ.get("LN_SELECTOR_REDUCED_MOTION") == "1"

    def ease_out_cubic(t: float) -> float:
        return 1 - pow(1 - t, 3)

    def ease_in_out_quart(t: float) -> float:
        if t < 0.5:
            return 8 * t * t * t * t
        return 1 - pow(-2 * t + 2, 4) / 2

    def ease_out_back(t: float) -> float:
        c1 = 1.70158
        c3 = c1 + 1
        return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)

    class ClassifierApp:
        def __init__(self, master: tk.Tk) -> None:
            self.master = master
            self.master.title("轻小说联网分类工具")
            self.master.geometry("1360x840")
            self.master.minsize(1160, 720)
            self.master.configure(bg=COLORS["bg"])
            self.settings = load_app_settings()
            self.root_var = tk.StringVar()
            self.network_var = tk.BooleanVar(value=self.settings.use_network)
            self.recursive_var = tk.BooleanVar(value=self.settings.recursive)
            self.auto_rename_var = tk.BooleanVar(value=self.settings.auto_rename)
            self.series_filter_var = tk.StringVar(value="全部系列")
            self.status_var = tk.StringVar(value="请选择或新建大文件夹。")
            self.health_var = tk.StringVar(value="待扫描")
            self.action_hint_var = tk.StringVar(value="快捷键：Ctrl+O 选择，F5 扫描，Ctrl+Enter 执行，Ctrl+Z 撤销")
            self.detail_title_var = tk.StringVar(value="Bangumi 信息")
            self.detail_meta_var = tk.StringVar(value="扫描后在右侧选择一本小说。")
            self.detail_file_var = tk.StringVar(value="未选择文件")
            self.detail_status_var = tk.StringVar(value="状态：待扫描")
            self.detail_target_var = tk.StringVar(value="目标：等待预览")
            self.detail_source_var = tk.StringVar(value="来源：无")
            self.plans: list[ClassificationPlan] = []
            self.events: queue.Queue[tuple[str, object]] = queue.Queue()
            self.worker: threading.Thread | None = None
            self.is_busy = False
            self.is_closing = False
            self.active_operation: str | None = None
            self.operation_token = 0
            self.selected_plan_index: int | None = None
            self.cover_bytes_cache: dict[str, bytes | None] = {}
            self.cover_worker_urls: set[str] = set()
            self.cover_lock = threading.Lock()
            self.cover_photo: object | None = None
            self.detail_cache: dict[str, BookMetadata | None] = {}
            self.detail_worker_keys: set[str] = set()
            self.detail_lock = threading.Lock()
            self.scan_token = 0
            self.preload_total = 0
            self.preload_done = 0
            self.metadata_preload_started_token: int | None = None
            self.current_detail_url: str | None = None
            self.progress_display_value = 0.0
            self.progress_maximum = 1.0
            self.progress_label: str | None = None
            self.toast_windows: list[tk.Toplevel] = []
            self.last_report_path: Path | None = None
            self.stat_total_var = tk.StringVar(value="0")
            self.stat_ready_var = tk.StringVar(value="0")
            self.stat_duplicate_var = tk.StringVar(value="0")
            self.stat_error_var = tk.StringVar(value="0")
            self.stat_values = {"total": 0, "ready": 0, "duplicate": 0, "error": 0}
            self.stat_animation_jobs: dict[str, str] = {}
            self.busy_controls: list[object] = []
            self._suspend_preview_invalidation = False
            self.progress_canvas = None
            self.progress_scan_job: str | None = None
            self._configure_style()
            self._build_widgets()
            self._bind_shortcuts()
            self._bind_preview_invalidation()
            self.master.protocol("WM_DELETE_WINDOW", self.on_close)
            if not REDUCED_MOTION:
                self._animate_initial_cards()
            self._refresh_action_states()
            self._poll_events()

        def _configure_style(self) -> None:
            style = ttk.Style(self.master)
            available_themes = set(style.theme_names())
            for preferred_theme in ("clam", "vista", "xpnative", "default"):
                if preferred_theme in available_themes:
                    style.theme_use(preferred_theme)
                    break
            self.master.option_add("*Font", f"{{{FONT_FAMILY}}} 9")
            style.configure(".", background=COLORS["bg"], foreground=COLORS["text"], fieldbackground=COLORS["card"])
            style.configure("App.TFrame", background=COLORS["bg"])
            style.configure("Sidebar.TFrame", background=COLORS["sidebar"])
            style.configure("Card.TFrame", background=COLORS["card"], relief="flat", borderwidth=1, bordercolor=COLORS["separator"])
            style.configure("Toolbar.TFrame", background=COLORS["card"], relief="flat", borderwidth=1, bordercolor=COLORS["separator"])
            style.configure("Card.TLabelframe", background=COLORS["card"], foreground=COLORS["text"], borderwidth=0, bordercolor=COLORS["separator"])
            style.configure("Card.TLabelframe.Label", background=COLORS["card"], foreground=COLORS["text"])
            style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"])
            style.configure("Muted.TLabel", background=COLORS["bg"], foreground=COLORS["muted"])
            style.configure("Card.TLabel", background=COLORS["card"], foreground=COLORS["text"])
            style.configure("CardMuted.TLabel", background=COLORS["card"], foreground=COLORS["muted"])
            style.configure("Section.TLabel", background=COLORS["card"], foreground=COLORS["text"], font=TITLE_FONT)
            style.configure("Toolbar.TLabel", background=COLORS["card"], foreground=COLORS["text"])
            style.configure("StatusIdle.TLabel", background=COLORS["panel"], foreground=COLORS["muted"], padding=(12, 6), font=(FONT_FAMILY, 9, "bold"))
            style.configure("StatusBusy.TLabel", background=COLORS["accent_soft"], foreground=COLORS["accent"], padding=(12, 6), font=(FONT_FAMILY, 9, "bold"))
            style.configure("StatusSuccess.TLabel", background=COLORS["ok_soft"], foreground=COLORS["ok"], padding=(12, 6), font=(FONT_FAMILY, 9, "bold"))
            style.configure("StatusWarning.TLabel", background=COLORS["warning_soft"], foreground=COLORS["warning"], padding=(12, 6), font=(FONT_FAMILY, 9, "bold"))
            style.configure("StatusError.TLabel", background=COLORS["danger_soft"], foreground=COLORS["danger"], padding=(12, 6), font=(FONT_FAMILY, 9, "bold"))
            style.configure("Sidebar.TLabel", background=COLORS["sidebar"], foreground=COLORS["text"])
            style.configure("SidebarMuted.TLabel", background=COLORS["sidebar"], foreground=COLORS["muted"])
            style.configure("Accent.TLabel", background=COLORS["bg"], foreground=COLORS["accent"], font=(FONT_FAMILY, 18, "bold"))
            style.configure("Hero.TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=HERO_FONT)
            style.configure("TEntry", fieldbackground=COLORS["panel"], foreground=COLORS["text"], insertcolor=COLORS["text"], bordercolor=COLORS["border"], lightcolor=COLORS["separator"], darkcolor=COLORS["separator"], padding=(8, 8))
            style.map("TEntry", bordercolor=[("focus", COLORS["accent"])], lightcolor=[("focus", COLORS["accent"])])
            style.configure("TCombobox", fieldbackground=COLORS["panel"], foreground=COLORS["text"], arrowcolor=COLORS["accent"], bordercolor=COLORS["border"], padding=(7, 6))
            style.map("TCombobox", fieldbackground=[("readonly", COLORS["panel"])], foreground=[("readonly", COLORS["text"])])
            style.configure("Treeview", background=COLORS["card"], fieldbackground=COLORS["card"], foreground=COLORS["text"], rowheight=38, borderwidth=0)
            style.configure("Treeview.Heading", background=COLORS["card_alt"], foreground=COLORS["accent"], relief="flat", font=(FONT_FAMILY, 9, "bold"), padding=(8, 8))
            style.map("Treeview", background=[("selected", COLORS["accent_soft"])], foreground=[("selected", COLORS["text"])])

        def _nav_button(self, parent, text: str, command, *, active: bool = False, busy_sensitive: bool = False) -> tk.Button:
            base_bg = COLORS["sidebar_active"] if active else COLORS["sidebar"]
            base_fg = COLORS["accent"] if active else COLORS["muted"]
            button = tk.Button(
                parent,
                text=text,
                bg=base_bg,
                fg=base_fg,
                activebackground=COLORS["sidebar_active"],
                activeforeground=COLORS["text"],
                disabledforeground=COLORS["muted"],
                relief="flat",
                bd=0,
                highlightthickness=2,
                highlightbackground=base_bg,
                highlightcolor=COLORS["accent"],
                takefocus=True,
                padx=16,
                pady=11,
                anchor="w",
                font=(FONT_FAMILY, 10, "bold"),
                cursor="hand2",
                command=lambda: self._button_press_feedback(button, command),
            )
            self._bind_button_hover(button, base_bg, COLORS["sidebar_active"])
            if busy_sensitive:
                self.busy_controls.append(button)
            return button

        def _action_button(
            self,
            parent,
            text: str,
            command,
            *,
            role: str = "secondary",
            busy_sensitive: bool = True,
        ) -> tk.Button:
            palette = {
                "primary": (COLORS["accent"], COLORS["button_text"], "#83def7"),
                "execute": (COLORS["file"], "#211400", "#ffc76b"),
                "danger": (COLORS["danger"], "#26070c", "#ff95a0"),
                "secondary": (COLORS["button_secondary"], COLORS["text"], COLORS["button_secondary_hover"]),
            }
            bg, fg, hover_bg = palette[role]
            button = tk.Button(
                parent,
                text=text,
                bg=bg,
                fg=fg,
                activebackground=hover_bg,
                activeforeground=fg,
                disabledforeground=COLORS["muted"],
                relief="flat",
                bd=0,
                highlightthickness=2,
                highlightbackground=bg,
                highlightcolor=COLORS["accent"],
                takefocus=True,
                padx=18,
                pady=10,
                font=(FONT_FAMILY, 10, "bold"),
                cursor="hand2",
                command=lambda: self._button_press_feedback(button, command),
            )
            self._bind_button_hover(button, bg, hover_bg)
            if busy_sensitive:
                self.busy_controls.append(button)
            return button

        def _checkbutton(
            self,
            parent,
            text: str,
            variable: tk.BooleanVar,
            *,
            busy_sensitive: bool = True,
        ) -> tk.Checkbutton:
            display_var = tk.StringVar()

            def refresh_label(*_args) -> None:
                display_var.set(f"✓  {text}" if variable.get() else f"□  {text}")

            variable.trace_add("write", refresh_label)
            refresh_label()
            checkbutton = tk.Checkbutton(
                parent,
                textvariable=display_var,
                variable=variable,
                indicatoron=False,
                bg=COLORS["card"],
                fg=COLORS["muted"],
                activebackground=COLORS["card_hover"],
                activeforeground=COLORS["text"],
                selectcolor=COLORS["accent_soft"],
                disabledforeground=COLORS["muted"],
                relief="flat",
                bd=0,
                highlightthickness=2,
                highlightbackground=COLORS["card"],
                highlightcolor=COLORS["accent"],
                takefocus=True,
                padx=10,
                pady=7,
                font=(FONT_FAMILY, 9, "bold"),
                cursor="hand2",
                anchor="w",
            )
            if busy_sensitive:
                self.busy_controls.append(checkbutton)
            return checkbutton

        def _bind_button_hover(self, button: tk.Button, base_bg: str, hover_bg: str) -> None:
            def enter(_event) -> None:
                if str(button.cget("state")) != "disabled":
                    button.configure(bg=hover_bg)

            def leave(_event) -> None:
                if str(button.cget("state")) != "disabled":
                    button.configure(bg=base_bg)

            button.bind("<Enter>", enter, add="+")
            button.bind("<Leave>", leave, add="+")

        def _button_press_feedback(self, button, command) -> None:
            if str(button.cget("state")) == "disabled":
                return
            if REDUCED_MOTION:
                command()
                return
            original_bg = button.cget("background")
            button.configure(bg=COLORS["violet"])

            def restore() -> None:
                try:
                    if button.winfo_exists():
                        button.configure(bg=original_bg)
                except tk.TclError:
                    pass

            self.master.after(110, restore)
            command()

        def _bind_shortcuts(self) -> None:
            shortcuts = {
                "<Control-o>": self.select_folder,
                "<F5>": self.scan,
                "<Control-Return>": self.apply_plan,
                "<Control-r>": self.open_last_report,
                "<Control-z>": self.undo_last_report,
            }

            def run(command) -> str:
                command()
                return "break"

            for sequence, command in shortcuts.items():
                self.master.bind_all(sequence, lambda _event, action=command: run(action))

        def _mark_clickable_controls(self, widget) -> None:
            if isinstance(widget, (ttk.Button, tk.Button, tk.Checkbutton)):
                widget.configure(cursor="hand2")
            for child in widget.winfo_children():
                self._mark_clickable_controls(child)

        def _bind_preview_invalidation(self) -> None:
            self.root_var.trace_add("write", self._on_preview_input_changed)
            self.network_var.trace_add("write", self._on_preview_input_changed)
            self.recursive_var.trace_add("write", self._on_preview_input_changed)
            self.auto_rename_var.trace_add("write", self._on_preview_input_changed)

        def _on_preview_input_changed(self, *_args) -> None:
            if self._suspend_preview_invalidation or self.is_busy or not self.plans:
                return
            self._invalidate_preview("目录或识别选项已变化，请重新扫描。")

        def _invalidate_preview(self, reason: str) -> None:
            if not self.plans:
                self._refresh_action_states()
                return
            self.scan_token += 1
            self.plans = []
            self.selected_plan_index = None
            self.metadata_preload_started_token = None
            with self.detail_lock:
                self.detail_cache.clear()
                self.detail_worker_keys.clear()
            self.tree.delete(*self.tree.get_children())
            self.series_filter.configure(values=("全部系列",))
            self.series_filter_var.set("全部系列")
            self.empty_table_label.place(relx=0.5, rely=0.54, anchor="center")
            self.update_stats()
            self.set_progress_idle()
            self.show_empty_detail(reason)
            self._set_phase("需要重新扫描", "warning", reason)
            self.log_message(reason)
            self._refresh_action_states()

        def _set_phase(self, text: str, kind: str = "idle", hint: str | None = None) -> None:
            style_by_kind = {
                "idle": "StatusIdle.TLabel",
                "busy": "StatusBusy.TLabel",
                "success": "StatusSuccess.TLabel",
                "warning": "StatusWarning.TLabel",
                "error": "StatusError.TLabel",
            }
            self.health_var.set(text)
            if hasattr(self, "health_label"):
                self.health_label.configure(style=style_by_kind.get(kind, "StatusIdle.TLabel"))
            if hint is not None:
                self.action_hint_var.set(hint)

        def _begin_operation(self, operation: str) -> int:
            self.operation_token += 1
            self.active_operation = operation
            self._set_busy(True)
            return self.operation_token

        def _finish_operation(self, operation_token: int) -> bool:
            if operation_token != self.operation_token:
                return False
            self.worker = None
            self.active_operation = None
            self._set_busy(False)
            return True

        def _refresh_action_states(self) -> None:
            if not hasattr(self, "apply_button"):
                return
            movable = any(plan.will_move for plan in self.plans)
            selection = self.tree.selection() if hasattr(self, "tree") else ()
            selected_plan = None
            if selection:
                try:
                    selected_index = int(selection[0])
                except ValueError:
                    selected_index = -1
                if 0 <= selected_index < len(self.plans):
                    selected_plan = self.plans[selected_index]
            self.apply_button.configure(state="normal" if movable and not self.is_busy else "disabled")
            can_edit = selected_plan is not None and selected_plan.status != "moved" and not self.is_busy
            self.edit_button.configure(state="normal" if can_edit else "disabled")
            self.series_intro_button.configure(state="normal" if self.plans and not self.is_busy else "disabled")

        def on_close(self) -> None:
            if self.is_closing:
                return
            if self.active_operation in {"apply", "undo"}:
                messagebox.showwarning("任务尚未完成", "正在移动文件或恢复文件。为保证报告完整，请等待任务结束后再关闭。")
                return
            if self.active_operation == "scan" and not messagebox.askyesno(
                "停止扫描",
                "扫描仍在进行。现在关闭不会移动文件，但本次预览会丢失。是否关闭？",
            ):
                return
            self.is_closing = True
            self.operation_token += 1
            self.scan_token += 1
            for toast in list(self.toast_windows):
                try:
                    toast.destroy()
                except tk.TclError:
                    pass
            self.master.destroy()

        def focus_workspace(self) -> None:
            self.action_hint_var.set("工作台：选择目录后按 F5 扫描，确认后按 Ctrl+Enter 执行。")
            self.show_toast("工作台已就绪")

        def open_settings(self) -> None:
            if self.is_busy:
                self.show_toast("任务进行中，请完成后再修改设置", kind="warning")
                return
            dialog = tk.Toplevel(self.master)
            dialog.title("设置")
            dialog.configure(bg=COLORS["bg"])
            dialog.geometry("560x520")
            dialog.minsize(520, 480)
            dialog.transient(self.master)
            dialog.grab_set()
            dialog_network_var = tk.BooleanVar(value=self.network_var.get())
            dialog_recursive_var = tk.BooleanVar(value=self.recursive_var.get())
            dialog_auto_rename_var = tk.BooleanVar(value=self.auto_rename_var.get())
            frame = ttk.Frame(dialog, style="Card.TFrame", padding=22)
            frame.pack(fill="both", expand=True, padx=16, pady=16)
            ttk.Label(frame, text="用户偏好 / SETTINGS", style="Section.TLabel").pack(anchor="w", pady=(0, 6))
            ttk.Label(frame, text="修改只会在点击保存后生效。", style="CardMuted.TLabel").pack(anchor="w", pady=(0, 12))
            option_row = ttk.Frame(frame, style="Card.TFrame")
            option_row.pack(fill="x", pady=(0, 10))
            self._checkbutton(option_row, "联网识别", dialog_network_var, busy_sensitive=False).pack(side="left", padx=(0, 8))
            self._checkbutton(option_row, "包含子文件夹", dialog_recursive_var, busy_sensitive=False).pack(side="left", padx=(0, 8))
            self._checkbutton(option_row, "自动重命名", dialog_auto_rename_var, busy_sensitive=False).pack(side="left")
            ttk.Label(frame, text="自定义规则（每行：匹配模式 => 系列名）", style="Card.TLabel", font=(FONT_FAMILY, 11, "bold")).pack(anchor="w", pady=(16, 6))
            rules_text = ScrolledText(
                frame,
                height=10,
                wrap="word",
                bg=COLORS["panel"],
                fg=COLORS["text"],
                insertbackground=COLORS["text"],
                selectbackground=COLORS["accent_soft"],
                relief="flat",
                borderwidth=0,
                padx=10,
                pady=10,
            )
            rules_text.pack(fill="both", expand=True)
            rules_text.insert(
                "1.0",
                "\n".join(f"{rule.pattern} => {rule.series}" for rule in self.settings.custom_rules),
            )
            ttk.Label(frame, text="示例：*SAO* => Sword Art Online。规则优先于联网识别。", style="CardMuted.TLabel", wraplength=500).pack(anchor="w", pady=(10, 4))
            error_var = tk.StringVar()
            ttk.Label(frame, textvariable=error_var, style="CardMuted.TLabel", foreground=COLORS["danger"]).pack(anchor="w", pady=(0, 8))

            def save_and_close() -> None:
                rules = []
                for raw_line in rules_text.get("1.0", "end").splitlines():
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=>" not in line:
                        error_var.set(f"规则格式不正确：{line}")
                        rules_text.focus_set()
                        return
                    pattern, series = [part.strip() for part in line.split("=>", 1)]
                    if not pattern or not series:
                        error_var.set(f"规则两侧都不能为空：{line}")
                        rules_text.focus_set()
                        return
                    rules.append(CustomRule(pattern=pattern, series=series))
                new_settings = AppSettings(
                    use_network=dialog_network_var.get(),
                    recursive=dialog_recursive_var.get(),
                    auto_rename=dialog_auto_rename_var.get(),
                    custom_rules=tuple(rules),
                )
                changed = new_settings != self.settings
                self._suspend_preview_invalidation = True
                self.network_var.set(new_settings.use_network)
                self.recursive_var.set(new_settings.recursive)
                self.auto_rename_var.set(new_settings.auto_rename)
                self._suspend_preview_invalidation = False
                self.settings = new_settings
                settings_error = try_save_app_settings(self.settings)
                if settings_error is not None:
                    self.show_toast("设置暂未写入磁盘", kind="warning")
                    self.log_message(f"设置保存失败：{settings_error}")
                else:
                    self.show_toast("设置已保存")
                dialog.destroy()
                if changed:
                    self._invalidate_preview("设置已变化，请重新扫描生成预览。")

            actions = ttk.Frame(frame, style="Card.TFrame")
            actions.pack(fill="x")
            self._action_button(actions, "取消", dialog.destroy, busy_sensitive=False).pack(side="right")
            self._action_button(actions, "保存设置", save_and_close, role="primary", busy_sensitive=False).pack(side="right", padx=(0, 8))
            dialog.bind("<Escape>", lambda _event: dialog.destroy())

        def open_last_report(self) -> None:
            report_path = self._find_last_report_path()
            if report_path is None:
                self.show_toast("还没有生成分类报告", kind="warning")
                return
            try:
                os.startfile(report_path)
            except OSError as exc:
                self.show_toast("报告无法打开，请检查文件关联", kind="warning")
                self.log_message(f"报告打开失败：{exc}")

        def _find_last_report_path(self) -> Path | None:
            if self.last_report_path and self.last_report_path.exists():
                return self.last_report_path
            folder = self.root_var.get().strip()
            report_path = Path(folder) / REPORT_FILE_NAME if folder else None
            if report_path and report_path.exists():
                self.last_report_path = report_path
                return report_path
            return None

        def undo_last_report(self) -> None:
            if self.is_busy:
                self.show_toast("当前任务尚未完成", kind="warning")
                return
            report_path = self._find_last_report_path()
            if report_path is None:
                self.show_toast("找不到可撤销的报告", kind="warning")
                return
            try:
                report_data = json.loads(report_path.read_text(encoding="utf-8"))
                if not isinstance(report_data, dict):
                    raise ValueError("报告根节点必须是对象")
                report_items = report_data.get("items") or []
                if not isinstance(report_items, list):
                    raise ValueError("报告 items 必须是数组")
                restore_total = sum(
                    1
                    for item in report_items
                    if isinstance(item, dict) and item.get("operation") == "moved"
                )
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                self.show_toast("撤销报告无法读取", kind="warning")
                self.log_message(f"撤销报告读取失败：{exc}")
                return
            if restore_total == 0:
                self.show_toast("报告中没有可恢复的移动记录", kind="warning")
                return
            if not messagebox.askyesno(
                "确认撤销分类",
                f"将尝试恢复 {restore_total} 个文件。\n\n报告：{report_path}\n\n撤销期间请勿移动相关文件，是否继续？",
            ):
                return
            operation_token = self._begin_operation("undo")
            self._set_phase("正在撤销", "busy", "正在按报告恢复文件，请勿关闭程序。")
            self.set_progress_operation(0, restore_total, "撤销中")
            self.log_message(f"开始撤销：{report_path}")

            def work() -> None:
                try:
                    restored, skipped = undo_classification_report(
                        report_path,
                        progress=lambda msg: self.events.put(("worker_log", (operation_token, msg))),
                        progress_count=lambda done, total: self.events.put(
                            ("operation_progress", (operation_token, "undo", done, total))
                        ),
                    )
                    self.events.put(("undo_done", (operation_token, restored, skipped, report_path)))
                except Exception as exc:
                    self.events.put(("operation_error", (operation_token, "undo", exc, report_path)))

            self.worker = threading.Thread(target=work, daemon=True)
            self.worker.start()

        def _build_widgets(self) -> None:
            self.master.columnconfigure(0, minsize=232)
            self.master.columnconfigure(1, weight=1)
            self.master.rowconfigure(0, weight=1)

            sidebar = ttk.Frame(self.master, style="Sidebar.TFrame", padding=(24, 26))
            sidebar.grid(row=0, column=0, sticky="nsew")
            sidebar.rowconfigure(6, weight=1)
            ttk.Label(sidebar, text="LIGHT NOVEL", style="Sidebar.TLabel", font=(FONT_FAMILY, 18, "bold")).grid(row=0, column=0, sticky="w")
            ttk.Label(sidebar, text="SELECTOR CONSOLE", style="SidebarMuted.TLabel", font=(FONT_FAMILY, 9, "bold")).grid(row=1, column=0, sticky="w", pady=(0, 28))
            self._nav_button(sidebar, "工作台 / 预览", self.focus_workspace, active=True).grid(row=2, column=0, sticky="ew", pady=(0, 8))
            self.settings_nav_button = self._nav_button(sidebar, "设置 / 规则", self.open_settings, busy_sensitive=True)
            self.settings_nav_button.grid(row=3, column=0, sticky="ew", pady=(0, 8))
            self.report_nav_button = self._nav_button(sidebar, "报告 / 打开", self.open_last_report)
            self.report_nav_button.grid(row=4, column=0, sticky="ew", pady=(0, 8))
            self.undo_nav_button = self._nav_button(sidebar, "撤销上次移动", self.undo_last_report, busy_sensitive=True)
            self.undo_nav_button.grid(row=5, column=0, sticky="ew", pady=(0, 8))
            ttk.Label(sidebar, text="SAFE WORKFLOW", style="SidebarMuted.TLabel", font=(FONT_FAMILY, 8, "bold")).grid(row=7, column=0, sticky="w", pady=(24, 2))
            ttk.Label(sidebar, text="先预览，再执行，可撤销", style="SidebarMuted.TLabel").grid(row=8, column=0, sticky="w", pady=(0, 8))
            ttk.Label(sidebar, text=f"v{APP_VERSION}", style="SidebarMuted.TLabel").grid(row=9, column=0, sticky="w")

            self.main_frame = ttk.Frame(self.master, style="App.TFrame", padding=(28, 22))
            self.main_frame.grid(row=0, column=1, sticky="nsew")
            self.main_frame.columnconfigure(0, weight=1)
            self.main_frame.rowconfigure(4, weight=1)

            header = ttk.Frame(self.main_frame, style="App.TFrame")
            header.grid(row=0, column=0, sticky="ew", pady=(0, 18))
            header.columnconfigure(0, weight=1)
            header.columnconfigure(1, weight=0)
            ttk.Label(header, text="轻小说分类控制台", style="Hero.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Label(header, text="识别、校正、归档，每一步都有预览与恢复路径。", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))
            self.health_label = ttk.Label(header, textvariable=self.health_var, style="StatusIdle.TLabel")
            self.health_label.grid(row=0, column=1, rowspan=2, sticky="e", padx=(18, 0))

            top = ttk.Frame(self.main_frame, style="Card.TFrame", padding=(20, 18))
            top.grid(row=1, column=0, sticky="ew", pady=(0, 14))
            top.columnconfigure(1, weight=1)

            ttk.Label(top, text="来源目录 / SOURCE", style="Section.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")
            ttk.Label(top, text="扫描阶段只生成预览，不会移动原文件。执行分类前会再次确认。", style="CardMuted.TLabel").grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 14))
            self.select_folder_button = self._action_button(top, "选择大文件夹", self.select_folder, role="primary")
            self.select_folder_button.grid(row=2, column=0, padx=(0, 10), sticky="w")
            self.root_entry = ttk.Entry(top, textvariable=self.root_var)
            self.root_entry.grid(row=2, column=1, sticky="ew", padx=(0, 8))
            self.busy_controls.append(self.root_entry)
            self.create_folder_button = self._action_button(top, "新建大文件夹", self.create_folder)
            self.create_folder_button.grid(row=2, column=2, padx=(0, 8))
            self.open_folder_button = self._action_button(top, "打开目录", self.open_folder, busy_sensitive=False)
            self.open_folder_button.grid(row=2, column=3)

            stats = ttk.Frame(self.main_frame, style="App.TFrame")
            stats.grid(row=2, column=0, sticky="ew", pady=(0, 14))
            for col in range(4):
                stats.columnconfigure(col, weight=1)
            self._stat_card(stats, "文件总数", self.stat_total_var, "扫描到的支持格式", COLORS["accent"], 0)
            self._stat_card(stats, "可执行", self.stat_ready_var, "确认后会移动", COLORS["ok"], 1)
            self._stat_card(stats, "重复", self.stat_duplicate_var, "默认安全跳过", COLORS["file"], 2)
            self._stat_card(stats, "错误", self.stat_error_var, "需要人工处理", COLORS["danger"], 3)

            options = ttk.Frame(self.main_frame, style="Toolbar.TFrame", padding=(14, 11))
            options.grid(row=3, column=0, sticky="ew", pady=(0, 14))
            options.columnconfigure(0, weight=1)
            option_group = ttk.Frame(options, style="Toolbar.TFrame")
            option_group.grid(row=0, column=0, sticky="w")
            self.network_check = self._checkbutton(option_group, "联网识别", self.network_var)
            self.network_check.pack(side="left", padx=(0, 8))
            self.recursive_check = self._checkbutton(option_group, "包含子文件夹", self.recursive_var)
            self.recursive_check.pack(side="left", padx=(0, 8))
            self.rename_check = self._checkbutton(option_group, "自动重命名", self.auto_rename_var)
            self.rename_check.pack(side="left")
            action_group = ttk.Frame(options, style="Toolbar.TFrame")
            action_group.grid(row=0, column=1, sticky="e")
            self.scan_button = self._action_button(action_group, "扫描并预览", self.scan, role="primary")
            self.scan_button.pack(side="left", padx=(0, 8))
            self.edit_button = self._action_button(action_group, "修正分类", self.edit_selected_plan)
            self.edit_button.pack(side="left", padx=(0, 8))
            self.apply_button = self._action_button(action_group, "执行分类", self.apply_plan, role="execute")
            self.apply_button.pack(side="left")

            content = ttk.Frame(self.main_frame, style="App.TFrame", padding=(0, 0, 0, 8))
            content.grid(row=4, column=0, sticky="nsew")
            content.columnconfigure(0, minsize=318)
            content.columnconfigure(1, weight=1)
            content.rowconfigure(0, weight=1)

            detail_frame = ttk.Frame(content, style="Card.TFrame", padding=(16, 16))
            detail_frame.grid(row=0, column=0, sticky="nsew")
            detail_frame.columnconfigure(0, weight=1)
            detail_frame.rowconfigure(6, weight=1)

            ttk.Label(detail_frame, text="详情 / DETAIL", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 12))
            self.cover_label = ttk.Label(detail_frame, text="暂无封面", anchor="center", style="CardMuted.TLabel")
            self.cover_label.grid(row=1, column=0, sticky="ew", pady=(0, 10))
            ttk.Label(detail_frame, textvariable=self.detail_title_var, style="Card.TLabel", font=("", 12, "bold"), wraplength=280).grid(
                row=2, column=0, sticky="ew", pady=(0, 4)
            )
            ttk.Label(detail_frame, textvariable=self.detail_meta_var, style="CardMuted.TLabel", wraplength=280).grid(
                row=3, column=0, sticky="ew", pady=(0, 8)
            )
            detail_status = ttk.Frame(detail_frame, style="Card.TFrame")
            detail_status.grid(row=4, column=0, sticky="ew", pady=(0, 8))
            for row, variable in enumerate((self.detail_file_var, self.detail_status_var, self.detail_target_var, self.detail_source_var)):
                ttk.Label(detail_status, textvariable=variable, style="CardMuted.TLabel", wraplength=280).grid(row=row, column=0, sticky="w", pady=(0 if row == 0 else 3, 0))
            detail_actions = ttk.Frame(detail_frame, style="Card.TFrame")
            detail_actions.grid(row=5, column=0, sticky="ew", pady=(0, 8))
            self.open_subject_button = self._action_button(detail_actions, "打开条目", self.open_current_subject, busy_sensitive=False)
            self.open_subject_button.configure(state="disabled")
            self.open_subject_button.pack(side="left")
            self.summary_text = ScrolledText(detail_frame, width=34, height=18, wrap="word")
            self.summary_text.grid(row=6, column=0, sticky="nsew")
            self.summary_text.configure(state="disabled", bg=COLORS["panel"], fg=COLORS["text"], insertbackground=COLORS["text"], selectbackground=COLORS["accent_soft"], relief="flat", borderwidth=0, padx=8, pady=8)

            right_frame = ttk.Frame(content, style="App.TFrame")
            right_frame.grid(row=0, column=1, sticky="nsew")
            right_frame.columnconfigure(0, weight=1)
            right_frame.rowconfigure(1, weight=1)
            right_frame.rowconfigure(2, weight=0)

            table_frame = ttk.Frame(right_frame, style="Card.TFrame", padding=(14, 14))
            table_frame.columnconfigure(0, weight=1)
            table_frame.rowconfigure(1, weight=1)

            series_bar = ttk.Frame(right_frame, style="Toolbar.TFrame", padding=(14, 10))
            series_bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
            series_bar.columnconfigure(1, weight=1)
            ttk.Label(series_bar, text="系列筛选", style="Toolbar.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 10))
            self.series_filter = ttk.Combobox(
                series_bar,
                textvariable=self.series_filter_var,
                state="readonly",
                values=("全部系列",),
            )
            self.series_filter.grid(row=0, column=1, sticky="ew", padx=(0, 8))
            self.series_filter.bind("<<ComboboxSelected>>", self.on_series_filter_changed)
            self.busy_controls.append(self.series_filter)
            self.series_intro_button = self._action_button(series_bar, "系列介绍", self.show_selected_series_intro)
            self.series_intro_button.grid(row=0, column=2)

            table_frame.grid(row=1, column=0, sticky="nsew")
            ttk.Label(table_frame, text="分类队列 / CLASSIFICATION QUEUE", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 10))

            columns = ("file", "rename", "series", "target", "source", "status", "detail")
            self.tree = ttk.Treeview(table_frame, columns=columns, show="headings")
            self.tree.heading("file", text="文件")
            self.tree.heading("rename", text="新文件名")
            self.tree.heading("series", text="系列名")
            self.tree.heading("target", text="目标文件夹")
            self.tree.heading("source", text="识别来源")
            self.tree.heading("status", text="状态")
            self.tree.heading("detail", text="详情")
            self.tree.column("file", width=240, anchor="w")
            self.tree.column("rename", width=240, anchor="w")
            self.tree.column("series", width=200, anchor="w")
            self.tree.column("target", width=190, anchor="w")
            self.tree.column("source", width=130, anchor="w")
            self.tree.column("status", width=90, anchor="center")
            self.tree.column("detail", width=130, anchor="center")
            self.tree.grid(row=1, column=0, sticky="nsew")

            scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
            scrollbar.grid(row=1, column=1, sticky="ns")
            horizontal_scrollbar = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
            horizontal_scrollbar.grid(row=2, column=0, sticky="ew")
            self.tree.configure(yscrollcommand=scrollbar.set, xscrollcommand=horizontal_scrollbar.set)
            self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
            self.tree.bind("<Double-1>", lambda _event: self.edit_selected_plan())
            self.tree.tag_configure("ready", background=COLORS["card"])
            self.tree.tag_configure("ready_alt", background=COLORS["card_alt"])
            self.tree.tag_configure("duplicate", background=COLORS["warning_soft"])
            self.tree.tag_configure("error", background=COLORS["danger_soft"])
            self.tree.tag_configure("manual", background=COLORS["violet_soft"])
            self.tree.tag_configure("moved", background=COLORS["ok_soft"])
            self.tree.tag_configure("unchanged", background=COLORS["card_alt"])
            self.empty_table_label = tk.Label(
                table_frame,
                text="尚无分类预览\n选择目录后点击“扫描并预览”",
                bg=COLORS["card"],
                fg=COLORS["muted"],
                font=(FONT_FAMILY, 11),
                justify="center",
                padx=24,
                pady=18,
            )
            self.empty_table_label.place(relx=0.5, rely=0.54, anchor="center")

            bottom = ttk.Frame(right_frame, style="Card.TFrame", padding=(14, 12))
            bottom.grid(row=2, column=0, sticky="ew")
            bottom.columnconfigure(0, weight=1)
            bottom.columnconfigure(1, minsize=240)
            ttk.Label(bottom, textvariable=self.status_var, style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 4))
            ttk.Label(bottom, textvariable=self.action_hint_var, style="CardMuted.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 8))
            self.progress_canvas = tk.Canvas(bottom, height=16, bg=COLORS["card"], highlightthickness=0)
            self.progress_canvas.grid(row=0, column=1, rowspan=2, sticky="ew", padx=(12, 0), pady=(0, 8))
            self.progress_canvas.bind(
                "<Configure>",
                lambda _event: self.draw_progress_canvas(
                    self.progress_display_value,
                    self.progress_maximum,
                    label=self.progress_label,
                ),
            )
            self.log = ScrolledText(bottom, height=5, wrap="word")
            self.log.grid(row=2, column=0, columnspan=2, sticky="ew")
            self.log.configure(state="disabled", bg=COLORS["panel"], fg=COLORS["text"], insertbackground=COLORS["text"], selectbackground=COLORS["accent_soft"], relief="flat", borderwidth=0, padx=8, pady=6)
            self.bind_mousewheel(self.tree, lambda units: self.tree.yview_scroll(units, "units"))
            self.bind_mousewheel(self.summary_text, lambda units: self.summary_text.yview_scroll(units, "units"))
            self.bind_mousewheel(self.log, lambda units: self.log.yview_scroll(units, "units"))
            self._mark_clickable_controls(self.master)
            self.show_empty_detail("扫描后在右侧选择一本小说。")

        def _stat_card(self, parent, title: str, value_var: tk.StringVar, caption: str, color: str, column: int) -> None:
            frame = tk.Frame(parent, bg=COLORS["card"], highlightthickness=1, highlightbackground=COLORS["border"])
            frame.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 10, 0))
            color_bar = tk.Frame(frame, bg=color, height=3)
            color_bar.pack(fill="x", side="top")
            body = tk.Frame(frame, bg=COLORS["card"], padx=16, pady=12)
            body.pack(fill="both", expand=True)
            title_label = tk.Label(body, text=title, bg=COLORS["card"], fg=COLORS["muted"], font=BODY_FONT)
            value_label = tk.Label(body, textvariable=value_var, bg=COLORS["card"], fg=COLORS["text"], font=(FONT_FAMILY, 22, "bold"))
            caption_label = tk.Label(body, text=caption, bg=COLORS["card"], fg=COLORS["muted"], font=CAPTION_FONT)
            title_label.pack(anchor="w")
            value_label.pack(anchor="w", pady=(2, 0))
            caption_label.pack(anchor="w", pady=(2, 0))

            def set_card_bg(bg: str) -> None:
                frame.configure(bg=bg, highlightbackground=COLORS["accent"] if bg == COLORS["card_hover"] else COLORS["border"])
                body.configure(bg=bg)
                for label in (title_label, value_label, caption_label):
                    label.configure(bg=bg)

            for widget in (frame, body, title_label, value_label, caption_label):
                widget.bind("<Enter>", lambda _event: set_card_bg(COLORS["card_hover"]), add="+")
                widget.bind("<Leave>", lambda _event: set_card_bg(COLORS["card"]), add="+")

        def update_stats(self) -> None:
            counts = count_plan_statuses(self.plans)
            self.animate_stat_value("total", self.stat_total_var, counts["total"])
            self.animate_stat_value("ready", self.stat_ready_var, counts["ready"])
            self.animate_stat_value("duplicate", self.stat_duplicate_var, counts["duplicate"])
            self.animate_stat_value("error", self.stat_error_var, counts["error"])

        def animate_stat_value(self, key: str, value_var: tk.StringVar, target: int, *, duration_ms: int = 360) -> None:
            current_job = self.stat_animation_jobs.pop(key, None)
            if current_job:
                try:
                    self.master.after_cancel(current_job)
                except tk.TclError:
                    pass
            start = self.stat_values.get(key, 0)
            delta = target - start
            if REDUCED_MOTION or delta == 0:
                value_var.set(str(target))
                self.stat_values[key] = target
                return
            steps = 14

            def step(frame: int = 0) -> None:
                t = min(frame / steps, 1.0)
                value = round(start + delta * ease_out_cubic(t))
                value_var.set(str(value))
                if frame < steps:
                    job = self.master.after(max(1, duration_ms // steps), lambda: step(frame + 1))
                    self.stat_animation_jobs[key] = job
                else:
                    self.stat_values[key] = target
                    self.stat_animation_jobs.pop(key, None)

            step()

        def bind_mousewheel(self, widget, scroll_command) -> None:
            def on_mousewheel(event):
                units = -int(event.delta / 120) if event.delta else 0
                if units == 0:
                    units = -1 if event.delta > 0 else 1
                scroll_command(units)
                return "break"

            def on_button4(_event):
                scroll_command(-1)
                return "break"

            def on_button5(_event):
                scroll_command(1)
                return "break"

            widget.bind("<MouseWheel>", on_mousewheel, add="+")
            widget.bind("<Button-4>", on_button4, add="+")
            widget.bind("<Button-5>", on_button5, add="+")

        def set_summary_text(self, text: str) -> None:
            self.summary_text.configure(state="normal")
            self.summary_text.delete("1.0", "end")
            self.summary_text.insert("1.0", text)
            self.summary_text.configure(state="disabled")

        def set_detail_url(self, url: str | None) -> None:
            self.current_detail_url = url
            if hasattr(self, "open_subject_button"):
                self.open_subject_button.configure(state="normal" if url else "disabled")

        def set_detail_state(self, *, file_name: str, status: str, target: str, source: str) -> None:
            self.detail_file_var.set(f"文件：{file_name}")
            self.detail_status_var.set(f"状态：{status}")
            self.detail_target_var.set(f"目标：{target}")
            self.detail_source_var.set(f"来源：{source}")

        def open_current_subject(self) -> None:
            if self.current_detail_url:
                try:
                    opened = webbrowser.open(self.current_detail_url)
                except webbrowser.Error as exc:
                    opened = False
                    self.log_message(f"条目打开失败：{exc}")
                if not opened:
                    self.show_toast("无法打开浏览器条目", kind="warning")

        def filtered_plan_indices(self) -> list[int]:
            selected = self.series_filter_var.get()
            if not selected or selected == "全部系列":
                return list(range(len(self.plans)))
            return [
                index
                for index, plan in enumerate(self.plans)
                if (plan.series_key or plan.series_name) == selected
            ]

        def refresh_series_filter(self) -> None:
            series_names = sorted({plan.series_key or plan.series_name for plan in self.plans})
            values = ["全部系列", *series_names]
            if hasattr(self, "series_filter"):
                self.series_filter.configure(values=values)
            if self.series_filter_var.get() not in values:
                self.series_filter_var.set("全部系列")

        def on_series_filter_changed(self, _event: object | None = None) -> None:
            if self.is_busy:
                return
            self._render_plans()

        def show_selected_series_intro(self) -> None:
            indices = self.filtered_plan_indices()
            if not indices:
                self.show_empty_detail("当前系列没有可显示的小说。")
                return
            plan = self.plans[indices[0]]
            self.selected_plan_index = None
            title = plan.series_name
            meta_parts = [f"{plan.resolver_source} {plan.confidence:.0%}", f"{len(indices)} 本"]
            if plan.metadata_url:
                meta_parts.append(plan.metadata_url)
            self.detail_title_var.set(title)
            self.detail_meta_var.set(" | ".join(meta_parts))
            self.set_detail_state(
                file_name=f"系列视图：{title}",
                status=f"{len(indices)} 本",
                target=plan.target_dir.name,
                source=plan.resolver_source,
            )
            self.set_detail_url(plan.metadata_url)
            self.set_summary_text(plan.metadata_summary or "没有从 Bangumi 获取到系列简介。")
            self.show_cover_for_plan(indices[0], plan.metadata_cover_url)

        def set_progress_idle(self) -> None:
            if self.progress_canvas is None:
                return
            self.progress_display_value = 0.0
            self.progress_maximum = 1.0
            self.progress_label = None
            self.stop_scanning_animation()
            self.draw_progress_canvas(0, 1)

        def set_progress_scanning(self) -> None:
            if self.progress_canvas is not None:
                self.progress_maximum = 1.0
                self.progress_label = "扫描中"
                self.start_scanning_animation()

        def set_progress_preloading(self, done: int, total: int) -> None:
            if self.progress_canvas is None:
                return
            maximum = max(total, 1)
            self.progress_maximum = float(maximum)
            self.progress_label = None
            self.animate_progress_to(min(done, maximum), maximum)

        def set_progress_operation(self, done: int, total: int, label: str) -> None:
            if self.progress_canvas is None:
                return
            maximum = max(total, 1)
            self.progress_maximum = float(maximum)
            self.progress_label = label
            if done <= 0:
                self.progress_display_value = 0.0
                self.draw_progress_canvas(0, maximum, label=label)
                return
            self.animate_progress_to(min(done, maximum), maximum, label=label)

        def animate_progress_to(
            self,
            target: float,
            maximum: float,
            *,
            duration_ms: int = 420,
            label: str | None = None,
        ) -> None:
            self.progress_maximum = float(maximum)
            self.progress_label = label
            start = self.progress_display_value
            delta = target - start
            if REDUCED_MOTION or abs(delta) < 0.01:
                self.progress_display_value = target
                self.draw_progress_canvas(target, maximum, label=label)
                return
            steps = 18

            def step(frame: int = 0) -> None:
                t = min(frame / steps, 1.0)
                value = start + delta * ease_out_cubic(t)
                self.progress_display_value = value
                self.draw_progress_canvas(value, maximum, label=label)
                if frame < steps:
                    self.master.after(max(1, duration_ms // steps), lambda: step(frame + 1))

            step()

        def draw_progress_canvas(self, value: float, maximum: float, *, label: str | None = None) -> None:
            if self.progress_canvas is None:
                return
            canvas = self.progress_canvas
            width = max(canvas.winfo_width(), 1)
            height = max(canvas.winfo_height(), 1)
            canvas.delete("all")
            pad = 1
            radius = height // 2
            canvas.create_rectangle(pad + radius, pad, width - radius - pad, height - pad, fill=COLORS["panel"], outline="")
            canvas.create_oval(pad, pad, pad + radius * 2, height - pad, fill=COLORS["panel"], outline="")
            canvas.create_oval(width - radius * 2 - pad, pad, width - pad, height - pad, fill=COLORS["panel"], outline="")
            ratio = 0 if maximum <= 0 else max(0.0, min(value / maximum, 1.0))
            fill_width = max(radius * 2, int(width * ratio)) if ratio else 0
            if fill_width:
                canvas.create_rectangle(pad + radius, pad, fill_width - radius, height - pad, fill=COLORS["accent"], outline="")
                canvas.create_oval(pad, pad, pad + radius * 2, height - pad, fill=COLORS["accent"], outline="")
                canvas.create_oval(fill_width - radius * 2, pad, fill_width, height - pad, fill=COLORS["accent"], outline="")
            progress_text = f"{label}  {ratio:.0%}" if label else f"{ratio:.0%}"
            canvas.create_text(width // 2, height // 2, text=progress_text, fill=COLORS["text"], font=(FONT_FAMILY, 8, "bold"))

        def start_scanning_animation(self) -> None:
            self.stop_scanning_animation()
            if REDUCED_MOTION:
                canvas = self.progress_canvas
                if canvas is not None:
                    width = max(canvas.winfo_width(), 1)
                    height = max(canvas.winfo_height(), 1)
                    canvas.delete("all")
                    canvas.create_rectangle(0, 0, width, height, fill=COLORS["panel"], outline="")
                    canvas.create_text(width // 2, height // 2, text="扫描中", fill=COLORS["accent"], font=(FONT_FAMILY, 8, "bold"))
                return
            frame_count = 48

            def tick(frame: int = 0) -> None:
                if self.progress_canvas is None:
                    return
                canvas = self.progress_canvas
                width = max(canvas.winfo_width(), 1)
                height = max(canvas.winfo_height(), 1)
                canvas.delete("all")
                radius = height // 2
                canvas.create_rectangle(radius, 1, width - radius, height - 1, fill=COLORS["panel"], outline="")
                canvas.create_oval(1, 1, radius * 2, height - 1, fill=COLORS["panel"], outline="")
                canvas.create_oval(width - radius * 2 - 1, 1, width - 1, height - 1, fill=COLORS["panel"], outline="")
                t = (frame % frame_count) / frame_count
                eased = ease_in_out_quart(t)
                block_width = max(52, width // 4)
                x0 = int(-block_width + (width + block_width * 2) * eased)
                x1 = x0 + block_width
                canvas.create_rectangle(max(radius, x0), 1, min(width - radius, x1), height - 1, fill=COLORS["accent"], outline="")
                canvas.create_text(width // 2, height // 2, text="扫描中", fill=COLORS["text"], font=(FONT_FAMILY, 8, "bold"))
                self.progress_scan_job = self.master.after(28, lambda: tick(frame + 1))

            tick()

        def stop_scanning_animation(self) -> None:
            if self.progress_scan_job:
                try:
                    self.master.after_cancel(self.progress_scan_job)
                except tk.TclError:
                    pass
                self.progress_scan_job = None

        def _animate_initial_cards(self) -> None:
            start_x, start_y = 40, 30
            end_x, end_y = 28, 22
            steps = 16
            self.main_frame.configure(padding=(start_x, start_y))

            def step(frame: int = 0) -> None:
                t = min(frame / steps, 1.0)
                eased = ease_out_back(t)
                pad_x = round(start_x + (end_x - start_x) * eased)
                pad_y = round(start_y + (end_y - start_y) * eased)
                self.main_frame.configure(padding=(pad_x, pad_y))
                if frame < steps:
                    self.master.after(18, lambda: step(frame + 1))

            step()

        def show_toast(self, message: str, *, kind: str = "info") -> None:
            toast = tk.Toplevel(self.master)
            toast.overrideredirect(True)
            toast.configure(bg=COLORS["card"])
            toast.attributes("-alpha", 0.0)
            toast.attributes("-topmost", True)
            color = {
                "info": COLORS["accent"],
                "success": COLORS["ok"],
                "warning": COLORS["warning"],
                "error": COLORS["danger"],
            }.get(kind, COLORS["accent"])
            marker = tk.Frame(toast, width=4, bg=color)
            marker.pack(side="left", fill="y")
            label = tk.Label(toast, text=message, bg=COLORS["card"], fg=COLORS["text"], padx=18, pady=10, font=(FONT_FAMILY, 10, "bold"))
            label.pack(side="left", fill="both", expand=True)
            self.master.update_idletasks()
            target_x = self.master.winfo_rootx() + self.master.winfo_width() - 360
            start_x = target_x + 52
            y = self.master.winfo_rooty() + 42 + len(self.toast_windows) * 56
            toast.geometry(f"320x44+{start_x}+{y}")
            self.toast_windows.append(toast)
            if REDUCED_MOTION:
                toast.geometry(f"320x44+{target_x}+{y}")
                toast.attributes("-alpha", 0.98)

                def destroy_reduced_toast() -> None:
                    if toast in self.toast_windows:
                        self.toast_windows.remove(toast)
                    try:
                        toast.destroy()
                    except tk.TclError:
                        pass

                toast.after(2200, destroy_reduced_toast)
                return

            def fade(frame: int = 0, direction: int = 1) -> None:
                steps = 12
                t = min(frame / steps, 1.0)
                alpha = ease_in_out_quart(t)
                if direction < 0:
                    alpha = 1.0 - alpha
                    x = int(target_x + 24 * ease_in_out_quart(t))
                else:
                    x = int(start_x + (target_x - start_x) * ease_out_back(t))
                toast.geometry(f"320x44+{x}+{y}")
                toast.attributes("-alpha", max(0.0, min(alpha, 0.98)))
                if frame < steps:
                    toast.after(18, lambda: fade(frame + 1, direction))
                elif direction > 0:
                    toast.after(2200, lambda: fade(0, -1))
                else:
                    if toast in self.toast_windows:
                        self.toast_windows.remove(toast)
                    toast.destroy()

            fade()

        def set_tree_detail_status(self, index: int, status: str) -> None:
            item_id = str(index)
            if not self.tree.exists(item_id):
                return
            values = list(self.tree.item(item_id, "values"))
            while len(values) < 7:
                values.append("")
            values[6] = status
            self.tree.item(item_id, values=values)

        def show_empty_detail(self, message: str) -> None:
            self.selected_plan_index = None
            self.detail_title_var.set("Bangumi 信息")
            self.detail_meta_var.set(message)
            self.set_detail_state(file_name="未选择文件", status="待扫描", target="等待预览", source="无")
            self.set_detail_url(None)
            self.set_summary_text("暂无简介。")
            self.clear_cover("暂无封面")

        def clear_cover(self, text: str) -> None:
            self.cover_photo = None
            self.cover_label.configure(image="", text=text)

        def display_cover(self, data: bytes) -> bool:
            if Image is None or ImageTk is None:
                self.clear_cover("需要安装 Pillow 才能显示封面")
                return False
            try:
                with Image.open(io.BytesIO(data)) as image:
                    image.thumbnail((240, 340), Image.LANCZOS)
                    photo = ImageTk.PhotoImage(image.copy())
            except Exception:
                self.clear_cover("封面无法读取")
                return False
            self.cover_photo = photo
            self.cover_label.configure(image=photo, text="")
            return True

        def on_tree_select(self, _event: object | None = None) -> None:
            selection = self.tree.selection()
            if not selection:
                self.show_empty_detail("请在右侧选择一本小说。")
                self._refresh_action_states()
                return
            try:
                index = int(selection[0])
            except ValueError:
                return
            if index < 0 or index >= len(self.plans):
                return
            self.show_plan_detail(index)
            self._refresh_action_states()

        def edit_selected_plan(self) -> None:
            if self.is_busy:
                self.show_toast("当前任务尚未完成", kind="warning")
                return
            selection = self.tree.selection()
            if not selection:
                self.show_toast("请先选择一条分类结果", kind="warning")
                return
            try:
                index = int(selection[0])
            except ValueError:
                return
            if index < 0 or index >= len(self.plans):
                return
            plan = self.plans[index]
            if plan.status == "moved":
                self.show_toast("已移动的结果不能再次修正，请先撤销或重新扫描", kind="warning")
                return
            new_series = simpledialog.askstring(
                "修正分类",
                "请输入新的系列名：",
                initialvalue=plan.series_name,
                parent=self.master,
            )
            if not new_series:
                return
            folder_name = safe_folder_name(new_series)
            target_dir = plan.target_dir.parent / folder_name
            target_name = plan.rename_to or plan.source_path.name
            target_path = target_dir / target_name
            try:
                already_classified = plan.source_path.resolve() == target_path.resolve()
            except OSError:
                already_classified = plan.source_path.absolute() == target_path.absolute()
            self.plans[index] = replace(
                plan,
                series_name=folder_name,
                target_dir=target_dir,
                target_path=target_path,
                resolver_source="手动修正",
                confidence=1.0,
                series_key=folder_name,
                status="unchanged" if already_classified else "ready",
                note="文件已在正确的系列目录中，无需移动。" if already_classified else "用户手动修正分类。",
                duplicate_of=None,
            )
            self._render_plans()
            self.tree.selection_set(str(index))
            self.show_plan_detail(index)
            self._set_phase("已手动修正", "success", "修正已写入预览，确认后执行分类即可落盘。")
            self.show_toast("分类已修正")

        def show_plan_detail(self, index: int) -> None:
            plan = self.plans[index]
            self.selected_plan_index = index
            self.action_hint_var.set("选中结果：双击表格行或点击“修正分类”可手动调整。")
            cache_key = str(plan.source_path)
            with self.detail_lock:
                has_cached_detail = cache_key in self.detail_cache
                cached_detail = self.detail_cache.get(cache_key)
            if has_cached_detail:
                if cached_detail is not None:
                    self.show_book_metadata(index, cached_detail)
                else:
                    self.show_series_fallback(index, loading=False)
                return

            self.show_series_fallback(index, loading=self.network_var.get())
            if self.network_var.get():
                self.load_book_metadata(index)

        def show_series_fallback(self, index: int, *, loading: bool = False) -> None:
            plan = self.plans[index]
            title = plan.metadata_title or plan.series_name
            meta_parts = [f"{plan.resolver_source} {plan.confidence:.0%}"]
            if loading:
                meta_parts.append("正在查询当前卷")
            if plan.metadata_url:
                meta_parts.append(plan.metadata_url)
            self.detail_title_var.set(title)
            self.detail_meta_var.set(" | ".join(meta_parts))
            self.set_detail_state(
                file_name=plan.source_path.name,
                status=plan_status_label(plan.status),
                target=f"重复于 {plan.duplicate_of.name}" if plan.duplicate_of else plan.target_dir.name,
                source=f"{plan.resolver_source} {plan.confidence:.0%}",
            )
            self.set_detail_url(plan.metadata_url)
            self.set_summary_text(plan.metadata_summary or "没有从 Bangumi 获取到简介。")
            self.show_cover_for_plan(index, plan.metadata_cover_url)

        def show_book_metadata(self, index: int, metadata: BookMetadata) -> None:
            plan = self.plans[index]
            meta_parts = [f"{metadata.source} 单卷 {metadata.confidence:.0%}"]
            if metadata.url:
                meta_parts.append(metadata.url)
            self.detail_title_var.set(metadata.title)
            self.detail_meta_var.set(" | ".join(meta_parts))
            self.set_detail_state(
                file_name=plan.source_path.name,
                status=plan_status_label(plan.status),
                target=f"重复于 {plan.duplicate_of.name}" if plan.duplicate_of else plan.target_dir.name,
                source=f"{metadata.source} {metadata.confidence:.0%}",
            )
            self.set_detail_url(metadata.url)
            self.set_summary_text(metadata.summary or "没有从 Bangumi 获取到这一卷的简介。")
            self.show_cover_for_plan(index, metadata.cover_url)

        def show_cover_for_plan(self, index: int, fallback_url: str | None) -> None:
            if 0 <= index < len(self.plans):
                local_cover = self.plans[index].local_cover_bytes
                if local_cover and self.display_cover(local_cover):
                    return
            self.load_cover(index, fallback_url)

        def reserve_detail_fetch(self, cache_key: str) -> bool:
            with self.detail_lock:
                if cache_key in self.detail_cache or cache_key in self.detail_worker_keys:
                    return False
                self.detail_worker_keys.add(cache_key)
                return True

        def load_book_metadata(self, index: int) -> None:
            if index < 0 or index >= len(self.plans):
                return
            plan = self.plans[index]
            cache_key = str(plan.source_path)
            if not self.reserve_detail_fetch(cache_key):
                return
            token = self.scan_token
            self.set_tree_detail_status(index, "查询中")

            def work() -> None:
                metadata: BookMetadata | None = None
                try:
                    resolver = SeriesResolver(use_network=True, timeout=10)
                    query = plan.identity_query or plan.source_path.name
                    metadata = resolver.resolve_book_metadata_for_query(query, series_name=plan.series_name)
                except Exception:
                    metadata = None
                self.events.put(("metadata", (token, index, cache_key, metadata)))

            threading.Thread(target=work, daemon=True).start()

        def start_metadata_preload(self) -> None:
            if not self.network_var.get() or not self.plans or any(plan.status == "moved" for plan in self.plans):
                return
            if self.metadata_preload_started_token == self.scan_token:
                return
            self.metadata_preload_started_token = self.scan_token
            plans_snapshot = list(enumerate(self.plans))
            token = self.scan_token
            total = len(plans_snapshot)
            self.preload_total = total
            self.preload_done = 0
            self.set_progress_preloading(0, total)

            def work() -> None:
                done = 0
                done_lock = threading.Lock()

                def report_done() -> None:
                    nonlocal done
                    with done_lock:
                        done += 1
                        current_done = done
                    self.events.put(("preload_progress", (token, current_done, total)))

                def fetch_one(index: int, plan: ClassificationPlan) -> None:
                    try:
                        cache_key = str(plan.source_path)
                        if not self.reserve_detail_fetch(cache_key):
                            return
                        self.events.put(("detail_status", (token, index, "\u9884\u53d6\u4e2d")))
                        metadata: BookMetadata | None = None
                        try:
                            resolver = SeriesResolver(use_network=True, timeout=10)
                            query = plan.identity_query or plan.source_path.name
                            metadata = resolver.resolve_book_metadata_for_query(query, series_name=plan.series_name)
                        except Exception:
                            metadata = None
                        self.events.put(("metadata", (token, index, cache_key, metadata)))
                        if metadata and metadata.cover_url and not plan.local_cover_bytes:
                            if self.reserve_cover_fetch(metadata.cover_url):
                                self.download_cover_to_cache(token, index, metadata.cover_url)
                    finally:
                        report_done()

                worker_count = min(METADATA_PRELOAD_WORKERS, max(1, total))
                with ThreadPoolExecutor(max_workers=worker_count) as executor:
                    futures = [executor.submit(fetch_one, index, plan) for index, plan in plans_snapshot]
                    for future in futures:
                        try:
                            future.result()
                        except Exception:
                            pass

            threading.Thread(target=work, daemon=True).start()

        def reserve_cover_fetch(self, url: str) -> bool:
            with self.cover_lock:
                if url in self.cover_bytes_cache or url in self.cover_worker_urls:
                    return False
                self.cover_worker_urls.add(url)
                return True

        def download_cover_to_cache(self, token: int, index: int, url: str) -> None:
            data: bytes | None = None
            error: Exception | None = None
            try:
                data = http_bytes(url, timeout=12)
            except Exception as exc:
                error = exc
            with self.cover_lock:
                self.cover_worker_urls.discard(url)
                self.cover_bytes_cache[url] = data
            self.events.put(("cover", (token, index, url, data, error)))

        def load_cover(self, index: int, url: str | None) -> None:
            if not url:
                self.clear_cover("暂无封面")
                return
            with self.cover_lock:
                has_cache = url in self.cover_bytes_cache
                cached = self.cover_bytes_cache.get(url)
                is_loading = url in self.cover_worker_urls
            if has_cache:
                if cached:
                    self.display_cover(cached)
                else:
                    self.clear_cover("封面加载失败")
                return
            if is_loading:
                self.clear_cover("封面加载中...")
                return
            if not self.reserve_cover_fetch(url):
                self.clear_cover("封面加载中...")
                return
            self.clear_cover("封面加载中...")
            token = self.scan_token

            def work() -> None:
                self.download_cover_to_cache(token, index, url)

            threading.Thread(target=work, daemon=True).start()

        def log_message(self, message: str) -> None:
            self.log.configure(state="normal")
            self.log.insert("end", message + "\n")
            line_count = int(self.log.index("end-1c").split(".")[0])
            if line_count > 300:
                self.log.delete("1.0", f"{line_count - 300}.0")
            self.log.see("end")
            self.log.configure(state="disabled")
            self.status_var.set(message)

        def select_folder(self) -> None:
            if self.is_busy:
                self.show_toast("当前任务尚未完成", kind="warning")
                return
            folder = filedialog.askdirectory(title="选择存放轻小说的大文件夹")
            if folder:
                self.root_var.set(folder)
                self._set_phase("目录已选择", "success", "下一步：按 F5 或点击“扫描并预览”。")
                self.log_message(f"已选择：{folder}")

        def create_folder(self) -> None:
            if self.is_busy:
                self.show_toast("当前任务尚未完成", kind="warning")
                return
            parent = filedialog.askdirectory(title="选择新大文件夹的上级目录")
            if not parent:
                return
            name = simpledialog.askstring("新建大文件夹", "请输入大文件夹名称：", initialvalue="轻小说合集")
            if not name:
                return
            folder = Path(parent) / safe_folder_name(name)
            if folder.exists():
                if not messagebox.askyesno("文件夹已存在", f"{folder} 已存在，要使用它吗？"):
                    return
            else:
                try:
                    folder.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    messagebox.showerror("创建失败", f"无法创建文件夹：\n{folder}\n\n{exc}")
                    return
            self.root_var.set(str(folder))
            self._set_phase("目录已选择", "success", "下一步：按 F5 扫描这个新目录。")
            self.log_message(f"已创建/选择：{folder}")

        def open_folder(self) -> None:
            folder = self._current_root()
            if not folder:
                return
            try:
                os.startfile(folder)
            except OSError as exc:
                self.show_toast("目录无法打开", kind="warning")
                self.log_message(f"目录打开失败：{exc}")

        def _current_root(self) -> str | None:
            folder = self.root_var.get().strip()
            if not folder:
                messagebox.showwarning("需要大文件夹", "请先选择或新建一个大文件夹。")
                return None
            folder_path = Path(folder)
            if not folder_path.exists():
                messagebox.showwarning("文件夹不存在", "当前大文件夹不存在。")
                return None
            if not folder_path.is_dir():
                messagebox.showwarning("路径不是文件夹", "请输入或选择一个文件夹路径。")
                return None
            return folder

        def _set_busy(self, busy: bool) -> None:
            self.is_busy = busy
            self.master.configure(cursor="watch" if busy else "")
            for control in self.busy_controls:
                try:
                    if isinstance(control, ttk.Combobox):
                        control.configure(state="disabled" if busy else "readonly")
                    else:
                        control.configure(state="disabled" if busy else "normal")
                except tk.TclError:
                    pass
            self._refresh_action_states()

        def scan(self) -> None:
            if self.is_busy:
                self.show_toast("当前任务尚未完成", kind="warning")
                return
            folder = self._current_root()
            if not folder:
                return
            root_path = Path(folder).expanduser().resolve()
            settings_snapshot = AppSettings(
                use_network=bool(self.network_var.get()),
                recursive=bool(self.recursive_var.get()),
                auto_rename=bool(self.auto_rename_var.get()),
                custom_rules=self.settings.custom_rules,
            )
            self.settings = settings_snapshot
            settings_error = try_save_app_settings(self.settings)
            if settings_error is not None:
                self.log_message(f"设置保存失败，继续扫描：{settings_error}")
            self.scan_token += 1
            scan_token = self.scan_token
            operation_token = self._begin_operation("scan")
            self.tree.delete(*self.tree.get_children())
            self.empty_table_label.configure(text="正在扫描目录并建立分类预览...")
            self.empty_table_label.place(relx=0.5, rely=0.54, anchor="center")
            self.plans = []
            self.selected_plan_index = None
            self.update_stats()
            with self.detail_lock:
                self.detail_cache.clear()
                self.detail_worker_keys.clear()
            self.metadata_preload_started_token = None
            with self.cover_lock:
                self.cover_worker_urls.clear()
            self.show_empty_detail("正在读取文件与书籍信息。")
            self.set_progress_scanning()
            self._set_phase("扫描中", "busy", "正在读取文件、识别系列并检查重复项。")
            self.log_message("开始扫描，联网识别会按文件名查询公开书库。")

            def work() -> None:
                try:
                    plans = build_classification_plan(
                        root_path,
                        recursive=settings_snapshot.recursive,
                        use_network=settings_snapshot.use_network,
                        auto_rename=settings_snapshot.auto_rename,
                        custom_rules=settings_snapshot.custom_rules,
                        progress=lambda msg: self.events.put(("worker_log", (operation_token, msg))),
                    )
                    self.events.put(("plans", (operation_token, scan_token, plans)))
                except Exception as exc:
                    self.events.put(("operation_error", (operation_token, "scan", exc, None)))

            self.worker = threading.Thread(target=work, daemon=True)
            self.worker.start()

        def apply_plan(self) -> None:
            if self.is_busy:
                self.show_toast("当前任务尚未完成", kind="warning")
                return
            if not self.plans:
                messagebox.showinfo("没有预览", "请先扫描并确认预览结果。")
                return
            movable = sum(1 for plan in self.plans if plan.will_move)
            if movable == 0:
                messagebox.showinfo("没有可执行项", "当前预览中没有需要移动的文件。请重新扫描或修正分类。")
                return
            counts = count_plan_statuses(self.plans)
            plans_snapshot = list(self.plans)
            report_path = plans_snapshot[0].target_dir.parent / REPORT_FILE_NAME
            if not messagebox.askyesno(
                "确认执行分类",
                f"将移动 {movable} 个文件。\n重复项 {counts['duplicate']} 个、错误项 {counts['error']} 个会跳过。\n\n报告：{report_path}\n\n执行期间请勿移动相关文件，是否继续？",
            ):
                return
            operation_token = self._begin_operation("apply")
            self._set_phase("执行中", "busy", "正在移动文件并持续写入可撤销报告。")
            self.set_progress_operation(0, len(plans_snapshot), "执行中")
            self.log_message("开始移动文件。")

            def work() -> None:
                try:
                    result = execute_classification_plan(
                        plans_snapshot,
                        progress=lambda msg: self.events.put(("worker_log", (operation_token, msg))),
                        progress_count=lambda done, total: self.events.put(
                            ("operation_progress", (operation_token, "apply", done, total))
                        ),
                        report_path=report_path,
                    )
                    self.events.put(("apply_done", (operation_token, *result, report_path)))
                except Exception as exc:
                    self.events.put(("operation_error", (operation_token, "apply", exc, report_path)))

            self.worker = threading.Thread(target=work, daemon=True)
            self.worker.start()

        def _poll_events(self) -> None:
            if self.is_closing:
                return
            try:
                while True:
                    event, payload = self.events.get_nowait()
                    if event == "worker_log":
                        operation_token, message = payload  # type: ignore[misc]
                        if operation_token == self.operation_token:
                            self.log_message(str(message))
                    elif event == "plans":
                        operation_token, scan_token, plans = payload  # type: ignore[misc]
                        if operation_token != self.operation_token or scan_token != self.scan_token:
                            continue
                        self.plans = list(plans)
                        self._finish_operation(operation_token)
                        self._render_plans()
                        counts = count_plan_statuses(self.plans)
                        if self.plans:
                            self._set_phase(
                                f"预览完成：{counts['ready']} 可执行",
                                "success",
                                "检查结果后可修正分类，确认无误按 Ctrl+Enter 执行。",
                            )
                            self.log_message(f"预览完成：找到 {len(self.plans)} 个支持文件。")
                        else:
                            self._set_phase(
                                "未找到文件",
                                "warning",
                                "可以更换目录或开启“包含子文件夹”后重新扫描。",
                            )
                            self.log_message("扫描完成：没有找到支持的小说文件。")
                    elif event == "operation_progress":
                        operation_token, operation, done, total = payload  # type: ignore[misc]
                        if operation_token != self.operation_token:
                            continue
                        label = "执行中" if operation == "apply" else "撤销中"
                        self.set_progress_operation(done, total, label)
                        self.status_var.set(f"{label}：{done}/{total}")
                    elif event == "metadata":
                        token, index, cache_key, metadata = payload  # type: ignore[misc]
                        if token != self.scan_token:
                            continue
                        with self.detail_lock:
                            self.detail_worker_keys.discard(cache_key)
                            self.detail_cache[cache_key] = metadata
                        self.set_tree_detail_status(index, "已缓存" if metadata is not None else "无详情")
                        if index == self.selected_plan_index:
                            if metadata is not None:
                                self.show_book_metadata(index, metadata)
                            else:
                                self.show_series_fallback(index, loading=False)
                    elif event == "detail_status":
                        token, index, status = payload  # type: ignore[misc]
                        if token == self.scan_token:
                            self.set_tree_detail_status(index, status)
                    elif event == "preload_progress":
                        token, done, total = payload  # type: ignore[misc]
                        if token != self.scan_token:
                            continue
                        if any(plan.status == "moved" for plan in self.plans):
                            continue
                        self.preload_done = done
                        self.preload_total = total
                        if self.active_operation is None:
                            self.set_progress_preloading(done, total)
                        if done >= total:
                            if self.active_operation is None:
                                self._set_phase("详情已缓存", "success", "可继续查看详情、修正分类或执行移动。")
                                self.status_var.set(f"详情预加载完成：{done}/{total}")
                        else:
                            if self.active_operation is None:
                                self._set_phase(f"预加载 {done}/{total}", "busy")
                                self.status_var.set(f"后台预加载详情：{done}/{total}")
                    elif event == "cover":
                        token, index, _url, data, error = payload  # type: ignore[misc]
                        if token != self.scan_token:
                            continue
                        if index == self.selected_plan_index:
                            has_local_cover = 0 <= index < len(self.plans) and bool(self.plans[index].local_cover_bytes)
                            if has_local_cover:
                                continue
                            if error is None and data:
                                self.display_cover(data)
                            else:
                                self.clear_cover("封面加载失败")
                    elif event == "apply_done":
                        operation_token, moved, skipped, report_path = payload  # type: ignore[misc]
                        if operation_token != self.operation_token:
                            continue
                        self._finish_operation(operation_token)
                        self.last_report_path = report_path
                        actual_targets: dict[str, Path] = {}
                        try:
                            report_data = json.loads(Path(report_path).read_text(encoding="utf-8"))
                            for item in report_data.get("items") or []:
                                if not isinstance(item, dict) or item.get("operation") != "moved":
                                    continue
                                source_value = str(item.get("source_path") or "")
                                target_value = str(item.get("actual_target_path") or "")
                                if source_value and target_value:
                                    actual_targets[source_value] = Path(target_value)
                        except (OSError, json.JSONDecodeError, AttributeError):
                            actual_targets = {}
                        updated_plans = []
                        for plan in self.plans:
                            if not plan.will_move:
                                updated_plans.append(plan)
                                continue
                            actual_target = actual_targets.get(str(plan.source_path), plan.target_path)
                            updated_plans.append(
                                replace(
                                    plan,
                                    target_dir=actual_target.parent,
                                    target_path=actual_target,
                                    status="moved",
                                    note=f"已移动到 {actual_target}。",
                                )
                            )
                        self.plans = updated_plans
                        self._render_plans()
                        self.set_progress_operation(len(self.plans), len(self.plans), "已完成")
                        self._set_phase("分类完成", "success", "报告已生成，可打开报告或用 Ctrl+Z 撤销上次移动。")
                        self.log_message(f"分类完成：移动 {moved} 个文件，跳过 {skipped} 个文件。报告：{report_path}")
                        self.show_toast("分类完成，报告已生成", kind="success")
                        messagebox.showinfo("完成", f"分类完成：移动 {moved} 个文件，跳过 {skipped} 个文件。")
                    elif event == "undo_done":
                        operation_token, restored, skipped, report_path = payload  # type: ignore[misc]
                        if operation_token != self.operation_token:
                            continue
                        self._finish_operation(operation_token)
                        self.last_report_path = report_path
                        self._invalidate_preview("撤销已完成，请重新扫描确认当前文件状态。")
                        self._set_phase("撤销完成", "success", "文件已按报告恢复；重新扫描可刷新分类预览。")
                        self.log_message(f"撤销完成：恢复 {restored} 个文件，跳过 {skipped} 个文件。")
                        self.show_toast(f"撤销完成：恢复 {restored} 个，跳过 {skipped} 个", kind="success")
                    elif event == "operation_error":
                        operation_token, operation, error_value, context_path = payload  # type: ignore[misc]
                        if operation_token != self.operation_token:
                            continue
                        self._finish_operation(operation_token)
                        if context_path is not None and Path(context_path).exists():
                            self.last_report_path = Path(context_path)
                        self.set_progress_idle()
                        if operation in {"apply", "undo"}:
                            self._invalidate_preview("文件状态可能已部分变化，请先查看报告并重新扫描。")
                        else:
                            self.empty_table_label.configure(text="扫描失败\n请查看下方日志后重试")
                            self.empty_table_label.place(relx=0.5, rely=0.54, anchor="center")
                        operation_name = {"scan": "扫描", "apply": "执行分类", "undo": "撤销"}.get(operation, operation)
                        self._set_phase(f"{operation_name}失败", "error", "检查日志中的错误原因，修正后重新扫描。")
                        self.log_message(f"{operation_name}失败：{error_value}")
                        messagebox.showerror(f"{operation_name}失败", str(error_value))
            except queue.Empty:
                pass
            if not self.is_closing:
                try:
                    self.master.after(120, self._poll_events)
                except tk.TclError:
                    pass

        def _render_plans(self) -> None:
            self.refresh_series_filter()
            self.update_stats()
            self.tree.delete(*self.tree.get_children())
            visible_indices = self.filtered_plan_indices()
            if visible_indices:
                self.empty_table_label.place_forget()
            else:
                empty_text = "当前筛选没有结果" if self.plans else "没有找到可分类文件"
                self.empty_table_label.configure(text=empty_text)
                self.empty_table_label.place(relx=0.5, rely=0.54, anchor="center")
            for row_number, index in enumerate(visible_indices):
                plan = self.plans[index]
                source = f"{plan.resolver_source} {plan.confidence:.0%}"
                cache_key = str(plan.source_path)
                with self.detail_lock:
                    has_detail_cache = cache_key in self.detail_cache
                    is_loading = cache_key in self.detail_worker_keys
                    cached_detail = self.detail_cache.get(cache_key)
                if not self.network_var.get():
                    detail_status = "未联网"
                elif is_loading:
                    detail_status = "预取中"
                elif has_detail_cache:
                    detail_status = "已缓存" if cached_detail is not None else "无详情"
                else:
                    detail_status = "待预取"
                status_text = plan_status_label(plan.status)
                if plan.note and plan.status in {"ready", "moved", "unchanged"}:
                    detail_status = plan.note
                if plan.status == "moved":
                    row_tag = "moved"
                elif plan.resolver_source == "手动修正":
                    row_tag = "manual"
                elif plan.status == "ready" and row_number % 2 == 1:
                    row_tag = "ready_alt"
                else:
                    row_tag = plan.status
                self.tree.insert(
                    "",
                    "end",
                    iid=str(index),
                    tags=(row_tag,),
                    values=(
                        plan.source_path.name,
                        plan.target_path.name if plan.rename_to else "",
                        plan.series_name,
                        plan.target_dir.name,
                        source,
                        status_text,
                        detail_status,
                    ),
                )
            if visible_indices:
                first_id = str(visible_indices[0])
                self.tree.selection_set(first_id)
                self.tree.focus(first_id)
                self.show_plan_detail(visible_indices[0])
                if self.network_var.get():
                    self.start_metadata_preload()
                else:
                    self.set_progress_idle()
            else:
                self.set_progress_idle()
                self._set_phase("无可显示结果", "warning", "可以更换目录、调整筛选条件或开启包含子文件夹后重新扫描。")
                self.show_empty_detail("没有找到可分类文件。")
            self._refresh_action_states()

    root = tk.Tk()
    try:
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    ClassifierApp(root)
    root.mainloop()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="轻小说联网分类工具")
    parser.add_argument("folder", nargs="?", help="要分类的大文件夹；不提供时启动窗口界面")
    parser.add_argument("--undo-report", help="按 classification_report.json 撤销一次分类移动")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不移动文件")
    parser.add_argument("--no-network", action="store_true", help="关闭联网识别，只使用本地文件名规则")
    parser.add_argument("--recursive", action="store_true", help="包含子文件夹中的小说文件")
    parser.add_argument("--auto-rename", action="store_true", help="根据电子书内容和 Bangumi 单卷信息自动重命名")
    parser.add_argument("--quiet", action="store_true", help="减少命令行输出")
    return parser.parse_args(argv)


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.undo_report:
        restored, skipped = undo_classification_report(Path(args.undo_report), progress=None if args.quiet else print)
        print(f"撤销完成：恢复 {restored} 个文件，跳过 {skipped} 个文件。")
        return 0
    if args.folder:
        return run_cli(args)
    launch_gui()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
