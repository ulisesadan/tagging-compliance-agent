# Tagging Compliance Agent - Azure CLI deployment

**Audience:** Azure platform administrators and the agent's implementation team.  
**Reference date:** October 28, 2026.  
**Outcome:** The existing Python agent runs in Microsoft Foundry, reports Azure resource-tag compliance, and can optionally add tags in an explicitly authorized pilot resource group.

All Azure provisioning and deployment operations below use **Azure CLI (`az`)**, including `az rest` for Foundry APIs. PowerShell handles variables, JSON files, and polling. Neither `azd`, a local Docker installation, nor a local Python environment is required.

The CLI pilot was **live-verified against Azure on October 28, 2026**, with the corrections discovered during that run incorporated below. See [live verification](#live-verification) for the tested configuration and limitations. Complete your own acceptance and governance checks before enabling production writes.

See the [Azure architecture diagram](agent-deploy-test-architecture.md) for the verified pilot's resource boundaries, identity/RBAC relationships, and data flows. It records the historical deployment, which was removed after testing.

## Live verification

The tested profile used one dedicated resource group in East US 2, PowerShell 7.6.9, Azure CLI 2.91.0, and `gpt-5.4-mini` version `2026-03-17`, GlobalStandard capacity 25 (25,000 tokens/minute).

| Live check | Verified result |
|---|---|
| Container and hosting | Frozen-lock Linux AMD64 build succeeded; hosted version 1 became active and its endpoint was pinned to that version |
| Runtime permissions | Reader and Tag Contributor were confined to the dedicated test resource group; no runtime Owner/Contributor or subscription-wide governance assignment |
| Reporting | Both reporting tools executed; resource IDs, counts, and percentages matched a separate Resource Graph query |
| Approved write | ARM and Activity Log confirmed `Application_Name=Tagging Agent Pilot` and the generated audit marker on the disposable fixture |
| Preservation and recovery | Existing description remained unchanged; a same-value retry returned `tags_skipped_already_set` without rewriting the audit marker; other baseline resources' tags were unchanged |
| Post-write report | Seven resources scored, zero excluded, seven still overall non-compliant; the fixture's Application_Name was compliant, producing 14.3% group compliance for that tag |
| Telemetry | The connected Application Insights component contained traces, dependencies, requests, and exception records |

Azure automatically added an Application Insights smart-detector alert rule during the pilot, so inventory grew from six to seven resources. Compare percentages to the current inventory, not a hard-coded resource count.

The run exposed and corrected model lifecycle/quota selection, connection payload submission, Dockerfile path resolution, unnecessary directory lookups, and response-status/rate-limit handling. An early low-capacity write response failed **after** its tool had applied the tags; authoritative state was checked before the same-value recovery. A later report completed after the rate window refreshed.

This is not production certification. Separate deployment/target groups or subscriptions, subscription-wide Reader, other models/regions, bulk tagging, replacing an existing value with a different value, and portal/Cloud Shell UI actions were not live-tested. Governance-rule reconciliation remains required.

### October 30, 2026: read-only CLI retest

A fresh deployment in subscription `de40fdb3-141c-427b-bea2-3519781af333` passed the read-only CLI path. These resources were **left running** after verification and continue to incur charges; the earlier October 28 environment described above was removed.

| Item | Retest evidence |
|---|---|
| Scope | `rg-tagging-cli-test-73a0ae81`, East US 2; deployment and fixture share this dedicated group |
| Foundry | Account `foundry-tagging-73a0ae81`, project `tagging-governance`, agent `tagging-compliance-agent`, active version `1`, endpoint pinned to version `1` at 100% |
| Model | `tagging-model`: `gpt-5.4-mini` version `2026-03-17`, GlobalStandard capacity 25; returned limits 25,000 tokens/minute and 25 requests/minute |
| Build | Registry `acrtagging73a0ae81`, ACR run `ch1`, Linux AMD64, image tag `release-73a0ae81`; digest `sha256:04b4f26b7799b2179efaad9ffc037b799e8a0d6aa0dc4126581b397cfee44f40` |
| Runtime access | Principal `8571e2e6-c770-4137-9683-58287e9afeee`: Reader on the dedicated group only; no Tag Contributor, Contributor, or Owner assignment |
| Reporting | Both tools returned six resources, zero exclusions, six non-compliant resources, 100% overall non-compliance; exact resource IDs and counts matched an independent Resource Graph query |
| Percentages and preservation | `Resource_Description`: 16.7% compliant, 83.3% missing; other required tags 100% missing. Fixture `sttagging73a0ae81` retained only its original `Resource_Description=Existing pilot value` tag |
| Telemetry | `appi-tagging-73a0ae81`, linked to `log-tagging-73a0ae81`, contained traces, dependencies, and a request record |

The first invocation returned `status=completed` but both tool outputs contained `Error: Function failed.` Traces showed Resource Graph `AccessDenied` immediately after the Reader assignment. A later identical read-only invocation passed without changing permissions. Always inspect tool outputs and allow RBAC propagation; protocol completion alone is not acceptance.

No tag-write access was granted and no remediation test was performed. The authenticated Responses endpoint is `https://foundry-tagging-73a0ae81.services.ai.azure.com/api/projects/tagging-governance/agents/tagging-compliance-agent/endpoint/protocols/openai/responses?api-version=v1`. Use the cleanup procedure below only with explicit approval for this dedicated environment.

After the CLI deployment test, the operator separately approved instruction-based evaluation-suite generation. `azd ai agent eval generate` targeted this new project explicitly without changing the existing azd manifest. It created dataset `tagging-compliance-cli-smoke` version `1.0` (requested sample count: 15) and evaluator `tagging-compliance-cli-smoke` version `1` with seven dimensions. The local [evaluation configuration](../tagging-compliance-agent/src/agent-framework-agent-with-local-tools-responses/eval.cli-test.yaml) retains remote artifact references; the CLI did not download the referenced local evaluator file, so that dangling `local_uri` was removed. Evaluation execution and full local artifact caching were not performed. Future evaluation commands must explicitly target this test project's endpoint, because the existing azd manifest references a different project.

## 1. Understand the deployment and its limits

The implementation is the [hosted agent](../tagging-compliance-agent/src/agent-framework-agent-with-local-tools-responses/main.py), not the older [local chat application](../remediation/chat.py).

| Component | Purpose |
|---|---|
| Foundry account and project | Host the agent and provide its model endpoint |
| Azure OpenAI model deployment | Reasoning and tool calling through `FoundryChatClient` |
| Azure Container Registry (ACR) | Build and store the existing Linux container |
| Log Analytics and Application Insights | Connected telemetry destination |
| Azure Resource Graph | Read resource inventory and tags |
| ARM Tags API | Merge approved tags into individual resources |
| Disposable storage account | A taggable resource for acceptance testing; no data needs to be uploaded |

The [existing manifest](../tagging-compliance-agent/azure.yaml) uses `azd` source-code deployment and references an existing project. This runbook deliberately uses the supported **container + REST** alternative so the deployment can be implemented with `az` commands. It does not modify that manifest or deploy to its preconfigured project.

### Mandatory governance checkpoint

Review these files with the governance owner before treating the report as authoritative:

- [Original naming convention](../prompt-instructions/tagging-naming-convention.md).
- [Naming convention actually packaged with the hosted agent](../tagging-compliance-agent/src/agent-framework-agent-with-local-tools-responses/tagging-naming-convention.md).
- [Runtime scoring rules](../tagging-compliance-agent/src/agent-framework-agent-with-local-tools-responses/rules.json).

Important current behavior:

- The runtime rules score **all eight** listed tags as required: `Application_Name`, `Entity`, `Organization`, `CCoE_ID_Number`, `CHG_Ticket`, `Resource_Groups`, `Resource_Description`, and `Launch_Date`. The prose convention marks some of them optional. Resolve this discrepancy before production use.
- Classification checks missing/placeholder values and the configured regular expressions. It does not enforce every prose rule, such as equality between `Resource_Groups` and the real resource-group name.
- Reports query the Resource Graph **Resources** table, not resource-group objects. The bulk tool tags resources **inside** a group, not the group object itself.
- Writes add missing/empty keys and skip requested keys with existing non-empty values. Consequently, existing `TBD` or invalid non-empty values are **not automatically corrected**.
- Actual writes add `Tagged_By_Agent=tagging-compliance-agent@<UTC timestamp>`. The CSV audit file is container-local and is **not durable evidence**.
- Scoring excludes matching `DATABRICKS-RG-*` groups. The bulk write tool does not apply that scoring exclusion. Do not use bulk remediation in platform-managed groups.
- Confirmation is a prompt instruction, not a separate approval service. RBAC is the enforceable Azure access boundary; the code has no fixed subscription/resource-group allow-list.
- Scheduled execution, Teams/email notifications, durable CSV export, and a separate end-user application are not implemented by this deployment.

## 2. Prerequisites and permissions

Use **PowerShell 7.4 or newer** and **Azure CLI 2.80.0 or newer**. If missing, use the official [PowerShell installation](https://learn.microsoft.com/powershell/scripting/install/installing-powershell-on-windows) and [Azure CLI installation](https://learn.microsoft.com/cli/azure/install-azure-cli-windows) instructions.

Use subscriptions in the **same Microsoft Entra tenant**. This runbook uses public Azure endpoints for a pilot. If your organization requires private endpoints, stop and use the approved network design and a network-connected execution environment; do not relax existing network controls.

Arrange these permissions before running commands:

| Actor | Required access |
|---|---|
| Subscription/bootstrap administrator | Register resource providers and create the two resource groups, if not already prepared |
| Deployment operator | Contributor on the deployment resource group and the disposable target resource group |
| Role-assignment administrator | Owner or Role Based Access Control Administrator at the scopes receiving assignments |
| Agent deployment operator | Foundry Project Manager at project scope; assigned below |
| Foundry project managed identity | Foundry User on its parent account; AcrPull on the RBAC-mode registry |
| Agent's runtime instance identity | Reader on the governed subscription; optionally Tag Contributor on the pilot resource group only |

Contributor/Owner management access alone does not grant Foundry data-plane access. Conversely, Foundry Project Manager does not authorize arbitrary Reader/Tag Contributor/AcrPull assignments outside its limited role-assignment permissions.

Choose a region supporting both hosted agents and the approved model. `eastus2` below is an example, not a data-residency recommendation. Check [hosted-agent availability](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agents#platform-details).

## 3. Set variables and sign in

Run all blocks in the **same PowerShell session**, from the workspace root. Replace the three IDs first. Keep a record of the generated names; rerunning this initialization generates a different environment.

```powershell
if ($PSVersionTable.PSVersion -lt [version]"7.4") {
    throw "Open PowerShell 7.4 or newer before continuing."
}
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

$TenantId = "<TENANT-ID>"
$DeploymentSubscriptionId = "<DEPLOYMENT-SUBSCRIPTION-ID>"
$GovernedSubscriptionId = "<GOVERNED-SUBSCRIPTION-ID>"
foreach ($Id in @($TenantId, $DeploymentSubscriptionId, $GovernedSubscriptionId)) {
    [void][guid]::Parse($Id)
}

$CliVersion = (az version --output json | ConvertFrom-Json).'azure-cli'
if ([version]$CliVersion -lt [version]"2.80.0") {
    throw "Azure CLI 2.80.0 or newer is required."
}

$Suffix = [guid]::NewGuid().ToString("N").Substring(0, 8)
$Location = "eastus2"
$DeploymentResourceGroup = "rg-tagging-agent-pilot-$Suffix"
$PilotResourceGroup = "rg-tagging-target-pilot-$Suffix"
$FoundryName = "foundry-tagging-$Suffix"
$ProjectName = "tagging-governance"
$ModelDeploymentName = "tagging-model"
$AcrName = "acrtagging$Suffix"
$WorkspaceName = "log-tagging-$Suffix"
$AppInsightsName = "appi-tagging-$Suffix"
$TestStorageName = "sttagging$Suffix"
$AgentName = "tagging-compliance-agent"
$ImageTag = "release-$Suffix"
$ApiVersion = "v1"
$Audience = "https://ai.azure.com"
$DeploymentScope = "/subscriptions/$DeploymentSubscriptionId"
$GovernedScope = "/subscriptions/$GovernedSubscriptionId"
$PilotScope = "$GovernedScope/resourceGroups/$PilotResourceGroup"
$ReaderScope = $GovernedScope

$SourceDirectory = (Resolve-Path -LiteralPath ".\01-tagging-compliance-agent\tagging-compliance-agent\src\agent-framework-agent-with-local-tools-responses").Path
$WorkDirectory = Join-Path ([System.IO.Path]::GetTempPath()) "tagging-agent-$Suffix"
$BuildContext = Join-Path $WorkDirectory "build"
New-Item -ItemType Directory -Path $BuildContext | Out-Null

az login --tenant $TenantId
az account set --subscription $DeploymentSubscriptionId
foreach ($SubscriptionId in @($DeploymentSubscriptionId, $GovernedSubscriptionId)) {
    $ActualTenant = az account show --subscription $SubscriptionId --query tenantId --output tsv
    if ($ActualTenant -ne $TenantId) { throw "Both subscriptions must belong to the selected tenant." }
}
```

The native-command error setting makes failed `az` commands stop the procedure. Do not continue past a failed command without resolving it.

### Optional: use one named test group and avoid subscription-wide access

For a dedicated, non-production group such as `agent-deploy-test`, run this override after initialization and before step 4:

```powershell
$DeploymentResourceGroup = "agent-deploy-test"
$PilotResourceGroup = $DeploymentResourceGroup
$PilotScope = "$GovernedScope/resourceGroups/$PilotResourceGroup"
$ReaderScope = $PilotScope
```

In this profile the subscriptions must be the same, all test infrastructure is in the named group, and Reader/Tag Contributor are group-scoped. Reports must explicitly filter to that group and will include the infrastructure as well as the fixture; do not expect exactly one scored resource. Do not test bulk tagging in this combined group.

## 4. Register providers and create resource groups

A subscription administrator runs this section if these providers are not already registered. Registration permission is subscription-scoped, not just resource-group Contributor.

```powershell
foreach ($Namespace in @(
    "Microsoft.CognitiveServices", "Microsoft.ContainerRegistry",
    "Microsoft.OperationalInsights", "Microsoft.Insights"
)) {
    az provider register --namespace $Namespace --subscription $DeploymentSubscriptionId --wait
}
foreach ($Namespace in @("Microsoft.ResourceGraph", "Microsoft.Storage")) {
    az provider register --namespace $Namespace --subscription $GovernedSubscriptionId --wait
}

az group create --name $DeploymentResourceGroup --location $Location --subscription $DeploymentSubscriptionId --output table
az group create --name $PilotResourceGroup --location $Location --subscription $GovernedSubscriptionId --output table
```

Apply your organization's required creation tags to these and subsequent create commands when Azure Policy requires them. Do not disable policy to complete the pilot.

## 5. Create Foundry and configure project access

```powershell
az cognitiveservices account create `
    --name $FoundryName --resource-group $DeploymentResourceGroup `
    --subscription $DeploymentSubscriptionId --location $Location `
    --kind AIServices --sku S0 --custom-domain $FoundryName `
    --assign-identity --allow-project-management true --yes --output none

az cognitiveservices account project create `
    --name $FoundryName --resource-group $DeploymentResourceGroup `
    --subscription $DeploymentSubscriptionId --project-name $ProjectName `
    --location $Location --assign-identity --output none

$FoundryId = az cognitiveservices account show --name $FoundryName --resource-group $DeploymentResourceGroup --subscription $DeploymentSubscriptionId --query id --output tsv
$ProjectId = az cognitiveservices account project show --name $FoundryName --resource-group $DeploymentResourceGroup --subscription $DeploymentSubscriptionId --project-name $ProjectName --query id --output tsv
$ProjectPrincipalId = az cognitiveservices account project show --name $FoundryName --resource-group $DeploymentResourceGroup --subscription $DeploymentSubscriptionId --project-name $ProjectName --query identity.principalId --output tsv
if ([string]::IsNullOrWhiteSpace($ProjectPrincipalId)) { throw "The project must have a system-assigned identity." }

$ProjectEndpoint = "https://${FoundryName}.services.ai.azure.com/api/projects/${ProjectName}"
$AgentUrl = "${ProjectEndpoint}/agents/${AgentName}"
$DeployerObjectId = az ad signed-in-user show --query id --output tsv
$FoundryUserRoleId = "53ca6127-db72-4b80-b1b0-d745d6d5456d"
$FoundryProjectManagerRoleId = "eadc314b-1a2d-4efa-be10-5d325db5065e"

az role assignment create --assignee-object-id $DeployerObjectId --assignee-principal-type User --role $FoundryProjectManagerRoleId --scope $ProjectId --subscription $DeploymentSubscriptionId --output none

$ExistingInferenceAssignment = @(az role assignment list --scope $FoundryId --subscription $DeploymentSubscriptionId --fill-principal-name false --query "[?principalId=='$ProjectPrincipalId' && ends_with(roleDefinitionId, '$FoundryUserRoleId')].id" --output tsv)
if ($ExistingInferenceAssignment.Count -eq 0) {
    az role assignment create --assignee-object-id $ProjectPrincipalId --assignee-principal-type ServicePrincipal --role $FoundryUserRoleId --scope $FoundryId --subscription $DeploymentSubscriptionId --output none
}

az cognitiveservices account project show --name $FoundryName --resource-group $DeploymentResourceGroup --subscription $DeploymentSubscriptionId --project-name $ProjectName --query "{State:properties.provisioningState,Endpoints:properties.endpoints}" --output json
```

Confirm `Succeeded` and verify the project endpoint against the returned endpoints. The role IDs also work while the older **Azure AI User / Azure AI Project Manager** role names remain visible.

## 6. Select and deploy a model

Do not assume a hard-coded model version remains deployable. List the account's models, then select an approved **OpenAI chat model with function/tool calling**, preferably a generally available model such as `gpt-5.4-mini` if offered. Catalog presence and positive quota alone do not prove that new deployments are allowed.

```powershell
$AvailableModels = az cognitiveservices account list-models --name $FoundryName --resource-group $DeploymentResourceGroup --subscription $DeploymentSubscriptionId --output json | ConvertFrom-Json
$AvailableModels | Where-Object format -eq "OpenAI" |
    Select-Object name, version, lifecycleStatus, @{Name="InferenceRetirement"; Expression={$_.deprecation.inference}}, @{Name="DeploymentTypes"; Expression={$_.skus.name -join ", "}} |
    Format-Table -AutoSize

$ModelName = Read-Host "Approved OpenAI chat/tool-calling model name"
$ModelVersion = Read-Host "Available version for that model"
$ModelSku = Read-Host "Approved deployment type, for example Standard, DataZoneStandard, or GlobalStandard"
$ModelCapacity = [int](Read-Host "Approved SKU capacity, for example 25")
$SelectedModel = @($AvailableModels | Where-Object { $_.format -eq "OpenAI" -and $_.name -eq $ModelName -and $_.version -eq $ModelVersion })
if ($SelectedModel.Count -ne 1 -or $ModelCapacity -lt 1) { throw "Select one available model/version and positive capacity." }
if ($SelectedModel[0].lifecycleStatus -notin @("GenerallyAvailable", "Preview", "Legacy")) {
    throw "The model lifecycle does not permit this selection. Choose a currently deployable version."
}
if ($SelectedModel[0].deprecation.inference -and [datetimeoffset]::Parse($SelectedModel[0].deprecation.inference) -le [datetimeoffset]::UtcNow) {
    throw "This model version has reached its inference retirement date."
}
$SelectedSku = @($SelectedModel[0].skus | Where-Object { $_.name -eq $ModelSku -and $_.usageName -notlike "*-finetune" })
if ($SelectedSku.Count -ne 1 -or -not $SelectedSku[0].usageName) { throw "Select an unambiguous supported inference deployment type." }
$QuotaRows = az cognitiveservices usage list --location $Location --subscription $DeploymentSubscriptionId --output json | ConvertFrom-Json
$QuotaRow = @($QuotaRows | Where-Object { $_.name.value -eq $SelectedSku[0].usageName })
if ($QuotaRow.Count -ne 1) { throw "Cannot verify quota for the selected SKU usageName." }
$AvailableQuota = $QuotaRow[0].limit - $QuotaRow[0].currentValue
if ($AvailableQuota -lt $ModelCapacity) { throw "Insufficient available quota for the requested capacity." }
Write-Host "Verified quota $($SelectedSku[0].usageName): $AvailableQuota available."

az cognitiveservices account deployment create `
    --name $FoundryName --resource-group $DeploymentResourceGroup `
    --subscription $DeploymentSubscriptionId --deployment-name $ModelDeploymentName `
    --model-format OpenAI --model-name $ModelName --model-version $ModelVersion `
    --sku-name $ModelSku --sku-capacity $ModelCapacity --output none

az cognitiveservices account deployment show --name $FoundryName --resource-group $DeploymentResourceGroup --subscription $DeploymentSubscriptionId --deployment-name $ModelDeploymentName --query "{State:properties.provisioningState,RateLimits:properties.rateLimits}" --output json
```

Expect `Succeeded`. Review Preview/Legacy lifecycle limitations before approving those selections. Match quota using the SKU's returned `usageName`, not a guessed name: for example, the `gpt-4.1-mini` pool can be named `OpenAI.GlobalStandard.gpt4.1-mini`.

If Azure returns `ServiceModelDeprecating`, stop and choose another approved version; a model can remain in the catalog and retain quota while being closed to new deployments. If capacity is rejected, inspect quota with `az cognitiveservices usage list --location $Location --subscription $DeploymentSubscriptionId --output table` and request capacity or select another **approved** option. Check the [model lifecycle and retirement schedule](https://learn.microsoft.com/azure/foundry/openai/concepts/model-retirement-schedule).

Global deployments can process requests outside the resource region; choose deployment type with the data-residency owner. Capacity units vary by model and should not be assumed to equal a fixed tokens-per-minute amount.

Inspect the returned token/request rate limits, not just provisioning status. Tool-rich multi-turn conversations include instructions, inventory, tool outputs, and follow-up model calls. For `gpt-5.4-mini` GlobalStandard, capacity 5 provided only 5,000 tokens/minute and failed during this test's write conversation; approve adequate headroom, for example capacity 25 for 25,000 tokens/minute, before running the full pilot.

## 7. Create the registry and telemetry resources

Use classic **RBAC registry permissions** so `AcrPull` applies. Do not use registry admin passwords.

```powershell
az acr create --name $AcrName --resource-group $DeploymentResourceGroup --subscription $DeploymentSubscriptionId --location $Location --sku Basic --admin-enabled false --role-assignment-mode rbac --output none
$AcrId = az acr show --name $AcrName --subscription $DeploymentSubscriptionId --query id --output tsv
$AcrLoginServer = az acr show --name $AcrName --subscription $DeploymentSubscriptionId --query loginServer --output tsv
az role assignment create --assignee-object-id $ProjectPrincipalId --assignee-principal-type ServicePrincipal --role AcrPull --scope $AcrId --subscription $DeploymentSubscriptionId --output none

$WorkspaceId = az monitor log-analytics workspace create --workspace-name $WorkspaceName --resource-group $DeploymentResourceGroup --subscription $DeploymentSubscriptionId --location $Location --retention-time 30 --query id --output tsv
$AppInsightsId = "$DeploymentScope/resourceGroups/$DeploymentResourceGroup/providers/Microsoft.Insights/components/$AppInsightsName"
$AppInsightsBodyPath = Join-Path $WorkDirectory "app-insights-create.json"
@{
    location = $Location
    kind = "web"
    properties = @{ Application_Type = "web"; WorkspaceResourceId = $WorkspaceId }
} | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $AppInsightsBodyPath -Encoding utf8NoBOM
az rest --method put --url "https://management.azure.com${AppInsightsId}?api-version=2020-02-02" --body "@$AppInsightsBodyPath" --output none
```

Create the two Foundry project connections. Their shape follows the official [Foundry starter infrastructure](https://github.com/Azure-Samples/azd-ai-starter-basic/blob/main/infra/core/ai/ai-project.bicep) and [ARM connection schema](https://learn.microsoft.com/azure/templates/microsoft.cognitiveservices/2025-06-01/accounts/projects/connections). These are ARM request bodies: submit them with `az rest`, not the project connection CLI's `--file` parameter, which expects a different schema.

```powershell
$RegistryConnectionPath = Join-Path $WorkDirectory "registry-connection.json"
@{
    properties = @{
        category = "ContainerRegistry"
        target = $AcrLoginServer
        authType = "ManagedIdentity"
        isSharedToAll = $true
        credentials = @{ clientId = $ProjectPrincipalId; resourceId = $AcrId }
        metadata = @{ ResourceId = $AcrId }
    }
} | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $RegistryConnectionPath -Encoding utf8NoBOM
az rest --method put --url "https://management.azure.com${ProjectId}/connections/tagging-registry?api-version=2025-06-01" --body "@$RegistryConnectionPath" --output none

$ApplicationInsightsConnectionString = az resource show --ids $AppInsightsId --api-version 2020-02-02 --query properties.ConnectionString --output tsv
if ([string]::IsNullOrWhiteSpace($ApplicationInsightsConnectionString)) { throw "Application Insights did not return its connection string." }
$TelemetryConnectionPath = Join-Path $WorkDirectory "telemetry-connection.json"
@{
    properties = @{
        category = "AppInsights"
        target = $AppInsightsId
        authType = "ApiKey"
        isSharedToAll = $true
        credentials = @{ key = $ApplicationInsightsConnectionString }
        metadata = @{ ApiType = "Azure"; ResourceId = $AppInsightsId }
    }
} | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $TelemetryConnectionPath -Encoding utf8NoBOM
try {
    az rest --method put --url "https://management.azure.com${ProjectId}/connections/tagging-telemetry?api-version=2025-06-01" --body "@$TelemetryConnectionPath" --output none
} finally {
    Remove-Item -LiteralPath $TelemetryConnectionPath
    $ApplicationInsightsConnectionString = $null
}
```

The App Insights connection string is obtained at runtime, not committed to source or included in the container build context. Review retention, telemetry access, and possible prompt/tag data collection with the data owner. Evaluation-specific telemetry-reader permissions are outside this runbook.

## 8. Build the existing container remotely

Copy an explicit file allow-list into a clean context. This prevents local credentials, virtual environments, and audit exports from being uploaded by the Dockerfile's `COPY . .`.

```powershell
$BuildFiles = @(
    "Dockerfile", "pyproject.toml", "uv.lock", "uv.toml",
    "main.py", "tools.py", "compliance_lib.py", "rules.json",
    "tagging-naming-convention.md", "requirements.txt"
)
foreach ($File in $BuildFiles) {
    $SourceFile = Join-Path $SourceDirectory $File
    if (-not (Test-Path -LiteralPath $SourceFile -PathType Leaf)) { throw "Missing source file: $File" }
    Copy-Item -LiteralPath $SourceFile -Destination $BuildContext
}

az acr build --registry $AcrName --subscription $DeploymentSubscriptionId --resource-group $DeploymentResourceGroup --platform linux/amd64 --image "${AgentName}:${ImageTag}" --file (Join-Path $BuildContext "Dockerfile") $BuildContext
az acr repository show --name $AcrName --subscription $DeploymentSubscriptionId --image "${AgentName}:${ImageTag}" --output json
$Image = "${AcrLoginServer}/${AgentName}:${ImageTag}"
```

Expect a successful build and an image digest. The shipped [Dockerfile](../tagging-compliance-agent/src/agent-framework-agent-with-local-tools-responses/Dockerfile) installs from the frozen [uv lock file](../tagging-compliance-agent/src/agent-framework-agent-with-local-tools-responses/uv.lock), not from the separate requirements file. Keep these existing dependency inputs together; do not silently regenerate the lock during deployment.

ACR Tasks must be permitted to access the public base-image/package sources used by the Dockerfile. A build-policy, package, or network failure is a blocking error, not a successful deployment.

## 9. Register the hosted agent and wait for readiness

This is a **first deployment**. `POST /agents` creates version `1` and starts provisioning automatically. It is not a legacy Assistants/persistent-agent API; no separate start command or capability host is required for this basic setup.

```powershell
$AgentDefinition = @{
    kind = "hosted"
    container_configuration = @{ image = $Image }
    cpu = "0.5"
    memory = "1Gi"
    protocol_versions = @(@{ protocol = "responses"; version = "2.0.0" })
    environment_variables = @{
        AZURE_AI_MODEL_DEPLOYMENT_NAME = $ModelDeploymentName
        PYTHONNOUSERSITE = "1"
    }
}
$CreateBodyPath = Join-Path $WorkDirectory "agent-create.json"
@{ name = $AgentName; definition = $AgentDefinition } |
    ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $CreateBodyPath -Encoding utf8NoBOM
az rest --method post --url "${ProjectEndpoint}/agents?api-version=$ApiVersion" --resource $Audience --headers "Content-Type=application/json" --body "@$CreateBodyPath" --output none

$AgentVersion = "1"
$VersionUrl = "${AgentUrl}/versions/${AgentVersion}?api-version=$ApiVersion"
$Deadline = (Get-Date).AddMinutes(20)
do {
    $Version = az rest --method get --url $VersionUrl --resource $Audience --output json | ConvertFrom-Json
    Write-Host "Version $AgentVersion status: $($Version.status)"
    if ($Version.status -in @("failed", "deleting", "deleted")) {
        throw ($Version | ConvertTo-Json -Depth 30)
    }
    if ($Version.status -eq "active") { break }
    Start-Sleep -Seconds 10
} while ((Get-Date) -lt $Deadline)
if ($Version.status -ne "active") { throw "Readiness timed out. Inspect the version before proceeding." }

$EndpointBodyPath = Join-Path $WorkDirectory "endpoint-version.json"
@{
    agent_endpoint = @{
        version_selector = @{
            version_selection_rules = @(@{ agent_version = $AgentVersion; traffic_percentage = 100; type = "FixedRatio" })
        }
        protocol_configuration = @{ responses = @{} }
    }
} | ConvertTo-Json -Depth 15 | Set-Content -LiteralPath $EndpointBodyPath -Encoding utf8NoBOM
az rest --method patch --url "${AgentUrl}?api-version=$ApiVersion" --resource $Audience --headers "Content-Type=application/merge-patch+json" --body "@$EndpointBodyPath" --output none

$AgentPrincipalId = az rest --method get --url "${AgentUrl}?api-version=$ApiVersion" --resource $Audience --query instance_identity.principal_id --output tsv
if ([string]::IsNullOrWhiteSpace($AgentPrincipalId)) { throw "The deployed agent has no runtime instance identity." }
Write-Host "Runtime agent principal: $AgentPrincipalId"
```

Configuration details matter:

- The environment variable is **`AZURE_AI_MODEL_DEPLOYMENT_NAME`**, matching the code, not the shorter variable used by some generic samples.
- Foundry injects **`FOUNDRY_PROJECT_ENDPOINT`** and the runtime identity configuration. Do not override reserved `FOUNDRY_*` variables or supply a client secret.
- Keep the Foundry project identity and the agent's **`instance_identity.principal_id`** separate. The latter runs the ARM/Resource Graph tools.
- The endpoint is pinned to a concrete version. Before future releases, follow the [candidate testing and promotion procedure](https://learn.microsoft.com/azure/foundry/agents/how-to/manage-hosted-agent#release-a-version-without-changing-production); do not let an untested latest version receive production traffic.
- If an agent with this name already exists, stop on the conflict. Do not delete it or assume its version is `1`.

## 10. Enable reporting and create the disposable test resource

The default `$ReaderScope` is the governed subscription for a complete subscription report. The optional group-only profile sets it to `$PilotScope`; in that case, reports must explicitly filter to that group. Resource Graph only returns resources the caller can read.

```powershell
$ReaderAssignmentId = az role assignment create --assignee-object-id $AgentPrincipalId --assignee-principal-type ServicePrincipal --role Reader --scope $ReaderScope --subscription $GovernedSubscriptionId --query id --output tsv

az storage account create `
    --name $TestStorageName --resource-group $PilotResourceGroup `
    --subscription $GovernedSubscriptionId --location $Location `
    --kind StorageV2 --sku Standard_LRS --https-only true --min-tls-version TLS1_2 `
    --allow-blob-public-access false --allow-shared-key-access false `
    --tags "Resource_Description=Existing pilot value" --output none
$TestResourceId = az storage account show --name $TestStorageName --resource-group $PilotResourceGroup --subscription $GovernedSubscriptionId --query id --output tsv

az role assignment list --scope $PilotScope --subscription $GovernedSubscriptionId --include-inherited --fill-principal-name false --query "[?principalId=='$AgentPrincipalId'].{Role:roleDefinitionName,Scope:scope}" --output table
```

At this point the runtime identity should have Reader, **not** Tag Contributor, Contributor, or Owner on the target scope. Allow time for RBAC propagation. If policy requires additional fixture tags, supply approved values instead of bypassing policy.

### Read-only conversation and proposed change

The invocation URL is the agent's **Responses endpoint**, not the project's general model endpoint.

```powershell
$ResponsesUrl = "${AgentUrl}/endpoint/protocols/openai/responses?api-version=$ApiVersion"
$ReportBodyPath = Join-Path $WorkDirectory "report-request.json"
@{
    input = "Call get_tag_report and list_non_compliant for subscription $GovernedSubscriptionId, resource group $PilotResourceGroup. Return the counts, per-tag percentages, and resource IDs. Do not write tags."
    store = $true
} | ConvertTo-Json | Set-Content -LiteralPath $ReportBodyPath -Encoding utf8NoBOM
$ReportResponse = az rest --method post --url $ResponsesUrl --resource $Audience --headers "Content-Type=application/json" --body "@$ReportBodyPath" --output json | ConvertFrom-Json
if ($ReportResponse.status -ne "completed" -or -not $ReportResponse.id) { throw ($ReportResponse | ConvertTo-Json -Depth 30) }
$ReportResponse.output | ConvertTo-Json -Depth 30

$TriageBodyPath = Join-Path $WorkDirectory "triage-request.json"
@{
    input = "For the disposable resource $TestResourceId, propose adding only Application_Name=Tagging Agent Pilot. Do not execute it. Restate the exact resource ID, proposed tag, and audit tag, and ask for confirmation."
    previous_response_id = $ReportResponse.id
    store = $true
} | ConvertTo-Json | Set-Content -LiteralPath $TriageBodyPath -Encoding utf8NoBOM
$TriageResponse = az rest --method post --url $ResponsesUrl --resource $Audience --headers "Content-Type=application/json" --body "@$TriageBodyPath" --output json | ConvertFrom-Json
if ($TriageResponse.status -ne "completed" -or -not $TriageResponse.id) { throw ($TriageResponse | ConvertTo-Json -Depth 30) }
$TriageResponse.output | ConvertTo-Json -Depth 30
```

Inspect the returned content, not just HTTP success or `completed`. Require real tool results, no authorization errors, and the fixture's exact ID. Expect the fixture among scored resources and percentages between 0 and 100; exactly one resource is expected only if the target group is otherwise empty. If Resource Graph has not indexed the fixture yet, wait and rerun the report; a zero-resource report is not a passing test.

`store=true` and `previous_response_id` preserve the proposed change and confirmation in one conversation. Review the resulting conversation retention with the data owner.

## 11. Optional: enable and verify a single-resource write

**Stop here for a reporting-only deployment.** Run this section only after an authorized operator approves the fixture, exact tag value, and pilot scope. Never grant the agent Owner or Contributor for tagging.

```powershell
$InitialTags = (az tag list --resource-id $TestResourceId --subscription $GovernedSubscriptionId --output json | ConvertFrom-Json).properties.tags
if ($InitialTags.Application_Name) { throw "The fixture already has Application_Name. Use an approved fixture with that key missing, or revise the write test." }
if ($InitialTags.Resource_Description -ne "Existing pilot value") { throw "The fixture baseline differs from this write test. Review it before granting write access." }

$TagAssignmentId = az role assignment create --assignee-object-id $AgentPrincipalId --assignee-principal-type ServicePrincipal --role "Tag Contributor" --scope $PilotScope --subscription $GovernedSubscriptionId --query id --output tsv
az role assignment list --scope $PilotScope --subscription $GovernedSubscriptionId --include-inherited --fill-principal-name false --query "[?principalId=='$AgentPrincipalId'].{Role:roleDefinitionName,Scope:scope}" --output table
```

After role propagation, inspect the proposal from the previous step. Only then send the explicit confirmation in the same conversation:

```powershell
$WriteBodyPath = Join-Path $WorkDirectory "write-request.json"
@{
    input = "I confirm: apply only Application_Name=Tagging Agent Pilot to $TestResourceId. I also approve the automatically generated Tagged_By_Agent audit tag. Do not tag any other resource."
    previous_response_id = $TriageResponse.id
    store = $true
} | ConvertTo-Json | Set-Content -LiteralPath $WriteBodyPath -Encoding utf8NoBOM
$WriteResponse = az rest --method post --url $ResponsesUrl --resource $Audience --headers "Content-Type=application/json" --body "@$WriteBodyPath" --output json | ConvertFrom-Json
$WriteResponse.output | ConvertTo-Json -Depth 30

$WrittenTags = (az tag list --resource-id $TestResourceId --subscription $GovernedSubscriptionId --output json | ConvertFrom-Json).properties.tags
if ($WriteResponse.status -ne "completed") {
    $WrittenTags | ConvertTo-Json
    throw ($WriteResponse | ConvertTo-Json -Depth 30)
}
if ($WrittenTags.Application_Name -ne "Tagging Agent Pilot") { throw "The requested tag was not applied." }
if ($WrittenTags.Resource_Description -ne "Existing pilot value") { throw "An existing tag changed unexpectedly." }
if ($WrittenTags.Tagged_By_Agent -notlike "tagging-compliance-agent@*") { throw "The required audit tag is missing or invalid." }
$WrittenTags | ConvertTo-Json
```

Wait for Resource Graph indexing and the deployment's token-rate window to refresh before this separate **read-only** check. Running another tool-rich report immediately after the write conversation can exhaust even the larger pilot allowance.

```powershell
$AfterReportResponse = az rest --method post --url $ResponsesUrl --resource $Audience --headers "Content-Type=application/json" --body "@$ReportBodyPath" --output json | ConvertFrom-Json
if ($AfterReportResponse.status -ne "completed" -or -not $AfterReportResponse.id) { throw ($AfterReportResponse | ConvertTo-Json -Depth 30) }
$AfterReportResponse.output | ConvertTo-Json -Depth 30
```

Verify the new report: `Application_Name` should now be compliant for the fixture. The resource can remain overall non-compliant because other required tags are still missing. Do not expect one successful tag write to produce 100% overall compliance. HTTP success alone does not pass this check; Foundry can return a response object with `status=failed`.

A failed/timed-out response is **not proof that no write occurred**: a tool can update ARM successfully and a later model reply can fail, including with a token-rate limit. Inspect `az tag list` and the Activity Log before deciding how to recover. Do not blindly retry, reset the fixture, or erase its audit marker. Any retry must remain within the exact approved resource/tag scope; this implementation skips already non-empty values.

## 12. Acceptance, operations, and troubleshooting

Before expanding permissions, record this evidence:

| Check | Passing result |
|---|---|
| Provisioning | Concrete agent version is `active`; deployed image matches the intended release |
| Read-only report | Fixture appears; tool returns counts, exclusion count, non-compliant percentage, and per-tag percentages without authorization errors |
| Proposal | Agent uses real inventory and asks before writing |
| Approved write | ARM shows the exact requested value and the generated audit marker; unrelated existing values are unchanged |
| Existing non-empty key | An explicitly approved attempt on a disposable fixture is reported as `tags_skipped_already_set`; the original value remains |
| Missing business information | Agent asks rather than inventing ownership/application information |
| Bulk operation, if separately tested | Only a disposable group is used; inspect `succeeded`, `failed`, `tags_written`, and skipped values for every resource |
| Observability | Foundry version/session logs are accessible; verify available traces in the connected Application Insights resource |

### Verify telemetry and change attribution with Azure CLI

Use the Application Insights query API's classic table names; Log Analytics workspace queries use different names. These commands return aggregate counts rather than prompt/tag contents.

```powershell
$AppInsightsAppId = az resource show --ids $AppInsightsId --api-version 2020-02-02 --query properties.AppId --output tsv
if ([string]::IsNullOrWhiteSpace($AppInsightsAppId)) { throw "Application Insights AppId is missing." }
$TelemetryQueryPath = Join-Path $WorkDirectory "telemetry-query.json"
@{
    query = "union traces, requests, dependencies, exceptions, customEvents | summarize Rows=count(), LastSeen=max(timestamp) by itemType | order by Rows desc"
    timespan = "PT2H"
} | ConvertTo-Json | Set-Content -LiteralPath $TelemetryQueryPath -Encoding utf8NoBOM
$Telemetry = az rest --method post --url "https://api.applicationinsights.io/v1/apps/${AppInsightsAppId}/query" --resource "https://api.applicationinsights.io" --headers "Content-Type=application/json" --body "@$TelemetryQueryPath" --output json | ConvertFrom-Json
if (-not $Telemetry.tables -or $Telemetry.tables[0].rows.Count -lt 1) { throw "No runtime telemetry was returned; allow ingestion time and investigate instrumentation." }
$Telemetry.tables[0] | ConvertTo-Json -Depth 10
```

Inspect exceptions rather than treating telemetry presence as an error-free runtime. The live pilot recorded the earlier model-throttling failures.

```powershell
az monitor activity-log list --resource-id $TestResourceId --subscription $GovernedSubscriptionId --offset 2h --max-events 100 --query "[?operationName.value=='Microsoft.Resources/tags/write'].{Time:eventTimestamp,Status:status.value,Caller:caller}" --output table
```

Require a `Succeeded` tag update attributable to the runtime agent principal, not the deployment operator. Activity Log and telemetry ingestion can lag.

The tag marker and Azure **Activity Log** are the immediately available change evidence. The code's local CSV can disappear across sessions/restarts; this runbook does not add persistent CSV storage. Restrict Foundry project membership: an authorized caller can request operations using the agent's granted Azure permissions, not their own ARM permissions.

| Symptom | Action |
|---|---|
| Foundry 401/403 | Confirm tenant, project data-plane role, and `--resource https://ai.azure.com`; allow role propagation |
| Image-pull 401/403 | Check the **project** principal's AcrPull assignment and registry RBAC mode; ABAC-enabled registries require appropriate repository roles instead |
| Model not found | Check the deployment name, successful model deployment, and `AZURE_AI_MODEL_DEPLOYMENT_NAME` |
| `ServiceModelDeprecating` | Catalog/quota presence is insufficient; select an approved non-deprecating version and recheck its SKU `usageName` quota |
| Model inference 403 | Check the project identity's Foundry User assignment on the parent account |
| Model token-rate limit / 429 | Review actual deployment rate limits and conversation size; obtain approval before raising capacity. For a failed write response, inspect ARM tags before retrying |
| Resource Graph 403/empty results | Check the **runtime agent** identity's Reader scope and inventory indexing; never interpret an incomplete scope as full-subscription compliance |
| Tagging 403 | Check Tag Contributor on the exact target scope, deny assignments, locks, and Azure Policy |
| Existing invalid/TBD value is unchanged | Expected additive-only behavior; replacement requires a separately approved manual process |
| Build/startup failure | Inspect ACR build output or Foundry version/session logs; do not regenerate dependencies or declare success without a completed invocation |
| Public endpoint blocked | Use the approved private-network path; do not disable isolation |

For ongoing releases, retain the previous image/version, pin production, test a candidate-specific session, and promote only the tested concrete version. See [manage hosted agents](https://learn.microsoft.com/azure/foundry/agents/how-to/manage-hosted-agent).

## 13. Disable, revoke write access, or clean up

Temporarily disable the endpoint without deleting versions:

```powershell
az rest --method post --url "${AgentUrl}:disable?api-version=$ApiVersion" --resource $Audience --output none
```

If step 11 created a Tag Contributor assignment, remove that exact assignment to return to report-only access:

```powershell
az role assignment delete --ids $TagAssignmentId --subscription $GovernedSubscriptionId
```

To re-enable the endpoint after approval:

```powershell
az rest --method post --url "${AgentUrl}:enable?api-version=$ApiVersion" --resource $Audience --output none
```

Disabling/revoking permissions does not undo completed tag changes, and in-flight work may still complete. Check the target tags and Activity Log. Rolling back an agent version also does not roll back resource tags.

For complete pilot removal, first remove any write assignment as above, then remove the Reader assignment created in step 10. Obtain explicit approval to delete the disposable agent **and all its sessions**, including stored conversations. Active/non-expired idle sessions otherwise block agent deletion; `force=true` cascades their removal. The following commands delete the agent and **only the dedicated pilot group(s) created by this runbook**. Do not use them against reused/shared agents or groups; leave the CLI group-deletion confirmation prompts enabled.

```powershell
az role assignment delete --ids $ReaderAssignmentId --subscription $GovernedSubscriptionId
az rest --method delete --url "${AgentUrl}?api-version=$ApiVersion" --url-parameters "force=true" --resource $Audience --output none
az group delete --name $PilotResourceGroup --subscription $GovernedSubscriptionId
if ($DeploymentSubscriptionId -ne $GovernedSubscriptionId -or $DeploymentResourceGroup -ne $PilotResourceGroup) {
    az group delete --name $DeploymentResourceGroup --subscription $DeploymentSubscriptionId
}
```

After exporting approved release/test evidence, remove only the temporary staging folder recorded in `$WorkDirectory`. Do not delete the workspace or original source. Resource groups persist in Azure until explicitly deleted; model tokens, hosted sessions, registry builds/storage, and telemetry can incur charges.

## References

- [Create Foundry projects - portal and Azure CLI](https://learn.microsoft.com/azure/foundry/how-to/create-projects)
- [Deploy a hosted agent - REST and container requirements](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent)
- [Hosted-agent permissions and identities](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agent-permissions)
- [Manage versions, routing, logs, and runtime identity](https://learn.microsoft.com/azure/foundry/agents/how-to/manage-hosted-agent)
- [ACR RBAC and ABAC permission modes](https://learn.microsoft.com/azure/container-registry/container-registry-rbac-abac-repository-permissions)
- [Azure tag operations](https://learn.microsoft.com/azure/azure-resource-manager/management/tag-resources-cli)
- [Portal-based companion guide](deployment-portal.md)
