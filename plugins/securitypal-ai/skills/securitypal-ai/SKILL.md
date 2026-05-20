---
name: securitypal-ai
description: Answer customer security questions, audit knowledge-library coverage, and find gaps in a customer's SecurityPal content. Use when Codex needs to ask SecurityPal AI questions, search source documents, list libraries, inspect tags and instruction sets, identify expired or under-described documents, verify Knowledge Library capabilities, or retrieve customer-specific autocomplete suggestions.
---

# SecurityPal AI

Use this skill to work against SecurityPal AI and Knowledge Library public endpoints with a customer's API token.

## Workflow

1. Check whether `SECURITYPAL_API_TOKEN` is already set.
   - If it is not set, ask the user for a customer API token or tell them to run:

```bash
export SECURITYPAL_API_TOKEN='your_customer_token_here'
```

2. Default the base URL to `https://app.securitypalhq.com/api` unless `SECURITYPAL_API_BASE_URL` is set.
   - Keep `/api` in the base URL. Helper command paths are normalized as `/v1/...`, producing full URLs like `/api/v1/auth/me`.
3. Discover the caller's Knowledge Library source model:

```bash
python3 scripts/securitypal_copilot_api.py me
python3 scripts/securitypal_copilot_api.py kb-capabilities
```

   - If `knowledge-library-rag-based-enabled` is enabled, use the RAG source model.
   - If it is missing or disabled, use the legacy source model.
   - Use `rag-enabled` only as a fallback/debug endpoint when `auth/me` does not expose usable feature flags.
4. Check whether the target `libraryId` is already known.
   - If it is not known, discover it first:

```bash
python3 scripts/securitypal_copilot_api.py list-libraries
```

   - Use the returned library `id` in later commands as `--library-id <id>`.
5. Start by discovering context:
   - Run `scripts/securitypal_copilot_api.py list-libraries`
   - If needed, run `list-tags`, `list-documents`, `list-instructions`, `list-memories`, or `rag-enabled`
   - Use `library-audit` when the user wants to understand what is in a customer's Knowledge Library or what needs cleanup.
6. Choose the narrowest SecurityPal AI endpoint or workflow that matches the task:
   - Use `library-audit` for read-only document/instruction inventory and hygiene reports
   - Use `expired-documents` when the user asks what documents are expired or need review
   - Use `knowledge-gaps` when the user asks what is missing for a topic
   - Use `answer-kb` for normal library-scoped Q&A when you want the helper to route by source model
   - Use `answer` for legacy library-scoped Q&A when the caller has `knowledge-library-rag-based-enabled` disabled or missing
   - Use `search` when the request should be constrained to specific document IDs
   - Use `answer-from-documents` for RAG document questions when `knowledge-library-rag-based-enabled` is enabled
   - Use `add-document` when the user asks to add or upload a Knowledge Library document and their token can access the signed upload and finalize endpoints
   - Use `get-autocomplete` to fetch previously generated autocomplete results
7. Summarize the result for the user and include relevant IDs, source metadata, and follow-up options.

## Source Model Routing

Use `auth/me` as the source of truth for source-model routing.

- Legacy source model (`knowledge-library-rag-based-enabled` missing or `false`):
  - supported: documents, legacy Q/A library
  - unsupported: instruction sets, memories
  - preferred Q&A command: `answer` or `answer-kb`
- RAG source model (`knowledge-library-rag-based-enabled` `true`):
  - supported: documents, instruction sets, memories
  - unsupported: legacy Q/A library
  - preferred Q&A command: `answer-from-documents` or `answer-kb`

For broad questions like "Based on my knowledge library, do we encrypt data at rest?", prefer:

```bash
python3 scripts/securitypal_copilot_api.py answer-kb --library-id 123 --question "Do we encrypt data at rest?" --include-sources
```

## Token Handling

- Read the token from `SECURITYPAL_API_TOKEN`.
- Never hardcode, print, or commit the token.
- Avoid copying the token into command history when possible.
- If the user provides a raw token in chat, move it into an environment variable before using it.

## First-Run Setup

When the token or library ID is missing, use this sequence:

```bash
export SECURITYPAL_API_TOKEN='your_customer_token_here'
python3 scripts/securitypal_copilot_api.py me
python3 scripts/securitypal_copilot_api.py kb-capabilities
python3 scripts/securitypal_copilot_api.py list-libraries
python3 scripts/securitypal_copilot_api.py answer-kb --library-id 123 --question "Do you encrypt data at rest?" --include-sources
```

If the user does not know the correct library, never guess. List libraries first and let the returned IDs drive later requests.

## Command Guide

Use the helper script for JSON endpoints:

```bash
python3 scripts/securitypal_copilot_api.py list-libraries
python3 scripts/securitypal_copilot_api.py me
python3 scripts/securitypal_copilot_api.py kb-capabilities
python3 scripts/securitypal_copilot_api.py list-tags --library-id 123
python3 scripts/securitypal_copilot_api.py list-documents --library-id 123 --limit 20
python3 scripts/securitypal_copilot_api.py list-memories --library-id 123
python3 scripts/securitypal_copilot_api.py add-document --library-id 123 --file /absolute/path/policy.pdf --tag-id TAG_UUID
python3 scripts/securitypal_copilot_api.py library-audit --library-id 123 --format markdown
python3 scripts/securitypal_copilot_api.py library-audit --format json
python3 scripts/securitypal_copilot_api.py expired-documents --library-id 123 --format markdown
python3 scripts/securitypal_copilot_api.py knowledge-gaps --library-id 123 --topic "data retention"
python3 scripts/securitypal_copilot_api.py answer-kb --library-id 123 --question "Do you encrypt data at rest?" --include-sources
python3 scripts/securitypal_copilot_api.py answer --library-id 123 --question "Do you encrypt data at rest?" --include-sources
python3 scripts/securitypal_copilot_api.py search --library-id 123 --question "How is SSO enforced?" --document-id 11111111-1111-1111-1111-111111111111
python3 scripts/securitypal_copilot_api.py answer-from-documents --library-id 123 --question "Summarize incident response testing."
python3 scripts/securitypal_copilot_api.py get-autocomplete --request-id REQUEST_UUID --product-id 123
```

## Library Audit

Use `library-audit` for read-only Knowledge Library cleanup reports. It fetches accessible libraries, document inventory, instruction sets, and RAG availability, then flags likely issues:

- documents without tags
- documents without descriptions
- documents past their review cycle, based on `reviewed_at` plus the day-based `review_cycle`
- documents with RAG sync statuses that need attention
- duplicate-looking document names
- instruction sets with missing guidance fields
- duplicate-looking instruction names

Markdown output is intended for a customer-facing summary. JSON output preserves the audited documents, instructions, issue counts, and endpoint errors for follow-up automation.

## Expired Documents

Use `expired-documents` for "which documents are expired?" requests. It reuses the audit inventory and returns a focused report with document id, name, reviewed date, day-based review cycle, computed expiration date, and issue reason.

Example:

```bash
python3 scripts/securitypal_copilot_api.py expired-documents --library-id 123 --format markdown
```

Issue reasons:

- `expired`: the document has a review date and its day-based review cycle has elapsed.
- `missing_review_date`: the document has a review cycle but no review date. Treat this separately from expired documents.

## Knowledge Gaps

Use `knowledge-gaps` for "what are we missing for <topic>?" requests. It calls `auth/me` first, then formats gaps according to the source model:

- Legacy: checks relevant documents, legacy Q/A library sources from the legacy answer flow, and stale/expired/missing/weak document signals.
- RAG: checks relevant synced documents, memories, useful instruction sets, and unsynced/stale/expired/missing document signals.

Example:

```bash
python3 scripts/securitypal_copilot_api.py knowledge-gaps --library-id 123 --topic "data retention"
```

## Document Uploads

Use `add-document` for "add this document" requests when the token can access document upload endpoints. The helper performs the three-step upload flow:

1. `POST /v1/libraries/{library_id}/documents/request-upload-url`
2. `PUT` the local file to the returned signed upload URL
3. `POST /v1/libraries/{library_id}/documents/finalize-upload`

Example:

```bash
python3 scripts/securitypal_copilot_api.py add-document --library-id 123 --file /absolute/path/policy.pdf
```

Optional metadata:

```bash
python3 scripts/securitypal_copilot_api.py add-document \
  --library-id 123 \
  --file /absolute/path/policy.pdf \
  --tag-id TAG_UUID \
  --owner-user-id 42 \
  --review-cycle 12 \
  --reviewed-at 2026-05-01T00:00:00Z \
  --reviewed-by-user-id 42
```

After upload, route follow-up expectations by source model:

- Legacy: the document should become available to document-based KB answers once upload processing completes.
- RAG: document sync/indexing status matters; check `rag_corpus_sync_status` with `list-documents` or `library-audit`.

## Multipart Endpoints

The helper script intentionally focuses on the JSON endpoints. For multipart endpoints, use `curl` or extend the script carefully:

- `POST /v1/copilot/request-autocomplete`
- `POST /v1/copilot/generate-selectors`

The backend route prefix still uses `copilot` for compatibility; the user-facing product name is SecurityPal AI.

Read [references/api-reference.md](references/api-reference.md) for field expectations and example `curl` payloads.

## Response Handling

- Prefer returning the parsed JSON response rather than hand-copying fields.
- When `includeSources`, `includeLibrary`, or `includeTags` are requested, preserve those relationships in your summary.
- If the API returns `403`, explain that the token likely lacks the relevant permission for that endpoint.
- If the API returns `404`, verify the selected library, document IDs, request ID, or account scope.
- If the API returns `504`, report the timeout and suggest retrying or narrowing the request.

## Resources

- [scripts/securitypal_copilot_api.py](scripts/securitypal_copilot_api.py): SecurityPal AI helper CLI for bearer-authenticated JSON endpoints.
- [references/api-reference.md](references/api-reference.md): Endpoint summary, request shapes, and multipart examples.
