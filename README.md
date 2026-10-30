# Tagging Compliance Agent

## Deployment guides

Step-by-step runbooks for the existing [Foundry hosted agent](tagging-compliance-agent/src/agent-framework-agent-with-local-tools-responses/main.py):

| Approach | Guide |
|---|---|
| Portal-based | [Azure portal + Foundry portal, using embedded Cloud Shell for hosted-agent deployment](docs/deployment-portal.md) |
| CLI-based | [Azure CLI (`az`) provisioning, container build, deployment, and verification](docs/deployment-cli.md) |

Both guides include permissions, a Reader-first rollout, an optional scoped tag-write test, acceptance checks, troubleshooting, and cleanup. They document the current additive-only write behavior and governance-rule discrepancies; they do not add scheduling or notifications. The procedures require live acceptance testing before production use.

A resource-group-scoped CLI pilot was live-verified on October 28, 2026, including hosted execution, reporting, a single-resource write, same-value skip/recovery, and telemetry. See the [tested configuration, corrections, and limitations](docs/deployment-cli.md#live-verification); the portal UI workflow was not click-tested.

The [Azure architecture diagram and resource inventory](docs/agent-deploy-test-architecture.md) describe that verified pilot, including identities, scoped permissions, build/inference flows, and telemetry. The pilot was removed after testing; the diagram is historical.

## Objective
An LLM-based agent that keeps Azure subscriptions compliant with the org's tagging naming convention. It:
1. **Reports** which resources/resource groups are missing required tags, and which have tags that don't match the naming convention (percentage of non-compliant resources per subscription).
2. **Remediates** automatically — applies/corrects tags using rules read from the prompt instructions file (naming convention), then notifies the owner of what was changed.

## Architecture (implemented)
- **Reasoning + orchestration layer**: [Microsoft Agent Framework](https://learn.microsoft.com/agent-framework/) (`agent-framework-core` + `agent-framework-foundry`) — the official successor to Semantic Kernel/AutoGen, running against a Microsoft Foundry model deployment. Chosen over the raw `azure-ai-projects` persistent-agent SDK (see `remediation/legacy/`) so the agent can support multi-turn conversations and more complex orchestration going forward.
- **Execution layer (tools)**: three Python functions in `remediation/tools.py`, exposed to the agent as function tools:
  - `get_tag_report` — compliance summary for a subscription or resource group.
  - `list_non_compliant` — detail + sibling tag examples, for grounded conversational triage.
  - `apply_resource_tags` — ARM Tags API write (`Merge` patch). The LLM decides *when* to call it based on conversation; the tool code itself holds the Azure RBAC (least-privilege separation between "the LLM that decides" and "the code that acts").
- **Audit trail**: every call to `apply_resource_tags` automatically stamps an extra tag — key name configured in `report/rules.json` → `audit_tag_key` (currently `Tagged_By_Agent`), value `"<agent-name>@<UTC timestamp>"` — on top of whatever tags were requested, and appends a row to `remediation/out/agent_applied_log.csv`. This happens in the tool's code, not the prompt, so it can't be skipped by the model.
- **Notification**: Teams webhook / email — not yet implemented; natural next step once the chat flow has been validated against a real subscription.

## Inputs
- `prompt-instructions/tagging-naming-convention.md` — the source of truth for required tag keys, allowed values/format, and per-resource-type rules (seeded from a real tag export; pending full governance sign-off — see "Open items" in that file).
- `report/rules.json` — machine-readable version of the same rules (plus `audit_tag_key`), consumed by both the standalone report and the agent's tools.

## First implementation: read-only compliance report
`report/compliance_report.py` (CLI) and `report/compliance_lib.py` (shared logic, also used by the agent's tools) query Azure Resource Graph (Reader-only, no writes) and classify every resource's required tags as `missing` / `placeholder` (e.g. `"TBD"`) / `invalid_format` / `compliant`, then write `summary.csv` (per-tag % non-compliant) and `details.csv` (per-resource breakdown) to an output folder.

```powershell
cd report
pip install -r requirements.txt
az login   # or rely on managed identity / env vars via DefaultAzureCredential
python compliance_report.py --subscriptions <sub-id>[,<sub-id>...] --output-dir out
# or: python compliance_report.py --all-subscriptions --output-dir out
```

Required RBAC to run it: **Reader** (or `Microsoft.ResourceGraph/resources/read` + `Microsoft.Resources/subscriptions/read`) at the subscription(s)/management group scope being scanned — matches the "report-only mode" recommendation below.

> Note: on this machine, installing these requirements needs the **x64** Python interpreter, not the default ARM64 one — `azure-identity`'s `cryptography` dependency has no prebuilt `win_arm64` wheel. Create the venv with `& "$env:LOCALAPPDATA\Programs\Python\Python311-x64\python.exe" -m venv .venv` and use `.\.venv\Scripts\python.exe` to run the scripts.

## Report contents (first deliverable)
- % of resources missing each required tag, and overall % non-compliant, per subscription.
- List of resources with missing tags.
- List of resources with tags present but not matching the naming convention (incorrect key casing, invalid value, wrong format, etc.).

## Remediation agent (implemented — Agent Framework, multi-turn)
Replaces the earlier batch propose/review/apply CSV flow (preserved for reference in `remediation/legacy/`). The new agent supports three operator-facing actions in one conversation:
1. **Report** — "give me the tag compliance report for subscription X" (optionally scoped to a resource group) → agent calls `get_tag_report`.
2. **Multi-turn triage help** — "help me fix tags in resource group Y" → agent calls `list_non_compliant`, proposes values grounded in the naming convention + compliant sibling resources, and asks clarifying questions when it can't confidently infer a value.
3. **Tagging on request** — once the operator confirms an exact resource + tag values in conversation, the agent calls `apply_resource_tags`, which writes the tags **and automatically adds the `Tagged_By_Agent` audit tag** to every resource it touches.

### Running the agent
```powershell
cd remediation
# On this machine: use the x64 Python venv (ARM64 lacks prebuilt wheels for some deps).
& "$env:LOCALAPPDATA\Programs\Python\Python311-x64\python.exe" -m venv $env:LOCALAPPDATA\venvs\tagging-remediation
& "$env:LOCALAPPDATA\venvs\tagging-remediation\Scripts\python.exe" -m pip install -r requirements.txt

$env:PROJECT_ENDPOINT = "https://<resource>.services.ai.azure.com/api/projects/<project>"
$env:MODEL_DEPLOYMENT_NAME = "<your-model-deployment-name>"

& "$env:LOCALAPPDATA\venvs\tagging-remediation\Scripts\python.exe" chat.py
```

Note: `agent-framework` (the meta-package) pulls in every optional provider integration (AWS Bedrock, Anthropic, Cosmos DB, Azure Functions, etc.) — use the scoped `agent-framework-core` + `agent-framework-foundry` packages instead, as `requirements.txt` already does.

Validated so far: imports resolve cleanly (`agent_framework.foundry.FoundryChatClient`, `tools.py`, `chat.py`) in the venv above. **Not yet validated**: an actual live conversation against the Foundry project/model, or a real `apply_resource_tags` write. Try a report query first, then a tag-fix conversation on one test resource before trusting it broadly.

## Azure RBAC permissions required

| Identity | Role | Scope | Why |
|---|---|---|---|
| Tool/Function managed identity | **Reader** (or just `Microsoft.ResourceGraph/resources/read` + `Microsoft.Resources/subscriptions/resourceGroups/read`) | Subscription(s) or Management Group (if multi-sub) | Enumerate resources, resource groups, and their current tags via Resource Graph for the report. |
| Tool/Function managed identity | **Tag Contributor** (built-in role, `Microsoft.Resources/tags/*`) | Same scope as above | Lets the agent create/update/delete tags on any resource **without** granting write access to the resource configuration itself — this is the least-privilege role for this exact use case (do **not** use Contributor/Owner). Only needed to run `chat.py` with `apply_resource_tags` enabled; `get_tag_report`/`list_non_compliant` never write. |
| Whoever runs `chat.py` | **Foundry User** (or equivalent Foundry data-plane role) | Foundry project | Needed to create/invoke the agent via `agent-framework-foundry`. |
| Notification sender | Scoped Graph `Mail.Send` app permission, or just the Logic App's own connector credential | N/A | Only if notifying via email/Teams through Graph rather than a Logic App connector. |

Notes:
- Assign **Tag Contributor** and **Reader** at **Management Group** scope only if the agent must operate across multiple subscriptions; otherwise scope to the specific subscription(s) or resource groups in play, per least privilege.
- If some resources are locked down by Azure Policy "deny" effects on tags, the policy may block the agent's writes — check for conflicting policies before enabling auto-remediation broadly.
- Consider starting in **report-only mode** (Reader only) for a few cycles before granting Tag Contributor, to validate the agent's proposed changes are correct.

## Open questions / assumptions
- Confirmed: "PRM instructions" = **Prompt Instructions** (a file defining the naming convention) — `prompt-instructions/tagging-naming-convention.md` now seeded from a real tag export sample, with `Application_Name` as the priority tag for v1. Still needs governance team confirmation on allow-lists, resource-group naming scheme, and the open items listed at the end of that file.
- Assumed single subscription scope for v1; multi-subscription/management-group support can be added once scope is confirmed.
- Notification channel (Teams vs. email vs. both) not yet specified.
- Schedule cadence (daily/weekly) not yet specified.
