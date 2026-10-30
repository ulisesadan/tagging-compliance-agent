"""
Interactive Q&A review of remediation/out/proposals.csv. For each non-compliant
resource, shows the agent's proposed tag fix (value + confidence + rationale)
and asks you to approve, edit, or reject it. Writes decisions.csv — still no
ARM write calls here; run apply_tags.py afterward to actually apply approvals.

Usage:
    python review_cli.py --proposals out/proposals.csv --output out/decisions.csv
"""
import argparse
import csv
from collections import defaultdict
from pathlib import Path

DEFAULT_PROPOSALS = Path(__file__).parent / "out" / "proposals.csv"
DEFAULT_OUTPUT = Path(__file__).parent / "out" / "decisions.csv"


def prompt_decision(tag: str, current_value: str, proposed_value: str, confidence: str, rationale: str) -> tuple[str, str]:
    print(f"\n  Tag: {tag}")
    print(f"    Current value : {current_value or '(missing)'}")
    print(f"    Proposed value: {proposed_value or '(agent could not propose one)'}  [confidence: {confidence}]")
    print(f"    Rationale     : {rationale}")

    while True:
        choice = input("  Approve [y] / Edit [e] / Reject [n] / Skip [s]: ").strip().lower()
        if choice in ("y", "yes"):
            return "approved", proposed_value
        if choice in ("e", "edit"):
            new_value = input("    Enter the value to use instead: ").strip()
            return "approved", new_value
        if choice in ("n", "no"):
            return "rejected", ""
        if choice in ("s", "skip", ""):
            return "skipped", ""
        print("    Please enter y, e, n, or s.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive review of proposed tag fixes")
    parser.add_argument("--proposals", default=str(DEFAULT_PROPOSALS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    with open(args.proposals, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    by_resource: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_resource[row["resource_id"]].append(row)

    decisions = []
    for resource_id, tag_rows in by_resource.items():
        first = tag_rows[0]
        print(f"\n{'=' * 70}\nResource: {first['resource_name']} ({first['resource_type']})")
        print(f"Resource Group: {first['resourceGroup']}  Subscription: {first['subscriptionId']}")

        for row in tag_rows:
            decision, final_value = prompt_decision(
                row["tag"], row["current_value"], row["proposed_value"], row["confidence"], row["rationale"]
            )
            decisions.append({
                "subscriptionId": row["subscriptionId"],
                "resourceGroup": row["resourceGroup"],
                "resource_id": resource_id,
                "resource_name": first["resource_name"],
                "tag": row["tag"],
                "decision": decision,
                "final_value": final_value,
            })

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=[
            "subscriptionId", "resourceGroup", "resource_id", "resource_name", "tag", "decision", "final_value",
        ])
        writer.writeheader()
        writer.writerows(decisions)

    approved = sum(1 for d in decisions if d["decision"] == "approved")
    print(f"\n{approved} tag change(s) approved out of {len(decisions)} reviewed.")
    print(f"Decisions written to {output_path.resolve()}")
    print("Run apply_tags.py --decisions <this file> --apply to write the approved changes to Azure.")


if __name__ == "__main__":
    main()
