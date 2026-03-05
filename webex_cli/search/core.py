from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Callable

from webex_cli.errors import CliError, DomainCode

FieldSchema = dict[str, str]
_INT_PATTERN = re.compile(r"^-?\d+$")


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str
    pos: int


@dataclass(frozen=True)
class _Comparison:
    field: str
    op: str
    value: Any
    pos: int


@dataclass(frozen=True)
class _Logical:
    op: str
    left: Any
    right: Any


@dataclass(frozen=True)
class _SortSpec:
    field: str
    descending: bool


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _error(message: str, *, pos: int, token: str | None = None, details: dict[str, Any] | None = None) -> CliError:
    payload = {"column": pos + 1}
    if token is not None:
        payload["token"] = token
    if details:
        payload.update(details)
    return CliError(DomainCode.VALIDATION_ERROR, message, details=payload)


def _tokenize(expression: str) -> list[_Token]:
    tokens: list[_Token] = []
    index = 0
    while index < len(expression):
        char = expression[index]
        if char.isspace():
            index += 1
            continue
        if char in {"(", ")", ","}:
            mapping = {"(": "LPAREN", ")": "RPAREN", ",": "COMMA"}
            tokens.append(_Token(mapping[char], char, index))
            index += 1
            continue
        if expression.startswith(">=", index) or expression.startswith("<=", index) or expression.startswith("!=", index) or expression.startswith("!~", index):
            tokens.append(_Token("OP", expression[index : index + 2], index))
            index += 2
            continue
        if char in {"=", "~", ">", "<"}:
            tokens.append(_Token("OP", char, index))
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            start = index
            index += 1
            value_chars: list[str] = []
            while index < len(expression):
                current = expression[index]
                if current == "\\":
                    index += 1
                    if index >= len(expression):
                        raise _error("Unterminated escape sequence in filter expression.", pos=start, token=expression[start:])
                    value_chars.append(expression[index])
                    index += 1
                    continue
                if current == quote:
                    index += 1
                    break
                value_chars.append(current)
                index += 1
            else:
                raise _error("Unterminated string literal in filter expression.", pos=start, token=expression[start:])
            tokens.append(_Token("STRING", "".join(value_chars), start))
            continue
        if char.isalnum() or char == "_":
            start = index
            value_chars: list[str] = []
            while index < len(expression) and (expression[index].isalnum() or expression[index] == "_"):
                value_chars.append(expression[index])
                index += 1
            tokens.append(_Token("IDENT", "".join(value_chars), start))
            continue
        raise _error("Unexpected character in filter expression.", pos=index, token=char)
    tokens.append(_Token("EOF", "", len(expression)))
    return tokens


class _Parser:
    def __init__(self, expression: str) -> None:
        self._expression = expression
        self._tokens = _tokenize(expression)
        self._index = 0

    def parse(self) -> Any:
        node = self._parse_or()
        token = self._current()
        if token.kind != "EOF":
            raise _error("Unexpected trailing token in filter expression.", pos=token.pos, token=token.value)
        return node

    def _current(self) -> _Token:
        return self._tokens[self._index]

    def _advance(self) -> _Token:
        token = self._current()
        self._index += 1
        return token

    def _match_keyword(self, keyword: str) -> bool:
        token = self._current()
        if token.kind == "IDENT" and token.value.upper() == keyword:
            self._advance()
            return True
        return False

    def _expect(self, kind: str, message: str) -> _Token:
        token = self._current()
        if token.kind != kind:
            raise _error(message, pos=token.pos, token=token.value)
        return self._advance()

    def _parse_or(self) -> Any:
        node = self._parse_and()
        while self._match_keyword("OR"):
            node = _Logical("OR", node, self._parse_and())
        return node

    def _parse_and(self) -> Any:
        node = self._parse_primary()
        while self._match_keyword("AND"):
            node = _Logical("AND", node, self._parse_primary())
        return node

    def _parse_primary(self) -> Any:
        token = self._current()
        if token.kind == "LPAREN":
            self._advance()
            node = self._parse_or()
            self._expect("RPAREN", "Expected ')' in filter expression.")
            return node
        return self._parse_comparison()

    def _parse_comparison(self) -> _Comparison:
        field = self._expect("IDENT", "Expected field name in filter expression.")
        field_name = field.value.lower()
        if self._match_keyword("IN"):
            self._expect("LPAREN", "Expected '(' after IN.")
            values = [self._parse_value()]
            while self._current().kind == "COMMA":
                self._advance()
                values.append(self._parse_value())
            self._expect("RPAREN", "Expected ')' to close IN list.")
            return _Comparison(field_name, "IN", values, field.pos)
        operator = self._expect("OP", "Expected operator in filter expression.")
        return _Comparison(field_name, operator.value, self._parse_value(), field.pos)

    def _parse_value(self) -> Any:
        token = self._current()
        if token.kind not in {"IDENT", "STRING"}:
            raise _error("Expected literal value in filter expression.", pos=token.pos, token=token.value)
        self._advance()
        return _typed_literal(token.value, quoted=token.kind == "STRING")


def _typed_literal(value: str, *, quoted: bool) -> Any:
    if not quoted:
        lowered = value.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if _INT_PATTERN.fullmatch(value):
            return int(value)
    parsed_dt = _parse_datetime(value)
    if parsed_dt is not None and ("T" in value or "-" in value):
        return parsed_dt
    return value


def _parse_bool_like(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def _coerce_item_value(value: Any, field_type: str) -> Any:
    if value is None:
        return None
    if field_type == "bool":
        return _parse_bool_like(value)
    if field_type == "int":
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        text = str(value).strip()
        if not text:
            return None
        try:
            return int(float(text))
        except (TypeError, ValueError):
            return None
    if field_type == "datetime":
        return _parse_datetime(value)
    return str(value)


def _coerce_filter_value(value: Any, field_type: str, *, pos: int, field: str) -> Any:
    if field_type == "bool":
        parsed = _parse_bool_like(value)
        if parsed is not None:
            return parsed
        raise _error("Expected boolean literal for filter field.", pos=pos, details={"field": field})
    if field_type == "int":
        if isinstance(value, bool):
            raise _error("Expected integer literal for filter field.", pos=pos, details={"field": field})
        if isinstance(value, int):
            return value
        text = str(value).strip()
        if _INT_PATTERN.fullmatch(text):
            return int(text)
        raise _error("Expected integer literal for filter field.", pos=pos, details={"field": field})
    if field_type == "datetime":
        parsed = value if isinstance(value, datetime) else _parse_datetime(value)
        if parsed is None:
            raise _error("Expected datetime literal for filter field.", pos=pos, details={"field": field})
        return parsed
    return str(value)


def _string_equal(left: str, right: str, *, case_sensitive: bool) -> bool:
    if case_sensitive:
        return left == right
    return left.lower() == right.lower()


def _string_contains(left: str, right: str, *, case_sensitive: bool) -> bool:
    if case_sensitive:
        return right in left
    return right.lower() in left.lower()


def _compare(field_value: Any, comparison: _Comparison, field_type: str, *, case_sensitive: bool) -> bool:
    if field_value is None:
        return False
    if comparison.op == "IN":
        values = [_coerce_filter_value(item, field_type, pos=comparison.pos, field=comparison.field) for item in comparison.value]
        if field_type == "string":
            left = str(field_value)
            return any(_string_equal(left, str(item), case_sensitive=case_sensitive) for item in values)
        return field_value in values

    target = _coerce_filter_value(comparison.value, field_type, pos=comparison.pos, field=comparison.field)
    if field_type == "string":
        left = str(field_value)
        right = str(target)
        if comparison.op == "=":
            return _string_equal(left, right, case_sensitive=case_sensitive)
        if comparison.op == "!=":
            return not _string_equal(left, right, case_sensitive=case_sensitive)
        if comparison.op == "~":
            return _string_contains(left, right, case_sensitive=case_sensitive)
        if comparison.op == "!~":
            return not _string_contains(left, right, case_sensitive=case_sensitive)
        if not case_sensitive:
            left = left.lower()
            right = right.lower()
    if comparison.op == "=":
        return field_value == target
    if comparison.op == "!=":
        return field_value != target
    if comparison.op == ">":
        return field_value > target
    if comparison.op == ">=":
        return field_value >= target
    if comparison.op == "<":
        return field_value < target
    if comparison.op == "<=":
        return field_value <= target
    if comparison.op in {"~", "!~"}:
        raise _error("Substring operators are only valid for string fields.", pos=comparison.pos, details={"field": comparison.field})
    raise _error("Unsupported operator in filter expression.", pos=comparison.pos, token=comparison.op)


def _evaluate(node: Any, item: dict[str, Any], schema: FieldSchema, *, case_sensitive: bool) -> bool:
    if isinstance(node, _Logical):
        if node.op == "AND":
            return _evaluate(node.left, item, schema, case_sensitive=case_sensitive) and _evaluate(
                node.right, item, schema, case_sensitive=case_sensitive
            )
        return _evaluate(node.left, item, schema, case_sensitive=case_sensitive) or _evaluate(
            node.right, item, schema, case_sensitive=case_sensitive
        )
    if node.field not in schema:
        raise _error("Unknown filter field.", pos=node.pos, details={"field": node.field})
    field_type = schema[node.field]
    field_value = _coerce_item_value(item.get(node.field), field_type)
    return _compare(field_value, node, field_type, case_sensitive=case_sensitive)


def evaluate_filter(expression: str | None, item: dict[str, Any], schema: FieldSchema, *, case_sensitive: bool = False) -> bool:
    if expression is None or not expression.strip():
        return True
    parsed = _Parser(expression).parse()
    return _evaluate(parsed, item, schema, case_sensitive=case_sensitive)


def collect_pages(
    fetch_page: Callable[[str | None], tuple[list[dict[str, Any]], str | None]],
    *,
    start_token: str | None,
    max_pages: int,
) -> tuple[list[dict[str, Any]], str | None, list[str]]:
    if max_pages < 1:
        raise CliError(DomainCode.VALIDATION_ERROR, "`--max-pages` must be a positive integer.", details={"max_pages": max_pages})
    if start_token is not None:
        items, next_token = fetch_page(start_token)
        return list(items), next_token, []

    items: list[dict[str, Any]] = []
    warnings: list[str] = []
    token: str | None = None
    seen_tokens: set[str] = set()
    pages = 0
    while pages < max_pages:
        previous_count = len(items)
        page_items, next_token = fetch_page(token)
        items.extend(page_items)
        pages += 1
        if not next_token:
            return items, None, warnings
        if token is not None and next_token == token:
            raise CliError(
                DomainCode.UPSTREAM_UNAVAILABLE,
                "Pagination token repeated with no progress.",
                details={"reason": "PAGINATION_CYCLE", "page_token": next_token},
            )
        if next_token in seen_tokens:
            raise CliError(
                DomainCode.UPSTREAM_UNAVAILABLE,
                "Pagination loop detected.",
                details={"reason": "PAGINATION_CYCLE", "page_token": next_token},
            )
        if len(items) == previous_count and not page_items:
            raise CliError(
                DomainCode.UPSTREAM_UNAVAILABLE,
                "Pagination made no progress.",
                details={"reason": "PAGINATION_NO_PROGRESS", "page_token": next_token},
            )
        seen_tokens.add(next_token)
        token = next_token
    warnings.append("MAX_PAGES_LIMIT_REACHED")
    return items, token, warnings


def _normalize_sort_specs(sort_spec: str | None, tie_breaker_field: str) -> list[_SortSpec]:
    if sort_spec is None or not sort_spec.strip():
        fields = [_SortSpec(tie_breaker_field, False)]
    else:
        fields = []
        for raw_part in sort_spec.split(","):
            part = raw_part.strip()
            if not part:
                continue
            if ":" in part:
                field, direction = part.split(":", 1)
            else:
                field, direction = part, "asc"
            normalized_direction = direction.strip().lower()
            if normalized_direction not in {"asc", "desc"}:
                raise CliError(
                    DomainCode.VALIDATION_ERROR,
                    "Invalid sort direction.",
                    details={"sort": raw_part},
                )
            fields.append(_SortSpec(field.strip().lower(), normalized_direction == "desc"))
        if not fields:
            fields = [_SortSpec(tie_breaker_field, False)]
    if tie_breaker_field not in {item.field for item in fields}:
        fields.append(_SortSpec(tie_breaker_field, False))
    return fields


def _sort_value(item: dict[str, Any], field: str, schema: FieldSchema) -> tuple[int, Any]:
    field_type = schema.get(field, "string")
    value = _coerce_item_value(item.get(field), field_type)
    if value is None:
        return (1, "")
    if isinstance(value, datetime):
        return (0, value.timestamp())
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, str):
        return (0, value.lower())
    return (0, value)


def sort_items(items: list[dict[str, Any]], sort_spec: str | None, schema: FieldSchema, *, tie_breaker_field: str) -> list[dict[str, Any]]:
    specs = _normalize_sort_specs(sort_spec, tie_breaker_field)
    for spec in specs:
        if spec.field not in schema:
            raise CliError(DomainCode.VALIDATION_ERROR, "Unknown sort field.", details={"field": spec.field})

    result = list(items)
    for spec in reversed(specs):
        result.sort(key=lambda item, field=spec.field: _sort_value(item, field, schema), reverse=spec.descending)
    return result
