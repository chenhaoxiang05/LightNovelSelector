from __future__ import annotations

import fnmatch
import hashlib
import ipaddress
import json
import posixpath
import socket
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Iterable
from pathlib import Path

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from .constants import (
    ARCHIVE_TEXT_MAX_BYTES,
    ARCHIVE_XML_MAX_BYTES,
    CONTENT_HINT_MAX_CHARS,
    CONTENT_HINT_TEXT_EXTENSIONS,
    COVER_MAX_BYTES,
    FILE_FINGERPRINT_CHUNK_SIZE,
    IDENTITY_MAX_AUTHORS,
    IDENTITY_MAX_TAGS,
    IDENTITY_VALUE_MAX_CHARS,
    LOCAL_COVER_EXTENSIONS,
    METADATA_TEXT_MAX_CHARS,
    REMOTE_JSON_MAX_BYTES,
    REMOTE_URL_MAX_CHARS,
    USER_AGENT,
)
from .identity import (
    identity_from_filename,
    merge_book_identities,
    normalize_identity_values,
)
from .models import BookIdentity, CustomRule
from .parsing import (
    collapse_spaces,
    extract_series_guess,
    html_to_text,
    normalize_for_match,
    normalize_language_code,
    parse_volume_number,
)
from .scan_cache import PersistentScanCache, capture_file_snapshot

_PROXY_SYNTHETIC_NETWORKS = (ipaddress.ip_network("198.18.0.0/15"),)
_PROXY_SYNTHETIC_DOMAIN_SUFFIXES = (
    "anilist.co",
    "bgm.tv",
    "jikan.moe",
    "myanimelist.net",
)


def validate_https_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise ValueError("远程地址不能为空。")
    url = url.strip()
    if len(url) > REMOTE_URL_MAX_CHARS:
        raise ValueError("远程地址过长。")
    try:
        parsed = urllib.parse.urlsplit(url)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("远程地址格式无效。") from exc
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("仅允许访问不含登录信息的 HTTPS 地址。")
    hostname = parsed.hostname.rstrip(".").casefold()
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal", ".home.arpa")):
        raise ValueError("不允许访问本机或内部网络地址。")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError("不允许访问本机或内部网络地址。")
    return url


def _validate_public_hostname_resolution(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    hostname = parsed.hostname
    if not hostname:
        raise urllib.error.URLError("远程地址缺少主机名。")
    normalized_hostname = hostname.rstrip(".").casefold()
    trusted_proxy_domain = any(
        normalized_hostname == suffix or normalized_hostname.endswith(f".{suffix}")
        for suffix in _PROXY_SYNTHETIC_DOMAIN_SUFFIXES
    )
    try:
        addresses = {
            ipaddress.ip_address(str(item[4][0]).split("%", 1)[0])
            for item in socket.getaddrinfo(
                hostname,
                parsed.port or 443,
                type=socket.SOCK_STREAM,
            )
        }
    except (OSError, ValueError) as exc:
        raise urllib.error.URLError(f"无法安全解析远程主机：{hostname}") from exc
    if not addresses or any(
        not address.is_global
        and not (trusted_proxy_domain and any(address in network for network in _PROXY_SYNTHETIC_NETWORKS))
        for address in addresses
    ):
        raise urllib.error.URLError("远程主机解析到了本机或内部网络地址。")


class _HttpsOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_https_url(newurl)
        _validate_public_hostname_resolution(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_HTTPS_OPENER = urllib.request.build_opener(_HttpsOnlyRedirectHandler)


def _open_https(request: urllib.request.Request, *, timeout: float):
    _validate_public_hostname_resolution(request.full_url)
    return _HTTPS_OPENER.open(request, timeout=timeout)


def http_json(url: str, *, payload: dict | None = None, timeout: float = 10.0) -> dict:
    url = validate_https_url(url)
    headers = {"User-Agent": USER_AGENT}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    with _open_https(request, timeout=timeout) as response:
        validate_https_url(response.geturl())
        charset = response.headers.get_content_charset() or "utf-8"
        response_data = response.read(REMOTE_JSON_MAX_BYTES + 1)
    if len(response_data) > REMOTE_JSON_MAX_BYTES:
        raise RuntimeError(f"远程接口返回的 JSON 超过允许大小（{REMOTE_JSON_MAX_BYTES} 字节）。")
    try:
        result = json.loads(response_data.decode(charset, errors="replace"))
    except (json.JSONDecodeError, LookupError, RecursionError, ValueError) as exc:
        raise RuntimeError("远程接口返回了无效 JSON。") from exc
    if not isinstance(result, dict):
        raise RuntimeError("远程接口返回的 JSON 根节点不是对象。")
    return result


def http_bytes(url: str, *, timeout: float = 10.0, max_bytes: int = COVER_MAX_BYTES) -> bytes:
    if max_bytes < 1:
        raise ValueError("max_bytes 必须大于 0。")
    url = validate_https_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with _open_https(request, timeout=timeout) as response:
        validate_https_url(response.geturl())
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise RuntimeError(f"远程文件超过允许大小（{max_bytes} 字节）。")
    return data


def xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def is_image_zip_member(name: str) -> bool:
    suffix = Path(urllib.parse.unquote(name)).suffix.casefold()
    return suffix in LOCAL_COVER_EXTENSIONS and not name.endswith("/")


def resolve_zip_member(base_path: str, href: str) -> str:
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(base_path), href))
    return joined.lstrip("/")


def read_zip_member(
    zip_file: zipfile.ZipFile,
    member_name: str,
    *,
    max_bytes: int | None = None,
) -> bytes | None:
    if max_bytes is not None and max_bytes < 1:
        raise ValueError("max_bytes 必须大于 0。")
    names = {name.casefold(): name for name in zip_file.namelist()}
    actual_name = names.get(member_name.casefold())
    if not actual_name:
        return None
    try:
        info = zip_file.getinfo(actual_name)
        if max_bytes is not None and info.file_size > max_bytes:
            return None
        with zip_file.open(info) as member:
            data = member.read(max_bytes + 1 if max_bytes is not None else -1)
        if max_bytes is not None and len(data) > max_bytes:
            return None
        return data
    except (EOFError, KeyError, OSError, RuntimeError, zipfile.BadZipFile):
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

    return min(images, key=sort_key)


def read_epub_cover_bytes(path: Path) -> bytes | None:
    try:
        with zipfile.ZipFile(path) as epub:
            container_xml = read_zip_member(
                epub,
                "META-INF/container.xml",
                max_bytes=ARCHIVE_XML_MAX_BYTES,
            )
            if not container_xml:
                return None
            container = ElementTree.fromstring(container_xml)
            rootfile_path = None
            for element in container.iter():
                if xml_local_name(element.tag) == "rootfile":
                    rootfile_path = element.attrib.get("full-path")
                    if rootfile_path:
                        break
            if not rootfile_path:
                return None

            opf_data = read_zip_member(epub, rootfile_path, max_bytes=ARCHIVE_XML_MAX_BYTES)
            if not opf_data:
                return None
            opf_root = ElementTree.fromstring(opf_data)
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
                data = read_zip_member(
                    epub,
                    resolve_zip_member(rootfile_path, cover_href),
                    max_bytes=COVER_MAX_BYTES,
                )
                if data:
                    return data

            image_hrefs = [
                item.get("href", "") for item in manifest_items if item.get("media-type", "").startswith("image/")
            ]
            fallback_name = pick_archive_cover_name(resolve_zip_member(rootfile_path, href) for href in image_hrefs)
            if fallback_name:
                return read_zip_member(epub, fallback_name, max_bytes=COVER_MAX_BYTES)
    except (
        OSError,
        KeyError,
        RuntimeError,
        zipfile.BadZipFile,
        ElementTree.ParseError,
        DefusedXmlException,
    ):
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
            container_data = read_zip_member(
                epub,
                "META-INF/container.xml",
                max_bytes=ARCHIVE_XML_MAX_BYTES,
            )
            if not container_data:
                return None
            container = ElementTree.fromstring(container_data)
            rootfile_path = None
            for element in container.iter():
                if xml_local_name(element.tag) == "rootfile":
                    rootfile_path = element.attrib.get("full-path")
                    break
            if not rootfile_path:
                return None

            opf_data = read_zip_member(epub, rootfile_path, max_bytes=ARCHIVE_XML_MAX_BYTES)
            if not opf_data:
                return None
            opf_root = ElementTree.fromstring(opf_data)
            titles: list[str] = []
            manifest: dict[str, str] = {}
            spine_ids: list[str] = []
            for element in opf_root.iter():
                name = xml_local_name(element.tag)
                if name == "title" and element.text:
                    titles.append(collapse_spaces(element.text)[:METADATA_TEXT_MAX_CHARS])
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
                data = read_zip_member(epub, member, max_bytes=ARCHIVE_TEXT_MAX_BYTES)
                if not data:
                    continue
                text = html_to_text(decode_bytes(data))
                if text:
                    text_parts.append(text[:1200])
                if sum(len(part) for part in text_parts) >= CONTENT_HINT_MAX_CHARS:
                    break
            hint = collapse_spaces(" ".join(text_parts))
            return hint[:CONTENT_HINT_MAX_CHARS] or None
    except (
        OSError,
        KeyError,
        RuntimeError,
        zipfile.BadZipFile,
        ElementTree.ParseError,
        DefusedXmlException,
    ):
        return None


def read_epub_book_identity(path: Path, fallback: BookIdentity | None = None) -> BookIdentity | None:
    fallback = fallback or identity_from_filename(path.name)
    try:
        with zipfile.ZipFile(path) as epub:
            container_data = read_zip_member(
                epub,
                "META-INF/container.xml",
                max_bytes=ARCHIVE_XML_MAX_BYTES,
            )
            if not container_data:
                return None
            container = ElementTree.fromstring(container_data)
            rootfile_path = next(
                (
                    element.attrib.get("full-path")
                    for element in container.iter()
                    if xml_local_name(element.tag) == "rootfile" and element.attrib.get("full-path")
                ),
                None,
            )
            if not rootfile_path:
                return None
            opf_data = read_zip_member(epub, rootfile_path, max_bytes=ARCHIVE_XML_MAX_BYTES)
            if not opf_data:
                return None
            opf_root = ElementTree.fromstring(opf_data)

            titles: list[str] = []
            creators: list[str] = []
            languages: list[str] = []
            subjects: list[str] = []
            series_names: list[str] = []
            series_index: int | None = None
            for element in opf_root.iter():
                name = xml_local_name(element.tag).casefold()
                text = collapse_spaces(element.text or "")
                if name == "title" and text and len(titles) < 3:
                    titles.append(text[:METADATA_TEXT_MAX_CHARS])
                elif name == "creator" and text and len(creators) < IDENTITY_MAX_AUTHORS * 2:
                    creators.append(text[:IDENTITY_VALUE_MAX_CHARS])
                elif name == "language" and text and len(languages) < 8:
                    languages.append(text[:35])
                elif name == "subject" and text and len(subjects) < IDENTITY_MAX_TAGS * 2:
                    subjects.append(text[:IDENTITY_VALUE_MAX_CHARS])
                elif name == "meta":
                    meta_name = str(element.attrib.get("name") or "").casefold()
                    property_name = str(element.attrib.get("property") or "").casefold()
                    content = collapse_spaces(str(element.attrib.get("content") or "") or text)[
                        :METADATA_TEXT_MAX_CHARS
                    ]
                    if content and (meta_name == "calibre:series" or property_name == "belongs-to-collection"):
                        if len(series_names) < 8:
                            series_names.append(content)
                    elif meta_name == "calibre:series_index" and content:
                        try:
                            numeric_index = float(content)
                        except ValueError:
                            numeric_index = -1
                        if numeric_index.is_integer() and 0 <= numeric_index <= 999:
                            series_index = int(numeric_index)

            title = titles[0] if titles else fallback.title
            series_name = series_names[0] if series_names else extract_series_guess(title)
            language = next(
                (normalized for value in languages if (normalized := normalize_language_code(value)) is not None),
                fallback.language,
            )
            volume_number = series_index
            if volume_number is None:
                volume_number = parse_volume_number(title)
            if volume_number is None:
                volume_number = fallback.volume_number
            epub_identity = BookIdentity(
                title=title,
                series_name=series_name,
                authors=normalize_identity_values(
                    creators,
                    limit=IDENTITY_MAX_AUTHORS,
                    kind="author",
                ),
                volume_number=volume_number,
                language=language,
                tags=normalize_identity_values(subjects, limit=IDENTITY_MAX_TAGS),
            )
            return merge_book_identities(fallback, epub_identity)
    except (
        OSError,
        KeyError,
        RuntimeError,
        zipfile.BadZipFile,
        ElementTree.ParseError,
        DefusedXmlException,
    ):
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


def read_book_identity(path: Path, hint: str | None = None) -> BookIdentity:
    fallback = identity_from_filename(path.name, hint=hint)
    if path.suffix.casefold() == ".epub":
        return read_epub_book_identity(path, fallback) or fallback
    return fallback


def read_archive_cover_bytes(path: Path) -> bytes | None:
    try:
        with zipfile.ZipFile(path) as archive:
            cover_name = pick_archive_cover_name(archive.namelist())
            if not cover_name:
                return None
            return read_zip_member(archive, cover_name, max_bytes=COVER_MAX_BYTES)
    except (OSError, KeyError, RuntimeError, zipfile.BadZipFile):
        return None


def read_local_cover_bytes(path: Path) -> bytes | None:
    suffix = path.suffix.casefold()
    if suffix == ".epub":
        return read_epub_cover_bytes(path)
    if suffix in {".cbz", ".zip"}:
        return read_archive_cover_bytes(path)
    return None


def file_fingerprint(
    path: Path,
    *,
    checkpoint: Callable[[], None] | None = None,
    scan_cache: PersistentScanCache | None = None,
) -> str:
    cached_snapshot = None
    if scan_cache is not None:
        if checkpoint:
            checkpoint()
        cached_snapshot = capture_file_snapshot(path)
        cached = scan_cache.get_fingerprint(path, cached_snapshot)
        if cached is not None:
            if checkpoint:
                checkpoint()
            if capture_file_snapshot(path) != cached_snapshot:
                raise OSError(f"文件在读取缓存指纹时发生变化：{path}")
            return cached

    initial_stat = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            if checkpoint:
                checkpoint()
            chunk = handle.read(FILE_FINGERPRINT_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    final_stat = path.stat()
    if initial_stat.st_size != final_stat.st_size or initial_stat.st_mtime_ns != final_stat.st_mtime_ns:
        raise OSError(f"文件在计算指纹时发生变化：{path}")
    fingerprint = f"{final_stat.st_size}:{digest.hexdigest()}"
    if scan_cache is not None and cached_snapshot is not None and cached_snapshot.cacheable:
        final_snapshot = capture_file_snapshot(path)
        if cached_snapshot != final_snapshot:
            raise OSError(f"文件在计算指纹时发生变化：{path}")
        scan_cache.remember_fingerprint(path, final_snapshot, fingerprint)
    return fingerprint


def file_quick_signature(
    path: Path,
    *,
    checkpoint: Callable[[], None] | None = None,
    scan_cache: PersistentScanCache | None = None,
) -> str:
    cached_snapshot = None
    if scan_cache is not None:
        if checkpoint:
            checkpoint()
        cached_snapshot = capture_file_snapshot(path)
        cached = scan_cache.get_quick_signature(path, cached_snapshot)
        if cached is not None:
            if checkpoint:
                checkpoint()
            if capture_file_snapshot(path) != cached_snapshot:
                raise OSError(f"文件在读取缓存快速签名时发生变化：{path}")
            return cached

    initial_stat = path.stat()
    digest = hashlib.sha256()
    digest.update(str(initial_stat.st_size).encode("ascii"))
    with path.open("rb") as handle:
        if checkpoint:
            checkpoint()
        digest.update(handle.read(FILE_FINGERPRINT_CHUNK_SIZE))
        if initial_stat.st_size > FILE_FINGERPRINT_CHUNK_SIZE:
            if checkpoint:
                checkpoint()
            handle.seek(max(0, initial_stat.st_size - FILE_FINGERPRINT_CHUNK_SIZE))
            digest.update(handle.read(FILE_FINGERPRINT_CHUNK_SIZE))
    final_stat = path.stat()
    if initial_stat.st_size != final_stat.st_size or initial_stat.st_mtime_ns != final_stat.st_mtime_ns:
        raise OSError(f"文件在计算快速签名时发生变化：{path}")
    signature = f"{final_stat.st_size}:{digest.hexdigest()}"
    if scan_cache is not None and cached_snapshot is not None and cached_snapshot.cacheable:
        final_snapshot = capture_file_snapshot(path)
        if cached_snapshot != final_snapshot:
            raise OSError(f"文件在计算快速签名时发生变化：{path}")
        scan_cache.remember_quick_signature(path, final_snapshot, signature)
    return signature


def find_duplicate_files(
    paths: Iterable[Path],
    *,
    checkpoint: Callable[[], None] | None = None,
    scan_cache: PersistentScanCache | None = None,
) -> dict[Path, Path]:
    candidates: dict[str, list[Path]] = {}
    duplicates: dict[Path, Path] = {}
    for path in paths:
        if checkpoint:
            checkpoint()
        try:
            signature = file_quick_signature(
                path,
                checkpoint=checkpoint,
                scan_cache=scan_cache,
            )
        except OSError:
            continue
        candidates.setdefault(signature, []).append(path)

    for group in candidates.values():
        if len(group) < 2:
            continue
        seen: dict[str, Path] = {}
        for path in group:
            if checkpoint:
                checkpoint()
            try:
                fingerprint = file_fingerprint(
                    path,
                    checkpoint=checkpoint,
                    scan_cache=scan_cache,
                )
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
