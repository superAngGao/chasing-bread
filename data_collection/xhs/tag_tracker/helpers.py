from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from data_collection.xhs.tag_tracker.config import TRACKER_SCHEMA_VERSION


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def to_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        if not cleaned:
            return 0
        m = re.search(r"-?\d+", cleaned)
        if m:
            try:
                return int(m.group(0))
            except ValueError:
                return 0
    return 0


def extract_note_id(item: dict[str, Any]) -> str:
    note_card = item.get("note_card") or item.get("noteCard")
    if isinstance(note_card, dict):
        for key in ("id", "note_id", "noteId"):
            value = note_card.get(key)
            if isinstance(value, str) and value:
                return value
    for key in ("id", "note_id", "noteId"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def extract_xsec_token(item: dict[str, Any]) -> str:
    value = item.get("xsec_token")
    if isinstance(value, str) and value:
        return value
    note_card = item.get("note_card") or item.get("noteCard")
    if isinstance(note_card, dict):
        v2 = note_card.get("xsec_token")
        if isinstance(v2, str) and v2:
            return v2
    return ""


def is_note_item(item: dict[str, Any]) -> bool:
    model_type = item.get("model_type") or item.get("modelType")
    if isinstance(model_type, str):
        return model_type.lower() == "note"
    return isinstance(item.get("note_card") or item.get("noteCard"), dict)


def extract_publish_time(item: dict[str, Any]) -> tuple[str | None, str | None]:
    note_card = item.get("note_card") or item.get("noteCard")
    if not isinstance(note_card, dict):
        return None, None
    tags = note_card.get("corner_tag_info")
    if not isinstance(tags, list):
        return None, None
    for tag in tags:
        if not isinstance(tag, dict):
            continue
        if tag.get("type") == "publish_time":
            text = tag.get("text")
            if isinstance(text, str) and text.strip():
                raw = text.strip()
                if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
                    return raw, raw
                return raw, None
    return None, None


def extract_content_fields(item: dict[str, Any]) -> dict[str, Any]:
    note_card = item.get("note_card") or item.get("noteCard")
    if not isinstance(note_card, dict):
        return {"title": None, "author": None, "content": None}
    user = note_card.get("user")
    author = None
    if isinstance(user, dict):
        author = user.get("nickname") or user.get("nick_name")
    content = (
        note_card.get("desc")
        or note_card.get("content")
        or note_card.get("note_content")
        or note_card.get("display_desc")
    )
    if isinstance(content, str):
        content = content.strip() or None
    else:
        content = None
    return {"title": note_card.get("display_title"), "author": author, "content": content}


def extract_metrics(item: dict[str, Any]) -> dict[str, int]:
    note_card = item.get("note_card") or item.get("noteCard")
    interact = note_card.get("interact_info") if isinstance(note_card, dict) else {}
    if not isinstance(interact, dict):
        interact = {}
    return {
        "like_count": to_int(interact.get("liked_count")),
        "comment_count": to_int(interact.get("comment_count")),
        "collected_count": to_int(interact.get("collected_count")),
        "shared_count": to_int(interact.get("shared_count")),
    }


def extract_note_tags(item: dict[str, Any]) -> list[str]:
    note_card = item.get("note_card") or item.get("noteCard")
    if not isinstance(note_card, dict):
        return []

    tags: list[str] = []
    tag_list = note_card.get("tag_list") or note_card.get("tagList")
    if isinstance(tag_list, list):
        for tag_obj in tag_list:
            if not isinstance(tag_obj, dict):
                continue
            name = (
                tag_obj.get("name")
                or tag_obj.get("tag_name")
                or tag_obj.get("tagName")
                or tag_obj.get("title")
            )
            if isinstance(name, str):
                name = name.strip().lstrip("#")
                if name:
                    tags.append(name)

    text_parts = [note_card.get("display_title"), note_card.get("desc"), note_card.get("content")]
    for text in text_parts:
        if not isinstance(text, str) or not text:
            continue
        for m in re.findall(r"#([^\s#]{1,30})", text):
            t = m.strip().lstrip("#")
            if t:
                tags.append(t)

    out: list[str] = []
    seen: set[str] = set()
    for t in tags:
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def load_tracker(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "version": TRACKER_SCHEMA_VERSION,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "notes": {},
            "runs": [],
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("tracker file must be a JSON object")
    data.setdefault("version", TRACKER_SCHEMA_VERSION)
    data.setdefault("created_at", now_iso())
    data.setdefault("updated_at", now_iso())
    data.setdefault("notes", {})
    data.setdefault("runs", [])
    if not isinstance(data["notes"], dict):
        data["notes"] = {}
    if not isinstance(data["runs"], list):
        data["runs"] = []
    return data


def append_snapshot(
    *,
    note_rec: dict[str, Any],
    snapshot: dict[str, Any],
    max_history_per_note: int,
) -> bool:
    history = note_rec.setdefault("history", [])
    if not isinstance(history, list):
        history = []
        note_rec["history"] = history
    latest = note_rec.get("latest")
    changed = True
    if isinstance(latest, dict):
        changed = (
            latest.get("metrics") != snapshot.get("metrics")
            or latest.get("top_commenters") != snapshot.get("top_commenters")
            or latest.get("note_content") != snapshot.get("note_content")
        )
    if changed:
        history.append(snapshot)
        if len(history) > max_history_per_note:
            del history[0 : len(history) - max_history_per_note]
        note_rec["latest"] = snapshot
    return changed
