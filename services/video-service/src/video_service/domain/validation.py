"""Upload validation (M05 Step 2, FR-M05-01).

Server-side validation of the upload request BEFORE minting a signed URL —
container/codec (via content-type), declared size, and source type. Pure
function, so the checks are unit-testable and identical to what the client
should pre-check.
"""

from __future__ import annotations

#: Containers/codecs M05 accepts (phone + DSLR + web).
ALLOWED_CONTENT_TYPES = frozenset({"video/mp4", "video/quicktime", "video/webm"})
#: Capture sources (Book M05 §3.1).
ALLOWED_SOURCE_TYPES = frozenset({"mobile", "dslr", "nets", "match"})
#: Hard upload ceiling (bytes). 500 MB — a generous single-stroke clip.
MAX_SIZE_BYTES = 500 * 1024 * 1024
#: A clip below this is almost certainly truncated / not a real upload.
MIN_SIZE_BYTES = 1024


def validate_upload(*, content_type: str, source_type: str, size_bytes: int | None) -> list[str]:
    """Return a list of validation-failure reason codes (empty = valid)."""
    reasons: list[str] = []
    if content_type not in ALLOWED_CONTENT_TYPES:
        reasons.append("unsupported_content_type")
    if source_type not in ALLOWED_SOURCE_TYPES:
        reasons.append("unsupported_source_type")
    if size_bytes is not None:
        if size_bytes > MAX_SIZE_BYTES:
            reasons.append("file_too_large")
        elif size_bytes < MIN_SIZE_BYTES:
            reasons.append("file_too_small")
    return reasons
