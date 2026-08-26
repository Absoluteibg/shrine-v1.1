"""
Text -> URL-slug conversion.

Deliberately has no database access. Turning a slug into a *unique*
slug (checking for collisions and appending -2, -3, ...) is a business
rule that differs by entity (globally unique for Work, unique-per-work
for Chapter), so that part lives in each service instead of here.
"""

import re
import unicodedata

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = value.lower()
    value = _NON_ALNUM.sub("-", value).strip("-")
    return value or "untitled"
