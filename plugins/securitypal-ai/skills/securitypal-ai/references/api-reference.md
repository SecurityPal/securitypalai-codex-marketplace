# SecurityPal AI API Reference

## Base Setup

- Base URL: `https://app.securitypalhq.com/api`
- Auth header: `Authorization: Bearer $SECURITYPAL_API_TOKEN`
- Override base URL with `SECURITYPAL_API_BASE_URL` if needed.
- Endpoint paths below are normalized as `/v1/...`, so the full URL for `GET /v1/auth/me` is `https://app.securitypalhq.com/api/v1/auth/me`.

## Recommended Discovery Order

1. `GET /v1/auth/me`
2. `GET /v1/libraries/`
3. `GET /v1/libraries/{library_id}/tags`
4. `GET /v1/copilot/get-documents?libraryId=...`
5. If RAG is enabled, `GET /v1/copilot/get-instructions?libraryId=...`
6. If RAG is enabled, `GET /v1/copilot/get-memory?productId=...`

Use these calls to discover valid `libraryId`, `tagIds`, `documentIds`, and `instructionIds` before asking SecurityPal AI a question.

Use `GET /v1/auth/me` to inspect `knownFeatureFlags["knowledge-library-rag-based-enabled"]`.

- Missing or `false`: legacy source model. Documents and the legacy Q/A library are available. Instruction sets and memories are not.
- `true`: RAG source model. Documents, instruction sets, and memories are available. The legacy Q/A library is not.

`GET /v1/copilot/check-knowledge-library-v2-enabled?libraryId=...` is retained as a fallback/debug check when `auth/me` does not expose feature flags.

For cleanup and inventory work, prefer the helper CLI's `library-audit` command. It combines the library, document, instruction, and RAG availability endpoints into a read-only report and flags common hygiene issues.

For review-expiration work, prefer `expired-documents`. For topic coverage checks, prefer `knowledge-gaps`.

## JSON Endpoints

### Get authenticated user and feature flags

- `GET /v1/auth/me`
- Response includes:
  - `data`: authenticated user summary
  - `knownFeatureFlags`: map of enabled feature flags for the API-token caller

### List libraries

- `GET /v1/libraries/`
- Optional query: `includeTags=true|false`

### List tags for a library

- `GET /v1/libraries/{library_id}/tags`

### List documents

- `GET /v1/copilot/get-documents`
- Query params:
  - `libraryId` required
  - `offset` optional
  - `limit` optional

### List instruction sets

- `GET /v1/copilot/get-instructions`
- Query params:
  - `libraryId` required
  - `offset` optional
  - `limit` optional

### Get memory

- `GET /v1/copilot/get-memory`
- Query params:
  - `productId` required
- Returns one memory object. A missing memory returns `404`.

### Request signed document upload URLs

- `POST /v1/libraries/{library_id}/documents/request-upload-url`
- Body:

```json
{
  "fileName": "policy.pdf"
}
```

### Finalize document upload

- `POST /v1/libraries/{library_id}/documents/finalize-upload`
- Body:

```json
{
  "gcsFileName": "uuid_policy.pdf",
  "originalFileName": "policy.pdf",
  "gcsPath": "temp/company/uuid_policy.pdf",
  "tagIds": ["optional-tag-uuid"],
  "ownerUserIds": [42],
  "reviewCycle": 12,
  "reviewedAt": "2026-05-01T00:00:00Z",
  "reviewedByUserId": 42
}
```

The helper CLI wraps the signed upload flow:

```bash
python3 scripts/securitypal_copilot_api.py add-document --library-id 123 --file /absolute/path/policy.pdf
```

If the caller is on the legacy source model, the uploaded document is usable by document-based KB answers after processing. If the caller is on the RAG source model, check document sync/indexing status before assuming it is available in RAG answers.

### Update document metadata

- `POST /v1/libraries/{library_id}/documents/{document_id}/update`
- Body fields are optional; omitted fields are unchanged.

```json
{
  "name": "SOC 2 Type II.pdf",
  "description": "Current SOC 2 Type II report",
  "tagIds": ["optional-tag-uuid"],
  "ownerUserIds": [42],
  "reviewCycle": 90,
  "reviewedAt": "2026-05-01T00:00:00Z",
  "reviewedByUserId": 42
}
```

Passing `tagIds` replaces the document's full tag set. To remove one tag while preserving the others, fetch the document's current tags and submit the remaining tag IDs, or use the helper CLI's `remove-document-tag` command.

### Delete document

- `POST /v1/libraries/{library_id}/documents/{document_id}/delete`
- Empty body.

This permanently deletes the document. Confirm the `document_id` from `list-documents` before calling it.

The helper CLI wraps document mutation flows:

```bash
python3 scripts/securitypal_copilot_api.py update-document --library-id 123 --document-id DOCUMENT_UUID --description "Current SOC 2 Type II report"
python3 scripts/securitypal_copilot_api.py remove-document-tag --library-id 123 --document-id DOCUMENT_UUID --tag-id TAG_UUID
python3 scripts/securitypal_copilot_api.py delete-document --library-id 123 --document-id DOCUMENT_UUID
```

### Check Knowledge Library v2 / RAG availability

- `GET /v1/copilot/check-knowledge-library-v2-enabled`
- Query params:
  - `libraryId` required

### Ask SecurityPal AI

- `POST /v1/copilot/answer`
- Body:

```json
{
  "libraryId": 123,
  "question": "Do you support SSO?",
  "instruction": "Answer briefly.",
  "tagIds": ["uuid-tag"],
  "includeSources": true,
  "includeLibrary": true,
  "includeTags": true
}
```

### Search within selected documents

- `POST /v1/copilot/search`
- Body:

```json
{
  "libraryId": 123,
  "question": "How are backups encrypted?",
  "instructionIds": ["uuid-instruction"],
  "documentIds": ["uuid-document"]
}
```

### Ask using document RAG

- `POST /v1/copilot/answer-from-documents`
- Body:

```json
{
  "libraryId": 123,
  "question": "Summarize business continuity controls.",
  "instruction": "Cite the strongest evidence first."
}
```

## Helper-Only Routing

The helper CLI provides `answer-kb` as a routing command:

```bash
python3 scripts/securitypal_copilot_api.py answer-kb --library-id 123 --question "Do you encrypt data at rest?"
```

It calls `GET /v1/auth/me` first.

- Legacy source model: routes to `POST /v1/copilot/answer`; `--include-sources`, `--include-library`, and `--include-tags` are supported.
- RAG source model: routes to `POST /v1/copilot/answer-from-documents`; include flags are not available on that endpoint, so the helper exits with an explicit message when they are requested.

### Find expired documents

```bash
python3 scripts/securitypal_copilot_api.py expired-documents --library-id 123 --format markdown
```

The helper returns document id, name, reviewed date, day-based review cycle, computed expiration date, and issue reason. Missing review dates are reported as `missing_review_date`, not `expired`.

### Find knowledge gaps

```bash
python3 scripts/securitypal_copilot_api.py knowledge-gaps --library-id 123 --topic "data retention"
```

The helper calls `GET /v1/auth/me` first. Legacy reports document and Q/A library gaps. RAG reports document, memory, and instruction-set gaps.

### Fetch autocomplete results

- `GET /v1/copilot/request-autocomplete`
- Query params:
  - `requestId` required
  - `productId` required
  - `offset` optional
  - `limit` optional

## Multipart Endpoints

### Request autocomplete

- `POST /v1/copilot/request-autocomplete`
- Content type: `multipart/form-data`
- Required form fields:
  - `libraryId`
  - `prospect`
  - `file`
- Optional form fields:
  - `instruction`
  - `tagIds`
  - `includeSources`
  - `includeLibrary`
  - `includeTags`
  - `sourceType`

Example:

```bash
curl -X POST "$SECURITYPAL_API_BASE_URL/v1/copilot/request-autocomplete" \
  -H "Authorization: Bearer $SECURITYPAL_API_TOKEN" \
  -F "libraryId=123" \
  -F "prospect=Acme Corp" \
  -F "instruction=Answer in concise security-review language." \
  -F "includeSources=true" \
  -F "file=@/absolute/path/questionnaire.html"
```

### Generate selectors

- `POST /v1/copilot/generate-selectors`
- Content type: `multipart/form-data`
- Required form fields:
  - `file`
  - `questionsAndAnswers` as serialized JSON string
  - `productId`

Example:

```bash
curl -X POST "$SECURITYPAL_API_BASE_URL/v1/copilot/generate-selectors" \
  -H "Authorization: Bearer $SECURITYPAL_API_TOKEN" \
  -F "productId=123" \
  -F 'questionsAndAnswers={\"data\":[{\"question\":\"Do you encrypt data?\",\"answer\":\"Yes\"}]}' \
  -F "file=@/absolute/path/questionnaire.html"
```

## Common Response Signals

- `403`: token lacks permission, such as SecurityPal AI access
- `404`: invalid library, document, product, or request ID
- `422`: malformed parameters
- `504`: timeout or backend processing failure

## Notes

- `libraryId` may appear as either integer or string in some schemas; prefer the integer ID returned by library listing.
- `tagIds`, `documentIds`, and `instructionIds` are UUIDs.
- `GET /v1/copilot/request-autocomplete` uses `productId` in the query even though other endpoints usually call this `libraryId`.
- The backend route prefix still uses `copilot` for compatibility; the user-facing product name is SecurityPal AI.
