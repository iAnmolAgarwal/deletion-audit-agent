"""ReplyCache: content-addressed reply files that are written once and never overwritten.

Layout: ``<root>/<key[:2]>/<key>.json``. Each entry holds the raw reply exactly as returned,
the model ID and original ``usage`` copied from it, the run that bought it, the time it was
written, the ``request-id`` header, the request body and the API version that make up the
key. It holds no parsed answer and no derived fact.

* ``put`` writes a temporary file, fsyncs it and hard-links it into place; the link fails
  when the entry exists, so an existing entry is never replaced (first writer wins).
* ``get`` returns None only when the file does not exist. An unreadable file, one whose
  stored request does not hash to its key, or one whose ``model`` or ``usage`` differs from
  the copy inside its raw reply, raises :class:`CacheCorruptError`.
"""
from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import CacheCorruptError
from .reply import ModelReply, flatten_usage
from .request import API_VERSION, ModelRequest, canonical_json

ENTRY_FIELDS: frozenset[str] = frozenset({
    "key", "api_version", "request", "raw", "model", "usage", "bought_by_run", "written_at",
    "request_id",
})


class ReplyCache:
    """Reply files under ``root`` (see the module docstring)."""

    def __init__(self, root: Path) -> None:
        """Use ``root`` as the cache directory; it is created on first write."""
        self.root = Path(root)

    def path_for(self, key: str) -> Path:
        """The file that holds the entry for ``key``."""
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("cache keys are 64 lowercase hex characters")
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> ModelReply | None:
        """Return the cached reply for ``key`` (``from_cache=True``), or None when absent."""
        path = self.path_for(key)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise CacheCorruptError(f"cannot read cache entry {path}: {exc}") from exc
        entry, request = self._parse_entry(text, key, path)
        return ModelReply(
            key=key, raw=entry["raw"], model=entry["model"], usage=flatten_usage(entry["usage"]),
            stop_reason=str(entry["raw"].get("stop_reason")), request_id=entry["request_id"],
            from_cache=True, bought_by_run=entry["bought_by_run"], request=request)

    @staticmethod
    def _parse_entry(text: str, key: str, path: Path) -> tuple[dict[str, Any], ModelRequest]:
        """Parse an entry, check it belongs to ``key``, and return it with its request."""
        try:
            entry = json.loads(text)
        except ValueError as exc:
            raise CacheCorruptError(f"cache entry {path} is not JSON") from exc
        if (not isinstance(entry, dict) or set(entry) != ENTRY_FIELDS or not isinstance(entry["raw"], dict)
                or not isinstance(entry["model"], str) or not isinstance(entry["bought_by_run"], str)):
            raise CacheCorruptError(f"cache entry {path} does not have the entry fields")
        if entry["model"] != entry["raw"].get("model") or entry["usage"] != entry["raw"].get("usage"):
            raise CacheCorruptError(f"cache entry {path}: model or usage differs from the raw reply")
        if entry["key"] != key or entry["api_version"] != API_VERSION:
            raise CacheCorruptError(f"cache entry {path} names another key or API version")
        try:
            request = ModelRequest(entry["request"])
        except ValueError as exc:
            raise CacheCorruptError(f"cache entry {path} holds an invalid request") from exc
        if request.key() != key:
            raise CacheCorruptError(f"cache entry {path}: stored request does not hash to its key")
        return entry, request

    def put(self, req: ModelRequest, raw: Mapping[str, Any], run_id: str, *,
            request_id: str | None = None) -> None:
        """Store ``raw`` for ``req`` unless an entry already exists; atomic, never overwrites."""
        key = req.key()
        path = self.path_for(key)
        if path.exists():
            return
        entry = {
            "key": key, "api_version": API_VERSION, "request": req.plain_body(), "raw": dict(raw),
            "model": raw.get("model"), "usage": raw.get("usage"), "bought_by_run": run_id,
            "written_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "request_id": request_id,
        }
        data = canonical_json(entry).encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(tmp, path)
            except FileExistsError:
                pass
        finally:
            os.unlink(tmp)
