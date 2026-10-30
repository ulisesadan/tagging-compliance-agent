# Tagging Compliance Agent - Portal-based deployment

**Audience:** Azure administrators implementing the tagging-compliance pilot through a browser.  
**Reference date:** October 28, 2026.  
**Outcome:** Deploy the existing agent, validate a read-only report, and optionally enable a tightly scoped remediation test.

This guide uses **Azure portal + Microsoft Foundry portal**, with **embedded Azure Cloud Shell** for operations not offered by a documented graphical hosted-agent deployment wizard. This is the agreed browser-based route: no local Azure CLI, Docker, Python installation, or VS Code deployment extension is required.

The source files are an input artifact. Obtain the source ZIP described below from the application owner, or prepare it from the supplied workspace. All Azure deployment actions take place in the browser.

The shared container/Azure API path was **live-verified through Windows PowerShell and Azure CLI**; see the [CLI pilot results and limitations](deployment-cli.md#live-verification). The graphical portal actions and an embedded Cloud Shell session were not click-tested. A provisioned resource or an HTTP success response is not a substitute for your own acceptance checks.

The [Azure architecture diagram](agent-deploy-test-architecture.md) shows the verified resource, identity, and data-flow design. It documents the historical pilot, which was removed after testing.

## 1. Know what you are implementing

This is the [Python hosted agent](../tagging-compliance-agent/src/agent-framework-agent-with-local-tools-responses/main.py), with four local tools:

1. `get_tag_report` - compliance summary.
2. `list_non_compliant` - inventory details and compliant sibling examples.
3. `apply_resource_tags` - additive tag merge on one resource.
4. `apply_tags_to_resource_group` - additive tag merge on resources inside a group.

**Do not create a prompt-only agent and paste the naming convention into it.** That does not deploy the Python tools or their Azure permissions. The hosted container is built and registered through Cloud Shell later in this guide.

The [existing deployment manifest](../tagging-compliance-agent/azure.yaml) points to a different preconfigured project and uses `azd` code deployment. This manual container route does not use or change that project configuration.

### Governance and safety gates

Before deployment, have the governance owner compare the [original naming convention](../prompt-instructions/tagging-naming-convention.md), [packaged convention](../tagging-compliance-agent/src/agent-framework-agent-with-local-tools-responses/tagging-naming-convention.md), and [runtime rules](../tagging-compliance-agent/src/agent-framework-agent-with-local-tools-responses/rules.json).

- The runtime currently requires **all eight** configured tags, while the prose marks some optional. Resolve that discrepancy before production scoring.
- The report queries Azure resources, not resource-group objects. Some prose rules, such as checking that `Resource_Groups` equals the actual group name, are not enforced by the scoring code.
- Writes skip existing non-empty values, including existing `TBD`/invalid values. This is not a general overwrite/correction engine.
- Every actual write adds `Tagged_By_Agent=tagging-compliance-agent@<UTC timestamp>`.
- The local CSV audit log is ephemeral in a hosted container. Use the tag marker and Azure Activity Log; durable CSV retention needs a separate implementation.
- Reporting excludes matching `DATABRICKS-RG-*` groups, but the bulk write tool does not apply those exclusions. Do not bulk-tag platform-managed groups.
- Operator confirmation is enforced by instructions to the model, not an external approval workflow. **Azure RBAC** is the actual access boundary.
- Scheduling, notifications, and an independent end-user application are not part of this implementation.

## 2. Prepare access and record the deployment values

Use deployment and governed subscriptions in the **same Entra tenant**. Start with a dedicated pilot. This guide assumes approved public endpoints; private networking requires an approved design and a Cloud Shell/execution environment with the necessary network reachability.

Record these values as you create resources:

| Value | Suggested example / instruction |
|---|---|
| Deployment subscription ID | Subscription containing Foundry and supporting services |
| Governed subscription ID | Subscription the agent will report on |
| Deployment resource group | `rg-tagging-agent-pilot-<unique-suffix>` |
| Pilot target resource group | `rg-tagging-target-pilot-<unique-suffix>` |
| Region | For example East US 2; verify hosted-agent and model availability |
| Foundry account/resource name | Record the actual created account name |
| Foundry project name | `tagging-governance` |
| Project endpoint | Copy the project endpoint from the project overview |
| Model deployment name | `tagging-model` |
| Container registry name | Globally unique, lowercase letters/digits |
| Log Analytics workspace | `log-tagging-<unique-suffix>` |
| Application Insights name | `appi-tagging-<unique-suffix>` |
| Test storage account name | Globally unique, lowercase letters/digits, 3-24 characters |
| Agent name | `tagging-compliance-agent` |

Arrange these permissions:

- A bootstrap administrator can register providers and create the resource groups.
- The operator has **Contributor** on the deployment and disposable target groups.
- A role-assignment administrator has **Owner** or **Role Based Access Control Administrator** at the scopes where roles are assigned.
- The operator receives **Foundry Project Manager** on the project.
- The project identity receives **Foundry User** on the parent account and **AcrPull** on the registry.
- The runtime agent identity receives **Reader** on the governed subscription, and optionally **Tag Contributor** on the pilot group only.

Foundry roles might still display their former names, **Azure AI User / Azure AI Project Manager**. Do not give the runtime agent Owner or Contributor.

### Register providers, if necessary

1. Open [Azure portal](https://portal.azure.com).
2. Open **Subscriptions**, select the deployment subscription, then **Resource providers**.
3. Register `Microsoft.CognitiveServices`, `Microsoft.ContainerRegistry`, `Microsoft.OperationalInsights`, and `Microsoft.Insights` if not already registered.
4. In the governed subscription, verify/register `Microsoft.ResourceGraph` and `Microsoft.Storage`.
5. Wait for registration to complete. Ask a subscription administrator if registration is not permitted.

## 3. Create two dedicated resource groups

1. Search for **Resource groups**, select **Create**.
2. Select the deployment subscription, enter the deployment group name, and choose the approved region.
3. Add organization-required tags, then select **Review + create > Create**.
4. Repeat for the pilot target group in the governed subscription.
5. Keep the target group free of production resources. Bulk tagging must never be tested in a shared group.

## 4. Create the Foundry project and check its identity

1. Open [Microsoft Foundry](https://ai.azure.com) and select the correct directory/subscription.
2. Use the **new Foundry** experience, not a legacy hub-based project.
3. Open the project selector and choose **Create new project**.
4. Enter the project name. Open **Advanced options** to choose the deployment subscription, existing deployment resource group, and approved region.
5. Create a new Foundry resource or select an approved existing one. Record its actual resource/account name.
6. Select **Create** and wait for completion.
7. Open the project overview/settings and record its **project endpoint**, in this form:

   ```text
   https://<foundry-account>.services.ai.azure.com/api/projects/<project>
   ```

8. Use the project's Azure resource link to open the **project resource** in Azure portal. Under **Identity**, verify its system-assigned identity and copy the **Object (principal) ID**.
9. Keep this ID as **Project principal ID**. It is not the runtime agent identity, which will not exist until the hosted agent is created.

For a new project, use its default system-assigned identity. Do not change an existing user-assigned identity configuration to follow this pilot.

### Assign the Foundry roles

Use **Access control (IAM) > Add > Add role assignment** at each scope:

| Scope to open | Role | Member |
|---|---|---|
| Foundry project resource | Foundry Project Manager | Deployment operator |
| Parent Foundry account resource | Foundry User | Project principal ID |

For the identity assignment, select the project under **Managed identity** if available, or locate its service principal using the recorded object ID. Check **Role assignments** first: the portal may have already created the Foundry User assignment.

## 5. Deploy the reasoning model

1. In Foundry, open **Discover > Models**.
2. Select an approved Azure OpenAI chat model supporting function/tool calling; `gpt-5.4-mini` is an example if currently offered.
3. Select **Deploy > Custom settings**.
4. Select the intended Foundry resource/project and a deployable model version. Review its lifecycle and retirement date; prefer **Generally available** and do not select a deprecating/retired version just because it still appears in the catalog.
5. Set the **deployment name** to `tagging-model`, or record your chosen name exactly.
6. Select the approved deployment type and quota-supported capacity with headroom for tool calls and multi-turn history. For the `gpt-5.4-mini` GlobalStandard pilot, capacity 25 provides 25,000 tokens/minute; capacity 5 proved insufficient for the full conversation.
7. Select **Deploy** and verify **Succeeded** in the deployment details/list.
8. Test a simple model prompt in the model playground before continuing.

The deployment name, not merely the catalog model name, is passed to the agent. Global deployment types can process requests outside the resource region; choose the deployment type with the data-residency owner.

Positive quota is not proof of new-deployment availability. If creation returns `ServiceModelDeprecating`, select another approved version rather than retrying the same model with different capacity. Consult the [current retirement schedule](https://learn.microsoft.com/azure/foundry/openai/concepts/model-retirement-schedule).

## 6. Create the container registry and grant image-pull access

1. In Azure portal search **Container registries**, then select **Create**.
2. Choose the deployment subscription, deployment resource group, approved region, and globally unique registry name.
3. Select **Basic** for this public-endpoint pilot.
4. Set the role-assignment permissions mode to **RBAC Registry Permissions**, not the RBAC + ABAC repository mode.
5. Leave the registry **Admin user disabled**. Apply required organizational tags, then create the registry.
6. Open its **Access control (IAM)** and assign **AcrPull** to the **Foundry project principal ID**.
7. Check the assignment scope is this registry. Do not assign Reader/Tag Contributor to the project identity for the tagging tools.

The deployment operator's Contributor access to the deployment group covers this provisioning/build path. If image-building is delegated separately, the builder needs appropriate ACR Tasks and push permissions.

## 7. Create the telemetry destination

1. Search **Log Analytics workspaces > Create**.
2. Select the deployment subscription/group, workspace name, and approved region; create it.
3. Review its retention settings, initially 30 days or your organization's required value.
4. Search **Application Insights > Create**.
5. Choose the same subscription/group and an approved region.
6. Select the workspace created above to make this a **workspace-based** component.
7. Record the Application Insights resource name and create it.

The project connection is configured through Cloud Shell below. Do not paste telemetry connection strings into source files or the image. Grant the support team only approved telemetry-reader access and review what prompt/tag data may be recorded.

## 8. Create a disposable taggable resource

1. Search **Storage accounts > Create**.
2. Select the governed subscription and the **pilot target group**, not the agent's deployment group.
3. Enter the test storage name; use Standard performance and locally redundant storage for the pilot.
4. Require secure transfer and TLS 1.2 or newer. Disable anonymous blob access and shared-key access for this unused fixture.
5. On **Tags**, add `Resource_Description` with value `Existing pilot value`.
6. For the write test, `Application_Name` must initially be missing/empty. If policy requires it at creation, use an approved alternative fixture or revise the test with the governance owner. Do not bypass policy.
7. Create the account. No containers, files, or business data are needed.
8. Open its **Tags** and **JSON View/Properties** to record the initial tags and resource ID.

## 9. Open Cloud Shell and upload the approved source

### Source artifact

Obtain a ZIP containing these **ten files at its root**, taken from the [hosted source folder](../tagging-compliance-agent/src/agent-framework-agent-with-local-tools-responses):

```text
Dockerfile
pyproject.toml
uv.lock
uv.toml
main.py
tools.py
compliance_lib.py
rules.json
tagging-naming-convention.md
requirements.txt
```

If preparing the input yourself, select only these files in Windows File Explorer and use **Compress to ZIP file**. Do not select the whole workspace or include a parent folder in the archive. Exclude credentials, environment files, virtual environments, and audit exports. No local build is performed.

### Browser shell setup

1. Select the **Cloud Shell** icon in the Azure portal toolbar.
2. Choose **PowerShell**. Complete the Cloud Shell initialization/storage selection using an approved subscription; any supporting storage can incur charges.
3. Use **Manage files / Upload** to upload the source ZIP. Record the exact uploaded path shown by Cloud Shell.
4. Keep this shell open through deployment and testing. If it disconnects, restore the recorded values instead of creating another environment.
5. Run the following, entering values from the worksheet. Use PowerShell 7.4+ and Azure CLI 2.80.0+.

```powershell
if ($PSVersionTable.PSVersion -lt [version]"7.4") { throw "PowerShell 7.4 or newer is required." }
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
$CliVersion = (az version --output json | ConvertFrom-Json).'azure-cli'
if ([version]$CliVersion -lt [version]"2.80.0") { throw "Update the Cloud Shell Azure CLI before continuing." }

$DeploymentSubscriptionId = Read-Host "Deployment subscription ID"
$GovernedSubscriptionId = Read-Host "Governed subscription ID"
$DeploymentResourceGroup = Read-Host "Deployment resource group name"
$PilotResourceGroup = Read-Host "Pilot target resource group name"
$FoundryName = Read-Host "Foundry account/resource name"
$ProjectName = Read-Host "Foundry project name"
$ProjectEndpoint = (Read-Host "Project endpoint copied from Foundry").TrimEnd("/")
$ModelDeploymentName = Read-Host "Model deployment name"
$AcrName = Read-Host "Container registry name"
$AppInsightsName = Read-Host "Application Insights name"
$TestStorageName = Read-Host "Disposable storage account name"
$UploadedZip = Read-Host "Exact uploaded ZIP path shown by Cloud Shell"
$AgentName = "tagging-compliance-agent"
$ApiVersion = "v1"
$Audience = "https://ai.azure.com"
$ReleaseId = [guid]::NewGuid().ToString("N").Substring(0, 8)
$ImageTag = "release-$ReleaseId"
$WorkDirectory = Join-Path ([System.IO.Path]::GetTempPath()) "tagging-agent-$ReleaseId"
$ExtractedSource = Join-Path $WorkDirectory "source"
$BuildContext = Join-Path $WorkDirectory "build"
New-Item -ItemType Directory -Path $BuildContext | Out-Null
Expand-Archive -LiteralPath $UploadedZip -DestinationPath $ExtractedSource
az account set --subscription $DeploymentSubscriptionId

$DeploymentTenant = az account show --subscription $DeploymentSubscriptionId --query tenantId --output tsv
$GovernedTenant = az account show --subscription $GovernedSubscriptionId --query tenantId --output tsv
if ($DeploymentTenant -ne $GovernedTenant) { throw "Use subscriptions in the same Entra tenant." }

$BuildFiles = @(
    "Dockerfile", "pyproject.toml", "uv.lock", "uv.toml",
    "main.py", "tools.py", "compliance_lib.py", "rules.json",
    "tagging-naming-convention.md", "requirements.txt"
)
foreach ($File in $BuildFiles) {
    $SourceFile = Join-Path $ExtractedSource $File
    if (-not (Test-Path -LiteralPath $SourceFile -PathType Leaf)) { throw "Missing archive-root file: $File" }
    Copy-Item -LiteralPath $SourceFile -Destination $BuildContext
}

$ProjectPrincipalId = az cognitiveservices account project show --name $FoundryName --resource-group $DeploymentResourceGroup --subscription $DeploymentSubscriptionId --project-name $ProjectName --query identity.principalId --output tsv
if ([string]::IsNullOrWhiteSpace($ProjectPrincipalId)) { throw "Verify the project's system-assigned identity." }
$ProjectId = az cognitiveservices account project show --name $FoundryName --resource-group $DeploymentResourceGroup --subscription $DeploymentSubscriptionId --project-name $ProjectName --query id --output tsv
$AcrId = az acr show --name $AcrName --subscription $DeploymentSubscriptionId --query id --output tsv
$AcrLoginServer = az acr show --name $AcrName --subscription $DeploymentSubscriptionId --query loginServer --output tsv
$AppInsightsId = "/subscriptions/$DeploymentSubscriptionId/resourceGroups/$DeploymentResourceGroup/providers/Microsoft.Insights/components/$AppInsightsName"
$GovernedScope = "/subscriptions/$GovernedSubscriptionId"
$PilotScope = "$GovernedScope/resourceGroups/$PilotResourceGroup"
$AgentUrl = "${ProjectEndpoint}/agents/${AgentName}"
$TestResourceId = az storage account show --name $TestStorageName --resource-group $PilotResourceGroup --subscription $GovernedSubscriptionId --query id --output tsv
```

Compare the values to the portal resources before continuing. Resolve every CLI error; the error settings intentionally stop failed native commands.

## 10. Connect the registry and telemetry to the project

These are management-plane connections; creating them does not create a prompt-only agent. The connection shapes match the [official Foundry starter](https://github.com/Azure-Samples/azd-ai-starter-basic/blob/main/infra/core/ai/ai-project.bicep) and [ARM connection schema](https://learn.microsoft.com/azure/templates/microsoft.cognitiveservices/2025-06-01/accounts/projects/connections). Submit these ARM bodies with `az rest`; the connection CLI's `--file` parameter expects a different schema.

```powershell
$RegistryConnectionPath = Join-Path $WorkDirectory "registry-connection.json"
@{
    properties = @{
        category = "ContainerRegistry"; target = $AcrLoginServer
        authType = "ManagedIdentity"; isSharedToAll = $true
        credentials = @{ clientId = $ProjectPrincipalId; resourceId = $AcrId }
        metadata = @{ ResourceId = $AcrId }
    }
} | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $RegistryConnectionPath -Encoding utf8NoBOM
az rest --method put --url "https://management.azure.com${ProjectId}/connections/tagging-registry?api-version=2025-06-01" --body "@$RegistryConnectionPath" --output none

$ApplicationInsightsConnectionString = az resource show --ids $AppInsightsId --api-version 2020-02-02 --query properties.ConnectionString --output tsv
if ([string]::IsNullOrWhiteSpace($ApplicationInsightsConnectionString)) { throw "Verify the Application Insights resource." }
$TelemetryConnectionPath = Join-Path $WorkDirectory "telemetry-connection.json"
@{
    properties = @{
        category = "AppInsights"; target = $AppInsightsId
        authType = "ApiKey"; isSharedToAll = $true
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

## 11. Build and register the hosted agent

### Build in Azure, not on your workstation

```powershell
az acr build --registry $AcrName --subscription $DeploymentSubscriptionId --resource-group $DeploymentResourceGroup --platform linux/amd64 --image "${AgentName}:${ImageTag}" --file (Join-Path $BuildContext "Dockerfile") $BuildContext
az acr repository show --name $AcrName --subscription $DeploymentSubscriptionId --image "${AgentName}:${ImageTag}" --output json
$Image = "${AcrLoginServer}/${AgentName}:${ImageTag}"
```

Wait for the build to succeed and record the image digest. You can also open the registry's **Repositories** and **Runs/Tasks** views to inspect the image and build history.

The container uses the shipped [Dockerfile](../tagging-compliance-agent/src/agent-framework-agent-with-local-tools-responses/Dockerfile) and frozen dependency lock. Do not regenerate dependency files to hide a build failure. Linux AMD64 is required even if your computer is ARM-based.

### Register the first version

```powershell
$CreateBodyPath = Join-Path $WorkDirectory "agent-create.json"
@{
    name = $AgentName
    definition = @{
        kind = "hosted"
        container_configuration = @{ image = $Image }
        cpu = "0.5"; memory = "1Gi"
        protocol_versions = @(@{ protocol = "responses"; version = "2.0.0" })
        environment_variables = @{
            AZURE_AI_MODEL_DEPLOYMENT_NAME = $ModelDeploymentName
            PYTHONNOUSERSITE = "1"
        }
    }
} | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $CreateBodyPath -Encoding utf8NoBOM
az rest --method post --url "${ProjectEndpoint}/agents?api-version=$ApiVersion" --resource $Audience --headers "Content-Type=application/json" --body "@$CreateBodyPath" --output none

$AgentVersion = "1"
$Deadline = (Get-Date).AddMinutes(20)
do {
    $Version = az rest --method get --url "${AgentUrl}/versions/${AgentVersion}?api-version=$ApiVersion" --resource $Audience --output json | ConvertFrom-Json
    Write-Host "Version $AgentVersion status: $($Version.status)"
    if ($Version.status -in @("failed", "deleting", "deleted")) { throw ($Version | ConvertTo-Json -Depth 30) }
    if ($Version.status -eq "active") { break }
    Start-Sleep -Seconds 10
} while ((Get-Date) -lt $Deadline)
if ($Version.status -ne "active") { throw "Deployment timed out. Inspect the version before proceeding." }

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
if ([string]::IsNullOrWhiteSpace($AgentPrincipalId)) { throw "The agent has no runtime instance identity." }
Write-Host "Runtime agent principal: $AgentPrincipalId"
```

This first-create operation automatically provisions version `1`; there is no separate start operation. Stop if the name already exists instead of deleting/reusing an unknown deployment.

Foundry injects `FOUNDRY_PROJECT_ENDPOINT` and the runtime identity. Do not supply a client secret, override reserved `FOUNDRY_*` variables, or substitute `MODEL_DEPLOYMENT_NAME` for the variable the code actually reads.

Record the **runtime agent principal**, separately from the project principal. Optionally inspect the hosted agent in the project's agent list; Cloud Shell is the authoritative invocation path in this guide and does not depend on a portal playground exposing hosted-agent controls.

## 12. Grant Reader and validate a read-only conversation

1. In Azure portal open the **governed subscription > Access control (IAM)**.
2. Choose **Add role assignment > Reader**.
3. Assign it to the **runtime agent principal** printed above. This is an Entra service principal, not the Foundry project identity.
4. Confirm the subscription scope and review **Role assignments**.
5. Do not grant Tag Contributor yet. If Reader is intentionally limited to the pilot group, only claim report coverage for that group, not the subscription.

If the identity cannot be located in the portal picker, an authorized administrator can assign it in the embedded shell without a directory lookup. Use **either** the portal assignment **or** this command:

```powershell
az role assignment create --assignee-object-id $AgentPrincipalId --assignee-principal-type ServicePrincipal --role Reader --scope $GovernedScope --subscription $GovernedSubscriptionId --output none
```

Allow RBAC propagation, then invoke a report and a proposal:

```powershell
az role assignment list --scope $PilotScope --subscription $GovernedSubscriptionId --include-inherited --fill-principal-name false --query "[?principalId=='$AgentPrincipalId'].{Role:roleDefinitionName,Scope:scope}" --output table

$ResponsesUrl = "${AgentUrl}/endpoint/protocols/openai/responses?api-version=$ApiVersion"
$ReportBodyPath = Join-Path $WorkDirectory "report-request.json"
@{
    input = "Call get_tag_report and list_non_compliant for subscription $GovernedSubscriptionId, resource group $PilotResourceGroup. Return counts, per-tag percentages, and resource IDs. Do not write tags."
    store = $true
} | ConvertTo-Json | Set-Content -LiteralPath $ReportBodyPath -Encoding utf8NoBOM
$ReportResponse = az rest --method post --url $ResponsesUrl --resource $Audience --headers "Content-Type=application/json" --body "@$ReportBodyPath" --output json | ConvertFrom-Json
if ($ReportResponse.status -ne "completed" -or -not $ReportResponse.id) { throw ($ReportResponse | ConvertTo-Json -Depth 30) }
$ReportResponse.output | ConvertTo-Json -Depth 30

$TriageBodyPath = Join-Path $WorkDirectory "triage-request.json"
@{
    input = "For disposable resource $TestResourceId, propose adding only Application_Name=Tagging Agent Pilot. Do not execute. Restate the resource ID, proposed tag, and automatic audit tag, and ask for confirmation."
    previous_response_id = $ReportResponse.id
    store = $true
} | ConvertTo-Json | Set-Content -LiteralPath $TriageBodyPath -Encoding utf8NoBOM
$TriageResponse = az rest --method post --url $ResponsesUrl --resource $Audience --headers "Content-Type=application/json" --body "@$TriageBodyPath" --output json | ConvertFrom-Json
if ($TriageResponse.status -ne "completed" -or -not $TriageResponse.id) { throw ($TriageResponse | ConvertTo-Json -Depth 30) }
$TriageResponse.output | ConvertTo-Json -Depth 30
```

Check the output for actual inventory/tool results, not just a generic answer:

- The otherwise empty pilot group contains the fixture, and its exact ID appears.
- One resource is scored, with meaningful per-tag percentages in the 0-100 range.
- No tag changes occur, and there are no tool authorization errors.
- The proposal names only the fixture and asks for confirmation.

Resource Graph indexing can lag creation. Wait and rerun if the fixture is absent; do not accept a zero-resource report as a successful test. `store=true` retains the conversation in Foundry, and `previous_response_id` carries the proposal/confirmation context; obtain the data owner's approval for retention.

## 13. Optional: enable a narrowly scoped write

**Stop here if the deployment is reporting-only.**

Before granting write access, check that the fixture still matches the proposed test:

```powershell
$InitialTags = (az tag list --resource-id $TestResourceId --subscription $GovernedSubscriptionId --output json | ConvertFrom-Json).properties.tags
if ($InitialTags.Application_Name) { throw "The write-test key is already set; select an approved fixture or revise the write test." }
if ($InitialTags.Resource_Description -ne "Existing pilot value") { throw "The fixture baseline differs. Review it before granting write access." }
```

1. Get approval for the exact disposable resource, `Application_Name=Tagging Agent Pilot`, and automatic audit tag.
2. Open **pilot target resource group > Access control (IAM)**.
3. Add **Tag Contributor** for the **runtime agent principal**.
4. Confirm the scope is this pilot group, not the governed subscription or management group.
5. Wait for propagation.

If the portal picker cannot locate the identity, use this Cloud Shell alternative instead of the UI assignment:

```powershell
az role assignment create --assignee-object-id $AgentPrincipalId --assignee-principal-type ServicePrincipal --role "Tag Contributor" --scope $PilotScope --subscription $GovernedSubscriptionId --output none
```

Review the proposal, then confirm it in the same conversation:

```powershell
$WriteBodyPath = Join-Path $WorkDirectory "write-request.json"
@{
    input = "I confirm: apply only Application_Name=Tagging Agent Pilot to $TestResourceId. I approve the automatic Tagged_By_Agent audit tag. Do not tag any other resource."
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
if ($WrittenTags.Application_Name -ne "Tagging Agent Pilot") { throw "The requested tag is missing." }
if ($WrittenTags.Resource_Description -ne "Existing pilot value") { throw "An existing tag changed." }
if ($WrittenTags.Tagged_By_Agent -notlike "tagging-compliance-agent@*") { throw "The audit tag is missing or invalid." }
$WrittenTags | ConvertTo-Json
```

A failed/timed-out response does not prove that no tags changed: a write tool can succeed before a later model reply fails. Inspect the resource's **Tags** and **Activity log** before any retry. Do not reset the fixture or remove the audit marker; recover only within the exact approved scope. Raise model capacity only with approval.

After Resource Graph indexing and the model's token-rate window refresh, run this separate read-only report:

```powershell
$AfterReportResponse = az rest --method post --url $ResponsesUrl --resource $Audience --headers "Content-Type=application/json" --body "@$ReportBodyPath" --output json | ConvertFrom-Json
if ($AfterReportResponse.status -ne "completed" -or -not $AfterReportResponse.id) { throw ($AfterReportResponse | ConvertTo-Json -Depth 30) }
$AfterReportResponse.output | ConvertTo-Json -Depth 30
```

Inspect the response status and actual tool results. HTTP success alone is insufficient; Foundry can return `status=failed`.

## 14. Verify the result in the portals

1. Refresh the test storage account's **Tags**:
   - `Application_Name` is exactly `Tagging Agent Pilot`.
   - `Resource_Description` is still `Existing pilot value`.
   - `Tagged_By_Agent` contains the expected agent name and UTC timestamp.
2. Open the account's **Activity log** and locate the tag update operation.
3. After Resource Graph refresh, rerun the report. The fixture's `Application_Name` is compliant; the overall resource can remain non-compliant because other required tags are missing.
4. Open **Application Insights > Investigate > Transaction search / Performance** and verify available runtime telemetry after requests. Inspect Foundry version/session logs for startup/tool failures. Do not assume telemetry exists just because the component was created.
5. On a disposable fixture, separately verify that an approved request to replace an already non-empty key is reported as skipped and leaves the original unchanged.
6. Do not expand to bulk writes until governance approves the target group and an explicit bulk-impact confirmation test. Inspect individual successes, failures, actual writes, and skips; the bulk operation is not transactional.

Deployment is accepted only when the real report and, if enabled, authoritative ARM tag checks pass. Record the project endpoint, agent/version, image digest, runtime principal ID, role scopes, model deployment/version, and acceptance evidence.

## 15. Troubleshoot, disable, and clean up

| Problem | Portal checks / next action |
|---|---|
| Foundry API 401/403 | Verify operator Foundry data-plane role, selected directory, and Cloud Shell `--resource https://ai.azure.com`; allow propagation |
| Image pull fails | Registry IAM: project principal has AcrPull; verify classic RBAC mode, image tag, and permitted networking |
| Model inference fails | Verify deployment name/status and project identity's Foundry User on the parent account |
| Model creation returns `ServiceModelDeprecating` | Select an approved non-deprecating version; catalog presence and quota alone do not permit new deployments |
| Resource inventory empty/403 | Verify the runtime principal's Reader scope and Resource Graph indexing |
| Tag write denied | Verify runtime Tag Contributor at exact target scope; inspect Policy, locks, and deny assignments |
| Invalid/TBD tag unchanged | Expected: the tool does not overwrite non-empty values |
| Build/startup fails | Check registry build logs or hosted version/session logs; do not continue on a failed or timed-out deployment |
| Private endpoint/network block | Use approved network connectivity; do not enable public access as a workaround |

### Temporarily stop the agent

In the embedded shell:

```powershell
az rest --method post --url "${AgentUrl}:disable?api-version=$ApiVersion" --resource $Audience --output none
```

Then open the pilot group's **IAM > Role assignments**, select the runtime agent's **Tag Contributor** assignment, and remove it if returning to report-only mode. In-flight changes may still complete; check the target tags and Activity Log.

After approval, re-enable the endpoint with:

```powershell
az rest --method post --url "${AgentUrl}:enable?api-version=$ApiVersion" --resource $Audience --output none
```

Disabling the endpoint, removing roles, or rolling back code does **not** undo completed tag changes. Tag restoration needs a separately approved change using the recorded original state.

### Delete the pilot

1. Disable the endpoint.
2. In IAM, remove the exact runtime agent Reader/Tag Contributor assignments created for the pilot, including Reader at subscription scope.
3. With explicit approval to delete this disposable agent, its versions, and **all sessions/stored conversations**, use the embedded shell. Active/non-expired idle sessions otherwise block deletion; `force=true` cascades their removal. Do not use it for a shared/production agent:

   ```powershell
   az rest --method delete --url "${AgentUrl}?api-version=$ApiVersion" --url-parameters "force=true" --resource $Audience --output none
   ```

4. Open the **dedicated pilot target group**, review its resources, then choose **Delete resource group** and confirm its name.
5. Repeat for the **dedicated deployment group** only if it is not shared and no retained version depends on its image.
6. Remove only the uploaded source archive and temporary staging folder recorded for this deployment after exporting approved evidence. Do not delete the original workspace.
7. Review any Cloud Shell storage created during initialization separately; do not delete storage used by other sessions or workloads.

For later releases, keep production pinned, deploy/test a candidate-specific session, promote the tested version, and retain the prior version/image for rollback. The platform's default latest-version routing is not a safe production promotion gate.

## References

- [Create a Foundry project](https://learn.microsoft.com/azure/foundry/how-to/create-projects)
- [Deploy models through Foundry portal](https://learn.microsoft.com/azure/foundry/foundry-models/how-to/deploy-foundry-models)
- [Deploy a hosted agent and container requirements](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent)
- [Hosted-agent permissions](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agent-permissions)
- [Manage hosted-agent identity, routing, and lifecycle](https://learn.microsoft.com/azure/foundry/agents/how-to/manage-hosted-agent)
- [Azure Cloud Shell file transfer](https://learn.microsoft.com/azure/cloud-shell/using-the-cloud-shell-window#upload-and-download-files)
- [Azure CLI companion guide](deployment-cli.md)
