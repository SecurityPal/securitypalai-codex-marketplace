# SecurityPal AI Codex Marketplace

This repository publishes the SecurityPal AI plugin for Codex. The plugin helps Codex answer customer security questions, inspect Knowledge Library content, audit source coverage, and manage Knowledge Library documents through SecurityPal public APIs.

## Install

Install the `securitypal-ai` plugin from this marketplace in Codex, then use the `securitypal-ai` skill when working with SecurityPal AI or Knowledge Library data.

## Authentication

Create a SecurityPal personal access token for the customer account you want to query at <https://app.securitypalhq.com/settings#api>, then export it before using the helper commands:

```bash
export SECURITYPAL_API_TOKEN='your_customer_token_here'
```

The helper defaults to production:

```bash
export SECURITYPAL_API_BASE_URL='https://app.securitypalhq.com/api'
```

Only set `SECURITYPAL_API_BASE_URL` when SecurityPal support gives you a different environment. Keep `/api` in the base URL.

## Required Access

The token must be able to call `GET /v1/auth/me` and read libraries through `GET /v1/libraries/`.

Additional commands require matching account permissions:

- Library inventory: read Knowledge Library documents, tags, instruction sets, and memories.
- Question answering: access the selected library and the relevant SecurityPal AI answer endpoint.
- Document upload/update/delete: manage Knowledge Library documents and use signed upload/finalize endpoints.

## First Command

Run the doctor command first. It validates the token, base URL, source-model routing, account access, and visible libraries:

```bash
python3 plugins/securitypal-ai/skills/securitypal-ai/scripts/securitypal_copilot_api.py check-auth
```

## Examples

```bash
python3 plugins/securitypal-ai/skills/securitypal-ai/scripts/securitypal_copilot_api.py list-libraries --include-tags
python3 plugins/securitypal-ai/skills/securitypal-ai/scripts/securitypal_copilot_api.py answer-kb --library-id 123 --question "Do we encrypt data at rest?"
python3 plugins/securitypal-ai/skills/securitypal-ai/scripts/securitypal_copilot_api.py add-document --library-id 123 --file /absolute/path/policy.pdf --dry-run
```

`answer-kb` routes by `auth/me`. Legacy libraries support `--include-sources`, `--include-library`, and `--include-tags`; RAG libraries route to `answer-from-documents`, where those include flags are not available.
