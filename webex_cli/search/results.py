from __future__ import annotations

from typing import Iterable


def match_query(query: str | None, values: Iterable[object], *, case_sensitive: bool = False) -> tuple[bool, int, str]:
    texts: list[str] = []
    for value in values:
        text = str(value).strip()
        if text:
            texts.append(text)

    if query is None or not query.strip():
        return True, 0, texts[0] if texts else ""
    if not texts:
        return False, 0, ""

    query_text = query.strip()
    query_tokens = [token for token in query_text.split() if token]
    normalized_query = query_text if case_sensitive else query_text.lower()
    normalized_tokens = query_tokens if case_sensitive else [token.lower() for token in query_tokens]
    normalized_texts = texts if case_sensitive else [text.lower() for text in texts]
    combined = " ".join(normalized_texts)

    whole_query_match = normalized_query in combined
    token_hits = sum(1 for token in normalized_tokens if token in combined)
    if not whole_query_match and token_hits < len(normalized_tokens):
        return False, 0, texts[0]

    best_snippet = texts[0]
    best_snippet_score = -1
    for raw_text, normalized_text in zip(texts, normalized_texts):
        snippet_score = (100 if normalized_query in normalized_text else 0) + sum(
            10 for token in normalized_tokens if token in normalized_text
        )
        if snippet_score > best_snippet_score:
            best_snippet = raw_text
            best_snippet_score = snippet_score

    score = (200 if whole_query_match else 0) + token_hits * 10
    return True, score, best_snippet


def primary_sort_field(sort_value: str | None, *, default_field: str) -> str:
    if sort_value is None or not sort_value.strip():
        return default_field
    first_part = sort_value.split(",", 1)[0].strip()
    if not first_part:
        return default_field
    field_name = first_part.split(":", 1)[0].strip().lower()
    return field_name or default_field
