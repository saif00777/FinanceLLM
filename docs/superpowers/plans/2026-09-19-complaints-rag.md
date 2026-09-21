# Consumer Complaints RAG Implementation Plan

**Goal:** Build a safe, Qdrant-backed retrieval branch for consented consumer-complaint narratives.

**Architecture:** Local ingestion converts each consented narrative into one redacted retrieval document with coarse metadata. Qdrant stores embeddings plus filtered payload; the future graph router calls retrieval only after domain routing, never as a SQL substitute.

## Constraints

- Process only `consumer_complaint_narrative` rows with `consumer_consent_provided=Consent provided`.
- Do not embed or store ZIP code, raw complaint ID, dates sent to company, or direct identifiers from narrative text.
- Locally redact e-mail, phone, SSN, payment-card, and account-number-like text before an embedding call.
- Store a SHA-256 source ID, product, sub-product, issue, company, state, and received year as Qdrant payload.
- Use Qdrant only for the complaint-document branch; MotherDuck SQL stays isolated.

## Tasks

1. Add `app/rag/complaints.py` with `redact_text`, `ComplaintDocument`, and streaming CSV construction; write failing tests for consent filtering, redaction, source hashing, and metadata exclusions.
2. Add `app/rag/qdrant_store.py` behind a retrieval protocol; write fake-client tests for collection creation, payload filters, and top-k retrieval.
3. Add a batch ingestion CLI with checkpoints and dry-run mode; require Qdrant settings only for upload.
4. Add a retrieval specialist and router branch after domain guards; cite returned source hashes and preserve SQL isolation.
5. Add public RAG evaluation fixtures for relevance, unsupported questions, prompt injection in narrative text, and metadata-filter enforcement.

**Initial corpus profile:** 555,957 complaints; 66,806 consented narratives; narrative lengths 8-5,151 characters; data dates 2011-12-01 through 2016-04-25.