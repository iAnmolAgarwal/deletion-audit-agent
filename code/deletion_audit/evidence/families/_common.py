"""Helpers shared by the family parsers: file content access and JSON flattening."""
from __future__ import annotations

import json
import re
from functools import cached_property
from pathlib import Path
from typing import Any

from ..model import ParseError

SQL_CREATE_TABLE = re.compile(r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?\"?(\w+)\"?",
                              re.IGNORECASE | re.MULTILINE)


class Content:
    """Lazy, cached views of one file's bytes for sniffers and parsers."""

    def __init__(self, path: Path, data: bytes) -> None:
        """Wrap the bytes read from ``path``."""
        self.path = path
        self.data = data

    @cached_property
    def text(self) -> str | None:
        """The bytes decoded as UTF-8 (BOM stripped), or None when they are not UTF-8."""
        try:
            return self.data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return None

    @cached_property
    def lines(self) -> tuple[str, ...]:
        """Text lines without line endings; empty when the file is not text."""
        return tuple(self.text.splitlines()) if self.text is not None else ()

    @cached_property
    def json(self) -> Any:
        """The parsed JSON document, or None when the text is not a JSON object or array."""
        text = self.text
        if text is None or not text.lstrip().startswith(("{", "[")):
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    @cached_property
    def sql_tables(self) -> tuple[str, ...]:
        """Table names declared by ``CREATE TABLE`` statements, lower-cased, in order."""
        if self.text is None or self.json is not None:
            return ()
        return tuple(m.group(1).lower() for m in SQL_CREATE_TABLE.finditer(self.text))


def raw_scalar(value: Any) -> str:
    """A JSON scalar as a raw string: null -> ``"null"``, booleans lower-case, numbers as
    JSON writes them, strings unchanged."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    return json.dumps(value)


def flatten(value: Any, prefix: str = "") -> dict[str, str]:
    """Flatten nested JSON into ``{"a.b": "...", "a.c[0]": "..."}`` raw strings."""
    out: dict[str, str] = {}
    if isinstance(value, dict):
        if not value and prefix:
            out[prefix] = "{}"
        for key, item in value.items():
            out.update(flatten(item, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, list):
        if not value and prefix:
            out[prefix] = "[]"
        for index, item in enumerate(value):
            out.update(flatten(item, f"{prefix}[{index}]"))
    else:
        out[prefix] = raw_scalar(value)
    return out


def require_dict(value: Any, where: str) -> dict[str, Any]:
    """Return ``value`` if it is a JSON object, else raise ParseError naming ``where``."""
    if not isinstance(value, dict):
        raise ParseError(f"{where}: expected an object")
    return value


def require_list(value: Any, where: str) -> list[Any]:
    """Return ``value`` if it is a JSON array, else raise ParseError naming ``where``."""
    if not isinstance(value, list):
        raise ParseError(f"{where}: expected an array")
    return value


def optional_str(value: Any) -> str | None:
    """A JSON value as a raw string, or None for null / absent."""
    return None if value is None else raw_scalar(value)
