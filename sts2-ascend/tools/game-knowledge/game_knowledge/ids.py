"""Identifiers shared by resource, runtime, and assembly extraction layers."""

from __future__ import annotations

import re


def model_entry_id(type_name: str) -> str:
    """Reproduce ``StringHelper.Slugify(type.Name)`` used by ModelId.Entry.

    The game's .NET regular expression inserts an underscore before every
    non-leading ASCII uppercase character, including adjacent acronym
    letters.  It then uppercases, maps whitespace to underscores, and drops
    all remaining non ``[A-Z0-9_]`` characters.
    """

    value = type_name.strip()
    value = re.sub(r"(?<!^)(?=[A-Z])", "_", value)
    value = re.sub(r"\s+", "_", value.upper())
    return re.sub(r"[^A-Z0-9_]", "", value)

