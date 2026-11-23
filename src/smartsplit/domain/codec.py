"""Tagged JSON for nested domain values: JSONB columns and model tool calls (CONTRACTS conventions).

Dataclasses become `{"type": "<ClassName>", ...fields}`, so unions round-trip; decoding is
driven by the declared field types, so enums, dates and tuples come back as themselves.
"""

import dataclasses
import types
from datetime import date, datetime
from enum import Enum
from typing import Any, Literal, TypeAliasType, Union, cast, get_args, get_origin

type Json = bool | int | float | str | list[Json] | dict[str, Json] | None


def encode(value: object) -> Json:
    """Turn a domain value into JSON-ready data."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, tuple | list):
        return [encode(item) for item in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        encoded: dict[str, Json] = {"type": type(value).__name__}
        for field in dataclasses.fields(value):
            encoded[field.name] = encode(getattr(value, field.name))
        return encoded
    raise TypeError(f"can't encode {type(value).__name__}")


def decode(data: Json, hint: object) -> Any:
    """Rebuild a value of type `hint` (a class, tuple, union or alias) from `encode`'s output.

    Returns Any because `hint` may be a union or alias, which Python can't express as a type
    variable; callers assign the result to a typed field.
    """
    return _decode(data, hint)


def _decode(data: Json, hint: Any) -> Any:
    if isinstance(hint, TypeAliasType):
        return _decode(data, hint.__value__)
    origin = get_origin(hint)
    if origin in (Union, types.UnionType):
        return _decode_union(data, get_args(hint))
    if origin is Literal:
        return _choose(data, get_args(hint))
    if origin is tuple:
        return _decode_tuple(data, get_args(hint))
    if hint is type(None):
        if data is not None:
            raise ValueError("expected null")
        return None
    if isinstance(hint, type):
        return _decode_class(data, hint)
    raise TypeError(f"can't decode into {hint!r}")


def _decode_union(data: Json, options: tuple[Any, ...]) -> Any:
    """Tagged dicts pick their class by name; plain values prefer an exact primitive match,
    then the first class that accepts them (dates, datetimes, enums)."""
    leaves = _flatten(options)
    if data is None and type(None) in leaves:
        return None
    if isinstance(data, dict):
        for leaf in leaves:
            if isinstance(leaf, type) and leaf.__name__ == data.get("type"):
                return _decode_class(data, leaf)
        raise ValueError(f"no union member named {data.get('type')!r}")
    for leaf in leaves:
        if get_origin(leaf) is Literal and _matches(data, get_args(leaf)):
            return _choose(data, get_args(leaf))
        if type(data) is leaf:
            return data
    for leaf in leaves:
        if isinstance(leaf, type) and leaf is not type(None):
            try:
                return _decode_class(data, leaf)
            except ValueError:
                continue
    raise ValueError(f"{data!r} matches no union member")


def _flatten(options: tuple[Any, ...]) -> list[Any]:
    """Expand aliases and nested unions into their member types."""
    leaves: list[Any] = []
    for option in options:
        resolved = option.__value__ if isinstance(option, TypeAliasType) else option
        if get_origin(resolved) in (Union, types.UnionType):
            leaves += _flatten(get_args(resolved))
        else:
            leaves.append(resolved)
    return leaves


def _decode_tuple(data: Json, args: tuple[Any, ...]) -> tuple[Any, ...]:
    if not isinstance(data, list):
        raise ValueError("expected a list")
    if args[-1:] == (Ellipsis,):
        return tuple(_decode(item, args[0]) for item in data)
    if len(args) != len(data):
        raise ValueError("wrong tuple length")
    return tuple(_decode(item, arg) for item, arg in zip(data, args, strict=True))


def _decode_field(data: dict[str, Json], field: dataclasses.Field[Any]) -> Any:
    """A field added later with a default still decodes records stored before it existed."""
    if field.name in data:
        return _decode(data[field.name], field.type)
    if field.default is not dataclasses.MISSING:
        return field.default
    raise ValueError(f"missing field {field.name!r}")


def _decode_class(data: Json, cls: type) -> Any:
    if dataclasses.is_dataclass(cls):
        if not isinstance(data, dict) or data.get("type") != cls.__name__:
            raise ValueError(f"expected a {cls.__name__}")
        return cls(**{f.name: _decode_field(data, f) for f in dataclasses.fields(cls)})
    if issubclass(cls, Enum):
        return cls(_choose(data, tuple(member.value for member in cls)))
    if cls is datetime:
        return datetime.fromisoformat(cast(str, data))
    if cls is date:
        return date.fromisoformat(cast(str, data))
    if cls is float and isinstance(data, int | float) and not isinstance(data, bool):
        return float(data)
    if cls in (bool, int, str) and type(data) is cls:
        return data
    raise ValueError(f"expected {cls.__name__}, got {data!r}")


def _matches(data: object, options: tuple[Any, ...]) -> bool:
    return any(_same(data, option) for option in options)


def _choose(data: object, options: tuple[Any, ...]) -> Any:
    """The option equal to `data`, ignoring case for text: model output doesn't guarantee the
    casing of enum values ("Soft_exclude")."""
    for option in options:
        if _same(data, option):
            return option
    raise ValueError(f"{data!r} is not one of {options}")


def _same(data: object, option: object) -> bool:
    if isinstance(data, str) and isinstance(option, str):
        return data.casefold() == option.casefold()
    return data == option
