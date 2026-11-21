# Policy RAG Assistant

The Policy Assistant retrieves current indexed sections from the configured Chroma collection, sends those sections to the LLM as RAG context, and validates that returned citations match retrieved document and section citations. If retrieval is unavailable, evidence is empty, or citations are missing or fabricated, it refuses. Sources currently carry `approval_status: unverified`; answers say so and must not be presented as company-approved policy.

From `L3/`, index the supplied versioned documents with `../.venv/bin/python -m policy.ingest_chroma`. Run the frozen evaluation set with `../.venv/bin/python -m policy.evaluate`. Evaluation needs the configured Chroma server and `OPENAI_API_KEY`. It runs the same 16 cases with `top_k=1` baseline retrieval and `top_k=6` revised retrieval, reports source recall, answer correctness, citation validity, and refusal accuracy separately, and writes `policy/evaluation_results.json`.

The wider top-k retrieval is the single documented retrieval improvement. Review cited passages manually and replace the unverified prototype corpus with approved current company policies before relying on answers for operations.
