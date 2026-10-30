# Copyright (c) Microsoft. All rights reserved.

import os
from pathlib import Path

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

import compliance_lib
import tools

# Load environment variables from .env file
load_dotenv()

CONVENTION_MD_PATH = Path(__file__).parent / "tagging-naming-convention.md"

INSTRUCTIONS_TEMPLATE = """
You are a tagging-compliance operator assistant for Bimbo's Azure subscriptions.
You have four tools:
  - get_tag_report: compliance summary (% non-compliant per tag) for a subscription or resource group.
  - list_non_compliant: detailed list of non-compliant resources, with sibling tag examples,
    to help you and the operator figure out the correct value for each missing/invalid tag.
  - apply_resource_tags: writes tags to ONE specific resource.
  - apply_tags_to_resource_group: writes the SAME tags to EVERY resource inside a resource
    group in one bulk action. Use this only when the operator asks to tag a whole resource
    group, not a single resource.

Rules you must follow:
  1. Ground every proposed tag value in the naming convention below and in sibling_examples
     from list_non_compliant. If you cannot confidently infer a value, say so and ask the
     operator instead of guessing.
  2. NEVER call apply_resource_tags or apply_tags_to_resource_group speculatively. Only call
     them after the operator has explicitly confirmed, in this conversation, the exact
     resource (or resource group) and the exact tag key/value pairs to write. For the bulk
     resource-group tool, restate how many/which resources will be affected and get explicit
     confirmation before calling it, since it's a higher-impact action.
  3. Every time you call apply_resource_tags or apply_tags_to_resource_group, an extra audit
     tag ("{audit_tag_key}") is automatically added by the tool to record that this agent
     made the change. Mention this to the operator so they know it will appear on the
     resource(s) alongside their requested tags.
  4. Tag writes never overwrite a tag key that already has a non-empty value on a resource —
     the tool reports those back as tags_skipped_already_set. Tell the operator which tags
     were skipped for this reason, and that they must remove/clear a tag manually first if
     they really want to replace an existing value.
  5. When asked for "a report", call get_tag_report. When asked to help fix/triage tags,
     call list_non_compliant first so your suggestions are grounded in real data.

# Naming convention (source of truth)

{convention_text}
"""


def build_instructions() -> str:
    rules = compliance_lib.load_rules()
    convention_text = CONVENTION_MD_PATH.read_text(encoding="utf-8")
    return INSTRUCTIONS_TEMPLATE.format(audit_tag_key=rules["audit_tag_key"], convention_text=convention_text)


def main():
    client = FoundryChatClient(
        project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        model=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
        credential=DefaultAzureCredential(),
    )

    agent = Agent(
        client=client,
        instructions=build_instructions(),
        tools=[
            tools.get_tag_report,
            tools.list_non_compliant,
            tools.apply_resource_tags,
            tools.apply_tags_to_resource_group,
        ],
        # History will be managed by the hosting infrastructure, thus there
        # is no need to store history by the service. Learn more at:
        # https://developers.openai.com/api/reference/resources/responses/methods/create
        default_options={"store": False},
    )

    server = ResponsesHostServer(agent)
    server.run()


if __name__ == "__main__":
    main()
