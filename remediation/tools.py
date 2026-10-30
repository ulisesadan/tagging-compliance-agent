"""
Function tools for the tagging-compliance Agent Framework agent. Three
capabilities, matching the three operator-facing actions:
  1. get_tag_report            - compliance summary for a subscription/resource group
  2. list_non_compliant        - detail list + sibling examples, for conversational triage
  3. apply_resource_tags       - writes tags via ARM (Merge) + ALWAYS stamps an audit tag

Tag writes are additive-only: any requested key that already has a non-empty
value on the resource is left untouched (reported back as "skipped"), never
overwritten. Every write that does happen also adds rules.json's
"audit_tag_key" tag so any tag change made by this agent is traceable.
"""
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from azure.identity import DefaultAzureCredential
from azure.mgmt.resource.resources import ResourceManagementClient
from azure.mgmt.resource.resources.models import Tags, TagsPatchResource
from pydantic import Field

REPORT_DIR = Path(__file__).parent.parent / "report"
sys.path.insert(0, str(REPORT_DIR))
import compliance_lib  # noqa: E402  (must follow sys.path mutation above)

AGENT_NAME = "tagging-compliance-agent"
APPLIED_LOG_PATH = Path(__file__).parent / "out" / "agent_applied_log.csv"
MAX_SIBLING_EXAMPLES = 3

_credential = DefaultAzureCredential()
_tag_clients: dict[str, ResourceManagementClient] = {}


def _tag_client(subscription_id: str) -> ResourceManagementClient:
    return _tag_clients.setdefault(subscription_id, ResourceManagementClient(_credential, subscription_id))


def _log_applied_change(resource_id: str, resource_name: str, tags_written: dict[str, str]) -> None:
    APPLIED_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    is_new = not APPLIED_LOG_PATH.exists()
    with open(APPLIED_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["timestamp", "resource_id", "resource_name", "tags_written"])
        writer.writerow([datetime.now(timezone.utc).isoformat(), resource_id, resource_name, json.dumps(tags_written)])


def get_tag_report(
    subscription_id: Annotated[str, Field(description="Azure subscription ID to scan")],
    resource_group: Annotated[str | None, Field(description="Optional resource group name to scope the scan to")] = None,
) -> str:
    """Returns a tag-compliance summary (per-tag % missing/placeholder/invalid/compliant,
    overall % non-compliant) for a subscription, or a single resource group within it."""
    classified, excluded = compliance_lib.classify_scope(_credential, [subscription_id], resource_group)
    rules = compliance_lib.load_rules()
    required_tags = rules["required_tags"]
    total = len(classified)
    non_compliant = sum(1 for item in classified if not item["compliant"])

    per_tag = {}
    for tag in required_tags:
        counts = {"missing": 0, "placeholder": 0, "invalid_format": 0, "compliant": 0}
        for item in classified:
            counts[item["tag_status"][tag]] += 1
        per_tag[tag] = {k: round(v / total * 100, 1) if total else 0.0 for k, v in counts.items()}

    return json.dumps({
        "subscription_id": subscription_id,
        "resource_group": resource_group,
        "total_resources_scored": total,
        "excluded_resources": len(excluded),
        "non_compliant_resources": non_compliant,
        "non_compliant_percent": round(non_compliant / total * 100, 1) if total else 0.0,
        "per_tag_percent": per_tag,
    })


def list_non_compliant(
    subscription_id: Annotated[str, Field(description="Azure subscription ID to scan")],
    resource_group: Annotated[str | None, Field(description="Optional resource group name to scope the scan to")] = None,
    max_results: Annotated[int, Field(description="Maximum number of non-compliant resources to return")] = 15,
) -> str:
    """Returns non-compliant resources (id, name, type, which tags are off and why, current
    values) plus example tag values from compliant sibling resources in the same resource
    group, to help propose consistent fixes in conversation."""
    classified, _ = compliance_lib.classify_scope(_credential, [subscription_id], resource_group)
    rules = compliance_lib.load_rules()
    required_tags = rules["required_tags"]

    siblings_by_rg: dict[str, list[dict[str, str]]] = {}
    for item in classified:
        if not item["compliant"]:
            continue
        rg = item["resourceGroup"]
        bucket = siblings_by_rg.setdefault(rg, [])
        if len(bucket) < MAX_SIBLING_EXAMPLES:
            bucket.append({tag: item["tag_values"][tag] for tag in required_tags if item["tag_values"][tag]})

    results = []
    for item in classified:
        if item["compliant"]:
            continue
        non_compliant_tags = [
            {"tag": tag, "status": item["tag_status"][tag], "current_value": item["tag_values"][tag]}
            for tag in required_tags
            if item["tag_status"][tag] != "compliant"
        ]
        results.append({
            "id": item["id"],
            "name": item["name"],
            "type": item["type"],
            "resourceGroup": item["resourceGroup"],
            "subscriptionId": item["subscriptionId"],
            "non_compliant_tags": non_compliant_tags,
            "sibling_examples": siblings_by_rg.get(item["resourceGroup"], []),
        })
        if len(results) >= max_results:
            break

    return json.dumps({"non_compliant_count_returned": len(results), "resources": results})


def _apply_tags_to_one(
    resource_id: str,
    resource_name: str,
    tags: dict[str, str],
    audit_tag_key: str,
    current_tags: dict[str, str] | None = None,
) -> dict:
    subscription_id = resource_id.split("/")[2]
    client = _tag_client(subscription_id)

    if current_tags is None:
        existing = client.tags.get_at_scope(scope=resource_id)
        current_tags = (existing.properties.tags if existing.properties else None) or {}

    skipped = {k: current_tags[k] for k in tags if current_tags.get(k)}
    tags_to_write = {k: v for k, v in tags.items() if k not in skipped}

    if not tags_to_write:
        return {"resource_id": resource_id, "tags_written": {}, "tags_skipped_already_set": skipped}

    tags_to_write[audit_tag_key] = f"{AGENT_NAME}@{datetime.now(timezone.utc).isoformat()}"
    poller = client.tags.begin_update_at_scope(
        scope=resource_id,
        parameters=TagsPatchResource(operation="Merge", properties=Tags(tags=tags_to_write)),
    )
    poller.result()
    _log_applied_change(resource_id, resource_name, tags_to_write)
    return {"resource_id": resource_id, "tags_written": tags_to_write, "tags_skipped_already_set": skipped}


def apply_resource_tags(
    resource_id: Annotated[str, Field(description="Full ARM resource ID to tag")],
    tags: Annotated[dict[str, str], Field(description="Tag key/value pairs to set on the resource")],
) -> str:
    """Applies the given tags to a single resource, but NEVER overwrites a tag key that
    already has a non-empty value on the resource (those are reported back as
    tags_skipped_already_set instead). Always also stamps the audit tag configured in
    rules.json on any actual write so every change made by this agent is traceable. Only
    call this after the operator has explicitly confirmed the exact tag values in
    conversation."""
    rules = compliance_lib.load_rules()
    resource_name = resource_id.rstrip("/").split("/")[-1]
    result = _apply_tags_to_one(resource_id, resource_name, tags, rules["audit_tag_key"])
    return json.dumps({"status": "applied", **result})


def apply_tags_to_resource_group(
    subscription_id: Annotated[str, Field(description="Azure subscription ID")],
    resource_group: Annotated[str, Field(description="Resource group name whose resources should all be tagged")],
    tags: Annotated[dict[str, str], Field(description="Tag key/value pairs to apply to every resource in the group")],
) -> str:
    """Applies the given tags to EVERY resource inside a resource group, but NEVER overwrites
    a tag key that already has a non-empty value on a given resource (reported per-resource
    as tags_skipped_already_set). Always also stamps the audit tag configured in rules.json
    on any actual write. This is a bulk, higher-impact action — only call it after the
    operator has explicitly confirmed both the resource group and the exact tag values in
    conversation. Returns which resources succeeded and which failed."""
    rules = compliance_lib.load_rules()
    audit_tag_key = rules["audit_tag_key"]
    resources = compliance_lib.fetch_resources(_credential, [subscription_id], resource_group)

    succeeded, failed = [], []
    for resource in resources:
        resource_id = resource["id"]
        try:
            result = _apply_tags_to_one(
                resource_id, resource.get("name", ""), tags, audit_tag_key, current_tags=resource.get("tags")
            )
            succeeded.append(result)
        except Exception as exc:
            failed.append({"resource_id": resource_id, "error": str(exc)})

    return json.dumps({
        "resource_group": resource_group,
        "total_resources": len(resources),
        "succeeded_count": len(succeeded),
        "failed_count": len(failed),
        "succeeded": succeeded,
        "failed": failed,
    })
