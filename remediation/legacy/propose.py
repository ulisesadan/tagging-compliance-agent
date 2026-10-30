"""
Proposes tag fixes for every non-compliant resource in a compliance_report.py
details.csv, using sibling resources in the same resource group as few-shot
grounding. Writes proposals.csv for human review (review_cli.py) — this script
makes no ARM write calls.

Usage:
    python propose.py --details-csv ../report/out/details.csv --output out/proposals.csv

Env vars (or pass --project-endpoint / --model):
    PROJECT_ENDPOINT      e.g. https://<resource>.services.ai.azure.com/api/projects/<project>
    MODEL_DEPLOYMENT_NAME e.g. gpt-4.1-mini
"""
import argparse
import csv
import os
from collections import defaultdict
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

import agent_lib

DEFAULT_DETAILS_CSV = Path(__file__).parent.parent / "report" / "out" / "details.csv"
DEFAULT_OUTPUT = Path(__file__).parent / "out" / "proposals.csv"
MAX_SIBLING_EXAMPLES = 3


def build_sibling_examples(rows: list[dict[str, str]], required_tags: list[str]) -> dict[tuple[str, str], list[dict[str, str]]]:
    """Groups compliant resources' tag values by (subscriptionId, resourceGroup)."""
    examples: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row["compliant"] != "True":
            continue
        key = (row["subscriptionId"], row["resourceGroup"])
        if len(examples[key]) >= MAX_SIBLING_EXAMPLES:
            continue
        examples[key].append({tag: row[f"{tag}_value"] for tag in required_tags if row[f"{tag}_value"]})
    return examples


def main() -> None:
    parser = argparse.ArgumentParser(description="Propose tag fixes for non-compliant resources (no writes)")
    parser.add_argument("--details-csv", default=str(DEFAULT_DETAILS_CSV))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--project-endpoint", default=os.getenv("PROJECT_ENDPOINT"))
    parser.add_argument("--model", default=os.getenv("MODEL_DEPLOYMENT_NAME"))
    args = parser.parse_args()

    if not args.project_endpoint or not args.model:
        raise SystemExit("Set PROJECT_ENDPOINT and MODEL_DEPLOYMENT_NAME (env vars or --project-endpoint/--model).")

    rules = agent_lib.load_rules()
    required_tags = rules["required_tags"]

    with open(args.details_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    sibling_examples = build_sibling_examples(rows, required_tags)
    non_compliant_rows = [r for r in rows if r["compliant"] != "True"]
    print(f"Found {len(non_compliant_rows)} non-compliant resources out of {len(rows)} scored.")

    project_client = AIProjectClient(endpoint=args.project_endpoint, credential=DefaultAzureCredential())
    agent = agent_lib.get_or_create_agent(project_client, args.model)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as out_f:
        writer = csv.writer(out_f)
        writer.writerow([
            "subscriptionId", "resourceGroup", "resource_id", "resource_name", "resource_type",
            "tag", "current_status", "current_value", "proposed_value", "confidence", "rationale",
        ])

        for row in non_compliant_rows:
            non_compliant_tags = [
                {"tag": tag, "status": row[f"{tag}_status"], "current_value": row[f"{tag}_value"]}
                for tag in required_tags
                if row[f"{tag}_status"] != "compliant"
            ]
            if not non_compliant_tags:
                continue

            resource = {"id": row["id"], "name": row["name"], "type": row["type"], "resourceGroup": row["resourceGroup"]}
            key = (row["subscriptionId"], row["resourceGroup"])

            try:
                proposals = agent_lib.propose_tags_for_resource(
                    project_client, agent, resource, non_compliant_tags, sibling_examples.get(key, [])
                )
            except Exception as exc:
                print(f"  [error] {row['name']}: {exc}")
                continue

            for proposal in proposals:
                tag = proposal.get("tag", "")
                current = next((t for t in non_compliant_tags if t["tag"] == tag), {})
                writer.writerow([
                    row["subscriptionId"], row["resourceGroup"], row["id"], row["name"], row["type"],
                    tag, current.get("status", ""), current.get("current_value", ""),
                    proposal.get("proposed_value") or "", proposal.get("confidence", ""), proposal.get("rationale", ""),
                ])
            print(f"  [ok] {row['name']}: {len(proposals)} proposal(s)")

    print(f"Proposals written to {output_path.resolve()}")


if __name__ == "__main__":
    main()
