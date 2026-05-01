# Agentic Testing — Design Guide

**Pillar:** Agentic Testing · **Version:** 1.0  
**Applicable to:** Complex user workflows · Multi-step transactions · LLM-powered products

---

## What is agentic testing?

Agentic testing uses AI agents — systems that perceive a test environment, reason about goals, plan action sequences, and execute adaptively — to replace brittle, hand-coded test scripts for complex, multi-step workflows.

Unlike traditional automation where every step is explicitly scripted, an agentic test receives a **goal** ("verify that a user can complete a mortgage application end-to-end") and autonomously navigates the application, adapts to UI changes, handles unexpected states, and reports results with reasoning.

---

## When to use agentic testing

Use agentic testing when:

- The workflow spans 15+ steps across multiple screens or services
- UI changes frequently and traditional selectors break every sprint
- End-to-end scenarios require dynamic test data generation
- You need exploratory testing at scale (finding unknown unknowns)
- Testing AI-powered features that themselves require intelligent evaluation

Do not use for unit testing, API contract testing, or simple CRUD flows where traditional automation is simpler and faster.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Test Agent Orchestrator             │
│                                                     │
│  Goal: "Complete a home loan application"           │
│  State: {screen: 'income_form', step: 4/12}        │
│  Memory: {pan_verified: true, salary: '15L'}        │
└──────────────┬──────────────────────────────────────┘
               │ Plan
               ▼
┌─────────────────────────────────────────────────────┐
│                    Planning Layer (LLM)              │
│  - Analyzes current DOM/screenshot                  │
│  - Selects next action from tool palette            │
│  - Handles unexpected states with recovery plans    │
└──────────────┬──────────────────────────────────────┘
               │ Execute
               ▼
┌─────────────────────────────────────────────────────┐
│                    Tool Palette                     │
│  click(selector)  │  type(text)  │  scroll()       │
│  screenshot()     │  assert()    │  navigate(url)  │
│  extract(field)   │  wait()      │  api_call()     │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
         Browser / API / Database
```

---

## Implementation with Claude + Playwright

```python
"""
Agentic Test Agent — Goal-Driven Browser Automation
Uses Claude to reason about test goals and control Playwright.
"""
import asyncio
import base64
from anthropic import Anthropic
from playwright.async_api import async_playwright

client = Anthropic()

AGENT_SYSTEM_PROMPT = """You are an expert QA test agent controlling a web browser.
You receive screenshots of the current state and a test goal.
You output a JSON action to take next.

Available actions:
  {"action": "click", "selector": "CSS or text selector"}
  {"action": "type", "selector": "...", "text": "..."}
  {"action": "assert", "selector": "...", "expected": "..."}
  {"action": "navigate", "url": "..."}
  {"action": "wait", "ms": 1000}
  {"action": "done", "status": "pass|fail", "summary": "..."}

Think step by step. If a step fails, try an alternative approach.
Output ONLY the JSON action, nothing else."""


async def run_agentic_test(goal: str, start_url: str, max_steps: int = 30):
    """
    Execute a goal-driven test using Claude as the reasoning engine.
    
    Args:
        goal: Natural language test objective
        start_url: Starting URL for the test session
        max_steps: Safety limit on agent steps
    
    Returns:
        dict with status, steps_taken, and summary
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 800})
        await page.goto(start_url)

        conversation = [
            {
                "role": "user",
                "content": f"TEST GOAL: {goal}\n\nStart at: {start_url}\nTake the first action."
            }
        ]

        steps = []
        
        for step in range(max_steps):
            # Capture current state as screenshot
            screenshot_bytes = await page.screenshot(type="png")
            screenshot_b64 = base64.standard_b64encode(screenshot_bytes).decode()

            # Add screenshot to conversation
            conversation.append({
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": screenshot_b64
                        }
                    },
                    {"type": "text", "text": f"Step {step+1}. Current URL: {page.url}\nWhat action should I take next?"}
                ]
            })

            # Reason with Claude
            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=512,
                system=AGENT_SYSTEM_PROMPT,
                messages=conversation
            )

            action_json = response.content[0].text.strip()
            conversation.append({"role": "assistant", "content": action_json})

            import json
            action = json.loads(action_json)
            steps.append(action)

            # Execute action
            if action["action"] == "done":
                await browser.close()
                return {
                    "status": action["status"],
                    "steps_taken": step + 1,
                    "summary": action.get("summary", ""),
                    "steps": steps
                }
            elif action["action"] == "click":
                await page.click(action["selector"])
            elif action["action"] == "type":
                await page.fill(action["selector"], action["text"])
            elif action["action"] == "navigate":
                await page.goto(action["url"])
            elif action["action"] == "wait":
                await asyncio.sleep(action["ms"] / 1000)
            elif action["action"] == "assert":
                element = await page.query_selector(action["selector"])
                actual = await element.text_content() if element else None
                if action["expected"] not in (actual or ""):
                    await browser.close()
                    return {
                        "status": "fail",
                        "steps_taken": step + 1,
                        "summary": f"Assertion failed: expected '{action['expected']}' in '{actual}'",
                        "steps": steps
                    }

        await browser.close()
        return {"status": "fail", "steps_taken": max_steps,
                "summary": "Max steps exceeded", "steps": steps}


if __name__ == "__main__":
    result = asyncio.run(run_agentic_test(
        goal="Verify that a new user can register, verify email, and complete profile setup",
        start_url="https://staging.yourapp.com/register"
    ))
    print(f"Status: {result['status']}")
    print(f"Steps: {result['steps_taken']}")
    print(f"Summary: {result['summary']}")
```

---

## Agent design patterns

### Pattern 1: Goal decomposition
For complex goals, have the orchestrator LLM decompose into subtasks before execution:

```
Goal: "Complete a NEFT transfer of ₹50,000 to a new payee"
  └─ Subtask 1: Login successfully
  └─ Subtask 2: Add new payee with IFSC validation
  └─ Subtask 3: Initiate transfer with correct details
  └─ Subtask 4: Verify OTP confirmation
  └─ Subtask 5: Confirm transaction reference received
```

### Pattern 2: Failure recovery
Agents must handle unexpected states. Use a recovery prompt when an action fails:

```
"The previous action failed. Current state shows an error modal.
Analyze the error, dismiss it if recoverable, and continue toward the goal.
If unrecoverable, report failure with root cause."
```

### Pattern 3: Parallel exploration
Run multiple agent instances in parallel with different test data sets:

```python
async def run_parallel_agents(goal: str, test_data_sets: list):
    tasks = [run_agentic_test(goal, data) for data in test_data_sets]
    results = await asyncio.gather(*tasks)
    return results
```

---

## Safety and control boundaries

Agentic tests MUST be constrained to prevent unintended side effects:

1. **Environment isolation** — Always run against staging, never production
2. **Action allowlist** — Restrict the tool palette; no file system access, no email sending
3. **Step limit** — Hard cap at 50 steps per test (configurable)
4. **Human confirmation gate** — For irreversible actions (data deletion, payment), require explicit approval
5. **Audit trail** — Log every action with screenshot for post-test review

---

## Metrics and evaluation

| Metric | Target | Measurement |
|--------|--------|-------------|
| Goal completion rate | > 90% | Tests that reach "done: pass" |
| Average steps to goal | < 20 | Steps per successful run |
| False negative rate | < 5% | Tests that pass but had real defects |
| Recovery success rate | > 70% | Unexpected states recovered gracefully |
| Cost per test run | < ₹5 | API tokens + compute per run |

---

*Maintained by AI CoE for Testing · Questions: raise a GitHub Issue*
