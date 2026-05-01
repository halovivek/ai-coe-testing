"""
AI Test Case Generator
======================
Generates structured BDD test cases from requirements using Claude.

Part of the AI CoE for Testing — halovivek/ai-coe-testing
Author: Vivek Rajagopalan · Senior Director, Engineering
"""

import json
import os
from dataclasses import dataclass
from typing import Optional
import anthropic

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """You are an expert QA engineer specializing in AI-powered test case generation.
When given a requirement, generate comprehensive test cases covering:
- Positive/happy path scenarios
- Negative and error scenarios  
- Boundary value and edge cases
- Security and data validation cases

Always respond with valid JSON only. No markdown, no explanation."""

TEST_CASE_SCHEMA = """
{
  "test_suite": {
    "title": "string",
    "requirement_id": "string",
    "test_type": "string",
    "generated_at": "ISO8601 timestamp",
    "cases": [
      {
        "scenario_id": "TC-001",
        "title": "string (max 80 chars)",
        "priority": "Critical|High|Medium|Low",
        "tags": ["functional", "regression", "smoke"],
        "preconditions": ["list of setup conditions"],
        "steps": [
          {"step": 1, "action": "string", "expected": "string"}
        ],
        "expected_result": "string",
        "test_data": {"key": "value"},
        "automation_feasibility": "High|Medium|Low",
        "automation_notes": "string"
      }
    ],
    "coverage_analysis": {
      "positive_cases": 0,
      "negative_cases": 0,
      "boundary_cases": 0,
      "security_cases": 0
    }
  }
}
"""


@dataclass
class TestGenerationConfig:
    test_type: str = "functional"
    include_negative: bool = True
    include_boundary: bool = True
    include_security: bool = False
    max_cases: int = 15
    domain_context: Optional[str] = None


def generate_test_cases(
    requirement: str,
    config: TestGenerationConfig = None,
    requirement_id: str = "REQ-001"
) -> dict:
    """
    Generate structured test cases from a requirement.

    Args:
        requirement: The feature requirement or user story text
        config: Test generation configuration
        requirement_id: Identifier for traceability

    Returns:
        Parsed JSON dict with test suite containing all generated cases

    Example:
        >>> result = generate_test_cases(
        ...     "As a user, I want to log in with email and password "
        ...     "so that I can access my account securely.",
        ...     config=TestGenerationConfig(include_security=True)
        ... )
        >>> print(f"Generated {len(result['test_suite']['cases'])} test cases")
    """
    if config is None:
        config = TestGenerationConfig()

    coverage_instructions = []
    if config.include_negative:
        coverage_instructions.append("negative and error scenarios")
    if config.include_boundary:
        coverage_instructions.append("boundary value cases")
    if config.include_security:
        coverage_instructions.append("security and injection cases")

    domain_note = ""
    if config.domain_context:
        domain_note = f"\nDomain context: {config.domain_context}"

    prompt = f"""Generate {config.test_type} test cases for the following requirement.
Include: positive scenarios, {', '.join(coverage_instructions)}.
Maximum {config.max_cases} test cases. Use requirement ID: {requirement_id}.{domain_note}

REQUIREMENT:
{requirement}

Respond with JSON matching this schema exactly:
{TEST_CASE_SCHEMA}"""

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()
    # Strip any accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip().rstrip("```").strip()

    return json.loads(raw)


def generate_api_contract_tests(openapi_spec: dict) -> dict:
    """
    Generate API contract tests from an OpenAPI/Swagger specification.

    Args:
        openapi_spec: Parsed OpenAPI 3.x specification dict

    Returns:
        Test suite covering all endpoints with positive, negative, and schema validation cases
    """
    spec_summary = json.dumps({
        "info": openapi_spec.get("info", {}),
        "paths": list(openapi_spec.get("paths", {}).keys()),
        "components": list(openapi_spec.get("components", {}).get("schemas", {}).keys())
    }, indent=2)

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"""Generate API contract test cases for this OpenAPI spec.
Include: schema validation, status code verification, auth tests, 
rate limiting, and error response validation.

SPEC SUMMARY:
{spec_summary}

Full spec paths to test: {json.dumps(list(openapi_spec.get('paths', {}).items())[:5], indent=2)}

Return JSON test suite in the standard schema."""
        }]
    )

    raw = response.content[0].text.strip()
    return json.loads(raw)


def export_to_gherkin(test_suite: dict) -> str:
    """Convert generated test cases to Gherkin BDD format."""
    lines = []
    suite = test_suite.get("test_suite", {})
    lines.append(f"Feature: {suite.get('title', 'Generated test suite')}")
    lines.append(f"  # Generated by AI CoE Test Generator")
    lines.append(f"  # Requirement: {suite.get('requirement_id', 'N/A')}")
    lines.append("")

    for case in suite.get("cases", []):
        lines.append(f"  @{' @'.join(case.get('tags', []))}")
        lines.append(f"  Scenario: {case['title']}")

        for pre in case.get("preconditions", []):
            lines.append(f"    Given {pre}")

        steps = case.get("steps", [])
        for i, step in enumerate(steps):
            keyword = "When" if i == 0 else "And"
            lines.append(f"    {keyword} {step['action']}")

        lines.append(f"    Then {case.get('expected_result', 'the operation succeeds')}")
        lines.append("")

    return "\n".join(lines)


def export_to_csv(test_suite: dict) -> str:
    """Export test cases as CSV for import into Jira/Zephyr/qTest."""
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Scenario ID", "Title", "Priority", "Tags", "Preconditions",
        "Steps", "Expected Result", "Automation Feasibility"
    ])

    for case in test_suite.get("test_suite", {}).get("cases", []):
        steps_text = " | ".join(
            [f"{s['step']}. {s['action']} → {s['expected']}"
             for s in case.get("steps", [])]
        )
        writer.writerow([
            case.get("scenario_id", ""),
            case.get("title", ""),
            case.get("priority", ""),
            ", ".join(case.get("tags", [])),
            " | ".join(case.get("preconditions", [])),
            steps_text,
            case.get("expected_result", ""),
            case.get("automation_feasibility", "")
        ])

    return output.getvalue()


if __name__ == "__main__":
    # Demo: generate test cases for a login feature
    requirement = """
    As a retail banking customer, I want to log in to the mobile banking app
    using my registered mobile number and 6-digit MPIN so that I can securely
    access my account and perform transactions.
    
    Acceptance criteria:
    - MPIN must be exactly 6 digits
    - Account locks after 3 consecutive failed attempts
    - Session expires after 5 minutes of inactivity
    - Biometric authentication available as alternative
    - OTP fallback when biometric unavailable
    """

    config = TestGenerationConfig(
        test_type="functional",
        include_negative=True,
        include_boundary=True,
        include_security=True,
        max_cases=12,
        domain_context="BFSI / Retail Banking / RBI compliance"
    )

    print("Generating test cases...")
    result = generate_test_cases(requirement, config, "REQ-AUTH-001")

    suite = result["test_suite"]
    print(f"\n=== {suite['title']} ===")
    print(f"Generated: {len(suite['cases'])} test cases")
    print(f"Coverage: {suite['coverage_analysis']}")
    print("\nFirst 3 test cases:")
    for case in suite["cases"][:3]:
        print(f"\n  [{case['scenario_id']}] {case['title']}")
        print(f"  Priority: {case['priority']} | Tags: {', '.join(case['tags'])}")

    # Export to Gherkin
    gherkin = export_to_gherkin(result)
    with open("generated_tests.feature", "w") as f:
        f.write(gherkin)
    print("\nGherkin feature file saved: generated_tests.feature")

    # Export to CSV
    csv_output = export_to_csv(result)
    with open("generated_tests.csv", "w") as f:
        f.write(csv_output)
    print("CSV export saved: generated_tests.csv")
