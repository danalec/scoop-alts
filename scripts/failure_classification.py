"""Classify an updater failure as an upstream problem or a problem in our code.

The two deserve different reactions: an upstream failure (a vendor refusing
connections, a rate limit, a 5xx) is not actionable by the maintainer and must
not read like a broken updater. Anything that is not clearly upstream stays in
the "code" bucket on purpose - a failure we cannot explain is treated as ours
until proven otherwise.
"""

from __future__ import annotations

import re
from typing import List, NamedTuple, Sequence

FAILURE_UPSTREAM = "upstream"
FAILURE_CODE = "code"

# Signals that only the network or the remote side can produce.
_UPSTREAM_PATTERNS = (
    r"connection refused",
    r"connection reset",
    r"connection aborted",
    r"failed to establish a new connection",
    r"name or service not known",
    r"temporary failure in name resolution",
    r"network is unreachable",
    r"no route to host",
    r"max retries exceeded",
    r"rate limit exceeded",
    r"too many requests",
    r"remote end closed connection",
    r"server error:\s*50[0-9]",
    r"\b50[0-9]\b\s*(service unavailable|bad gateway|gateway time-out)",
    r"sslerror",
    r"certificate verify failed",
    r"protocol error.*unexpected eof",
)


class FailureBucket(NamedTuple):
    """A group of failures that share a cause."""

    kind: str
    packages: List[str]


def classify_failure(error_text: str) -> str:
    """Return ``upstream`` for network/remote failures, ``code`` otherwise."""
    if not error_text:
        return FAILURE_CODE
    lowered = error_text.lower()
    for pattern in _UPSTREAM_PATTERNS:
        if re.search(pattern, lowered):
            return FAILURE_UPSTREAM
    return FAILURE_CODE


def group_failures(failures: Sequence[tuple]) -> List[FailureBucket]:
    """Group ``(package, error_text)`` pairs into upstream and code buckets.

    The upstream bucket comes first: it is the one that explains a run failing
    without anyone having broken anything.
    """
    upstream: List[str] = []
    code: List[str] = []
    for package, error_text in failures:
        if classify_failure(error_text) == FAILURE_UPSTREAM:
            upstream.append(package)
        else:
            code.append(package)

    buckets: List[FailureBucket] = []
    if upstream:
        buckets.append(FailureBucket(FAILURE_UPSTREAM, sorted(upstream)))
    if code:
        buckets.append(FailureBucket(FAILURE_CODE, sorted(code)))
    return buckets
