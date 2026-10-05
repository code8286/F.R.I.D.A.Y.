# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Minimal JSON-Schema (subset) validator — enough to strictly validate tool arguments.

Supported: type (incl. lists), enum, const, properties, required, additionalProperties (bool|schema),
items, minItems, maxItems, minLength, maxLength, pattern, minimum, maximum, anyOf, oneOf.
Unknown keywords are ignored (annotations like description/default). Bools are never ints.
"""

from __future__ import annotations

import re
from typing import Any

_TYPES = {"string", "integer", "number", "boolean", "object", "array", "null"}


def _is_type(value: Any, t: str) -> bool:
    if t == "string":
        return isinstance(value, str)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "object":
        return isinstance(value, dict)
    if t == "array":
        return isinstance(value, list)
    if t == "null":
        return value is None
    return False


def check_schema(schema: Any, path: str = "$") -> None:
    """Raise ValueError if the schema itself is malformed (called at tool registration)."""
    if not isinstance(schema, dict):
        raise ValueError(f"{path}: schema must be an object")
    t = schema.get("type")
    if t is not None:
        ts = t if isinstance(t, list) else [t]
        for x in ts:
            if x not in _TYPES:
                raise ValueError(f"{path}: unknown type {x!r}")
    for key in ("properties",):
        if key in schema:
            if not isinstance(schema[key], dict):
                raise ValueError(f"{path}.{key} must be an object")
            for name, sub in schema[key].items():
                check_schema(sub, f"{path}.{key}.{name}")
    if "required" in schema:
        req = schema["required"]
        if not isinstance(req, list) or not all(isinstance(r, str) for r in req):
            raise ValueError(f"{path}.required must be a list of strings")
        props = schema.get("properties", {})
        for r in req:
            if r not in props:
                raise ValueError(f"{path}.required names unknown property {r!r}")
    if "items" in schema:
        check_schema(schema["items"], f"{path}.items")
    if isinstance(schema.get("additionalProperties"), dict):
        check_schema(schema["additionalProperties"], f"{path}.additionalProperties")
    for key in ("anyOf", "oneOf"):
        if key in schema:
            if not isinstance(schema[key], list) or not schema[key]:
                raise ValueError(f"{path}.{key} must be a non-empty list")
            for i, sub in enumerate(schema[key]):
                check_schema(sub, f"{path}.{key}[{i}]")
    if "pattern" in schema:
        try:
            re.compile(schema["pattern"])
        except re.error as exc:
            raise ValueError(f"{path}.pattern invalid: {exc}") from exc


def validate(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []
    _validate(value, schema, path, errors)
    return errors


def _validate(value: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    t = schema.get("type")
    if t is not None:
        ts = t if isinstance(t, list) else [t]
        if not any(_is_type(value, x) for x in ts):
            errors.append(f"{path}: expected {'|'.join(ts)}, got {type(value).__name__}")
            return
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: must be one of {schema['enum']!r}")

    if "anyOf" in schema:
        if not any(not validate(value, sub, path) for sub in schema["anyOf"]):
            errors.append(f"{path}: does not match any allowed shape")
    if "oneOf" in schema:
        matches = sum(1 for sub in schema["oneOf"] if not validate(value, sub, path))
        if matches != 1:
            errors.append(f"{path}: must match exactly one allowed shape (matched {matches})")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: does not match pattern {schema['pattern']!r}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above maximum {schema['maximum']}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if "items" in schema:
            for i, item in enumerate(value):
                _validate(item, schema["items"], f"{path}[{i}]", errors)

    if isinstance(value, dict):
        props = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{path}.{name}: required")
        extra = schema.get("additionalProperties", True)
        for name, sub in value.items():
            if name in props:
                _validate(sub, props[name], f"{path}.{name}", errors)
            elif extra is False:
                errors.append(f"{path}.{name}: unexpected property")
            elif isinstance(extra, dict):
                _validate(sub, extra, f"{path}.{name}", errors)
