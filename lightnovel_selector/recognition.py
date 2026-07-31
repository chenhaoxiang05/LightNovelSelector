from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

from .models import BookIdentity
from .parsing import extract_series_guess, normalize_for_match, score_title

_CALIBRATION_POINTS = (
    (0.00, 0.00),
    (0.45, 0.38),
    (0.55, 0.50),
    (0.60, 0.56),
    (0.74, 0.68),
    (0.84, 0.80),
    (0.92, 0.90),
    (1.00, 0.97),
)


@dataclass(frozen=True, slots=True)
class RecognitionAssessment:
    confidence: float
    level: str
    reason: str
    evidence: tuple[str, ...]


def confidence_level(confidence: float) -> str:
    if confidence >= 0.85:
        return "高"
    if confidence >= 0.65:
        return "中"
    return "需复核"


def _calibrate_raw_confidence(value: float) -> float:
    raw = float(value) if math.isfinite(value) else 0.0
    raw = max(0.0, min(raw, 1.0))
    for (left_x, left_y), (right_x, right_y) in pairwise(_CALIBRATION_POINTS):
        if raw <= right_x:
            if right_x == left_x:
                return right_y
            position = (raw - left_x) / (right_x - left_x)
            return left_y + (right_y - left_y) * position
    return _CALIBRATION_POINTS[-1][1]


def assess_recognition(
    *,
    raw_confidence: float,
    source: str,
    identity_query: str,
    chosen_identity: BookIdentity,
    local_identity: BookIdentity,
    used_content_hint: bool,
    has_book_metadata: bool,
) -> RecognitionAssessment:
    if source == "自定义规则":
        return RecognitionAssessment(
            confidence=1.0,
            level="高",
            reason="命中了用户明确配置的自定义分类规则。",
            evidence=("自定义规则直接指定系列",),
        )
    if source == "本地修正记忆":
        return RecognitionAssessment(
            confidence=0.99,
            level="高",
            reason="命中了你之前手动确认并保存在本机的系列别名。",
            evidence=("人工修正记忆精确匹配",),
        )

    calibrated = _calibrate_raw_confidence(raw_confidence)
    query_series = extract_series_guess(identity_query)
    similarity = score_title(query_series, chosen_identity.series_name)
    evidence: list[str] = []

    if source.startswith("本地内容提示"):
        reason = "文件名信息不足，使用文件内容或 EPUB 元数据推断系列。"
        evidence.append("本地内容提供了可用标题")
        calibrated += 0.04
    elif source.startswith("本地规则"):
        reason = "根据文件名中的标题和卷号结构提取系列。"
        evidence.append("文件名规则提取系列")
    else:
        reason = f"{source} 返回了当前最可靠的系列匹配。"
        evidence.append(f"在线来源：{source}")

    if similarity >= 0.98:
        evidence.append("标题与系列完全一致")
        calibrated += 0.02
    elif similarity >= 0.88:
        evidence.append(f"标题相似度 {similarity:.0%}")
        calibrated += 0.01
    elif not source.startswith("本地"):
        evidence.append("来源通过跨语言标题或别名匹配")

    if used_content_hint and "本地内容提供了可用标题" not in evidence:
        evidence.append("正文或 EPUB 内容补充标题")
    if local_identity.volume_number is not None:
        evidence.append(f"识别到第 {local_identity.volume_number} 卷")
    if local_identity.authors:
        evidence.append("EPUB 元数据提供作者")
    if local_identity.language:
        evidence.append("检测到语言信息")
    if has_book_metadata:
        evidence.append("书籍详情与当前结果合并")
        if normalize_for_match(chosen_identity.series_name) == normalize_for_match(local_identity.series_name):
            calibrated += 0.02

    calibrated = round(max(0.0, min(calibrated, 0.99)), 4)
    return RecognitionAssessment(
        confidence=calibrated,
        level=confidence_level(calibrated),
        reason=reason,
        evidence=tuple(evidence[:6]),
    )
