# Step 2 — Rule-Connect-REST: ClaudeAPI

This is the core connector that calls Anthropic's Claude API from PEGA.

---

## 2.1 Create the Connector

**Navigate to**: Designer Studio > Integration > Connectors > Create > REST

| Field | Value |
|-------|-------|
| **Rule Name** | `ClaudeAPI` |
| **Apply to Class** | `Data-CopilotChat` |
| **RuleSet** | `(your app ruleset)` |
| **Description** | Calls Anthropic Claude API to generate AI responses |

---

## 2.2 Service tab — URL & Method

| Field | Value |
|-------|-------|
| **HTTP Method** | `POST` |
| **Endpoint URL** | `https://api.anthropic.com/v1/messages` |
| **Authentication** | None (we pass the key manually in headers) |
| **Timeout (seconds)** | `120` |
| **Connection Timeout** | `30` |

---

## 2.3 Headers tab

Add these 3 headers:

| Header Name | Value | Notes |
|-------------|-------|-------|
| `x-api-key` | `.pyAnthropicAPIKey` | Maps from property on clipboard |
| `anthropic-version` | `2023-06-01` | Fixed string — type literally |
| `Content-Type` | `application/json` | Fixed string |
| `Accept` | `application/json` | Fixed string |

> In PEGA Connect-REST, to use a property value in a header,
> map it as: Source = Property, Value = `.pyAnthropicAPIKey`

---

## 2.4 Request tab — Body Mapping

**Body Type**: `application/json`
**Body Template**: Select "Custom JSON template" and enter:

```json
{
  "model": "{.pyModel}",
  "max_tokens": {.pyMaxTokens},
  "system": "{.pySystemPrompt}",
  "messages": [
    {
      "role": "user",
      "content": "{.pyUserMessage}"
    }
  ]
}
```

> **Note on special characters**: PEGA will escape quotes and newlines
> in property values automatically when using the template approach.

### Alternative — use Request Data Transform

If the template approach doesn't handle the message array well,
create a Data Transform `ClaudeAPI-RequestDT` on `Data-CopilotChat`:

| Step | Target | Source | Notes |
|------|--------|--------|-------|
| Set | `.pyModel` | `"claude-sonnet-4-5"` | Default model |
| Set | `.pyMaxTokens` | `8000` | Default max tokens |
| Append to | `.pyMessages` | — | Add one page |
| Set | `.pyMessages(1).pyRole` | `"user"` | |
| Set | `.pyMessages(1).pyContent` | `.pyUserMessage` | |

Then in the Request tab, map `.pyMessages` to the `messages` array.

---

## 2.5 Response tab — Mapping

Claude returns this JSON structure:
```json
{
  "id": "msg_...",
  "type": "message",
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "Here is the generated rule..."
    }
  ],
  "model": "claude-sonnet-4-5",
  "usage": {
    "input_tokens": 1139,
    "output_tokens": 3200
  }
}
```

Create a Response Data Transform `ClaudeAPI-ResponseDT`:

| Step | Target (on Data-CopilotChat) | Source (from response) |
|------|------------------------------|------------------------|
| Set | `.pyResponse` | `content[0].text` |
| Set | `.pyInputTokens` | `usage.input_tokens` |
| Set | `.pyOutputTokens` | `usage.output_tokens` |
| Set | `.pySuccess` | `true` (hardcoded) |

> For `content[0].text`: In PEGA response mapping, use index `(1)` 
> since PEGA uses 1-based arrays: map `content(1).text` → `.pyResponse`

---

## 2.6 Test the connector

1. Open the ClaudeAPI rule
2. Click **Run** (top toolbar)
3. Set test values on the clipboard:
   - `.pyAnthropicAPIKey` = your `sk-ant-...` key
   - `.pyModel` = `claude-sonnet-4-5`
   - `.pyMaxTokens` = `100`
   - `.pySystemPrompt` = `You are a PEGA expert.`
   - `.pyUserMessage` = `Say hello in one sentence.`
4. Click **Run** — you should see Claude's response in `.pyResponse`

---

## 2.7 Error Handling

Add an error handler activity `ClaudeAPI-ErrorHandler` on `Data-CopilotChat`:

| Step | Method | Details |
|------|--------|---------|
| 1 | Property-Set | `.pySuccess` = `false` |
| 2 | Property-Set | `.pyErrorMessage` = `@(pxRequestor.pzErrorDetails)` |
| 3 | Property-Set | `.pyResponse` = `"Sorry, I could not connect to the AI service. Check your API key and try again."` |

Then in the Connect-REST rule, under **Error Handling** tab, point to this activity.
