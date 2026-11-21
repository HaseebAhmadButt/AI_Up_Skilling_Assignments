"""Exact cost-tier retrieval from Chroma for new software requests."""

from __future__ import annotations

import json
import os
from decimal import Decimal, InvalidOperation

from dotenv import load_dotenv


load_dotenv()


class PolicyRetrievalError(RuntimeError):
    """Chroma could not provide a single applicable approval policy record."""


def _cost_cents(value) -> int:
    try:
        cost = Decimal(str(value).replace("$", "").replace(",", "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise PolicyRetrievalError("Request cost is not a valid monetary amount.") from exc
    if not cost.is_finite() or cost <= 0 or cost.as_tuple().exponent < -2:
        raise PolicyRetrievalError("Request cost must be positive and have no more than two decimal places.")
    cents = cost * 100
    if cents != cents.to_integral_value():
        raise PolicyRetrievalError("Request cost cannot be represented as whole cents.")
    return int(cents)


def retrieve_approval_policy(request_cost) -> dict:
    """Retrieve exactly one cost-tier record from Chroma; never fall back to local rules."""
    cents = _cost_cents(request_cost)
    try:
        import chromadb
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

        client = chromadb.HttpClient(
            host=os.getenv("CHROMA_HOST", "localhost"),
            port=int(os.getenv("CHROMA_PORT", "8000")),
            tenant=os.getenv("CHROMA_TENANT", "default_tenant"),
            database=os.getenv("CHROMA_DATABASE", "default_database"),
        )
        client.heartbeat()
        collection = client.get_collection(
            name=os.getenv("CHROMA_COLLECTION", "assetdesk_policy"),
            embedding_function=DefaultEmbeddingFunction(),
        )
        result = collection.query(
            query_texts=[f"Software request approval rules for a cost of {cents} cents"],
            where={"$and": [
                {"record_type": "approval_tier"},
                {"is_current": True},
                {"min_cost_cents": {"$lte": cents}},
                {"max_cost_cents": {"$gte": cents}},
            ]},
            n_results=2,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        raise PolicyRetrievalError(
            "Could not retrieve the approval policy from ChromaDB; request routing stopped with no local fallback."
        ) from exc

    ids = result.get("ids", [[]])[0]
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]
    if len(ids) != 1 or len(documents) != 1 or len(metadatas) != 1:
        raise PolicyRetrievalError(
            f"Expected one matching approval policy for {cents} cents; Chroma returned {len(ids)}."
        )

    metadata = metadatas[0]
    try:
        required_roles = json.loads(metadata["required_roles_json"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise PolicyRetrievalError("Retrieved policy record has invalid required-role metadata.") from exc
    if not required_roles or metadata.get("approval_status") != "unverified":
        raise PolicyRetrievalError("Retrieved policy record is empty or not marked as prototype policy.")

    citation = (f"{metadata['document_title']}, {metadata['version']}, "
                f"§{metadata['section_id']} — {metadata['section_title']}")
    return {
        "record_id": ids[0],
        "policy_text": documents[0],
        "document_id": metadata["document_id"],
        "document_title": metadata["document_title"],
        "version": metadata["version"],
        "section_id": metadata["section_id"],
        "section_title": metadata["section_title"],
        "citation": citation,
        "approval_status": metadata["approval_status"],
        "required_roles": required_roles,
        "min_cost_cents": metadata["min_cost_cents"],
        "max_cost_cents": metadata["max_cost_cents"],
        "distance": distances[0] if distances else None,
    }
