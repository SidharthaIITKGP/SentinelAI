"""Privacy-safe audit content preparation using existing responsibility utilities."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from core.config import load_runtime_config
from engines.responsibility.pii_check.pii_detector import get_pii_detector
from engines.responsibility.pii_check.secret_detector import SecretDetector

SANITIZATION_FAILURE = "[CONTENT WITHHELD: SANITIZATION FAILED]"
METADATA_ONLY = "[CONTENT OMITTED: METADATA ONLY]"
REDACTED_METADATA = "[CONTENT REDACTED]"
_CONTENT_KEYS = frozenset({
    "flagged_text", "flagged_segments", "claim", "claim_text", "text",
    "content", "snippet", "original_response", "repaired_response",
})


@dataclass(frozen=True)
class StoredAuditContent:
    prompt: str
    llm_response: str
    final_response: str
    prompt_sha256: str
    llm_response_sha256: str
    final_response_sha256: str
    mode: str
    prompt_length: int
    llm_response_length: int
    final_response_length: int


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sanitize_evidence_metadata(value, mode: str):
    """Remove known free-text payload fields while preserving decision metadata."""
    if mode == "raw":
        return value
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return {
            key: (
                REDACTED_METADATA
                if key.casefold() in _CONTENT_KEYS
                else sanitize_evidence_metadata(item, mode)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_evidence_metadata(item, mode) for item in value]
    return value


def sanitize_content(value: str, *, scan_target: str) -> str:
    """Redact credentials and PII; withhold everything if either step fails."""
    try:
        _, without_secrets = SecretDetector().anonymize(value, scan_target=scan_target)
        _, without_pii = get_pii_detector().anonymize(
            without_secrets, scan_target=scan_target
        )
        return without_pii
    except Exception:
        return SANITIZATION_FAILURE


def prepare_audit_content(
    prompt: str, llm_response: str, final_response: str
) -> StoredAuditContent:
    mode = load_runtime_config().audit_content_mode
    hashes = (sha256_text(prompt), sha256_text(llm_response), sha256_text(final_response))
    if mode == "raw":
        stored = (prompt, llm_response, final_response)
    elif mode == "metadata_only":
        stored = (METADATA_ONLY, METADATA_ONLY, METADATA_ONLY)
    else:
        stored = (
            sanitize_content(prompt, scan_target="prompt"),
            sanitize_content(llm_response, scan_target="response"),
            sanitize_content(final_response, scan_target="response"),
        )
    return StoredAuditContent(
        *stored, *hashes, mode, len(prompt), len(llm_response), len(final_response)
    )
