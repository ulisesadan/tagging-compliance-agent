"""
Shared Resource Graph query + tag-classification logic, used by both the
standalone CLI report (compliance_report.py) and the Agent Framework agent's
tools (../remediation/tools.py). Keeping this in one place avoids the two
callers drifting out of sync on what "compliant" means.
"""
import json
import re
from pathlib import Path
from typing import Any

from azure.identity import DefaultAzureCredential
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

RULES_PATH = Path(__file__).parent / "rules.json"
RESOURCE_GRAPH_PAGE_SIZE = 1000


def load_rules() -> dict[str, Any]:
    with open(RULES_PATH, encoding="utf-8") as f:
        return json.load(f)


def list_all_subscription_ids(credential: DefaultAzureCredential) -> list[str]:
    from azure.mgmt.subscription import SubscriptionClient

    client = SubscriptionClient(credential)
    return [s.subscription_id for s in client.subscriptions.list() if s.subscription_id]


def fetch_resources(
    credential: DefaultAzureCredential,
    subscription_ids: list[str],
    resource_group: str | None = None,
) -> list[dict[str, Any]]:
    """Queries Resource Graph for resources + tags, optionally scoped to one resource group."""
    client = ResourceGraphClient(credential)
    resources: list[dict[str, Any]] = []
    skip_token: str | None = None

    query = "Resources"
    if resource_group:
        query += f"\n| where resourceGroup =~ '{resource_group}'"
    query += "\n| project id, name, type, resourceGroup, subscriptionId, tags"

    while True:
        options = QueryRequestOptions(
            result_format="objectArray",
            top=RESOURCE_GRAPH_PAGE_SIZE,
            skip_token=skip_token,
        )
        request = QueryRequest(subscriptions=subscription_ids, query=query, options=options)
        response = client.resources(request)
        resources.extend(response.data or [])

        skip_token = response.skip_token
        if not skip_token:
            break

    return resources


def is_excluded_resource_group(resource_group: str, rules: dict[str, Any]) -> bool:
    patterns = rules.get("excluded_resource_group_patterns", [])
    return any(re.search(p, resource_group or "", re.IGNORECASE) for p in patterns)


def classify_tag(tag_key: str, tags: dict[str, str], rules: dict[str, Any]) -> str:
    """Returns one of: missing, placeholder, invalid_format, compliant."""
    value = tags.get(tag_key)
    if value is None or str(value).strip() == "":
        return "missing"

    value = str(value).strip()
    placeholder_values = {p.lower() for p in rules.get("placeholder_values", [])}
    if value.lower() in placeholder_values:
        return "placeholder"

    pattern = rules.get("tag_format_regex", {}).get(tag_key)
    if pattern and not re.match(pattern, value):
        return "invalid_format"

    return "compliant"


def classify_resource(resource: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    tags = resource.get("tags") or {}
    required_tags = rules["required_tags"]
    tag_status = {tag: classify_tag(tag, tags, rules) for tag in required_tags}
    is_compliant = all(status == "compliant" for status in tag_status.values())

    return {
        "id": resource.get("id"),
        "name": resource.get("name"),
        "type": resource.get("type"),
        "resourceGroup": resource.get("resourceGroup"),
        "subscriptionId": resource.get("subscriptionId"),
        "compliant": is_compliant,
        "tag_status": tag_status,
        "tag_values": {tag: tags.get(tag, "") for tag in required_tags},
    }


def classify_scope(
    credential: DefaultAzureCredential,
    subscription_ids: list[str],
    resource_group: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetches + classifies resources in scope. Returns (in_scope_classified, excluded_raw)."""
    rules = load_rules()
    resources = fetch_resources(credential, subscription_ids, resource_group)

    in_scope, excluded = [], []
    for resource in resources:
        if is_excluded_resource_group(resource.get("resourceGroup", ""), rules):
            excluded.append(resource)
        else:
            in_scope.append(resource)

    return [classify_resource(r, rules) for r in in_scope], excluded
