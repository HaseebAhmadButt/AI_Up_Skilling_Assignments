"""Index versioned policy sections from ``policy_documents`` into ChromaDB.

Run from the L3 directory with ``python -m policy.ingest_chroma``. The command
uses deterministic IDs and upsert, so rerunning it updates the same records.
Historical versions are retained; no collections or records are deleted.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()
DOCS_DIR = Path(__file__).resolve().parents[1] / "policy_documents"
COLLECTION_NAME = os.getenv("CHROMA_COLLECTION", "assetdesk_policy")
SECTION_HEADING = re.compile(r"^##\s+§(?P<section_id>[\w.-]+)\s+[-—]\s+(?P<title>.+?)\s*$")
REQUIRED_FIELDS = (
    "document_id",
    "document_title",
    "version",
    "effective_date",
    "approval_status",
    "authority",
    "source_path",
)


@dataclass(frozen=True)
class PolicySection:
    """One Chroma record with its citation and source metadata."""

    record_id: str
    text: str
    metadata: dict[str, str | int | bool]


def parse_front_matter(text: str, path: Path) -> dict[str, str]:
    """Read the deliberately simple ``key: value`` YAML subset used by policy docs."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path}: missing YAML front matter")
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise ValueError(f"{path}: unterminated YAML front matter") from exc

    fields: dict[str, str] = {}
    for line in lines[1:end]:
        key, separator, value = line.partition(":")
        if not separator or not key.strip() or not value.strip():
            raise ValueError(f"{path}: invalid front matter line: {line!r}")
        fields[key.strip()] = value.strip().strip("\"'")

    missing = [name for name in REQUIRED_FIELDS if not fields.get(name)]
    if missing:
        raise ValueError(f"{path}: missing required metadata: {', '.join(missing)}")
    return fields


def split_policy_sections(path: Path) -> list[PolicySection]:
    """Convert each stable ``## §...`` section into a citation-ready record."""
    text = path.read_text(encoding="utf-8")
    fields = parse_front_matter(text, path)
    lines = text.splitlines()
    sections: list[PolicySection] = []
    current_id: str | None = None
    current_title: str | None = None
    body: list[str] = []

    def add_section() -> None:
        if current_id is None or current_title is None:
            return
        section_text = "\n".join(body).strip()
        if not section_text:
            raise ValueError(f"{path}: section {current_id} is empty")
        stable_key = f"{fields['document_id']}:{fields['version']}:{current_id}"
        record_id = hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:32]
        metadata: dict[str, str | int | bool] = {
            **fields,
            "section_id": current_id,
            "section_title": current_title,
            "source_file": path.name,
            "is_current": True,
            "record_type": "policy_section",
        }
        sections.append(PolicySection(record_id, section_text, metadata))

        # Index cost bands as separate structured records so boundary amounts use
        # exact Chroma metadata filtering instead of approximate semantic ranking.
        if fields.get("document_id") == "software-request-approval" and current_id == "2":
            for row in re.findall(r"^\|\s*([\d,]+)\s*\|\s*([\d,]+)\s*\|\s*([^|]+?)\s*\|\s*$",
                                  section_text, re.M):
                minimum, maximum, role_text = row
                minimum_cents = int(minimum.replace(",", ""))
                maximum_cents = int(maximum.replace(",", ""))
                roles = [role.strip() for role in role_text.split(",") if role.strip()]
                tier_key = f"{fields['document_id']}:{fields['version']}:{current_id}:tier:{minimum_cents}"
                tier_id = hashlib.sha256(tier_key.encode("utf-8")).hexdigest()[:32]
                tier_text = (f"For a request cost from {minimum_cents} through {maximum_cents} cents inclusive, "
                             f"the required approvers in order are: {', '.join(roles)}.")
                tier_metadata = {
                    **fields,
                    "section_id": current_id,
                    "section_title": current_title,
                    "source_file": path.name,
                    "is_current": True,
                    "record_type": "approval_tier",
                    "min_cost_cents": minimum_cents,
                    "max_cost_cents": maximum_cents,
                    "required_roles_json": json.dumps(roles),
                }
                sections.append(PolicySection(tier_id, tier_text, tier_metadata))

    for line in lines:
        if line.strip() == "---" and not sections and current_id is None:
            # Skip the YAML block; the closing delimiter is the second such line.
            continue
        match = SECTION_HEADING.match(line)
        if match:
            add_section()
            current_id = match.group("section_id")
            current_title = match.group("title").strip()
            body = []
        elif current_id is not None:
            body.append(line)
    add_section()

    if not sections:
        raise ValueError(f"{path}: no stable '## §N — Section title' headings found")
    return sections


def load_policy_sections(docs_dir: Path = DOCS_DIR) -> list[PolicySection]:
    """Load Markdown policy sources; skip README and other non-policy Markdown."""
    sections: list[PolicySection] = []
    for path in sorted(docs_dir.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        sections.extend(split_policy_sections(path))
    if not sections:
        raise ValueError(f"No policy sections found in {docs_dir}")
    current_versions = {}
    for section in sections:
        metadata = section.metadata
        document_id = metadata["document_id"]
        effective_date = metadata.get("effective_date", "unspecified")
        date_is_set = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", effective_date))
        candidate = (date_is_set, effective_date if date_is_set else "", _version_key(metadata["version"]))
        current = current_versions.get(document_id)
        if current is None or candidate > current[0]:
            current_versions[document_id] = (candidate, metadata["version"])
    for section in sections:
        metadata = section.metadata
        metadata["is_current"] = metadata["version"] == current_versions[metadata["document_id"]][1]
    return sections


def _version_key(version: str) -> tuple[int, ...]:
    """Compare version strings by their numeric components (v2.0.0, l3-prototype-10, etc.)."""
    numbers = re.findall(r"\d+", version)
    return tuple(int(number) for number in numbers) or (0,)


def create_client():
    """Connect to the configured Chroma HTTP server (local defaults match the prototype)."""
    import chromadb

    return chromadb.HttpClient(
        host=os.getenv("CHROMA_HOST", "localhost"),
        port=int(os.getenv("CHROMA_PORT", "8000")),
        tenant=os.getenv("CHROMA_TENANT", "default_tenant"),
        database=os.getenv("CHROMA_DATABASE", "default_database"),
    )


def ingest(docs_dir: Path = DOCS_DIR) -> int:
    """Upsert the versioned policy sections and return the number of records indexed."""
    sections = load_policy_sections(docs_dir)
    client = create_client()
    client.heartbeat()
    # Use the same explicit embedding function when querying this collection in RAG.
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

    embedding_function = DefaultEmbeddingFunction()
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_function,
        metadata={"description": "AssetDesk prototype policy sections", "embedding": "Chroma default"},
    )
    collection.upsert(
        ids=[section.record_id for section in sections],
        documents=[section.text for section in sections],
        metadatas=[section.metadata for section in sections],
    )
    return len(sections)


def main() -> int:
    try:
        count = ingest()
    except Exception as exc:
        print(f"Policy indexing failed: {exc}", file=sys.stderr)
        print("Check that ChromaDB is running and that the configured tenant/database exist.", file=sys.stderr)
        return 1
    print(f"Indexed or updated {count} policy sections in Chroma collection '{COLLECTION_NAME}'.")
    print("These L2-derived documents are marked unverified prototype material.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
