"""
Future RAG architecture — interfaces only (not implemented).

Planned stack:
- Qdrant vector store (per-tenant collections)
- Embedding service (e.g. sentence-transformers or API)
- Tenant memory documents (policies, SOPs, past advisor notes)
- Business knowledge retrieval before LLM calls
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class RetrievalChunk:
    tenant_id: int
    document_id: str
    text: str
    score: float
    metadata: Dict[str, Any]


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        """Return embedding vectors for each text."""


class VectorStore(ABC):
    @abstractmethod
    def upsert(
        self, tenant_id: int, document_id: str, vector: List[float], payload: Dict[str, Any]
    ) -> None:
        pass

    @abstractmethod
    def search(
        self, tenant_id: int, query_vector: List[float], limit: int = 5
    ) -> List[RetrievalChunk]:
        pass


class TenantMemoryStore(ABC):
    @abstractmethod
    def save_note(self, tenant_id: int, note: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        pass

    @abstractmethod
    def recall(self, tenant_id: int, query: str, limit: int = 5) -> List[RetrievalChunk]:
        pass


class BusinessKnowledgeRetriever(ABC):
    """Combines embeddings + Qdrant + tenant memory for RAG context."""

    @abstractmethod
    def retrieve_context(
        self, tenant_id: int, question: str, *, max_tokens: int = 1500
    ) -> str:
        pass


# Stub implementations raise NotImplementedError until Phase 2 RAG rollout.


class QdrantVectorStore(VectorStore):
    def upsert(self, tenant_id: int, document_id: str, vector: List[float], payload: Dict[str, Any]) -> None:
        raise NotImplementedError("Qdrant RAG — Phase 2")

    def search(self, tenant_id: int, query_vector: List[float], limit: int = 5) -> List[RetrievalChunk]:
        raise NotImplementedError("Qdrant RAG — Phase 2")


class StubEmbeddingProvider(EmbeddingProvider):
    def embed(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError("Embeddings — Phase 2")
