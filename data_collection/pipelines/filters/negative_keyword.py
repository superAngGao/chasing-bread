"""Filter out items whose text matches negative keywords."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import FilterVerdict, ImageFilter

DEFAULT_NEGATIVE_KEYWORDS: set[str] = {
    "装修",
    "穿搭",
    "探店攻略",
    "妆容",
    "美甲",
    "壁纸",
    "头像",
    "表情包",
    "手机壳",
    "减肥",
    "测评",
    "避雷",
    "加盟",
    "招商",
    "转让",
}


class NegativeKeywordFilter(ImageFilter):
    name = "negative_keyword"

    def __init__(self, keywords: set[str] | None = None) -> None:
        self.keywords = keywords or DEFAULT_NEGATIVE_KEYWORDS

    def evaluate(self, image_path: Path, metadata: dict[str, Any]) -> FilterVerdict:
        title = metadata.get("title", "") or ""
        desc = metadata.get("description", "") or ""
        text = f"{title} {desc}".lower()

        matched = [kw for kw in self.keywords if kw in text]
        passed = len(matched) == 0
        score = 1.0 if passed else 0.0
        reason = "" if passed else f"matched: {', '.join(matched)}"

        return FilterVerdict(
            passed=passed,
            score=score,
            reason=reason,
            filter_name=self.name,
            details={"matched_keywords": matched},
        )
