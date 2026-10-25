"""A JSON Schema subset checker, used to re-validate structured replies in code.

Only the keywords in :data:`SUPPORTED_KEYWORDS` are accepted. :func:`check_schema_supported`
rejects a schema that uses any other keyword, so :func:`validate` never skips a constraint
silently. Values compared against ``enum`` or ``const`` must match exactly, as JSON Schema
defines it (developer decision T84): the API enforces the exact values, so a reply such as
``"not_deletion"`` for ``"NOT_DELETION"`` means something went wrong. It fails the check and goes
to repair, instead of passing here and then missing an exact comparison downstream. The match
is exact at every depth and type-exact (``True`` is not ``1``, ``1.0`` is not ``1``). A ``$ref``
must stand alone: a node with keywords beside its ``$ref`` is refused, never half-checked.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

SUPPORTED_KEYWORDS: frozenset[str] = frozenset({
    "type", "properties", "required", "additionalProperties", "items", "enum", "const",
    "anyOf", "allOf", "$ref", "$defs", "definitions", "description", "title", "default",
    "examples", "minItems", "maxItems",
})
_TYPES = frozenset({"object", "array", "string", "integer", "number", "boolean", "null"})


def check_schema_supported(schema: Any, path: str = "#") -> list[str]:
    """Return one problem string per unsupported keyword or malformed node in ``schema``."""
    if isinstance(schema, bool):
        return []
    if not isinstance(schema, Mapping):
        return [f"{path}: schema node is not an object"]
    problems = [f"{path}: unsupported keyword {k!r}" for k in schema if k not in SUPPORTED_KEYWORDS]
    problems += _check_type_keyword(schema.get("type"), path)
    for name, sub in _subschemas(schema):
        problems += check_schema_supported(sub, f"{path}/{name}")
    ref = schema.get("$ref")
    if ref is not None and len(schema) > 1:
        problems.append(f"{path}: $ref must stand alone; siblings {sorted(k for k in schema if k != '$ref')}")
    if ref is not None and not (isinstance(ref, str) and ref.startswith(("#/$defs/", "#/definitions/"))):
        problems.append(f"{path}: only local $defs/definitions references are supported")
    return problems


def unresolved_refs(schema: Any, root: Any = None) -> list[str]:
    """Return every ``$ref`` in ``schema`` that does not resolve inside ``root`` (default: ``schema``)."""
    if root is None:
        root = schema
    if not isinstance(schema, Mapping) or not isinstance(root, Mapping):
        return []
    missing: list[str] = []
    ref = schema.get("$ref")
    if isinstance(ref, str) and _resolve(ref, root) is False:
        missing.append(ref)
    for _, sub in _subschemas(schema):
        missing += unresolved_refs(sub, root)
    return missing


def _check_type_keyword(value: Any, path: str) -> list[str]:
    """Return problems with a ``type`` keyword value."""
    if value is None:
        return []
    names = value if isinstance(value, list) else [value]
    return [f"{path}: unknown type {n!r}" for n in names if n not in _TYPES]


def _subschemas(schema: Mapping[str, Any]) -> list[tuple[str, Any]]:
    """List the (path label, subschema) pairs directly under ``schema``."""
    subs: list[tuple[str, Any]] = []
    for group in ("properties", "$defs", "definitions"):
        for name, sub in (schema.get(group) or {}).items():
            subs.append((f"{group}/{name}", sub))
    for group in ("anyOf", "allOf"):
        for i, sub in enumerate(schema.get(group) or []):
            subs.append((f"{group}/{i}", sub))
    for single in ("items", "additionalProperties"):
        if isinstance(schema.get(single), Mapping):
            subs.append((single, schema[single]))
    return subs


def validate(value: Any, schema: Any, root: Mapping[str, Any] | None = None, path: str = "$") -> list[str]:
    """Return one error string per place where ``value`` breaks ``schema``; empty means valid."""
    if root is None:
        root = schema if isinstance(schema, Mapping) else {}
    if schema is True:
        return []
    if schema is False:
        return [f"{path}: no value is allowed here"]
    if not isinstance(schema, Mapping):
        return [f"{path}: schema node is not an object"]
    if "$ref" in schema:
        if len(schema) > 1:
            return [f"{path}: $ref with sibling keywords is not supported"]
        return validate(value, _resolve(schema["$ref"], root), root, path)
    errors = _check_type(value, schema.get("type"), path)
    if errors:
        return errors
    errors += _check_constants(value, schema, path)
    for sub in schema.get("allOf") or []:
        errors += validate(value, sub, root, path)
    if "anyOf" in schema and not any(not validate(value, s, root, path) for s in schema["anyOf"]):
        errors.append(f"{path}: matches no anyOf branch")
    if isinstance(value, Mapping):
        errors += _check_object(value, schema, root, path)
    if isinstance(value, list):
        errors += _check_array(value, schema, root, path)
    return errors


def _resolve(ref: str, root: Mapping[str, Any]) -> Any:
    """Resolve a local ``#/$defs/Name`` or ``#/definitions/Name`` reference."""
    group, _, name = ref[2:].partition("/")
    target = (root.get(group) or {}).get(name)
    if target is None:
        return False
    return target


def _type_matches(value: Any, name: str) -> bool:
    """Whether ``value`` has the JSON type ``name`` (booleans are not numbers)."""
    if name == "object":
        return isinstance(value, Mapping)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "null":
        return value is None
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return False


def _check_type(value: Any, type_kw: Any, path: str) -> list[str]:
    """Check the ``type`` keyword."""
    if type_kw is None:
        return []
    names = type_kw if isinstance(type_kw, list) else [type_kw]
    if any(_type_matches(value, n) for n in names):
        return []
    return [f"{path}: expected type {type_kw}, got {type(value).__name__}"]


def _same(a: Any, b: Any) -> bool:
    """Exact equality for enum/const at every depth: same type at each node (bool is not int,
    1.0 is not 1), same keys for objects, same length and order for arrays."""
    if isinstance(a, Mapping) and isinstance(b, Mapping):
        return set(a) == set(b) and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    return type(a) is type(b) and bool(a == b)


def _check_constants(value: Any, schema: Mapping[str, Any], path: str) -> list[str]:
    """Check the ``enum`` and ``const`` keywords."""
    errors: list[str] = []
    if "enum" in schema and not any(_same(value, e) for e in schema["enum"]):
        errors.append(f"{path}: value not in enum")
    if "const" in schema and not _same(value, schema["const"]):
        errors.append(f"{path}: value is not the const")
    return errors


def _check_object(value: Mapping[str, Any], schema: Mapping[str, Any], root: Mapping[str, Any],
                  path: str) -> list[str]:
    """Check ``required``, ``properties`` and ``additionalProperties``."""
    errors = [f"{path}: missing required {k!r}" for k in schema.get("required") or [] if k not in value]
    props: Mapping[str, Any] = schema.get("properties") or {}
    extra = schema.get("additionalProperties", True)
    for k, v in value.items():
        if k in props:
            errors += validate(v, props[k], root, f"{path}.{k}")
        elif extra is False:
            errors.append(f"{path}: unexpected property {k!r}")
        elif isinstance(extra, Mapping):
            errors += validate(v, extra, root, f"{path}.{k}")
    return errors


def _check_array(value: Sequence[Any], schema: Mapping[str, Any], root: Mapping[str, Any],
                 path: str) -> list[str]:
    """Check ``items``, ``minItems`` and ``maxItems``."""
    errors: list[str] = []
    if "minItems" in schema and len(value) < schema["minItems"]:
        errors.append(f"{path}: fewer than {schema['minItems']} items")
    if "maxItems" in schema and len(value) > schema["maxItems"]:
        errors.append(f"{path}: more than {schema['maxItems']} items")
    if "items" in schema:
        for i, item in enumerate(value):
            errors += validate(item, schema["items"], root, f"{path}[{i}]")
    return errors
