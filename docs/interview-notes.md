# Interview Notes

## Why this architecture?

- **FastAPI + REST + SSE:** typed, async Python routes work naturally with one-way streamed model output. SSE needs no persistent socket and Stop is a cancelled fetch.
- **PostgreSQL + pgvector:** relational ownership and transactions sit beside approximate vector search. HNSW works with an empty/small collection without IVFFlat training.
- **Memory retrieval:** a cosine threshold gates unrelated results, then similarity, importance, recency, and pinning are combined for ranking. Only the top results enter the prompt.
- **Safety:** memories are delimited as data, sensitive candidates are rejected, and all reads/writes are user-scoped.
- **Costs:** request limits, daily budget, bounded input/output, embedding batches, and one extraction call per exchange control free-tier usage.
- **Scale:** replace process-local limits with Redis, background extraction with a queue, then add workers, read replicas, partitioned event tables, and tenant quotas.

## Evaluation

Run the scripted evaluation against Fake, Mem0, and Custom providers before making performance claims. Record retrieval accuracy, p50 latency, and tokens/cost in the README; do not present placeholders as results.
