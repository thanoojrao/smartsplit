"""JSON schemas for strict tools, generated from the command dataclasses (SPEC section 8).

Every field is required (strict tools need that); optional fields accept null. Variants of a
union carry a `type` tag naming their class, so a tool call decodes with the domain codec.
"""

import dataclasses
import types
from datetime import date
from enum import Enum
from typing import Any, Literal, TypeAliasType, Union, get_args, get_origin

type Schema = dict[str, Any]


def object_schema(cls: type, *, tagged: bool) -> Schema:
    """The schema of one dataclass: its fields, plus a `type` tag when it is a union variant."""
    properties: Schema = {}
    if tagged:
        properties["type"] = {"type": "string", "enum": [cls.__name__]}
    for field in dataclasses.fields(cls):
        properties[field.name] = schema_for(field.type)
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def schema_for(hint: object) -> Schema:
    """The schema for one field type: primitives, dates, enums, literals, tuples, unions."""
    if isinstance(hint, TypeAliasType):
        return schema_for(hint.__value__)
    origin = get_origin(hint)
    if origin in (Union, types.UnionType):
        return {"anyOf": [schema_for(option) for option in _flatten(get_args(hint))]}
    if origin is Literal:
        return {"type": "string", "enum": list(get_args(hint))}
    if origin is tuple:
        args = get_args(hint)
        if args[-1:] == (Ellipsis,):
            return {"type": "array", "items": schema_for(args[0])}
        # A fixed pair such as (name, weight): positions are checked when the call is decoded.
        return {"type": "array", "items": {"anyOf": [schema_for(arg) for arg in args]}}
    return _schema_for_class(hint)


_PRIMITIVES: dict[object, Schema] = {
    type(None): {"type": "null"},
    bool: {"type": "boolean"},
    int: {"type": "integer"},
    str: {"type": "string"},
    date: {"type": "string", "format": "date"},
}


def _schema_for_class(hint: object) -> Schema:
    if hint in _PRIMITIVES:
        return dict(_PRIMITIVES[hint])
    if isinstance(hint, type) and issubclass(hint, Enum):
        return {"type": "string", "enum": [member.value for member in hint]}
    if isinstance(hint, type) and dataclasses.is_dataclass(hint):
        return object_schema(hint, tagged=True)
    raise TypeError(f"no schema for {hint!r}")


def _flatten(options: tuple[Any, ...]) -> list[Any]:
    leaves: list[Any] = []
    for option in options:
        resolved = option.__value__ if isinstance(option, TypeAliasType) else option
        if get_origin(resolved) in (Union, types.UnionType):
            leaves += _flatten(get_args(resolved))
        else:
            leaves.append(resolved)
    return leaves
