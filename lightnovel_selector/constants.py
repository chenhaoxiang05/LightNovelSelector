from __future__ import annotations

APP_NAME = "Light Novel Selector"
APP_VERSION = "2.1.0-dev.2"
USER_AGENT = f"LightNovelSelector/{APP_VERSION} (+local-file-classifier)"
BANGUMI_SEARCH_URL = "https://api.bgm.tv/v0/search/subjects"
BANGUMI_SUBJECT_WEB_URL = "https://bgm.tv/subject/{subject_id}"
BANGUMI_SEARCH_LIMIT = 20
BANGUMI_DETAIL_PAGES = 4
LOCAL_COVER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
METADATA_CACHE_VERSION = 1
METADATA_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30
METADATA_CACHE_MAX_ENTRIES = 2000
METADATA_CACHE_MAX_BYTES = 8 * 1024 * 1024
SETTINGS_MAX_BYTES = 1024 * 1024
REPORT_MAX_BYTES = 64 * 1024 * 1024
REPORT_JOURNAL_MAX_BYTES = 64 * 1024 * 1024
REPORT_JOURNAL_SCHEMA_VERSION = 1
REPORT_UI_MAX_ITEMS = 1000
CUSTOM_RULE_MAX_COUNT = 200
CUSTOM_RULE_PATTERN_MAX_CHARS = 240
SERIES_NAME_MAX_CHARS = 120
METADATA_TEXT_MAX_CHARS = 512
METADATA_SUMMARY_MAX_CHARS = 20_000
IDENTITY_VALUE_MAX_CHARS = 120
IDENTITY_MAX_AUTHORS = 8
IDENTITY_MAX_TAGS = 12
CLASSIFICATION_CANDIDATE_MAX_COUNT = 8
REMOTE_URL_MAX_CHARS = 4096
LOCAL_PATH_MAX_CHARS = 32_767
SCAN_MAX_FILES = 10_000
SCAN_MAX_ENTRIES = 200_000
CONTENT_HINT_MAX_CHARS = 5000
CONTENT_HINT_TEXT_EXTENSIONS = {".txt", ".md", ".html", ".htm"}
ARCHIVE_XML_MAX_BYTES = 2 * 1024 * 1024
ARCHIVE_TEXT_MAX_BYTES = 2 * 1024 * 1024
COVER_MAX_BYTES = 8 * 1024 * 1024
REMOTE_JSON_MAX_BYTES = 2 * 1024 * 1024
METADATA_PRELOAD_WORKERS = 4
FILE_FINGERPRINT_CHUNK_SIZE = 1024 * 1024
REPORT_SCHEMA_VERSION = 2
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
