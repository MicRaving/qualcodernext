"""User-facing search/help regex helpers.

A bare ``*`` in a query is treated as a wildcard (any run of characters)
rather than a regex quantifier on the previous character — so ``LM*`` finds
``LM`` followed by anything instead of ``L`` with an optional ``M``. An
escaped ``\\*`` keeps its literal meaning. Everything else passes through as
a regular expression.
"""

from __future__ import annotations

import re

# A ``*`` not preceded by a backslash → wildcard.
_BARE_STAR = re.compile(r"(?<!\\)\*")


def compile_user_pattern(query: str, *, ignore_case: bool = False) -> re.Pattern[str]:
    """Compile a user query as regex, mapping an unescaped ``*`` to ``.*``."""
    if len(query) > 500:
        raise re.error("pattern too long")
    pattern = _BARE_STAR.sub(".*", query)
    if len(pattern) > 2000:
        raise re.error("pattern too long")
    return re.compile(pattern, re.IGNORECASE if ignore_case else 0)
