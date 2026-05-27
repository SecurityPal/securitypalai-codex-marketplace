# SecurityPal AI Assistant Plugin

SecurityPal AI provides Codex and Claude Code skills for asking Knowledge Library questions, auditing library content, and managing source documents through SecurityPal public APIs.

## Install

Install the plugin through the Codex or Claude marketplace bundle published by SecurityPal, or use this source checkout for local development.

For local Codex skill testing:

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
ln -s "/absolute/path/to/security-pal/integrations/ai-assistants/plugins/securitypal-ai/skills/securitypal-ai" \
  "${CODEX_HOME:-$HOME/.codex}/skills/securitypal-ai"
```

For local Claude Code plugin testing:

```bash
claude --plugin-dir /absolute/path/to/security-pal/integrations/ai-assistants/plugins/securitypal-ai
```

## API Token Setup

Create a SecurityPal personal access token for the customer account you want to query at <https://app.securitypalhq.com/settings#api>, then export it before running helper commands:

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

Additional commands require the corresponding account permissions:

- Library inventory: read Knowledge Library documents, tags, instruction sets, and memories.
- Question answering: access the selected library and the relevant SecurityPal AI answer endpoint.
- Document upload/update/delete: manage Knowledge Library documents and use signed upload/finalize endpoints.

## First Command

Run the doctor command first. It validates the token, base URL, account feature flags, source-model routing, and accessible libraries:

```bash
python3 skills/securitypal-ai/scripts/securitypal_copilot_api.py check-auth
```

If you are already inside `skills/securitypal-ai`, use:

```bash
python3 scripts/securitypal_copilot_api.py check-auth
```

## Examples

List accessible libraries:

```bash
python3 scripts/securitypal_copilot_api.py list-libraries --include-tags
```

Ask a library-scoped Knowledge Library question using the source model from `auth/me`:

```bash
python3 scripts/securitypal_copilot_api.py answer-kb --library-id 123 --question "Do we encrypt data at rest?"
```

Preview a document upload before making API calls:

```bash
python3 scripts/securitypal_copilot_api.py add-document --library-id 123 --file /absolute/path/policy.pdf --dry-run
```

Then upload and check post-upload status:

```bash
python3 scripts/securitypal_copilot_api.py add-document --library-id 123 --file /absolute/path/policy.pdf --tag-id TAG_UUID
```

## Source Notes

`answer-kb` routes by `auth/me`:

- Legacy source model: calls `answer` and supports `--include-sources`, `--include-library`, and `--include-tags`.
- RAG source model: calls `answer-from-documents`; include flags are not available on that endpoint, so the helper exits with an explicit message if they are requested.
