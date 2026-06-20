# Step 3 — Activities: Orchestrator + 5 Agents

---

## 3.1 Activity: CopilotOrchestrate

**Purpose**: Receives the chat message, detects intent, calls the right agent.

| Field | Value |
|-------|-------|
| **Rule Name** | `CopilotOrchestrate` |
| **Apply to Class** | `Data-CopilotChat` |
| **RuleSet** | `(your app ruleset)` |
| **Description** | Routes chat message to correct Copilot agent |

### Parameters

| Name | Type | Mode | Description |
|------|------|------|-------------|
| `UserMessage` | Text | In | The developer's message |
| `RuleName` | Text | In | Currently open rule name (from context) |
| `RuleClass` | Text | In | Currently open rule class |
| `RuleSet` | Text | In | Currently open ruleset |

### Steps

| # | Method | Details |
|---|--------|---------|
| 1 | **Property-Set** | `.pyUserMessage` = `param.UserMessage` |
| 2 | **Property-Set** | `.pyRuleContext` = `param.RuleName + "\|" + param.RuleClass + "\|" + param.RuleSet` |
| 3 | **Property-Set** | `.pyAnthropicAPIKey` = *(your key or keystore lookup)* |
| 4 | **Property-Set** | `.pyModel` = `"claude-sonnet-4-5"` |
| 5 | **Property-Set** | `.pyMaxTokens` = `8000` |
| 6 | **Property-Set** | `.pyIntent` = `@(pega.ai.detectIntent(.pyUserMessage))` *(see note)* |

> **Intent Detection (Step 6)**: Use a When rule or simple string matching:
> - Contains "create" / "generate" / "build" → `Generate`
> - Contains "debug" / "fix" / "error" / "failing" → `Debug`
> - Contains "review" / "check" / "best practice" → `Review`
> - Contains "test" / "unit test" / "scenario" → `Test`
> - Default (how / what / explain / why) → `Mentor`

**Replace Step 6 with these When-based conditions:**

| # | Condition | When True | Method |
|---|-----------|-----------|--------|
| 6 | `.pyUserMessage` contains "generat" OR "create" OR "build" | Call `CopilotGenerate` | Call |
| 7 | `.pyUserMessage` contains "debug" OR "fix" OR "error" | Call `CopilotDebug` | Call |
| 8 | `.pyUserMessage` contains "review" OR "check in" | Call `CopilotReview` | Call |
| 9 | `.pyUserMessage` contains "test" OR "unit test" | Call `CopilotTest` | Call |
| 10 | *(else — default)* | Call `CopilotMentor` | Call |

**Condition syntax in PEGA Activity**:
- Step condition: `@(pega.r.contains(.pyUserMessage,"generat") || pega.r.contains(.pyUserMessage,"create"))`

---

## 3.2 Activity: CopilotGenerate

**Purpose**: Generates a new PEGA rule from a natural language description.

| Field | Value |
|-------|-------|
| **Rule Name** | `CopilotGenerate` |
| **Apply to Class** | `Data-CopilotChat` |
| **Description** | Generates a PEGA rule using AI + codebase context |

### Steps

| # | Method | Target / Details |
|---|--------|-----------------|
| 1 | **Property-Set** | `.pySystemPrompt` = *(see system prompt below)* |
| 2 | **Property-Set** | `.pyUserMessage` = `.pyUserMessage` *(already set by orchestrator)* |
| 3 | **Call** | `ClaudeAPI` (the Connect-REST rule) |
| 4 | **Property-Set** | If `.pySuccess` is true: `.pyIntent` = `"Generate"` |
| 5 | **Property-Set** | Format the response for chat display |

### System Prompt for Step 1 (copy exactly):

```
You are a PEGA platform expert and rule generator. You help developers 
create PEGA rules by generating detailed rule specifications.

When asked to create a rule, always respond with:
1. A brief summary of what the rule does
2. The rule type, name, class, and ruleset
3. A numbered list of steps (for Activities) or properties (for Data Pages)
4. Key things the developer needs to verify before using the rule
5. Any dependencies (other rules, classes, properties that must exist)

Keep responses concise and practical. Use PEGA terminology correctly.
Always base your suggestions on standard PEGA patterns.

Current developer context:
- Open Rule: {RuleName}
- Class: {RuleClass}  
- RuleSet: {RuleSet}
```

> **Inject context into prompt**: Before calling ClaudeAPI, set:
> `.pySystemPrompt` using `Property-Set` with the text above,
> replacing `{RuleName}`, `{RuleClass}`, `{RuleSet}` using
> `@pega.i.str.replace()` or string concatenation in PEGA.

---

## 3.3 Activity: CopilotDebug

**Purpose**: Analyses a PEGA rule and finds logic issues.

### Steps

| # | Method | Details |
|---|--------|---------|
| 1 | **Property-Set** | `.pySystemPrompt` = *(debug prompt — see below)* |
| 2 | **Property-Set** | Build message: `"Analyse this PEGA rule and find issues: " + .pyUserMessage` |
| 3 | **Call** | `ClaudeAPI` |

### Debug System Prompt:
```
You are a PEGA debugging expert. When given a description of a rule or 
an error, you:
1. Identify the likely root cause
2. List specific steps that may be causing the issue
3. Provide the exact fix (which step to change, what condition to add)
4. Mention any common PEGA pitfalls related to the issue

Focus on: null checks, missing error handling, incorrect page context,
wrong class references, activity step order issues, and missing When rules.
```

---

## 3.4 Activity: CopilotReview

**Purpose**: Reviews a rule against PEGA best practices.

### System Prompt:
```
You are a PEGA code reviewer. Review the described rule against these 
PEGA best practices:

NAMING: Does it follow RuleSet naming conventions?
REUSE: Is logic that should be in a function reused?
ERROR HANDLING: Are all error paths covered?
PERFORMANCE: Any loops that could be optimised?
SECURITY: Any hardcoded values that should be parameterised?
TESTABILITY: Can this rule be unit tested with PegaUnit?

Score each category: PASS / WARN / FAIL
Provide specific actionable fixes for WARN and FAIL items.
```

---

## 3.5 Activity: CopilotTest

**Purpose**: Generates PegaUnit test case specifications.

### System Prompt:
```
You are a PEGA test engineer. When given a rule description, generate
PegaUnit test cases covering:
1. Happy path (all inputs valid, expected output produced)
2. Null/empty input handling
3. Boundary conditions (max values, empty lists, etc.)
4. Error scenarios (what happens when called rules fail)

For each test case provide:
- Test case name (following naming convention: TC_<RuleName>_<Scenario>)
- Setup: what properties to set on the clipboard before running
- Expected result: what the clipboard should contain after running
- Assertion: the specific property and expected value to assert
```

---

## 3.6 Activity: CopilotMentor

**Purpose**: Answers questions in context of the developer's own codebase.

### System Prompt:
```
You are a PEGA platform mentor helping a developer understand PEGA 
concepts and best practices. 

When answering:
- Give practical, hands-on explanations
- Reference standard PEGA patterns (Obj-Open, Obj-Save, Data Pages, etc.)
- If the question is about a specific rule, suggest how to find it in
  Designer Studio
- Keep answers concise — bullet points over paragraphs
- If you're unsure, say so and suggest where in PEGA docs to look

Developer context: they are working on {RuleClass} in {RuleSet}.
```

---

## 3.7 Wiring it together

After creating all activities, update `CopilotOrchestrate` steps 6-10:

| Step | Condition | Step Method | Call Rule | Call Class |
|------|-----------|-------------|-----------|------------|
| 6 | `@pega.r.contains(.pyUserMessage,"generat")` | Call | `CopilotGenerate` | `Data-CopilotChat` |
| 7 | `@pega.r.contains(.pyUserMessage,"debug")` | Call | `CopilotDebug` | `Data-CopilotChat` |
| 8 | `@pega.r.contains(.pyUserMessage,"review")` | Call | `CopilotReview` | `Data-CopilotChat` |
| 9 | `@pega.r.contains(.pyUserMessage,"test")` | Call | `CopilotTest` | `Data-CopilotChat` |
| 10 | *(no condition = always runs as fallback)* | Call | `CopilotMentor` | `Data-CopilotChat` |

> **Important**: Steps 6-9 each need an **Exit condition** of `true` after 
> the Call so they skip remaining steps once matched. 
> Set the "On Success" to skip to the end step.
