"""
Shared helpers for the tagging-remediation reasoning layer: builds the Foundry
agent's grounding instructions from the naming-convention doc + rules.json,
gets-or-creates the Foundry prompt agent, and asks it to propose tag fixes for
a single resource (JSON in, JSON out). No ARM write calls live here.
"""
import json
import re
from pathlib import Path
from typing import Any

REPORT_DIR = Path(__file__).parent.parent / "report"
CONVENTION_MD_PATH = Path(__file__).parent.parent / "prompt-instructions" / "tagging-naming-convention.md"
RULES_PATH = REPORT_DIR / "rules.json"
AGENT_CACHE_PATH = Path(__file__).parent / ".agent_cache.json"
AGENT_NAME = "tagging-compliance-remediation-agent"

RESPONSE_CONTRACT = """
You are a tagging-compliance remediation assistant for Azure resources at Bimbo.
You will be given: the naming convention rules, one non-compliant resource (id, name,
type, resourceGroup, current tags, and which required tags are missing/placeholder/
invalid), and example tags from compliant sibling resources in the same resource group.

Propose a value for each listed non-compliant tag, using the sibling examples and the
resource's own name/type/resourceGroup as context. If you cannot confidently infer a
value, set "proposed_value" to null and "confidence" to "low" rather than guessing.

Respond with STRICT JSON only, no markdown fences, matching exactly this shape:
{
  "proposals": [
    {"tag": "<tag name>", "proposed_value": "<value or null>", "confidence": "high|medium|low", "rationale": "<one short sentence>"}
  ]
}
"""


def load_rules() -> dict[str, Any]:
    with open(RULES_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_convention_text() -> str:
    return CONVENTION_MD_PATH.read_text(encoding="utf-8")


def build_instructions() -> str:
    return f"{RESPONSE_CONTRACT}\n\n# Naming convention (source of truth)\n\n{load_convention_text()}"


def _load_cache() -> dict[str, str]:
    if AGENT_CACHE_PATH.exists():
        return json.loads(AGENT_CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_cache(cache: dict[str, str]) -> None:
    AGENT_CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def get_or_create_agent(project_client: Any, model_deployment_name: str) -> Any:
    """Reuses a cached agent by ID if it still exists, otherwise creates a new one."""
    cache = _load_cache()
    agent_id = cache.get(AGENT_NAME)
    if agent_id:
        try:
            return project_client.agents.get_agent(agent_id)
        except Exception:
            pass  # cached agent no longer exists; fall through and recreate

    agent = project_client.agents.create_agent(
        model=model_deployment_name,
        name=AGENT_NAME,
        instructions=build_instructions(),
    )
    cache[AGENT_NAME] = agent.id
    _save_cache(cache)
    return agent


def _extract_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"Agent response did not contain JSON: {text!r}")
    return json.loads(match.group(0))


def propose_tags_for_resource(
    project_client: Any,
    agent: Any,
    resource: dict[str, Any],
    non_compliant_tags: list[dict[str, Any]],
    sibling_examples: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Runs one thread+run against the agent and returns the parsed proposal list."""
    question = json.dumps(
        {
            "resource": {
                "id": resource["id"],
                "name": resource["name"],
                "type": resource["type"],
                "resourceGroup": resource["resourceGroup"],
            },
            "non_compliant_tags": non_compliant_tags,
            "sibling_examples": sibling_examples,
        },
        indent=2,
    )

    thread = project_client.agents.threads.create()
    project_client.agents.messages.create(thread_id=thread.id, role="user", content=question)
    run = project_client.agents.runs.create_and_process(thread_id=thread.id, agent_id=agent.id)

    if run.status == "failed":
        raise RuntimeError(f"Agent run failed for resource {resource['id']}: {run.last_error}")

    messages = project_client.agents.messages.list(thread_id=thread.id, order="desc")
    for message in messages:
        if message.role != "assistant":
            continue
        for content in message.content:
            if getattr(content, "type", None) == "text":
                parsed = _extract_json(content.text.value)
                return parsed.get("proposals", [])

    raise RuntimeError(f"No assistant response found for resource {resource['id']}")
