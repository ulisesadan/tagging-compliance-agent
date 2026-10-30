"""
Applies approved tag fixes to Azure resources via the ARM Tags API (Merge
patch). Defaults to --dry-run (prints what would change, writes no tags) —
pass --apply to actually write. Requires Tag Contributor on the target
resource(s)/scope.

Two input modes:
  --decisions out/decisions.csv   Apply only rows marked "approved" by review_cli.py (recommended).
  --proposals out/proposals.csv --min-confidence high
                                   Batch mode: auto-select proposals at/above the given
                                   confidence level, skipping anything with no proposed value.

Usage:
    python apply_tags.py --decisions out/decisions.csv --apply
    python apply_tags.py --proposals out/proposals.csv --min-confidence high --apply
"""
import argparse
import csv
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.mgmt.resource.resources import ResourceManagementClient
from azure.mgmt.resource.resources.models import Tags, TagsPatchResource

CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
DEFAULT_LOG = Path(__file__).parent / "out" / "applied_log.csv"


def load_from_decisions(path: str) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if r["decision"] == "approved" and r["final_value"]]


def load_from_proposals(path: str, min_confidence: str) -> list[dict[str, str]]:
    threshold = CONFIDENCE_RANK.get(min_confidence, 2)
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    selected = []
    for r in rows:
        if not r["proposed_value"]:
            continue
        if CONFIDENCE_RANK.get(r["confidence"], -1) < threshold:
            continue
        r = dict(r)
        r["final_value"] = r["proposed_value"]
        selected.append(r)
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply approved tag fixes via ARM Tags API (Merge)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--decisions", help="decisions.csv from review_cli.py (only 'approved' rows are applied)")
    group.add_argument("--proposals", help="proposals.csv for automated batch mode")
    parser.add_argument("--min-confidence", choices=["low", "medium", "high"], default="high",
                         help="Only used with --proposals")
    parser.add_argument("--apply", action="store_true", help="Actually write tags. Omit for a dry run.")
    parser.add_argument("--output-log", default=str(DEFAULT_LOG))
    args = parser.parse_args()

    changes = load_from_decisions(args.decisions) if args.decisions else load_from_proposals(args.proposals, args.min_confidence)
    if not changes:
        print("Nothing to apply.")
        return

    by_resource: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in changes:
        by_resource[row["resource_id"]].append(row)

    print(f"{'DRY RUN — ' if not args.apply else ''}Applying tag changes to {len(by_resource)} resource(s)...")

    clients: dict[str, ResourceManagementClient] = {}
    credential = DefaultAzureCredential() if args.apply else None

    log_path = Path(args.output_log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_rows = []

    for resource_id, rows in by_resource.items():
        patch = {r["tag"]: r["final_value"] for r in rows}
        subscription_id = rows[0]["subscriptionId"]
        resource_name = rows[0].get("resource_name", "")
        print(f"  {resource_name or resource_id}: {patch}")

        status = "dry_run"
        error = ""
        if args.apply:
            try:
                client = clients.setdefault(subscription_id, ResourceManagementClient(credential, subscription_id))
                poller = client.tags.begin_update_at_scope(
                    scope=resource_id,
                    parameters=TagsPatchResource(operation="Merge", properties=Tags(tags=patch)),
                )
                poller.result()
                status = "applied"
            except Exception as exc:
                status = "failed"
                error = str(exc)
                print(f"    [error] {error}")

        for row in rows:
            log_rows.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "resource_id": resource_id,
                "resource_name": resource_name,
                "tag": row["tag"],
                "new_value": row["final_value"],
                "status": status,
                "error": error,
            })

    with open(log_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "resource_id", "resource_name", "tag", "new_value", "status", "error"])
        writer.writeheader()
        writer.writerows(log_rows)

    print(f"Log written to {log_path.resolve()}")
    if not args.apply:
        print("This was a dry run — no tags were written. Re-run with --apply to write them.")


if __name__ == "__main__":
    main()
