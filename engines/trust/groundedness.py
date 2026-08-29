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
  Checks similarity threshold — grounded or not
  Checks number mismatch — catches "20 sick days" when doc says "10"
  Returns GroundednessResult with score, flagged claims, sources

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
    FlaggedClaim,
    GroundednessResult,
    SupportingSource,
    UseCase,
)

logger = logging.getLogger("sentinelai")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Constants
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
QDRANT_COLLECTION = "knowledge_base"
QDRANT_VECTOR_DIM = 384

# Minimum similarity score for a claim to be considered grounded
# per use case — finance is strictest (financial claims must be sourced)
GROUNDEDNESS_THRESHOLDS: dict[str, float] = {
    "customer_chatbot": 0.55,
    "hr_copilot":       0.55,
    "finance_tool":     0.60,
}

DEFAULT_THRESHOLD = 0.55

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

    # Embed all document contents
    contents = [doc["content"] for doc in flat_docs]
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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Private Helper 4 — Check Single Claim
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _check_single_claim(
    claim: str,
    use_case: str,
    threshold: float,
) -> tuple[bool, float, Optional[dict]]:
    """
    Check if a single claim is grounded in the knowledge base.

    Two-stage check:
    1. Similarity threshold: is the topic covered in our knowledge base?
    2. Number mismatch: if topic matches, do the numbers agree?

    Args:
        claim:     The claim text to check
        use_case:  Which use case knowledge base to search
        threshold: Minimum similarity to consider grounded

    Returns:
        Tuple of (is_grounded, best_similarity_score, best_matching_source)
        is_grounded=True  → claim is backed by source
        is_grounded=False → claim is ungrounded or numbers mismatch
    """
    # Search knowledge base
    results = await _embed_and_search(claim, use_case, top_k=3)

    if not results:
        logger.debug(f"No results found for claim: {claim[:60]}")
        return False, 0.0, None

    best = results[0]
    best_score = best["score"]

    # Stage 1 — Similarity threshold check
    if best_score < threshold:
        # Topic not covered in knowledge base at all
        logger.debug(
            f"Claim below threshold | score={best_score:.3f} | "
            f"threshold={threshold:.3f} | claim={claim[:60]}"
        )
        return False, best_score, best

    # Stage 2 — Number mismatch detection
    # Topic is covered — now check if numbers agree
    claim_numbers = _extract_numbers(claim)
    source_numbers = _extract_numbers(best["content"])

    if claim_numbers and source_numbers:
        # Both have numbers — check for mismatch
        # A mismatch is when claim numbers don't appear in source numbers at all
        claim_set = set(claim_numbers)
        source_set = set(source_numbers)

        # Check if ANY claim number is in the source
        # (allows for rounding differences within 0.01)
        has_match = any(
            any(abs(c - s) < 0.01 for s in source_set)
            for c in claim_set
        )

        if not has_match:
            logger.info(
                f"NUMBER MISMATCH detected | "
                f"claim_numbers={claim_numbers} | "
                f"source_numbers={source_numbers} | "
                f"claim={claim[:60]}"
            )
            # Topic matched but numbers wrong — hallucination
            return False, best_score, best

    # Both checks passed — claim is grounded
    logger.debug(
        f"Claim grounded | score={best_score:.3f} | "
        f"source={best['title']} | claim={claim[:60]}"
    )
    return True, best_score, best


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
        LLM says "20 sick days" → source says "10" → score ~0.50 → REPAIR
    """
    if _embedding_model is None or _qdrant_client is None:
        logger.warning(
            "Groundedness engine not initialized — returning default score 1.0"
        )
        return GroundednessResult(
            score=1.0,
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
            score=1.0,
            total_claims_checked=0,
            grounded_claims_count=0,
            use_case_kb_used=use_case,
        )

    # Check all claims concurrently
    check_tasks = [
        _check_single_claim(claim, use_case_str, threshold)
        for claim in claims
    ]
    results = await asyncio.gather(*check_tasks)

    # Process results
    flagged_claims: list[FlaggedClaim] = []
    supporting_sources: list[SupportingSource] = []
    grounded_count = 0

    for claim, (is_grounded, similarity_score, best_source) in zip(claims, results):
        if is_grounded:
            grounded_count += 1
            if best_source:
                # Add to supporting sources (avoid duplicates by doc_id)
                existing_ids = [s.doc_id for s in supporting_sources]
                if best_source["doc_id"] not in existing_ids:
                    supporting_sources.append(
                        SupportingSource(
                            doc_id=best_source["doc_id"],
                            title=best_source["title"],
                            chunk_text=best_source["content"][:200],
                            similarity_score=round(similarity_score, 4),
                            use_case=use_case,
                        )
                    )
        else:
            flagged_claims.append(
                FlaggedClaim(
                    claim_text=claim,
                    similarity_score=round(similarity_score, 4),
                    threshold_used=threshold,
                )
            )

    # Calculate overall groundedness score
    overall_score = grounded_count / total_claims if total_claims > 0 else 1.0
    overall_score = round(overall_score, 4)

    logger.info(
        f"Groundedness check complete | "
        f"score={overall_score:.3f} | "
        f"grounded={grounded_count}/{total_claims} | "
        f"flagged={len(flagged_claims)} claims | "
        f"use_case={use_case_str}"
    )

    return GroundednessResult(
        score=overall_score,
        flagged_claims=flagged_claims,
        supporting_sources=supporting_sources,
        total_claims_checked=total_claims,
        grounded_claims_count=grounded_count,
        use_case_kb_used=use_case,
    )
