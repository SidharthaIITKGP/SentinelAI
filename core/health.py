"""Lightweight dependency health checks; never invokes model generation."""

from __future__ import annotations

import asyncio
import os


async def check_postgresql(timeout_seconds: float = 1.0) -> bool:
    try:
        from data.audit_logger import _get_pool
        pool = await asyncio.wait_for(_get_pool(), timeout=timeout_seconds)
        value = await asyncio.wait_for(pool.fetchval("SELECT 1"), timeout=timeout_seconds)
        return value == 1
    except Exception:
        return False


async def check_qdrant(timeout_seconds: float = 1.0) -> bool:
    client = None
    try:
        from qdrant_client import AsyncQdrantClient
        client = AsyncQdrantClient(
            host=os.getenv("QDRANT_HOST", "localhost"),
            port=int(os.getenv("QDRANT_PORT", "6333")),
            timeout=timeout_seconds,
        )
        await asyncio.wait_for(client.get_collections(), timeout=timeout_seconds)
        return True
    except Exception:
        return False
    finally:
        if client is not None:
            try:
                await client.close()
            except Exception:
                pass


def llm_is_configured() -> bool:
    """Configuration presence only; this deliberately makes no provider call."""
    return bool(os.getenv("GROQ_API_KEY", "").strip())
