from __future__ import annotations

from typing import Any


def extract_item_id(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    for key in ("id", "note_id", "noteId"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    note_card = (
        item.get("noteCard") if isinstance(item.get("noteCard"), dict) else item.get("note_card")
    )
    if isinstance(note_card, dict):
        value = note_card.get("id") or note_card.get("note_id") or note_card.get("noteId")
        if isinstance(value, str) and value:
            return value
    return ""
