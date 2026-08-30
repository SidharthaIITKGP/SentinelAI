"""
SentinelAI — Groundedness Engine (Hallucination Detector)

Checks if the LLM's response is factually grounded in Acme Corp's
knowledge base. Ungrounded claims are flagged as hallucination risk.

Two phases:

Phase 1 — Startup (initialize_knowledge_base):
  Loads sample_docs.json (30 documents across 3 use cases)
  Embeds each document using Sentence Transformers
  Stores embeddings in Qdrant collection "knowledge_base"
  with metadata: doc_id, title, content, use_case

Phase 2 — Runtime (check):
  Takes LLM response + use_case
  Splits response into individual claims/sentences
  Embeds each claim
  Searches Qdrant (filtered by use_case) for similar source docs
  Classifies each claim as supported, contradicted, or insufficient evidence
  Uses deterministic number, negation, and categorical contradiction checks
  Returns GroundednessResult with verdict, score, claim evidence, and sources

Key demo dependency:
  Demo Scenario 2 (HR hallucination) depends on this file.
  LLM says "20 sick days" → source says "10" → caught here → REPAIR fires.

Integration:
  Called from pipeline.py Step 4 via asyncio.gather (parallel)
  Initialized from main.py startup event
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)
from sentence_transformers import SentenceTransformer

from api.schemas import (
    ClaimEvaluation,
    DetectorStatus,
    FlaggedClaim,
    GroundednessResult,
    GroundednessVerdict,
    SupportingSource,
    UseCase,
)

logger = logging.getLogger("sentinelai")


class GroundednessUnavailableError(RuntimeError):
    """Raised when evidence retrieval cannot produce a verification result."""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Constants
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EMBEDDING_MODEL = "all-mpnet-base-v2"
QDRANT_COLLECTION = "knowledge_base"
QDRANT_VECTOR_DIM = 768

# Minimum similarity score for a claim to be considered grounded
# per use case — finance is strictest (financial claims must be sourced)
GROUNDEDNESS_THRESHOLDS: dict[str, float] = {
    "customer_chatbot": 0.50,
    "hr_copilot":       0.50,
    "finance_tool":     0.52,
}

DEFAULT_THRESHOLD = 0.55
PREGENERATION_EVIDENCE_MIN_SCORE = 0.30

# Evidence within this similarity distance is treated as comparably relevant.
# Conflicting, comparably relevant evidence is uncertainty, never a confident
# contradiction or support verdict.
EVIDENCE_CONFLICT_MARGIN = 0.05

# Module-level singletons — initialized once at startup
_embedding_model: Optional[SentenceTransformer] = None
_qdrant_client: Optional[QdrantClient] = None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 1 — Initialization
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def initialize_knowledge_base(
    docs_path: str = "engines/trust/knowledge_base/sample_docs.json",
    qdrant_host: str = "localhost",
    qdrant_port: int = 6333,
) -> None:
    """
    Initialize the knowledge base. Called once from main.py startup.

    Loads sample_docs.json, embeds all 30 documents using Sentence
    Transformers, and upserts them into Qdrant collection "knowledge_base".
    Each point is stored with metadata for use_case filtering at query time.

    Args:
        docs_path:   Path to sample_docs.json
        qdrant_host: Qdrant server host
        qdrant_port: Qdrant server port
    """
    global _embedding_model, _qdrant_client

    logger.info("Initializing groundedness engine...")

    # Load embedding model
    logger.info(f"Loading embedding model: {EMBEDDING_MODEL}")
    _embedding_model = SentenceTransformer(EMBEDDING_MODEL)
    logger.info("Embedding model loaded")

    # Connect to Qdrant
    logger.info(f"Connecting to Qdrant at {qdrant_host}:{qdrant_port}")
    _qdrant_client = QdrantClient(host=qdrant_host, port=qdrant_port)

    # Create collection if it doesn't exist
    existing = [c.name for c in _qdrant_client.get_collections().collections]

    if QDRANT_COLLECTION in existing:
        try:
            sample = _qdrant_client.get_collection(QDRANT_COLLECTION)
            if sample.config.params.vectors.size != QDRANT_VECTOR_DIM:
                logger.info(f"Vector dimension changed — recreating {QDRANT_COLLECTION}")
                _qdrant_client.delete_collection(QDRANT_COLLECTION)
                existing.remove(QDRANT_COLLECTION)
        except Exception:
            pass

    if QDRANT_COLLECTION not in existing:
        logger.info(f"Creating Qdrant collection: {QDRANT_COLLECTION}")
        _qdrant_client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=VectorParams(
                size=QDRANT_VECTOR_DIM,
                distance=Distance.COSINE,
            ),
        )
    else:
        logger.info(f"Qdrant collection '{QDRANT_COLLECTION}' already exists")

    # Load documents from JSON
    docs_file = Path(docs_path)
    if not docs_file.exists():
        raise FileNotFoundError(f"Knowledge base not found at: {docs_path}")

    with open(docs_file, "r") as f:
        all_docs = json.load(f)

    # Flatten all docs across use cases into one list
    # structure: {"customer_chatbot": [...], "hr_copilot": [...], "finance_tool": [...]}
    flat_docs = []
    for use_case, docs in all_docs.items():
        for doc in docs:
            flat_docs.append({
                "doc_id":   doc["id"],
                "title":    doc["title"],
                "content":  doc["content"],
                "use_case": use_case,
            })

    logger.info(f"Embedding {len(flat_docs)} knowledge base documents...")

    # Index the policy title with its content. Users commonly ask for a policy
    # by name (for example, "Shipping Policy"), and content-only vectors make
    # those otherwise valid queries unnecessarily weak.
    contents = [
        f'{doc["title"]}. {doc["content"]}'
        for doc in flat_docs
    ]
    embeddings = _embedding_model.encode(
        contents,
        show_progress_bar=True,
        batch_size=16,
    )

    # Build Qdrant points
    points = [
        PointStruct(
            id=idx,
            vector=embedding.tolist(),
            payload={
                "doc_id":   doc["doc_id"],
                "title":    doc["title"],
                "content":  doc["content"],
                "use_case": doc["use_case"],
            },
        )
        for idx, (doc, embedding) in enumerate(zip(flat_docs, embeddings))
    ]

    # Upsert to Qdrant
    _qdrant_client.upsert(
        collection_name=QDRANT_COLLECTION,
        points=points,
    )

    logger.info(
        f"Knowledge base initialized | "
        f"{len(flat_docs)} documents loaded | "
        f"Collection: {QDRANT_COLLECTION}"
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Private Helper 1 — Split Into Claims
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _split_into_claims(text: str) -> list[str]:
    """
    Split LLM response into individual sentences/claims for checking.

    Uses sentence boundary detection to split on:
    - Period followed by space and capital letter
    - Exclamation marks
    - Question marks
    - Newlines

    Filters out:
    - Empty strings
    - Very short fragments (< 15 chars) — not checkable claims
    - Pure numeric strings

    Args:
        text: LLM response text

    Returns:
        List of individual claim strings
    """
    import re
    
    # Strip markdown formatting before splitting
    # Markdown symbols reduce embedding similarity against plain-text KB
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # **bold** → bold
    text = re.sub(r'\*([^*]+)\*', r'\1', text)        # *italic* → italic
    text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)  # ## headers
    text = re.sub(r'^\s*[\*\-•]\s+', '', text, flags=re.MULTILINE)  # bullet points
    text = re.sub(r'`([^`]+)`', r'\1', text)          # `code` → code

    # Split on sentence boundaries
    sentences = re.split(
        r'(?<=[.!?])\s+(?=[A-Z])|(?<=[.!?])\n+|\n{2,}',
        text.strip(),
    )

    claims = []
    for sentence in sentences:
        sentence = sentence.strip()
        # Filter out fragments too short to be meaningful claims
        if len(sentence) < 15:
            continue
        # Filter out pure numeric strings
        if sentence.replace(".", "").replace(",", "").isdigit():
            continue
        claims.append(sentence)

    # If splitting produced nothing useful, treat whole response as one claim
    if not claims:
        claims = [text.strip()]

    # Filter out meta-statements and refusals
    # These are not factual claims — no point checking groundedness
    NON_FACTUAL_PREFIXES = [
        "i am an", "i'm an", "i cannot", "i can't",
        "i do not have", "i don't have", "i am unable",
        "i'm unable", "my knowledge", "my role",
        "please contact", "please consult", "please refer",
        "for more information", "i would recommend",
        "i am not able", "i'm not able",
        "as an hr", "as a finance", "as a customer",
    ]

    filtered_claims = []
    for claim in claims:
        claim_lower = claim.lower()
        is_non_factual = any(
            claim_lower.startswith(prefix)
            for prefix in NON_FACTUAL_PREFIXES
        )
        if not is_non_factual:
            filtered_claims.append(claim)

    # If all claims filtered out, there is no evidence basis for support.
    claims = filtered_claims if filtered_claims else []

    logger.debug(f"Split response into {len(claims)} claims")
    return claims


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Private Helper 2 — Extract Numbers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _extract_numbers(text: str) -> list[float]:
    """
    Extract all numeric values from text for mismatch detection.

    Handles:
    - Integers: "10", "20"
    - Decimals: "1.25", "62.5"
    - Percentages: "80%" → 80.0
    - Currency: "$500" → 500.0
    - Comma-separated: "4,200" → 4200.0

    Args:
        text: Text to extract numbers from

    Returns:
        List of float values found in text
    """
    # Remove currency symbols and percentage signs, keep numbers
    cleaned = re.sub(r'[$€£¥]', '', text)
    cleaned = re.sub(r'%', '', cleaned)
    cleaned = re.sub(r',(\d{3})', r'\1', cleaned)  # "4,200" → "4200"

    # Find all numeric patterns
    pattern = r'\b\d+(?:\.\d+)?\b'
    matches = re.findall(pattern, cleaned)

    return [float(m) for m in matches]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Private Helper 3 — Embed and Search Qdrant
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _embed_and_search(
    claim: str,
    use_case: str,
    top_k: int = 3,
) -> list[dict]:
    """
    Embed a claim and search Qdrant for similar knowledge base documents.
    Filters results by use_case so HR claims only match HR docs.

    Args:
        claim:    The claim text to search for
        use_case: Which use case to filter by
        top_k:    Number of results to return

    Returns:
        List of dicts with keys: score, doc_id, title, content, use_case
    """
    if _embedding_model is None or _qdrant_client is None:
        logger.warning("Groundedness engine not initialized")
        return []

    loop = asyncio.get_event_loop()

    def _search():
        """Run embedding + Qdrant search synchronously in executor."""
        # Embed the claim
        embedding = _embedding_model.encode(claim, show_progress_bar=False)

        # Query Qdrant with use_case filter
        try:
            results = _qdrant_client.query_points(
                collection_name=QDRANT_COLLECTION,
                query=embedding.tolist(),
                query_filter=Filter(
                    must=[
                        FieldCondition(
                            key="use_case",
                            match=MatchValue(value=use_case),
                        )
                    ]
                ),
                limit=top_k,
            ).points
        except Exception as exc:
            logger.warning(
                "Qdrant unavailable for groundedness search: %s",
                type(exc).__name__,
            )
            raise GroundednessUnavailableError(
                "Groundedness evidence retrieval is unavailable"
            ) from exc

        return [
            {
                "score":    result.score,
                "doc_id":   result.payload.get("doc_id", ""),
                "title":    result.payload.get("title", ""),
                "content":  result.payload.get("content", ""),
                "use_case": result.payload.get("use_case", ""),
            }
            for result in results
        ]

    return await loop.run_in_executor(None, _search)


async def retrieve_generation_evidence(
    query: str,
    use_case: UseCase | str,
    *,
    top_k: int = 3,
) -> list[dict]:
    """Retrieve relevant approved local evidence for the first generation call.

    This uses the same Qdrant collection and use-case isolation as the
    post-generation verifier. A modest retrieval floor keeps unrelated chunks
    out of the prompt; post-generation groundedness remains authoritative.
    """
    use_case_value = str(getattr(use_case, "value", use_case))
    results = await _embed_and_search(query, use_case_value, top_k=top_k)
    return [
        result
        for result in results
        if float(result.get("score", 0.0)) >= PREGENERATION_EVIDENCE_MIN_SCORE
    ]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Private Helper 4 — Check Single Claim
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _polarity_markers(text: str) -> dict[str, int]:
    """Return explicit policy-category polarities without an external judge."""
    normalized = re.sub(r"\s+", " ", text.lower())
    categories: dict[str, int] = {}
    patterns = {
        "permission": (
            r"\b(?:not allowed|not permitted|may not|prohibited)\b",
            r"\b(?:allowed|permitted|approved|may(?!\s+not\b))\b",
        ),
        "inclusion": (
            r"\b(?:does not include|do not include|excludes?)\b",
            r"\b(?:includes?|included)\b",
        ),
        "eligibility": (r"\b(?:not eligible|ineligible)\b", r"\beligible\b"),
        "requirement": (r"\bnot required\b", r"\brequired\b"),
        "availability": (r"\b(?:disabled|not enabled|not available|unavailable)\b", r"\b(?:enabled|available)\b"),
        "approval": (r"\b(?:not approved|prohibited)\b", r"\bapproved\b"),
        "direction": (r"\b(?:decrease|decreased|decline|declined)\b", r"\b(?:increase|increased|growth|grew)\b"),
    }
    for category, (negative, positive) in patterns.items():
        if re.search(negative, normalized):
            categories[category] = -1
        elif re.search(positive, normalized):
            categories[category] = 1
    return categories


def _evaluate_candidate(
    claim: str,
    candidate: dict,
    threshold: float,
) -> ClaimEvaluation:
    """Classify a claim against one retrieved candidate."""
    similarity = max(0.0, min(1.0, float(candidate.get("score", 0.0))))
    source = {
        "source_doc_id": str(candidate.get("doc_id", "")) or None,
        "source_title": str(candidate.get("title", "")) or None,
        "source_excerpt": str(candidate.get("content", ""))[:500] or None,
    }
    # A sufficiently descriptive verbatim policy sentence is direct evidence,
    # regardless of embedding dilution caused by comparing it with a long
    # document vector. Keep short/generic fragments on the semantic path.
    normalized_claim = re.sub(r"\s+", " ", claim).strip().casefold()
    normalized_source = re.sub(
        r"\s+", " ", str(candidate.get("content", ""))
    ).strip().casefold()
    if len(normalized_claim) >= 20 and normalized_claim in normalized_source:
        return ClaimEvaluation(
            claim_text=claim,
            verdict=GroundednessVerdict.SUPPORTED,
            similarity_score=max(similarity, threshold),
            reason="The claim is a verbatim statement from approved local evidence.",
            **source,
        )
    if similarity < threshold:
        return ClaimEvaluation(
            claim_text=claim,
            verdict=GroundednessVerdict.INSUFFICIENT_EVIDENCE,
            similarity_score=similarity,
            reason=(
                f"Best local evidence similarity {similarity:.3f} is below "
                f"the {threshold:.3f} threshold."
            ),
            **source,
        )

    source_text = str(candidate.get("content", ""))
    claim_numbers = _extract_numbers(claim)
    source_numbers = _extract_numbers(source_text)
    unmatched_numbers = [
        number
        for number in claim_numbers
        if not any(abs(number - source_number) < 0.01 for source_number in source_numbers)
    ]
    if claim_numbers and source_numbers and unmatched_numbers:
        return ClaimEvaluation(
            claim_text=claim,
            verdict=GroundednessVerdict.CONTRADICTED,
            similarity_score=similarity,
            reason="Material numeric values conflict with the retrieved local evidence.",
            contradiction_type="NUMERIC_MISMATCH",
            **source,
        )
    if claim_numbers and not source_numbers:
        return ClaimEvaluation(
            claim_text=claim,
            verdict=GroundednessVerdict.INSUFFICIENT_EVIDENCE,
            similarity_score=similarity,
            reason="The claim contains key numbers absent from the retrieved evidence.",
            **source,
        )

    claim_polarities = _polarity_markers(claim)
    source_polarities = _polarity_markers(source_text)
    conflicts = [
        category
        for category, polarity in claim_polarities.items()
        if category in source_polarities and source_polarities[category] != polarity
    ]
    if conflicts:
        contradiction_type = (
            "NEGATION" if conflicts[0] in {"permission", "inclusion", "eligibility", "requirement"}
            else "CATEGORICAL"
        )
        return ClaimEvaluation(
            claim_text=claim,
            verdict=GroundednessVerdict.CONTRADICTED,
            similarity_score=similarity,
            reason=f"Explicit {conflicts[0]} polarity conflicts with local evidence.",
            contradiction_type=contradiction_type,
            **source,
        )

    unlimited_terms = (
        "unlimited", "no limit", "no cap", "no maximum", "without limit",
    )
    if any(term in claim.lower() for term in unlimited_terms) and source_numbers:
        return ClaimEvaluation(
            claim_text=claim,
            verdict=GroundednessVerdict.CONTRADICTED,
            similarity_score=similarity,
            reason="An unlimited claim conflicts with an explicit numeric limit.",
            contradiction_type="CATEGORICAL",
            **source,
        )

    return ClaimEvaluation(
        claim_text=claim,
        verdict=GroundednessVerdict.SUPPORTED,
        similarity_score=similarity,
        reason="Relevant local evidence supports the claim with compatible values.",
        **source,
    )


def evaluate_claim(
    claim: str,
    search_results: list[dict],
    threshold: float,
) -> ClaimEvaluation:
    """Classify one claim using all retrieved top-k local evidence.

    Retrieval rank alone does not decide the verdict. The strongest supporting
    and contradicting candidates compete by similarity, while similarly strong
    conflict is reported as insufficient evidence.
    """
    if not search_results:
        return ClaimEvaluation(
            claim_text=claim,
            verdict=GroundednessVerdict.INSUFFICIENT_EVIDENCE,
            similarity_score=0.0,
            reason="No relevant local evidence was retrieved.",
        )

    evaluations = [
        _evaluate_candidate(claim, candidate, threshold)
        for candidate in search_results
    ]
    supports = [
        item for item in evaluations
        if item.verdict == GroundednessVerdict.SUPPORTED
    ]
    contradictions = [
        item for item in evaluations
        if item.verdict == GroundednessVerdict.CONTRADICTED
    ]
    strongest_support = max(supports, key=lambda item: item.similarity_score, default=None)
    strongest_contradiction = max(
        contradictions, key=lambda item: item.similarity_score, default=None
    )

    if strongest_support and strongest_contradiction:
        difference = strongest_support.similarity_score - strongest_contradiction.similarity_score
        if abs(difference) <= EVIDENCE_CONFLICT_MARGIN:
            return ClaimEvaluation(
                claim_text=claim,
                verdict=GroundednessVerdict.INSUFFICIENT_EVIDENCE,
                similarity_score=max(
                    strongest_support.similarity_score,
                    strongest_contradiction.similarity_score,
                ),
                source_doc_id=strongest_support.source_doc_id,
                source_title=strongest_support.source_title,
                source_excerpt=strongest_support.source_excerpt,
                reason=(
                    "Comparably strong local evidence both supports and contradicts "
                    "the claim; review or more evidence is required."
                ),
            )
        if difference > 0:
            return strongest_support.model_copy(update={
                "reason": (
                    "The strongest local evidence supports the claim and is more "
                    "relevant than the contradicting candidate."
                )
            })
        return strongest_contradiction.model_copy(update={
            "reason": (
                "The strongest local evidence contradicts the claim and no equally "
                "strong or stronger supporting evidence was retrieved."
            )
        })

    if strongest_support:
        return strongest_support
    if strongest_contradiction:
        return strongest_contradiction
    return max(evaluations, key=lambda item: item.similarity_score)


def aggregate_verdict(evaluations: list[ClaimEvaluation]) -> GroundednessVerdict:
    """Aggregate claim verdicts conservatively and deterministically."""
    verdicts = {evaluation.verdict for evaluation in evaluations}
    if GroundednessVerdict.CONTRADICTED in verdicts:
        return GroundednessVerdict.CONTRADICTED
    if GroundednessVerdict.INSUFFICIENT_EVIDENCE in verdicts or not evaluations:
        return GroundednessVerdict.INSUFFICIENT_EVIDENCE
    return GroundednessVerdict.SUPPORTED


async def _check_single_claim(
    claim: str,
    use_case: str,
    threshold: float,
) -> ClaimEvaluation:
    """
    Check if a single claim is grounded in the knowledge base.

    Deterministic evidence check:
    1. Similarity threshold: is the topic covered in our knowledge base?
    2. Number mismatch: if topic matches, do the numbers agree?

    Args:
        claim:     The claim text to check
        use_case:  Which use case knowledge base to search
        threshold: Minimum similarity to consider grounded

    Returns:
        A ClaimEvaluation with an explicit evidence verdict and source metadata.
    """
    # Search knowledge base
    results = await _embed_and_search(claim, use_case, top_k=3)

    return evaluate_claim(claim, results, threshold)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main Public Function
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def check(
    response: str,
    use_case: UseCase,
) -> GroundednessResult:
    """
    Main entry point. Called from core/pipeline.py Step 4.

    Checks if the LLM response is grounded in Acme Corp's knowledge base.
    Splits response into claims, checks each against Qdrant, returns result.

    Args:
        response: Raw LLM response text to evaluate
        use_case: Which use case determines which KB docs to search
                  and which threshold to apply

    Returns:
        GroundednessResult with:
          score:              0.0 (hallucinating) to 1.0 (fully grounded)
          flagged_claims:     list of ungrounded sentences
          supporting_sources: list of KB docs that DID support claims
          total_claims_checked
          grounded_claims_count
          use_case_kb_used

    Usage in pipeline.py:
        from engines.trust.groundedness import check as groundedness_check
        groundedness_result = await groundedness_check(llm_response, request.use_case)

    Demo Scenario 2:
        LLM says "20 sick days" → source says "10" → CONTRADICTED → REPAIR
    """
    if _embedding_model is None or _qdrant_client is None:
        logger.warning("Groundedness engine unavailable; verification not performed")
        return GroundednessResult(
            status=DetectorStatus.UNAVAILABLE,
            verdict=GroundednessVerdict.UNAVAILABLE,
            score=0.0,
            total_claims_checked=0,
            grounded_claims_count=0,
            use_case_kb_used=use_case,
        )

    use_case_str = use_case if isinstance(use_case, str) else use_case.value
    threshold = GROUNDEDNESS_THRESHOLDS.get(use_case_str, DEFAULT_THRESHOLD)

    logger.info(
        f"Checking groundedness | use_case={use_case_str} | "
        f"threshold={threshold} | response_length={len(response)}"
    )

    # Split response into individual claims
    claims = _split_into_claims(response)
    total_claims = len(claims)

    if total_claims == 0:
        logger.warning("No claims extracted from response")
        return GroundednessResult(
            verdict=GroundednessVerdict.INSUFFICIENT_EVIDENCE,
            score=0.5,
            total_claims_checked=0,
            grounded_claims_count=0,
            use_case_kb_used=use_case,
        )

    # Check all claims concurrently
    check_tasks = [
        _check_single_claim(claim, use_case_str, threshold)
        for claim in claims
    ]
    try:
        results = await asyncio.gather(*check_tasks)
    except Exception as exc:
        logger.warning(
            "Groundedness verification unavailable during evidence retrieval: %s",
            type(exc).__name__,
        )
        return GroundednessResult(
            status=DetectorStatus.UNAVAILABLE,
            verdict=GroundednessVerdict.UNAVAILABLE,
            score=0.0,
            total_claims_checked=0,
            grounded_claims_count=0,
            use_case_kb_used=use_case,
        )

    # Process results
    evaluations = list(results)
    verdict = aggregate_verdict(evaluations)
    flagged_claims: list[FlaggedClaim] = []
    supporting_sources: list[SupportingSource] = []
    grounded_count = sum(
        evaluation.verdict == GroundednessVerdict.SUPPORTED
        for evaluation in evaluations
    )

    for evaluation in evaluations:
        if evaluation.verdict != GroundednessVerdict.SUPPORTED:
            flagged_claims.append(
                FlaggedClaim(
                    claim_text=evaluation.claim_text,
                    similarity_score=round(evaluation.similarity_score, 4),
                    threshold_used=threshold,
                )
            )
        if evaluation.source_doc_id and evaluation.source_excerpt:
            existing_ids = {source.doc_id for source in supporting_sources}
            if evaluation.source_doc_id not in existing_ids:
                supporting_sources.append(
                    SupportingSource(
                        doc_id=evaluation.source_doc_id,
                        title=evaluation.source_title or "Untitled evidence",
                        chunk_text=evaluation.source_excerpt[:200],
                        similarity_score=round(evaluation.similarity_score, 4),
                        use_case=use_case,
                    )
                )

    score_values = {
        GroundednessVerdict.SUPPORTED: 1.0,
        GroundednessVerdict.INSUFFICIENT_EVIDENCE: 0.5,
        GroundednessVerdict.CONTRADICTED: 0.0,
    }
    # The public score maps the conservative aggregate verdict directly:
    # SUPPORTED=1.0, INSUFFICIENT_EVIDENCE=0.5, CONTRADICTED=0.0.
    overall_score = score_values[verdict]

    logger.info(
        f"Groundedness check complete | "
        f"score={overall_score:.3f} | "
        f"grounded={grounded_count}/{total_claims} | "
        f"flagged={len(flagged_claims)} claims | "
        f"use_case={use_case_str}"
    )

    return GroundednessResult(
        verdict=verdict,
        score=overall_score,
        flagged_claims=flagged_claims,
        supporting_sources=supporting_sources,
        claim_evaluations=evaluations,
        total_claims_checked=total_claims,
        grounded_claims_count=grounded_count,
        use_case_kb_used=use_case,
    )
