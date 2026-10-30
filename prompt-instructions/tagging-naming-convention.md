# Tagging Naming Convention (source of truth for the agent)

> Status: **derived from a raw tag export sample** (not an official governance doc yet). Treat the "Allowed values / format" columns as *inferred hypotheses* to validate with Bimbo's CCoE/governance team, not as confirmed rules. The priority tag for v1 of the agent is **`Application_Name`**.

## Required tags (apply to all resources/resource groups)
| Tag key | Required? | Observed format (from sample) | Example values |
|---|---|---|---|
| `Application_Name` | **Yes — priority tag for v1** | Free-text business application name, Title Case, words separated by spaces, may include `-` | `GBConnected QSR - Microsoft`, `Perfect Order BI DnA`, `DWH DnA Iberia`, `BBU GB Connected` |
| `Entity` | No | Short uppercase business-unit code (2–4 letters) | `QSR`, `BI`, `CB`, `BBU` |
| `Organization` | Yes | Short uppercase org code | `BQ`, `EMEA`, `CORP`, `BBU` |
| `CCoE_ID_Number` | Yes | `YY-NNNN` (year-sequence); **one sample shows a letter variant** `21-D0030` — confirm with governance whether the `D` is a valid segment or a data-entry inconsistency | `23-0345`, `22-0178`, `21-D0030` |
| `CHG_Ticket` | No | `CHGNNNNNNN` (ServiceNow change ticket) or `TBD` if not yet linked | `CHG0058121`, `CHG0028903` |
| `Resource_Groups` | Yes | Should equal the actual Azure resource group name the resource lives in | see "Known drift" below — **this tag frequently does NOT match the real resource group** |
| `Resource_Description` | No | Free text, or `TBD` placeholder | `GBCONNECTED_DATA_EXPLORER01_200`, `TBD` |
| `Launch_Date` | No | `D/M/YYYY` or `DD/MM/YYYY`, or `TBD` | `27/06/2024`, `5/2/2022`, `TBD` |

**Compliance rule candidate**: a tag value of literal `"TBD"` should be treated as **non-compliant / incomplete**, not as "present." Several resources (e.g. the OpenAI/AML endpoint `testdna-aistudio-3520`) still have `Application_Name: "TBD"`.

## Per-resource-type overrides (observed)
- **Azure Databricks workspaces/clusters/jobs**: in addition to the required tags above, carry Databricks-injected operational tags that are **not** part of the governance naming convention and should be excluded from compliance scoring: `Vendor` (`Databricks`), `ClusterId`, `ClusterName`, `JobId`, `RunName`, `DatabricksEnvironment`, `databricks-instance-name`, `management_service`. They also carry extra business tags not seen elsewhere: `Application_Owner`, `Application_Technical_Contact`, `Distribution_List`, `Creator`, `Full_Project_Name`, `project`.
- **Azure Machine Learning computes/endpoints**: carry Microsoft/platform system tags that should also be excluded from compliance scoring (they are auto-injected, not user-set): `ms.inv.v0.*` (e.g. `ms.inv.v0.security.ownerrole`, `ms.inv.v0.backedby.tenantid`, `ms.inv.v0.backedby.origin.*`), `SkipASMAzSecPackAutoConfig`, `platformsettings.host_environment.service.platform_optedin_for_rootcerts`, `AMLResourceType`, `ComputeType`, `AzureMLDeployment`, `AzureMLEndpoint`.

## Naming format rules
- `Application_Name` is Title Case free text (not a short code) — classification logic should check for *presence of a real value*, not an exact enum, but should flag `TBD`/blank as non-compliant.
- `Entity` and `Organization` appear to be short, all-uppercase codes — candidate rule: must match `^[A-Z]{2,5}$` plus a confirmed allow-list once governance shares the full code list.
- `CHG_Ticket` candidate pattern: `^CHG\d{7}$` or literal `TBD`.

## Known data-quality issues found in the sample (good first targets for the compliance report)
1. **`Application_Name` = "TBD"** on at least one resource (`testdna-aistudio-3520` in `rg-openai_env01`) — incomplete tagging.
2. **`Resource_Groups` tag doesn't match the actual resource group** in multiple cases:
   - Resource `cbperoramlcd02`: tag says `rg-aidna-bi-uks-d-pri`, actual resource group is `rg-dv-aidnaiberia-corp-suk`.
   - Resource `bbugbcbuadtcd01`: tag says `rg-gbconected-bbu-use2-d-pri`, actual resource group is `RG-GBCONECTEDBBU-DEV-EUS2` (also a different casing/naming scheme entirely — lowercase-hyphenated vs uppercase-segmented).
3. **Two competing resource-group naming schemes** appear to coexist: `rg-<app>-<entity>-<region>-<env>-<tier>` (lowercase, e.g. `rg-GBConnectedQSR-qsr-use2-d-pri`) and `RG-<APP>-<ENV>-<REGION>` (uppercase, e.g. `RG-GBCONECTEDBBU-DEV-EUS2`). Needs governance clarification on which is current/authoritative.
4. **Databricks-managed resource groups** (`DATABRICKS-RG-*`) are auto-created by the platform, not user-named — likely candidates for the **Exceptions** list below since their name can't be remediated by the agent.

## Exceptions (candidates, pending governance confirmation)
- Azure Databricks platform-managed resource groups (`DATABRICKS-RG-*`) — resource group name itself is not user-controlled.
- Ephemeral/job-scoped resources (Databricks cluster instances spun up per job run) — may not be worth tagging individually since they inherit from the workspace/job.

## Open items for governance team
- Confirm the authoritative resource-group naming convention (which of the two observed schemes is current).
- Confirm whether `CCoE_ID_Number` legitimately allows a letter segment (`21-D0030`) or if that's a data-entry error.
- Confirm the full allow-lists for `Entity` and `Organization` codes.
- Confirm whether `Resource_Groups` tag is still required now that Azure exposes the real resource group natively (it appears redundant and is a frequent source of drift).
