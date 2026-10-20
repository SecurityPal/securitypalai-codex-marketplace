#!/usr/bin/env python3
"""Helper CLI for SecurityPal AI public APIs."""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

DEFAULT_BASE_URL = "https://app.securitypalhq.com/api"
PUBLIC_API_VERSION = "2026-08-07"
PUBLIC_API_VERSION_HEADER = "X-API-Version"
DEFAULT_PAGE_LIMIT = 50
MAX_MARKDOWN_EXAMPLES = 10
MAX_GAP_EXAMPLES = 5
KNOWLEDGE_LIBRARY_RAG_FLAG = "knowledge-library-rag-based-enabled"
SOURCE_MODEL_LEGACY = "legacy"
SOURCE_MODEL_RAG = "rag"
PUBLIC_DOCUMENT_UPLOAD_URL_PATH = (
    "/v1/libraries/{library_id}/documents/request-upload-url"
)
PUBLIC_DOCUMENT_FINALIZE_UPLOAD_PATH = (
    "/v1/libraries/{library_id}/documents/finalize-upload"
)
PUBLIC_DOCUMENT_UPDATE_PATH = (
    "/v1/libraries/{library_id}/documents/{document_id}/update"
)
PUBLIC_DOCUMENT_DELETE_PATH = (
    "/v1/libraries/{library_id}/documents/{document_id}/delete"
)
SIGNED_UPLOAD_TIMEOUT_SECONDS = 300
SUCCESSFUL_RAG_SYNC_STATUSES = frozenset(
    {
        "completed",
    }
)


@dataclass
class ApiRequestError(Exception):
    status: int | None
    reason: str
    body: Any

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "body": self.body,
        }


def _base_url() -> str:
    return os.environ.get("SECURITYPAL_API_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _token() -> str:
    token = os.environ.get("SECURITYPAL_API_TOKEN")
    if not token:
        raise SystemExit("SECURITYPAL_API_TOKEN is required")
    return token


def _request(
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    exit_on_error: bool = True,
) -> Any:
    url = f"{_base_url()}{path}"
    if query:
        query_items: list[tuple[str, str]] = []
        for key, value in query.items():
            if value is None:
                continue
            if isinstance(value, list):
                query_items.extend((key, str(item)) for item in value)
            else:
                query_items.append((key, str(value)))
        if query_items:
            url = f"{url}?{urllib.parse.urlencode(query_items)}"

    data: bytes | None = None
    headers = {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/json",
        PUBLIC_API_VERSION_HEADER: PUBLIC_API_VERSION,
    }
    if payload is not None:
        filtered_payload = {k: v for k, v in payload.items() if v is not None}
        data = json.dumps(filtered_payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        error = ApiRequestError(
            status=exc.code,
            reason=exc.reason,
            body=_maybe_json(error_body),
        )
        if not exit_on_error:
            raise error from exc
        print(json.dumps(error.as_dict(), indent=2, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc
    except urllib.error.URLError as exc:
        if not exit_on_error:
            raise ApiRequestError(
                status=None,
                reason=f"Network error: {exc.reason}",
                body=None,
            ) from exc
        raise SystemExit(f"Network error: {exc.reason}") from exc

    return _maybe_json(body)


def _maybe_json(body: str) -> Any:
    if not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return body


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def _jsonapi_data(response: Any) -> Any:
    if isinstance(response, dict) and "data" in response:
        return response["data"]
    return response


def _jsonapi_meta(response: Any) -> dict[str, Any]:
    if isinstance(response, dict) and isinstance(response.get("meta"), dict):
        return response["meta"]
    return {}


def _resource_id(resource: Any) -> str | None:
    if isinstance(resource, dict):
        value = resource.get("id")
        if value is not None:
            return str(value)
    return None


def _resource_attributes(resource: Any) -> dict[str, Any]:
    if isinstance(resource, dict) and isinstance(resource.get("attributes"), dict):
        return resource["attributes"]
    if isinstance(resource, dict):
        return resource
    return {}


def _resource_relationships(resource: Any) -> dict[str, Any]:
    if isinstance(resource, dict) and isinstance(resource.get("relationships"), dict):
        return resource["relationships"]
    return {}


def _snake_to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


def _attribute_value(attributes: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        for candidate in (key, _snake_to_camel(key)):
            value = attributes.get(candidate)
            if value is not None:
                return value
    return None


def _relationship_list(resource: Any, name: str) -> list[Any]:
    relationships = _resource_relationships(resource)
    value = relationships.get(name)
    if isinstance(value, dict) and isinstance(value.get("data"), list):
        return value["data"]
    if isinstance(value, list):
        return value
    return []


def _parse_datetime(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _normalize_duplicate_key(value: str) -> str:
    without_extension = re.sub(r"\.[a-z0-9]{1,8}$", "", value.lower())
    return re.sub(r"[^a-z0-9]+", " ", without_extension).strip()


def _string_value(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _get_error_summary(error: ApiRequestError) -> dict[str, Any]:
    return {
        "status": error.status,
        "reason": error.reason,
        "body": error.body,
    }


def _extract_field(resource: Any, *keys: str) -> Any:
    return _attribute_value(_resource_attributes(resource), *keys)


def _review_cycle_days(attributes: dict[str, Any]) -> int | None:
    review_cycle = _attribute_value(attributes, "review_cycle")
    if review_cycle is None:
        review_cycle = _attribute_value(attributes, "minimum_product_review_cycle")
    if isinstance(review_cycle, bool):
        return None
    if isinstance(review_cycle, int) and review_cycle > 0:
        return review_cycle
    return None


def _document_expiration(
    document: Any,
    *,
    as_of: dt.datetime,
) -> dict[str, Any]:
    attributes = _resource_attributes(document)
    review_cycle = _review_cycle_days(attributes)
    reviewed_at = _parse_datetime(_attribute_value(attributes, "reviewed_at"))
    expiration_date = (
        reviewed_at + dt.timedelta(days=review_cycle)
        if reviewed_at is not None and review_cycle is not None
        else None
    )

    if review_cycle is None:
        issue_reason = "missing_review_cycle"
    elif reviewed_at is None:
        issue_reason = "missing_review_date"
    elif expiration_date is not None and expiration_date < as_of:
        issue_reason = "expired"
    else:
        issue_reason = None

    name = _string_value(
        _attribute_value(attributes, "name", "filename") or _resource_id(document),
        default="Unnamed document",
    )
    return {
        "id": _resource_id(document),
        "name": name,
        "reviewed_at": _attribute_value(attributes, "reviewed_at"),
        "review_cycle": _attribute_value(attributes, "review_cycle"),
        "minimum_product_review_cycle": _attribute_value(
            attributes,
            "minimum_product_review_cycle",
        ),
        "effective_review_cycle_days": review_cycle,
        "computed_expiration_date": expiration_date.isoformat()
        if expiration_date is not None
        else None,
        "issue_reason": issue_reason,
    }


def _upload_file_to_signed_url(upload_url: str, file_path: str) -> None:
    with open(file_path, "rb") as file:
        request = urllib.request.Request(
            upload_url,
            method="PUT",
            data=file.read(),
            headers={"Content-Type": "application/octet-stream"},
        )
    try:
        with urllib.request.urlopen(
            request,
            timeout=SIGNED_UPLOAD_TIMEOUT_SECONDS,
        ) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise ApiRequestError(
            status=exc.code,
            reason=exc.reason,
            body=_maybe_json(error_body),
        ) from exc
    except urllib.error.URLError as exc:
        raise ApiRequestError(
            status=None,
            reason=f"Signed upload network error: {exc.reason}",
            body=None,
        ) from exc


def _target_library_id(args: argparse.Namespace) -> int:
    library_ids: list[int] = []
    for value in [*(args.library_ids or []), *(args.product_ids or [])]:
        if value not in library_ids:
            library_ids.append(value)
    if not library_ids:
        raise SystemExit("--library-id or --product-id is required")
    if len(library_ids) > 1:
        raise SystemExit("add-document supports one --library-id or --product-id")
    return library_ids[0]


def _extract_finalized_document_ids(finalize_response: Any) -> list[str]:
    data = _jsonapi_data(finalize_response)
    if isinstance(data, dict):
        document_id = _resource_id(data)
        return [document_id] if document_id is not None else []
    if isinstance(data, list):
        return [
            document_id
            for document in data
            if (document_id := _resource_id(document)) is not None
        ]
    return []


def _upload_dry_run_result(
    *,
    file_path: str,
    file_name: str,
    library_id: int,
    args: argparse.Namespace,
) -> dict[str, Any]:
    return {
        "dry_run": True,
        "library_id": library_id,
        "file": {
            "path": file_path,
            "name": file_name,
            "size_bytes": os.path.getsize(file_path),
        },
        "metadata": {
            "tag_ids": args.tag_ids,
            "owner_user_ids": args.owner_user_ids,
            "review_cycle": args.review_cycle,
            "reviewed_at": args.reviewed_at,
            "reviewed_by_user_id": args.reviewed_by_user_id,
        },
        "planned_steps": [
            "request_signed_upload_url",
            "upload_file_to_signed_url",
            "finalize_upload",
            "check_uploaded_document_status",
        ],
    }


def _build_post_upload_status(
    *,
    library_id: int,
    document_ids: list[str],
    source_model: str,
) -> dict[str, Any]:
    if source_model == SOURCE_MODEL_RAG:
        return {
            "documents": [],
            "errors": [],
            "skipped_reason": (
                "Skipped immediate document status lookup for RAG source model; "
                "document indexing is asynchronous. Use list-documents or "
                "library-audit to check rag_corpus_sync_status after processing."
            ),
        }

    documents: list[Any] = []
    errors: list[dict[str, Any]] = []
    for document_id in document_ids:
        try:
            documents.append(_find_document(library_id, document_id))
        except ApiRequestError as error:
            errors.append(
                {
                    "document_id": document_id,
                    "error": _get_error_summary(error),
                }
            )
        except SystemExit as error:
            errors.append(
                {
                    "document_id": document_id,
                    "error": str(error),
                }
            )

    return {
        "documents": documents,
        "errors": errors,
        "skipped_reason": None,
    }


def _build_add_document_result(args: argparse.Namespace) -> dict[str, Any]:
    file_path = os.path.abspath(os.path.expanduser(args.file))
    if not os.path.isfile(file_path):
        raise SystemExit(f"File does not exist: {file_path}")

    library_id = _target_library_id(args)
    file_name = args.name or os.path.basename(file_path)
    if args.dry_run:
        return _upload_dry_run_result(
            file_path=file_path,
            file_name=file_name,
            library_id=library_id,
            args=args,
        )

    me_response = _request("GET", "/v1/auth/me")
    capabilities = _build_kb_capabilities(me_response)

    upload_url_path = PUBLIC_DOCUMENT_UPLOAD_URL_PATH.format(library_id=library_id)
    signed_url_response = _request(
        "POST",
        upload_url_path,
        payload={
            "fileName": file_name,
        },
    )
    signed_upload = _jsonapi_data(signed_url_response)
    if not isinstance(signed_upload, dict):
        raise SystemExit("Expected signed upload response to contain a data object")

    upload_url = _extract_field(signed_upload, "upload_url")
    gcs_file_name = _extract_field(signed_upload, "gcs_file_name")
    original_file_name = _extract_field(signed_upload, "file_name") or file_name
    gcs_path = _extract_field(signed_upload, "gcs_path")
    if not isinstance(upload_url, str) or not upload_url:
        raise SystemExit("Signed upload response did not include uploadUrl")
    if not isinstance(gcs_file_name, str) or not gcs_file_name:
        raise SystemExit("Signed upload response did not include gcsFileName")

    try:
        _upload_file_to_signed_url(upload_url, file_path)
    except ApiRequestError as error:
        print(json.dumps(error.as_dict(), indent=2, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from error

    finalize_path = PUBLIC_DOCUMENT_FINALIZE_UPLOAD_PATH.format(library_id=library_id)
    finalize_response = _request(
        "POST",
        finalize_path,
        payload={
            "gcsFileName": gcs_file_name,
            "originalFileName": original_file_name,
            "gcsPath": gcs_path,
            "tagIds": args.tag_ids,
            "ownerUserIds": args.owner_user_ids,
            "reviewCycle": args.review_cycle,
            "reviewedAt": args.reviewed_at,
            "reviewedByUserId": args.reviewed_by_user_id,
        },
    )
    source_model = capabilities["source_model"]
    finalized_document_ids = _extract_finalized_document_ids(finalize_response)
    post_upload_status = _build_post_upload_status(
        library_id=library_id,
        document_ids=finalized_document_ids,
        source_model=source_model,
    )
    if source_model == SOURCE_MODEL_RAG:
        availability_note = (
            "RAG answers depend on document sync/indexing after upload; check "
            "rag_corpus_sync_status in list-documents or library-audit."
        )
    else:
        availability_note = (
            "Legacy answers can use the document after upload processing completes."
        )

    return {
        "dry_run": False,
        "source_model": source_model,
        "library_id": library_id,
        "uploaded_file": {
            "path": file_path,
            "name": file_name,
            "gcs_file_name": gcs_file_name,
            "gcs_path": gcs_path,
        },
        "finalize_response": finalize_response,
        "finalized_document_ids": finalized_document_ids,
        "post_upload_status": post_upload_status,
        "availability_note": availability_note,
    }


def _document_tag_ids(document: Any) -> list[str]:
    tag_ids: list[str] = []
    for tag in _relationship_list(document, "tags"):
        tag_id = _resource_id(tag)
        if tag_id is not None:
            tag_ids.append(tag_id)
    return tag_ids


def _find_document(library_id: int, document_id: str) -> Any:
    documents, _ = _fetch_paginated(
        "/v1/copilot/get-documents",
        query={"libraryId": library_id},
        page_limit=DEFAULT_PAGE_LIMIT,
    )
    for document in documents:
        if _resource_id(document) == document_id:
            return document
    raise SystemExit(f"Document {document_id} was not found in library {library_id}")


def _update_document(
    *,
    library_id: int,
    document_id: str,
    payload: dict[str, Any],
) -> Any:
    return _request(
        "POST",
        PUBLIC_DOCUMENT_UPDATE_PATH.format(
            library_id=library_id,
            document_id=document_id,
        ),
        payload=payload,
    )


def _build_update_document_result(args: argparse.Namespace) -> dict[str, Any]:
    payload = {
        "name": args.name,
        "description": args.description,
        "tagIds": args.tag_ids,
        "ownerUserIds": args.owner_user_ids,
        "reviewCycle": args.review_cycle,
        "reviewedAt": args.reviewed_at,
        "reviewedByUserId": args.reviewed_by_user_id,
    }
    response = _update_document(
        library_id=args.library_id,
        document_id=args.document_id,
        payload=payload,
    )
    return {
        "library_id": args.library_id,
        "document_id": args.document_id,
        "updated_fields": sorted(
            key for key, value in payload.items() if value is not None
        ),
        "response": response,
    }


def _build_remove_document_tag_result(args: argparse.Namespace) -> dict[str, Any]:
    document = _find_document(args.library_id, args.document_id)
    existing_tag_ids = _document_tag_ids(document)
    tag_ids_to_remove = set(args.tag_ids)
    remaining_tag_ids = [
        tag_id for tag_id in existing_tag_ids if tag_id not in tag_ids_to_remove
    ]
    missing_tag_ids = sorted(tag_ids_to_remove - set(existing_tag_ids))
    response = _update_document(
        library_id=args.library_id,
        document_id=args.document_id,
        payload={"tagIds": remaining_tag_ids},
    )
    return {
        "library_id": args.library_id,
        "document_id": args.document_id,
        "removed_tag_ids": sorted(set(existing_tag_ids) - set(remaining_tag_ids)),
        "missing_tag_ids": missing_tag_ids,
        "remaining_tag_ids": remaining_tag_ids,
        "response": response,
    }


def _known_feature_flags(me_response: Any) -> dict[str, bool]:
    if not isinstance(me_response, dict):
        return {}
    value = me_response.get("known_feature_flags")
    if value is None:
        value = me_response.get("knownFeatureFlags")
    if not isinstance(value, dict):
        return {}
    return {
        flag: bool(enabled) for flag, enabled in value.items() if isinstance(flag, str)
    }


def _is_rag_source_model_enabled(me_response: Any) -> bool:
    return _known_feature_flags(me_response).get(KNOWLEDGE_LIBRARY_RAG_FLAG, False)


def _build_kb_capabilities(me_response: Any) -> dict[str, Any]:
    rag_enabled = _is_rag_source_model_enabled(me_response)
    source_model = SOURCE_MODEL_RAG if rag_enabled else SOURCE_MODEL_LEGACY
    if rag_enabled:
        supported_sources = ["documents", "instruction_sets", "memories"]
        unsupported_sources = ["legacy_qa_library"]
        recommended_question_endpoint = "/v1/copilot/answer-from-documents"
        recommended_question_command = "answer-from-documents"
    else:
        supported_sources = ["documents", "legacy_qa_library"]
        unsupported_sources = ["instruction_sets", "memories"]
        recommended_question_endpoint = "/v1/copilot/answer"
        recommended_question_command = "answer"

    return {
        "knowledge_library_rag_based_enabled": rag_enabled,
        "source_model": source_model,
        "supported_sources": supported_sources,
        "unsupported_sources": unsupported_sources,
        "recommended_question_endpoint": recommended_question_endpoint,
        "recommended_question_command": recommended_question_command,
        "feature_flag_source": "auth/me",
    }


def _fetch_paginated(
    path: str,
    *,
    query: dict[str, Any],
    page_limit: int,
) -> tuple[list[Any], dict[str, Any]]:
    offset = int(query.get("offset", 0) or 0)
    collected: list[Any] = []
    last_meta: dict[str, Any] = {}

    while True:
        page_query = {**query, "offset": offset, "limit": page_limit}
        response = _request(
            "GET",
            path,
            query=page_query,
            exit_on_error=False,
        )
        data = _jsonapi_data(response)
        if not isinstance(data, list):
            return collected, _jsonapi_meta(response)

        collected.extend(data)
        last_meta = _jsonapi_meta(response)

        total_count = last_meta.get("total_count")
        if isinstance(total_count, int) and len(collected) >= total_count:
            break
        has_next_page = last_meta.get("has_next_page")
        if has_next_page is False:
            break
        if len(data) < page_limit:
            break
        offset += page_limit

    return collected, last_meta


def _tag_names(tags: Iterable[Any]) -> list[str]:
    names: list[str] = []
    for tag in tags:
        attributes = _resource_attributes(tag)
        name = attributes.get("name") or attributes.get("label") or _resource_id(tag)
        if name:
            names.append(str(name))
    return names


def _audit_document(
    document: Any,
    *,
    duplicate_key_counts: dict[str, int],
    as_of: dt.datetime,
) -> dict[str, Any]:
    attributes = _resource_attributes(document)
    name = _string_value(
        _attribute_value(attributes, "name", "filename") or _resource_id(document),
        default="Unnamed document",
    )
    tags = _relationship_list(document, "tags")
    expiration = _document_expiration(document, as_of=as_of)

    issues: list[str] = []
    if not _string_value(_attribute_value(attributes, "description")).strip():
        issues.append("missing_description")
    if not tags:
        issues.append("missing_tags")

    rag_status = _attribute_value(attributes, "rag_corpus_sync_status")
    if (
        isinstance(rag_status, str)
        and rag_status.lower() not in SUCCESSFUL_RAG_SYNC_STATUSES
    ):
        issues.append("rag_sync_attention")

    if expiration["issue_reason"] == "missing_review_date":
        issues.append("missing_review_date")
    elif expiration["issue_reason"] == "expired":
        issues.append("expired_review")

    duplicate_key = _normalize_duplicate_key(name)
    if duplicate_key and duplicate_key_counts[duplicate_key] > 1:
        issues.append("duplicate_name_candidate")

    return {
        "id": _resource_id(document),
        "name": name,
        "filename": _attribute_value(attributes, "filename"),
        "file_type": _attribute_value(attributes, "file_type"),
        "description": _attribute_value(attributes, "description"),
        "tags": _tag_names(tags),
        "rag_corpus_sync_status": rag_status,
        "reviewed_at": _attribute_value(attributes, "reviewed_at"),
        "review_cycle": _attribute_value(attributes, "review_cycle"),
        "minimum_product_review_cycle": _attribute_value(
            attributes, "minimum_product_review_cycle"
        ),
        "computed_expiration_date": expiration["computed_expiration_date"],
        "issues": issues,
    }


def _audit_instruction(
    instruction: Any,
    *,
    duplicate_key_counts: dict[str, int],
) -> dict[str, Any]:
    attributes = _resource_attributes(instruction)
    name = _string_value(
        _attribute_value(attributes, "name") or _resource_id(instruction),
        default="Unnamed instruction",
    )
    visibility_scope = _attribute_value(attributes, "visibility_scope")
    issues: list[str] = []
    if (
        visibility_scope != "securitypal"
        and not _string_value(_attribute_value(attributes, "instruction_text")).strip()
    ):
        issues.append("missing_instruction_text")
    if not _string_value(_attribute_value(attributes, "when_to_use")).strip():
        issues.append("missing_when_to_use")
    duplicate_key = _normalize_duplicate_key(name)
    if duplicate_key and duplicate_key_counts[duplicate_key] > 1:
        issues.append("duplicate_name_candidate")

    return {
        "id": _resource_id(instruction),
        "name": name,
        "visibility_scope": visibility_scope,
        "when_to_use": _attribute_value(attributes, "when_to_use"),
        "issues": issues,
    }


def _count_issues(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        for issue in item.get("issues", []):
            counts[str(issue)] += 1
    return dict(sorted(counts.items()))


def _audit_library(
    library: Any,
    *,
    page_limit: int,
    as_of: dt.datetime,
    capabilities: dict[str, Any],
) -> dict[str, Any]:
    library_id = _resource_id(library)
    attributes = _resource_attributes(library)
    if library_id is None:
        return {
            "id": None,
            "name": attributes.get("name", "Unknown library"),
            "error": "Missing library id",
        }

    document_response_error: dict[str, Any] | None = None
    instruction_response_error: dict[str, Any] | None = None
    instructions_skipped_reason: str | None = None
    rag_enabled_response_error: dict[str, Any] | None = None

    try:
        documents, documents_meta = _fetch_paginated(
            "/v1/copilot/get-documents",
            query={"libraryId": library_id},
            page_limit=page_limit,
        )
    except ApiRequestError as error:
        documents = []
        documents_meta = {}
        document_response_error = _get_error_summary(error)

    source_model = capabilities["source_model"]
    if source_model == SOURCE_MODEL_RAG:
        try:
            instructions, instructions_meta = _fetch_paginated(
                "/v1/copilot/get-instructions",
                query={"libraryId": library_id},
                page_limit=page_limit,
            )
        except ApiRequestError as error:
            instructions = []
            instructions_meta = {}
            instruction_response_error = _get_error_summary(error)
        try:
            rag_enabled_response = _request(
                "GET",
                "/v1/copilot/check-knowledge-library-v2-enabled",
                query={"libraryId": library_id},
                exit_on_error=False,
            )
            rag_enabled_data = _jsonapi_data(rag_enabled_response)
            rag_enabled_attributes = _resource_attributes(rag_enabled_data)
            rag_enabled = _attribute_value(
                rag_enabled_attributes, "knowledge_library_v2_enabled"
            )
        except ApiRequestError as error:
            rag_enabled = None
            rag_enabled_response_error = _get_error_summary(error)
    else:
        instructions = []
        instructions_meta = {}
        instructions_skipped_reason = "Skipped for legacy source model"
        rag_enabled = False
        rag_enabled_response_error = None

    duplicate_document_keys: dict[str, int] = defaultdict(int)
    for document in documents:
        attributes = _resource_attributes(document)
        name = _string_value(_attribute_value(attributes, "name", "filename"))
        key = _normalize_duplicate_key(name)
        if key:
            duplicate_document_keys[key] += 1

    audited_documents = [
        _audit_document(
            document,
            duplicate_key_counts=duplicate_document_keys,
            as_of=as_of,
        )
        for document in documents
    ]

    duplicate_instruction_keys: dict[str, int] = defaultdict(int)
    for instruction in instructions:
        attributes = _resource_attributes(instruction)
        key = _normalize_duplicate_key(
            _string_value(_attribute_value(attributes, "name"))
        )
        if key:
            duplicate_instruction_keys[key] += 1

    audited_instructions = [
        _audit_instruction(
            instruction,
            duplicate_key_counts=duplicate_instruction_keys,
        )
        for instruction in instructions
    ]

    return {
        "id": library_id,
        "name": attributes.get("name"),
        "tags": _tag_names(_relationship_list(library, "tags")),
        "source_model": source_model,
        "knowledge_library_v2_enabled": rag_enabled,
        "documents": audited_documents,
        "document_count": documents_meta.get("total_count", len(audited_documents)),
        "document_issue_counts": _count_issues(audited_documents),
        "documents_error": document_response_error,
        "instructions": audited_instructions,
        "instruction_count": instructions_meta.get(
            "total_count",
            len(audited_instructions),
        ),
        "instruction_issue_counts": _count_issues(audited_instructions),
        "instructions_error": instruction_response_error,
        "instructions_skipped_reason": instructions_skipped_reason,
        "rag_enabled_error": rag_enabled_response_error,
    }


def _build_library_audit(args: argparse.Namespace) -> dict[str, Any]:
    as_of = _parse_datetime(args.as_of)
    if as_of is None:
        raise SystemExit("--as-of must be an ISO date or datetime")
    if args.page_limit < 1:
        raise SystemExit("--page-limit must be at least 1")

    me_response = _request("GET", "/v1/auth/me")
    capabilities = _build_kb_capabilities(me_response)
    libraries_response = _request(
        "GET",
        "/v1/libraries/",
        query={"includeTags": "true"},
    )
    libraries_data = _jsonapi_data(libraries_response)
    if not isinstance(libraries_data, list):
        raise SystemExit("Expected list-libraries response to contain a data array")

    requested_library_ids = {str(library_id) for library_id in args.library_ids or []}
    libraries = [
        library
        for library in libraries_data
        if not requested_library_ids or _resource_id(library) in requested_library_ids
    ]
    found_library_ids = {
        library_id
        for library in libraries
        if (library_id := _resource_id(library)) is not None
    }

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "as_of": as_of.isoformat(),
        "library_count": len(libraries),
        "missing_library_ids": sorted(requested_library_ids - found_library_ids),
        "libraries": [
            _audit_library(
                library,
                page_limit=args.page_limit,
                as_of=as_of,
                capabilities=capabilities,
            )
            for library in libraries
        ],
    }


def _build_check_auth() -> dict[str, Any]:
    token = os.environ.get("SECURITYPAL_API_TOKEN")
    checks: list[dict[str, Any]] = [
        {
            "name": "environment",
            "ok": bool(token),
            "base_url": _base_url(),
            "token_present": bool(token),
        }
    ]
    if not token:
        return {
            "ok": False,
            "base_url": _base_url(),
            "checks": checks,
        }

    try:
        me_response = _request("GET", "/v1/auth/me", exit_on_error=False)
        capabilities = _build_kb_capabilities(me_response)
        checks.append({"name": "auth/me", "ok": True})
    except ApiRequestError as error:
        return {
            "ok": False,
            "base_url": _base_url(),
            "checks": [
                *checks,
                {
                    "name": "auth/me",
                    "ok": False,
                    "error": _get_error_summary(error),
                },
            ],
        }

    try:
        libraries_response = _request(
            "GET",
            "/v1/libraries/",
            query={"includeTags": "true"},
            exit_on_error=False,
        )
        libraries_data = _jsonapi_data(libraries_response)
        accessible_libraries = (
            libraries_data if isinstance(libraries_data, list) else []
        )
        checks.append(
            {
                "name": "accessible_libraries",
                "ok": isinstance(libraries_data, list),
                "count": len(accessible_libraries),
                "examples": accessible_libraries[:MAX_GAP_EXAMPLES],
            }
        )
    except ApiRequestError as error:
        checks.append(
            {
                "name": "accessible_libraries",
                "ok": False,
                "error": _get_error_summary(error),
            }
        )

    return {
        "ok": all(bool(check["ok"]) for check in checks),
        "base_url": _base_url(),
        "account": me_response,
        "capabilities": capabilities,
        "checks": checks,
    }


def _build_expired_documents(args: argparse.Namespace) -> dict[str, Any]:
    audit = _build_library_audit(args)
    libraries: list[dict[str, Any]] = []
    for library in audit["libraries"]:
        documents = []
        for document in library.get("documents", []):
            issue_reason = None
            if "missing_review_date" in document.get("issues", []):
                issue_reason = "missing_review_date"
            elif "expired_review" in document.get("issues", []):
                issue_reason = "expired"
            if issue_reason is None:
                continue
            documents.append(
                {
                    "id": document.get("id"),
                    "name": document.get("name"),
                    "reviewed_at": document.get("reviewed_at"),
                    "review_cycle": document.get("review_cycle"),
                    "minimum_product_review_cycle": document.get(
                        "minimum_product_review_cycle"
                    ),
                    "effective_review_cycle_days": document.get("review_cycle")
                    or document.get("minimum_product_review_cycle"),
                    "computed_expiration_date": document.get(
                        "computed_expiration_date"
                    ),
                    "issue_reason": issue_reason,
                }
            )
        libraries.append(
            {
                "id": library.get("id"),
                "name": library.get("name"),
                "expired_or_missing_review_document_count": len(documents),
                "documents": documents,
                "documents_error": library.get("documents_error"),
            }
        )

    return {
        "generated_at": audit["generated_at"],
        "as_of": audit["as_of"],
        "library_count": audit["library_count"],
        "missing_library_ids": audit["missing_library_ids"],
        "libraries": libraries,
    }


def _topic_tokens(topic: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", topic.lower()) if len(token) > 2
    }


def _item_text(item: dict[str, Any], fields: Iterable[str]) -> str:
    values: list[str] = []
    for field in fields:
        value = item.get(field)
        if isinstance(value, list):
            values.extend(str(part) for part in value)
        elif value is not None:
            values.append(str(value))
    return " ".join(values).lower()


def _matches_topic(item: dict[str, Any], *, topic_tokens: set[str]) -> bool:
    if not topic_tokens:
        return False
    searchable = _item_text(
        item,
        (
            "name",
            "filename",
            "description",
            "tags",
            "when_to_use",
            "instruction_text",
            "content",
        ),
    )
    return any(token in searchable for token in topic_tokens)


def _extract_sources(response: Any) -> list[Any]:
    data = _jsonapi_data(response)
    if isinstance(data, dict):
        for key in ("sources", "relationships"):
            value = data.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                if key == "relationships":
                    value = value.get("sources")
                relationship_data = (
                    value.get("data") if isinstance(value, dict) else None
                )
                if isinstance(relationship_data, list):
                    return relationship_data
        attributes = _resource_attributes(data)
        value = attributes.get("sources")
        if isinstance(value, list):
            return value
    if isinstance(response, dict):
        value = response.get("sources")
        if isinstance(value, list):
            return value
    return []


def _source_type(source: Any) -> str | None:
    if not isinstance(source, dict):
        return None
    nested_source = source.get("source")
    if isinstance(nested_source, dict):
        attributes = _resource_attributes(nested_source)
        return str(nested_source.get("type") or attributes.get("type") or "")
    attributes = _resource_attributes(source)
    return str(source.get("type") or attributes.get("type") or "")


def _fetch_library_inventory(
    library_id: int,
    *,
    page_limit: int,
    as_of: dt.datetime,
) -> dict[str, Any]:
    try:
        documents, documents_meta = _fetch_paginated(
            "/v1/copilot/get-documents",
            query={"libraryId": library_id},
            page_limit=page_limit,
        )
        duplicate_document_keys: dict[str, int] = defaultdict(int)
        for document in documents:
            attributes = _resource_attributes(document)
            key = _normalize_duplicate_key(
                _string_value(_attribute_value(attributes, "name", "filename"))
            )
            if key:
                duplicate_document_keys[key] += 1
        audited_documents = [
            _audit_document(
                document,
                duplicate_key_counts=duplicate_document_keys,
                as_of=as_of,
            )
            for document in documents
        ]
        documents_error = None
    except ApiRequestError as error:
        audited_documents = []
        documents_meta = {}
        documents_error = _get_error_summary(error)

    try:
        instructions, instructions_meta = _fetch_paginated(
            "/v1/copilot/get-instructions",
            query={"libraryId": library_id},
            page_limit=page_limit,
        )
        duplicate_instruction_keys: dict[str, int] = defaultdict(int)
        for instruction in instructions:
            instruction_attributes = _resource_attributes(instruction)
            key = _normalize_duplicate_key(
                _string_value(_attribute_value(instruction_attributes, "name"))
            )
            if key:
                duplicate_instruction_keys[key] += 1
        audited_instructions = [
            _audit_instruction(
                instruction,
                duplicate_key_counts=duplicate_instruction_keys,
            )
            for instruction in instructions
        ]
        instructions_error = None
    except ApiRequestError as error:
        audited_instructions = []
        instructions_meta = {}
        instructions_error = _get_error_summary(error)

    return {
        "documents": audited_documents,
        "document_count": documents_meta.get("total_count", len(audited_documents)),
        "documents_error": documents_error,
        "instructions": audited_instructions,
        "instruction_count": instructions_meta.get(
            "total_count",
            len(audited_instructions),
        ),
        "instructions_error": instructions_error,
    }


def _fetch_memories(
    library_id: int,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    try:
        response = _request(
            "GET",
            "/v1/copilot/get-memory",
            query={"productId": library_id},
            exit_on_error=False,
        )
    except ApiRequestError as error:
        if error.status == 404:
            return [], None
        return [], _get_error_summary(error)
    data = _jsonapi_data(response)
    if isinstance(data, dict):
        memory_items = [data]
    elif isinstance(data, list):
        memory_items = data
    else:
        return [], None
    memories = []
    for memory in memory_items:
        attributes = _resource_attributes(memory)
        memories.append(
            {
                "id": _resource_id(memory) or _string_value(attributes.get("id")),
                "name": attributes.get("name"),
                "description": attributes.get("description"),
                "content": attributes.get("content"),
                "updated_at": _attribute_value(attributes, "updated_at"),
            }
        )
    return memories, None


def _build_knowledge_gaps(args: argparse.Namespace) -> dict[str, Any]:
    as_of = _parse_datetime(args.as_of)
    if as_of is None:
        raise SystemExit("--as-of must be an ISO date or datetime")
    if args.page_limit < 1:
        raise SystemExit("--page-limit must be at least 1")

    me_response = _request("GET", "/v1/auth/me")
    capabilities = _build_kb_capabilities(me_response)
    inventory = _fetch_library_inventory(
        args.library_id,
        page_limit=args.page_limit,
        as_of=as_of,
    )
    topic_tokens = _topic_tokens(args.topic)
    relevant_documents = [
        document
        for document in inventory["documents"]
        if _matches_topic(document, topic_tokens=topic_tokens)
    ]
    document_issues = sorted(
        {
            issue
            for document in relevant_documents
            for issue in document.get("issues", [])
            if issue
        }
    )
    gaps: list[str] = []
    documents_error = inventory["documents_error"]
    if documents_error is None and not relevant_documents:
        gaps.append("relevant_documents_missing")
    if documents_error is None and any(
        issue in document_issues
        for issue in ("missing_description", "missing_tags", "duplicate_name_candidate")
    ):
        gaps.append("relevant_documents_weak")
    if documents_error is None and "expired_review" in document_issues:
        gaps.append("relevant_documents_expired")
    if documents_error is None and "missing_review_date" in document_issues:
        gaps.append("relevant_documents_missing_review_date")

    result: dict[str, Any] = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "as_of": as_of.isoformat(),
        "library_id": args.library_id,
        "topic": args.topic,
        "source_model": capabilities["source_model"],
        "capabilities": capabilities,
        "documents": {
            "total_count": inventory["document_count"],
            "relevant_count": len(relevant_documents),
            "relevant_examples": relevant_documents[:MAX_GAP_EXAMPLES],
            "issues": document_issues,
            "error": documents_error,
        },
        "gaps": gaps,
    }

    if capabilities["source_model"] == SOURCE_MODEL_RAG:
        instructions_error = inventory["instructions_error"]
        relevant_instructions = [
            instruction
            for instruction in inventory["instructions"]
            if _matches_topic(instruction, topic_tokens=topic_tokens)
        ]
        memories, memories_error = _fetch_memories(args.library_id)
        relevant_memories = [
            memory
            for memory in memories
            if _matches_topic(memory, topic_tokens=topic_tokens)
        ]
        if instructions_error is None and not relevant_instructions:
            gaps.append("useful_instruction_sets_missing")
        if not relevant_memories and memories_error is None:
            gaps.append("relevant_memories_missing")
        if "rag_sync_attention" in document_issues:
            gaps.append("relevant_documents_unsynced")
        result["instruction_sets"] = {
            "total_count": inventory["instruction_count"],
            "relevant_count": len(relevant_instructions),
            "relevant_examples": relevant_instructions[:MAX_GAP_EXAMPLES],
            "error": instructions_error,
        }
        result["memories"] = {
            "total_count": len(memories),
            "relevant_count": len(relevant_memories),
            "relevant_examples": relevant_memories[:MAX_GAP_EXAMPLES],
            "error": memories_error,
        }
    else:
        try:
            answer_response = _request(
                "POST",
                "/v1/copilot/answer",
                payload={
                    "libraryId": args.library_id,
                    "question": f"What knowledge exists about {args.topic}?",
                    "includeSources": True,
                    "includeLibrary": True,
                    "includeTags": True,
                },
                exit_on_error=False,
            )
            sources = _extract_sources(answer_response)
            answer_library_sources = [
                source
                for source in sources
                if _source_type(source)
                in {"answerLibraryEntry", "answer_library_entry"}
            ]
            qa_error = None
        except ApiRequestError as error:
            sources = []
            answer_library_sources = []
            qa_error = _get_error_summary(error)
        if not answer_library_sources and qa_error is None:
            gaps.append("legacy_qa_entries_missing")
        result["legacy_qa_library"] = {
            "source_count": len(answer_library_sources),
            "source_examples": answer_library_sources[:MAX_GAP_EXAMPLES],
            "all_source_count": len(sources),
            "error": qa_error,
        }

    result["gaps"] = sorted(set(gaps))
    return result


def _format_issue_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{key}: {value}" for key, value in counts.items())


def _format_markdown_examples(items: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    issue_items = [item for item in items if item.get("issues")]
    for item in issue_items[:MAX_MARKDOWN_EXAMPLES]:
        item_id = item.get("id") or "unknown-id"
        issues = ", ".join(item.get("issues", []))
        lines.append(f"- `{item_id}` {item.get('name')}: {issues}")
    if len(issue_items) > MAX_MARKDOWN_EXAMPLES:
        lines.append(f"- ... {len(issue_items) - MAX_MARKDOWN_EXAMPLES} more")
    return lines


def _print_library_audit_markdown(audit: dict[str, Any]) -> None:
    lines = [
        "# SecurityPal Knowledge Library Audit",
        "",
        f"- Generated at: `{audit['generated_at']}`",
        f"- As of: `{audit['as_of']}`",
        f"- Libraries audited: {audit['library_count']}",
        "",
    ]
    if audit["missing_library_ids"]:
        missing_ids = ", ".join(
            f"`{library_id}`" for library_id in audit["missing_library_ids"]
        )
        lines.extend([f"- Requested libraries not found: {missing_ids}", ""])

    for library in audit["libraries"]:
        document_issue_counts = _format_issue_counts(
            library.get("document_issue_counts", {}),
        )
        instruction_issue_counts = _format_issue_counts(
            library.get("instruction_issue_counts", {}),
        )
        lines.extend(
            [
                (
                    "## "
                    f"{library.get('name') or 'Unnamed library'} "
                    f"(`{library.get('id')}`)"
                ),
                "",
                (
                    "- Knowledge Library v2 enabled: "
                    f"`{library.get('knowledge_library_v2_enabled')}`"
                ),
                f"- Tags: {', '.join(library.get('tags') or []) or 'none'}",
                f"- Documents: {library.get('document_count', 0)}",
                f"- Document issues: {document_issue_counts}",
                f"- Instruction sets: {library.get('instruction_count', 0)}",
                f"- Instruction issues: {instruction_issue_counts}",
                "",
            ]
        )
        for error_key, label in (
            ("documents_error", "Document inventory error"),
            ("instructions_error", "Instruction inventory error"),
            ("rag_enabled_error", "RAG status error"),
        ):
            if library.get(error_key):
                error = library[error_key]
                lines.append(
                    f"- {label}: `{error.get('status')}` {error.get('reason')}"
                )
        if (
            library.get("documents_error")
            or library.get("instructions_error")
            or library.get("rag_enabled_error")
        ):
            lines.append("")

        document_examples = _format_markdown_examples(library.get("documents", []))
        if document_examples:
            lines.extend(["### Document Examples", "", *document_examples, ""])

        instruction_examples = _format_markdown_examples(
            library.get("instructions", []),
        )
        if instruction_examples:
            lines.extend(["### Instruction Examples", "", *instruction_examples, ""])

    print("\n".join(lines).rstrip())


def _print_expired_documents_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# SecurityPal Expired Documents",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- As of: `{report['as_of']}`",
        f"- Libraries checked: {report['library_count']}",
        "",
    ]
    if report["missing_library_ids"]:
        missing_ids = ", ".join(
            f"`{library_id}`" for library_id in report["missing_library_ids"]
        )
        lines.extend([f"- Requested libraries not found: {missing_ids}", ""])

    for library in report["libraries"]:
        lines.extend(
            [
                (
                    "## "
                    f"{library.get('name') or 'Unnamed library'} "
                    f"(`{library.get('id')}`)"
                ),
                "",
                (
                    "- Expired or missing-review documents: "
                    f"{library.get('expired_or_missing_review_document_count', 0)}"
                ),
                "",
            ]
        )
        if library.get("documents_error"):
            error = library["documents_error"]
            lines.extend(
                [
                    f"- Document inventory error: `{error.get('status')}` "
                    f"{error.get('reason')}",
                    "",
                ]
            )
        for document in library.get("documents", []):
            lines.append(
                "- "
                f"`{document.get('id')}` {document.get('name')}: "
                f"{document.get('issue_reason')}; "
                f"reviewed `{document.get('reviewed_at')}`; "
                f"cycle `{document.get('effective_review_cycle_days')}` days; "
                f"expires `{document.get('computed_expiration_date')}`"
            )
        if library.get("documents"):
            lines.append("")

    print("\n".join(lines).rstrip())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Query SecurityPal AI and library public APIs.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_libraries = subparsers.add_parser(
        "list-libraries", help="List accessible libraries."
    )
    list_libraries.add_argument("--include-tags", action="store_true")

    subparsers.add_parser("me", help="Get authenticated user and feature flags.")

    subparsers.add_parser(
        "check-auth",
        help="Validate token, base URL, source model, and accessible libraries.",
    )
    subparsers.add_parser(
        "doctor",
        help="Alias for check-auth.",
    )

    subparsers.add_parser(
        "kb-capabilities",
        help="Detect the Knowledge Library source model from auth/me.",
    )

    list_tags = subparsers.add_parser("list-tags", help="List tags for a library.")
    list_tags.add_argument("--library-id", type=int, required=True)

    list_documents = subparsers.add_parser(
        "list-documents", help="List library documents."
    )
    list_documents.add_argument("--library-id", type=int, required=True)
    list_documents.add_argument("--offset", type=int, default=0)
    list_documents.add_argument("--limit", type=int, default=50)

    list_instructions = subparsers.add_parser(
        "list-instructions", help="List instruction sets."
    )
    list_instructions.add_argument("--library-id", type=int, required=True)
    list_instructions.add_argument("--offset", type=int, default=0)
    list_instructions.add_argument("--limit", type=int, default=50)

    list_memories = subparsers.add_parser("list-memories", help="List memories.")
    list_memories.add_argument("--library-id", type=int, required=True)

    rag_enabled = subparsers.add_parser(
        "rag-enabled", help="Check RAG/KL v2 availability."
    )
    rag_enabled.add_argument("--library-id", type=int, required=True)

    library_audit = subparsers.add_parser(
        "library-audit",
        help="Audit libraries for document and instruction hygiene issues.",
    )
    library_audit.add_argument(
        "--library-id",
        type=int,
        action="append",
        dest="library_ids",
        help="Limit the audit to one library. Repeat to audit multiple libraries.",
    )
    library_audit.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format.",
    )
    library_audit.add_argument(
        "--page-limit",
        type=int,
        default=DEFAULT_PAGE_LIMIT,
        help="Page size for paginated document and instruction endpoints.",
    )
    library_audit.add_argument(
        "--as-of",
        default=dt.datetime.now(dt.timezone.utc).date().isoformat(),
        help="ISO date/datetime used for stale review calculations.",
    )

    expired_documents = subparsers.add_parser(
        "expired-documents",
        help="List documents that are expired or missing a review date.",
    )
    expired_documents.add_argument(
        "--library-id",
        type=int,
        action="append",
        dest="library_ids",
        help="Limit the report to one library. Repeat to check multiple libraries.",
    )
    expired_documents.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format.",
    )
    expired_documents.add_argument(
        "--page-limit",
        type=int,
        default=DEFAULT_PAGE_LIMIT,
        help="Page size for paginated document and instruction endpoints.",
    )
    expired_documents.add_argument(
        "--as-of",
        default=dt.datetime.now(dt.timezone.utc).date().isoformat(),
        help="ISO date/datetime used for expiration calculations.",
    )

    knowledge_gaps = subparsers.add_parser(
        "knowledge-gaps",
        help="Find likely Knowledge Library gaps for a topic.",
    )
    knowledge_gaps.add_argument("--library-id", type=int, required=True)
    knowledge_gaps.add_argument("--topic", required=True)
    knowledge_gaps.add_argument(
        "--page-limit",
        type=int,
        default=DEFAULT_PAGE_LIMIT,
        help="Page size for paginated document and instruction endpoints.",
    )
    knowledge_gaps.add_argument(
        "--as-of",
        default=dt.datetime.now(dt.timezone.utc).date().isoformat(),
        help="ISO date/datetime used for expiration calculations.",
    )

    answer = subparsers.add_parser(
        "answer", help="Ask SecurityPal AI a library-scoped question."
    )
    answer.add_argument("--library-id", type=int, required=True)
    answer.add_argument("--question", required=True)
    answer.add_argument("--instruction")
    answer.add_argument("--tag-id", action="append", dest="tag_ids")
    answer.add_argument("--include-sources", action="store_true")
    answer.add_argument("--include-library", action="store_true")
    answer.add_argument("--include-tags", action="store_true")

    search = subparsers.add_parser("search", help="Search within selected documents.")
    search.add_argument("--library-id", type=int, required=True)
    search.add_argument("--question", required=True)
    search.add_argument("--document-id", action="append", dest="document_ids")
    search.add_argument("--instruction-id", action="append", dest="instruction_ids")

    answer_from_documents = subparsers.add_parser(
        "answer-from-documents",
        help="Ask SecurityPal AI using document RAG.",
    )
    answer_from_documents.add_argument("--library-id", type=int, required=True)
    answer_from_documents.add_argument("--question", required=True)
    answer_from_documents.add_argument("--instruction")

    answer_kb = subparsers.add_parser(
        "answer-kb",
        help="Ask a KB question using the source model reported by auth/me.",
    )
    answer_kb.add_argument("--library-id", type=int, required=True)
    answer_kb.add_argument("--question", required=True)
    answer_kb.add_argument("--instruction")
    answer_kb.add_argument("--tag-id", action="append", dest="tag_ids")
    answer_kb.add_argument("--include-sources", action="store_true")
    answer_kb.add_argument("--include-library", action="store_true")
    answer_kb.add_argument("--include-tags", action="store_true")

    add_document = subparsers.add_parser(
        "add-document",
        help="Upload and finalize a document using signed upload endpoints.",
    )
    add_document.add_argument("--file", required=True, help="Path to the document.")
    add_document.add_argument(
        "--name",
        help="Original filename to record. Defaults to the local file basename.",
    )
    add_document.add_argument(
        "--library-id",
        type=int,
        action="append",
        dest="library_ids",
        help="Library/product ID to associate with the document.",
    )
    add_document.add_argument(
        "--product-id",
        type=int,
        action="append",
        dest="product_ids",
        help="Alias for --library-id when using product terminology.",
    )
    add_document.add_argument("--tag-id", action="append", dest="tag_ids")
    add_document.add_argument(
        "--owner-user-id",
        type=int,
        action="append",
        dest="owner_user_ids",
    )
    add_document.add_argument("--review-cycle", type=int)
    add_document.add_argument("--reviewed-at")
    add_document.add_argument("--reviewed-by-user-id", type=int)
    add_document.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate local inputs and print planned upload steps without API calls.",
    )

    delete_document = subparsers.add_parser(
        "delete-document",
        help="Delete one Knowledge Library document.",
    )
    delete_document.add_argument("--library-id", type=int, required=True)
    delete_document.add_argument("--document-id", required=True)

    update_document = subparsers.add_parser(
        "update-document",
        help="Update Knowledge Library document metadata.",
    )
    update_document.add_argument("--library-id", type=int, required=True)
    update_document.add_argument("--document-id", required=True)
    update_document.add_argument("--name")
    update_document.add_argument("--description")
    update_document.add_argument("--tag-id", action="append", dest="tag_ids")
    update_document.add_argument(
        "--owner-user-id",
        type=int,
        action="append",
        dest="owner_user_ids",
    )
    update_document.add_argument("--review-cycle", type=int)
    update_document.add_argument("--reviewed-at")
    update_document.add_argument("--reviewed-by-user-id", type=int)

    remove_document_tag = subparsers.add_parser(
        "remove-document-tag",
        help="Remove one or more tags from a Knowledge Library document.",
    )
    remove_document_tag.add_argument("--library-id", type=int, required=True)
    remove_document_tag.add_argument("--document-id", required=True)
    remove_document_tag.add_argument(
        "--tag-id",
        action="append",
        required=True,
        dest="tag_ids",
    )

    get_autocomplete = subparsers.add_parser(
        "get-autocomplete",
        help="Fetch autocomplete request results.",
    )
    get_autocomplete.add_argument("--request-id", required=True)
    get_autocomplete.add_argument("--product-id", type=int, required=True)
    get_autocomplete.add_argument("--offset", type=int, default=0)
    get_autocomplete.add_argument("--limit", type=int, default=20)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "list-libraries":
        result = _request(
            "GET",
            "/v1/libraries/",
            query={"includeTags": str(args.include_tags).lower()},
        )
    elif args.command == "me":
        result = _request("GET", "/v1/auth/me")
    elif args.command in {"check-auth", "doctor"}:
        result = _build_check_auth()
    elif args.command == "kb-capabilities":
        me_response = _request("GET", "/v1/auth/me")
        result = _build_kb_capabilities(me_response)
    elif args.command == "list-tags":
        result = _request("GET", f"/v1/libraries/{args.library_id}/tags")
    elif args.command == "list-documents":
        result = _request(
            "GET",
            "/v1/copilot/get-documents",
            query={
                "libraryId": args.library_id,
                "offset": args.offset,
                "limit": args.limit,
            },
        )
    elif args.command == "list-instructions":
        result = _request(
            "GET",
            "/v1/copilot/get-instructions",
            query={
                "libraryId": args.library_id,
                "offset": args.offset,
                "limit": args.limit,
            },
        )
    elif args.command == "list-memories":
        result = _request(
            "GET",
            "/v1/copilot/get-memory",
            query={"productId": args.library_id},
        )
    elif args.command == "rag-enabled":
        result = _request(
            "GET",
            "/v1/copilot/check-knowledge-library-v2-enabled",
            query={"libraryId": args.library_id},
        )
    elif args.command == "library-audit":
        result = _build_library_audit(args)
        if args.format == "markdown":
            _print_library_audit_markdown(result)
            return
    elif args.command == "expired-documents":
        result = _build_expired_documents(args)
        if args.format == "markdown":
            _print_expired_documents_markdown(result)
            return
    elif args.command == "knowledge-gaps":
        result = _build_knowledge_gaps(args)
    elif args.command == "answer":
        result = _request(
            "POST",
            "/v1/copilot/answer",
            payload={
                "libraryId": args.library_id,
                "question": args.question,
                "instruction": args.instruction,
                "tagIds": args.tag_ids,
                "includeSources": args.include_sources,
                "includeLibrary": args.include_library,
                "includeTags": args.include_tags,
            },
        )
    elif args.command == "search":
        result = _request(
            "POST",
            "/v1/copilot/search",
            payload={
                "libraryId": args.library_id,
                "question": args.question,
                "instructionIds": args.instruction_ids,
                "documentIds": args.document_ids,
            },
        )
    elif args.command == "answer-from-documents":
        result = _request(
            "POST",
            "/v1/copilot/answer-from-documents",
            payload={
                "libraryId": args.library_id,
                "question": args.question,
                "instruction": args.instruction,
            },
        )
    elif args.command == "answer-kb":
        me_response = _request("GET", "/v1/auth/me")
        capabilities = _build_kb_capabilities(me_response)
        if capabilities["source_model"] == SOURCE_MODEL_RAG:
            if args.include_sources or args.include_library or args.include_tags:
                raise SystemExit(
                    "answer-kb include flags are only supported by the legacy "
                    "answer endpoint. The RAG source model routes to "
                    "answer-from-documents, which does not expose includeSources, "
                    "includeLibrary, or includeTags."
                )
            result = _request(
                "POST",
                "/v1/copilot/answer-from-documents",
                payload={
                    "libraryId": args.library_id,
                    "question": args.question,
                    "instruction": args.instruction,
                },
            )
        else:
            result = _request(
                "POST",
                "/v1/copilot/answer",
                payload={
                    "libraryId": args.library_id,
                    "question": args.question,
                    "instruction": args.instruction,
                    "tagIds": args.tag_ids,
                    "includeSources": args.include_sources,
                    "includeLibrary": args.include_library,
                    "includeTags": args.include_tags,
                },
            )
    elif args.command == "add-document":
        result = _build_add_document_result(args)
    elif args.command == "delete-document":
        result = _request(
            "POST",
            PUBLIC_DOCUMENT_DELETE_PATH.format(
                library_id=args.library_id,
                document_id=args.document_id,
            ),
            payload={},
        )
    elif args.command == "update-document":
        result = _build_update_document_result(args)
    elif args.command == "remove-document-tag":
        result = _build_remove_document_tag_result(args)
    elif args.command == "get-autocomplete":
        result = _request(
            "GET",
            "/v1/copilot/request-autocomplete",
            query={
                "requestId": args.request_id,
                "productId": args.product_id,
                "offset": args.offset,
                "limit": args.limit,
            },
        )
    else:
        raise SystemExit(f"Unsupported command: {args.command}")

    _print_json(result)


if __name__ == "__main__":
    main()
