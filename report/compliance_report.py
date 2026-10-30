"""
Tagging compliance report (read-only, Reader-scope).

Queries Azure Resource Graph for all resources across one or more subscriptions,
classifies each resource against the rules in rules.json (missing / placeholder /
invalid-format / compliant per required tag), and writes a summary + per-resource
detail CSV. No write permissions are used or required.

Usage:
    python compliance_report.py --subscriptions <sub-id>[,<sub-id>...] [--output-dir out]
    python compliance_report.py --all-subscriptions [--output-dir out]

Auth: uses DefaultAzureCredential (az login, environment vars, or managed identity).
Required RBAC: Reader (or Microsoft.ResourceGraph/resources/read +
Microsoft.Resources/subscriptions/read) at the scope(s) being queried.
"""
import argparse
import csv
import sys
from pathlib import Path
from typing import Any

from azure.identity import DefaultAzureCredential

import compliance_lib


def write_details_csv(path: Path, classified: list[dict[str, Any]], required_tags: list[str]) -> None:
    fieldnames = ["id", "name", "type", "resourceGroup", "subscriptionId", "compliant"]
    for tag in required_tags:
        fieldnames.append(f"{tag}_status")
        fieldnames.append(f"{tag}_value")

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for item in classified:
            row = {
                "id": item["id"],
                "name": item["name"],
                "type": item["type"],
                "resourceGroup": item["resourceGroup"],
                "subscriptionId": item["subscriptionId"],
                "compliant": item["compliant"],
            }
            for tag in required_tags:
                row[f"{tag}_status"] = item["tag_status"][tag]
                row[f"{tag}_value"] = item["tag_values"][tag]
            writer.writerow(row)


def write_summary_csv(path: Path, classified: list[dict[str, Any]], required_tags: list[str]) -> None:
    total = len(classified)
    non_compliant = sum(1 for item in classified if not item["compliant"])

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value"])
        writer.writerow(["total_resources_scored", total])
        writer.writerow(["non_compliant_resources", non_compliant])
        writer.writerow(["non_compliant_percent", f"{(non_compliant / total * 100):.1f}" if total else "0.0"])
        writer.writerow([])
        writer.writerow(["tag", "missing_pct", "placeholder_pct", "invalid_format_pct", "compliant_pct"])
        for tag in required_tags:
            counts = {"missing": 0, "placeholder": 0, "invalid_format": 0, "compliant": 0}
            for item in classified:
                counts[item["tag_status"][tag]] += 1
            writer.writerow([
                tag,
                f"{(counts['missing'] / total * 100):.1f}" if total else "0.0",
                f"{(counts['placeholder'] / total * 100):.1f}" if total else "0.0",
                f"{(counts['invalid_format'] / total * 100):.1f}" if total else "0.0",
                f"{(counts['compliant'] / total * 100):.1f}" if total else "0.0",
            ])


def main() -> None:
    parser = argparse.ArgumentParser(description="Azure tag compliance report (read-only)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--subscriptions", help="Comma-separated subscription IDs to scan")
    group.add_argument("--all-subscriptions", action="store_true", help="Scan every subscription the caller can read")
    parser.add_argument("--output-dir", default="out", help="Directory to write summary.csv and details.csv")
    args = parser.parse_args()

    rules = compliance_lib.load_rules()
    credential = DefaultAzureCredential()

    if args.all_subscriptions:
        subscription_ids = compliance_lib.list_all_subscription_ids(credential)
    else:
        subscription_ids = [s.strip() for s in args.subscriptions.split(",") if s.strip()]

    if not subscription_ids:
        print("No subscriptions resolved to scan.", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {len(subscription_ids)} subscription(s)...")
    classified, excluded = compliance_lib.classify_scope(credential, subscription_ids)
    print(f"Fetched {len(classified) + len(excluded)} resources.")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_details_csv(output_dir / "details.csv", classified, rules["required_tags"])
    write_summary_csv(output_dir / "summary.csv", classified, rules["required_tags"])

    if excluded:
        with open(output_dir / "excluded.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "name", "resourceGroup", "reason"])
            for r in excluded:
                writer.writerow([r.get("id"), r.get("name"), r.get("resourceGroup"), "excluded_resource_group_pattern"])

    non_compliant = sum(1 for item in classified if not item["compliant"])
    total = len(classified)
    pct = (non_compliant / total * 100) if total else 0.0
    print(f"Scored {total} resources ({len(excluded)} excluded). Non-compliant: {non_compliant} ({pct:.1f}%).")
    print(f"Reports written to {output_dir.resolve()}")


if __name__ == "__main__":
    main()
