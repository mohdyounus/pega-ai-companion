# Step 1 — Data Model (create these FIRST)

Create these classes and properties before building any activities.

---

## 1.1 Class: Data-CopilotChat

**Create via**: App Studio > Data > Data Types > New

| Field | Value |
|-------|-------|
| Class Name | `Data-CopilotChat` |
| Parent Class | `Data-` |
| Description | PEGA Copilot chat session data |
| RuleSet | `(your app ruleset)` |

### Properties to add on Data-CopilotChat

| Property Name | Type | Length | Description |
|---------------|------|--------|-------------|
| `pyUserMessage` | Text | 4000 | The developer's chat message |
| `pySystemPrompt` | Text | 4000 | System prompt for Claude |
| `pyModel` | Text | 100 | Claude model name |
| `pyMaxTokens` | Integer | — | Max response tokens |
| `pyResponse` | Text | 8000 | Claude's full response text |
| `pyIntent` | Text | 100 | Detected intent: Generate/Debug/Review/Test/Mentor |
| `pyRuleContext` | Text | 500 | Serialized rule context JSON |
| `pyInputTokens` | Integer | — | Tokens used in request |
| `pyOutputTokens` | Integer | — | Tokens used in response |
| `pyErrorMessage` | Text | 1000 | Error if Claude call fails |
| `pySuccess` | TrueFalse | — | Did the call succeed? |

---

## 1.2 Class: Data-CopilotMessage

**Purpose**: Represents one message in the messages array sent to Claude.

| Field | Value |
|-------|-------|
| Class Name | `Data-CopilotMessage` |
| Parent Class | `Data-` |
| Description | Single message in Claude conversation |

### Properties on Data-CopilotMessage

| Property Name | Type | Length | Description |
|---------------|------|--------|-------------|
| `pyRole` | Text | 50 | `user` or `assistant` |
| `pyContent` | Text | 8000 | Message text content |

---

## 1.3 Add Page List on Data-CopilotChat

After creating both classes, add a Page List property on `Data-CopilotChat`:

| Field | Value |
|-------|-------|
| Property Name | `pyMessages` |
| Type | Page List |
| Page Class | `Data-CopilotMessage` |
| Description | Array of messages for multi-turn conversation |

---

## 1.4 Property: API Key (on your App class or Data-CopilotChat)

> **Security**: Store the API key in a PEGA Keystore or as an encrypted property.
> For development, you can store it as a Text property.

| Property Name | Type | Notes |
|---------------|------|-------|
| `pyAnthropicAPIKey` | Text (encrypted) | Your `sk-ant-...` key |

**Recommended**: Use PEGA Keystore:
- App Studio > Security > Keystores > New Keystore
- Name: `AnthropicAPIKey`
- Type: `Basic`
- Reference it in Connect-REST as `{pyAnthropicAPIKey}`
