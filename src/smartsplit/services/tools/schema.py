"""JSON schemas for the agent's tools, generated from the argument dataclasses (SPEC 8.3).

Every field is listed as required, and optional ones accept null; a call that leaves one out
still decodes (`complete` fills it). Variants of a union carry a `type` tag naming their
class, so a tool call decodes with the domain codec.
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


def complete(data: object, hint: object) -> object:
    """Fill fields the model left out: null for optional ones, [] for lists, false for flags;
    and the `type` tag of a dataclass that isn't a union variant. Anything else is left for
    the codec to refuse."""
    if isinstance(hint, TypeAliasType):
        return complete(data, hint.__value__)
    origin = get_origin(hint)
    if origin in (Union, types.UnionType) and isinstance(data, dict):
        named = [
            option
            for option in _flatten(get_args(hint))
            if isinstance(option, type) and option.__name__ == data.get("type")
        ]
        return complete(data, named[0]) if named else data
    if origin is tuple and isinstance(data, list) and get_args(hint)[-1:] == (Ellipsis,):
        return [complete(item, get_args(hint)[0]) for item in data]
    if isinstance(hint, type) and dataclasses.is_dataclass(hint) and isinstance(data, dict):
        return _complete_fields(data, hint)
    return data


def _complete_fields(data: dict[str, object], cls: type) -> dict[str, object]:
    filled: dict[str, object] = {"type": cls.__name__, **data}
    for field in dataclasses.fields(cls):
        if field.name in data:
            filled[field.name] = complete(data[field.name], field.type)
        else:
            missing = _missing_value(field.type)
            if missing is not _NO_DEFAULT:
                filled[field.name] = missing
    return filled


_NO_DEFAULT = object()


def _missing_value(hint: object) -> object:
    if isinstance(hint, TypeAliasType):
        return _missing_value(hint.__value__)
    origin = get_origin(hint)
    if origin in (Union, types.UnionType) and type(None) in _flatten(get_args(hint)):
        return None
    if origin is tuple:
        return []
    if hint is bool:
        return False
    return _NO_DEFAULT
