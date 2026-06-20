# PEGA Developer Copilot — Build Checklist

Complete in this exact order.

---

## Phase 1 — Data Model (30 mins)

- [ ] Create class `Data-CopilotChat` (see `01_data_model.md`)
- [ ] Create class `Data-CopilotMessage`
- [ ] Add all properties on `Data-CopilotChat` (pyUserMessage, pyResponse, etc.)
- [ ] Add `pyMessages` page list property (Page Class = `Data-CopilotMessage`)
- [ ] Store your API key (Keystore or encrypted property `pyAnthropicAPIKey`)

## Phase 2 — Claude Connector (45 mins)

- [ ] Create `Rule-Connect-REST: ClaudeAPI` on `Data-CopilotChat` (see `02_connect_rest_claude.md`)
- [ ] Set URL: `https://api.anthropic.com/v1/messages`
- [ ] Add headers: `x-api-key`, `anthropic-version`, `Content-Type`
- [ ] Map request body (model, max_tokens, system, messages)
- [ ] Map response: `content(1).text` → `.pyResponse`
- [ ] ✅ **TEST**: Run the connector in the rule tester — verify Claude responds

## Phase 3 — Agent Activities (1-2 hours)

- [ ] Create `CopilotGenerate` activity with Generate system prompt
- [ ] Create `CopilotDebug` activity with Debug system prompt
- [ ] Create `CopilotReview` activity with Review system prompt
- [ ] Create `CopilotTest` activity with Test system prompt
- [ ] Create `CopilotMentor` activity with Mentor system prompt
- [ ] Create `CopilotOrchestrate` activity that routes to agents (see `03_activities.md`)
- [ ] ✅ **TEST**: Run `CopilotOrchestrate` with test message "generate an activity"

## Phase 4 — REST Service (30 mins)

- [ ] Create `Rule-Service-REST: CopilotChatService` (see `04_rest_service_and_js.md`)
- [ ] Map POST body → properties → `CopilotOrchestrate`
- [ ] Map response → JSON with `response`, `intent`, `success`
- [ ] ✅ **TEST**: Call via Postman/browser: `POST /prweb/api/CopilotChat/v1/message`

## Phase 5 — Chat UI (1 hour)

- [ ] Create `Rule-File-Text: CopilotChat` (JavaScript type) with `CopilotChat.js` content
- [ ] Create `Rule-HTML-Section: CopilotChat` with the HTML + CSS from `04_rest_service_and_js.md`
- [ ] Add Section to your developer harness as a right-side slider panel
- [ ] Pass `ruleName`, `ruleClass`, `ruleSet` as URL params or harness params
- [ ] ✅ **TEST**: Open chat, type "@generate test activity", see Claude respond

---

## What each message triggers

| You type | Agent called | Claude prompt |
|----------|-------------|---------------|
| `@generate Activity ProcessEmails...` | CopilotGenerate | Rule generator prompt |
| `@debug step 5 fails on null` | CopilotDebug | Debugger prompt |
| `@review my activity` | CopilotReview | Best practices prompt |
| `@test write unit tests` | CopilotTest | PegaUnit test prompt |
| `how does Obj-Open work?` | CopilotMentor | Mentor prompt |

---

## Files in this folder

| File | Contents |
|------|---------|
| `01_data_model.md` | Classes and properties to create |
| `02_connect_rest_claude.md` | Connect-REST rule spec (step-by-step) |
| `03_activities.md` | All 6 activity specs with system prompts |
| `04_rest_service_and_js.md` | REST Service + full JavaScript + HTML |
| `README.md` | This checklist |
