# Step 4 — REST Service & Chat Section JavaScript

---

## 4.1 Rule-Service-REST: CopilotChatService

This exposes a REST endpoint that your chat Section's JavaScript calls.

| Field | Value |
|-------|-------|
| **Rule Name** | `CopilotChatService` |
| **Apply to Class** | `Data-CopilotChat` |
| **RuleSet** | `(your app ruleset)` |
| **Description** | REST endpoint for Copilot chat panel |
| **HTTP Method** | `POST` |
| **URL Path** | `/CopilotChat/v1/message` |

### Request Mapping

| JSON Field | Maps to Property |
|------------|-----------------|
| `message` | `.pyUserMessage` |
| `ruleName` | *(store in a temp prop or pass as param)* |
| `ruleClass` | *(store in a temp prop)* |
| `ruleSet` | *(store in a temp prop)* |

### Activity to execute: `CopilotOrchestrate`

Pass the request fields as parameters to `CopilotOrchestrate`.

### Response Mapping

Return a JSON response after the activity runs:

```json
{
  "response": ".pyResponse",
  "intent": ".pyIntent",
  "success": ".pySuccess",
  "inputTokens": ".pyInputTokens",
  "outputTokens": ".pyOutputTokens"
}
```

### Access settings

- **Requires Authentication**: Yes (PEGA session)
- **CSRF**: Enable if calling from within PEGA portal
- **Allowed Origins**: `same-origin` (since the Section is embedded in PEGA)

---

## 4.2 Chat Section JavaScript

This goes in the **Rule-HTML-Section** for your Copilot chat panel.
Include it in the Section's HTML or link to a `Rule-File-Text` JavaScript rule.

### JavaScript Rule

| Field | Value |
|-------|-------|
| **Rule Name** | `CopilotChat` |
| **Rule Type** | `Rule-File-Text` |
| **File Type** | `JavaScript` |
| **Apply to Class** | `Data-CopilotChat` |

### JavaScript Code (CopilotChat.js)

```javascript
/* CopilotChat.js — PEGA Copilot Chat Panel */
/* Include in Rule-File-Text, type: JavaScript */

var PEGACopilot = (function () {

  /* ── State ─────────────────────────────────────── */
  var _history = [];
  var _busy    = false;

  /* ── DOM helpers ───────────────────────────────── */
  function getInput()  { return document.getElementById("copilot-input"); }
  function getLog()    { return document.getElementById("copilot-log"); }

  function addBubble(role, text, id) {
    var log  = getLog();
    var div  = document.createElement("div");
    div.className = "cplt-bubble cplt-" + role;
    if (id) div.id = id;
    div.innerHTML = marked(text); /* markdown rendering */
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    return div;
  }

  function updateBubble(id, text) {
    var el = document.getElementById(id);
    if (el) el.innerHTML = marked(text);
  }

  function marked(text) {
    /* minimal markdown: bold, code, bullets */
    return text
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/^- (.+)$/gm, "<li>$1</li>")
      .replace(/(<li>.*<\/li>)/s, "<ul>$1</ul>")
      .replace(/\n/g, "<br>");
  }

  /* ── Get PEGA context (current open rule) ──────── */
  function getContext() {
    try {
      /* PEGA stores current harness info on the page model */
      var ctx = {};
      if (window.PCore) {
        /* Constellation (Infinity 23+) */
        var store = PCore.getStore().getState();
        ctx.ruleName  = store.data && store.data.ruleName  || "";
        ctx.ruleClass = store.data && store.data.className || "";
        ctx.ruleSet   = store.data && store.data.ruleSet   || "";
      } else {
        /* Classic UI — read from URL params passed by the harness */
        var params = new URLSearchParams(window.location.search);
        ctx.ruleName  = params.get("ruleName")  || "";
        ctx.ruleClass = params.get("ruleClass") || "";
        ctx.ruleSet   = params.get("ruleSet")   || "";
      }
      return ctx;
    } catch(e) {
      return { ruleName: "", ruleClass: "", ruleSet: "" };
    }
  }

  /* ── Send message ──────────────────────────────── */
  function send() {
    if (_busy) return;

    var input = getInput();
    var text  = input.value.trim();
    if (!text) return;

    _busy = true;
    input.value = "";
    input.disabled = true;

    addBubble("user", text);
    var thinkingId = "cplt-thinking-" + Date.now();
    addBubble("bot", "⏳ _Thinking..._", thinkingId);

    var ctx = getContext();

    /* Build PEGA REST Service URL */
    var url = "/prweb/api/CopilotChat/v1/message";

    /* Get PEGA CSRF token */
    var csrf = "";
    try { csrf = pega.u.d.getCsrfToken ? pega.u.d.getCsrfToken() : ""; }
    catch(e) {}

    fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "anti-csrf-token": csrf
      },
      credentials: "same-origin",
      body: JSON.stringify({
        message:   text,
        ruleName:  ctx.ruleName,
        ruleClass: ctx.ruleClass,
        ruleSet:   ctx.ruleSet
      })
    })
    .then(function(r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(function(data) {
      var reply = data.response || "_(no response)_";
      updateBubble(thinkingId, reply);
      /* Tag with intent badge */
      if (data.intent) {
        var badge = document.createElement("span");
        badge.className = "cplt-badge cplt-badge-" + data.intent.toLowerCase();
        badge.textContent = data.intent;
        document.getElementById(thinkingId).prepend(badge);
      }
    })
    .catch(function(err) {
      updateBubble(thinkingId, "❌ Error: " + err.message);
    })
    .finally(function() {
      _busy = false;
      input.disabled = false;
      input.focus();
    });
  }

  /* ── Enter key handler ─────────────────────────── */
  function onKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  /* ── Init ──────────────────────────────────────── */
  function init() {
    var input = getInput();
    if (input) {
      input.addEventListener("keydown", onKeyDown);
    }
    var ctx = getContext();
    if (ctx.ruleName) {
      addBubble("bot",
        "👋 **PEGA Copilot ready**\n\nContext: `" + ctx.ruleName +
        "` on `" + ctx.ruleClass + "`\n\n" +
        "Try: **@generate** • **@debug** • **@review** • **@test** • **@explain**"
      );
    } else {
      addBubble("bot",
        "👋 **PEGA Copilot ready**\n\n" +
        "Open a rule in Designer Studio first, or just ask me anything.\n\n" +
        "Try: **@generate** • **@debug** • **@review** • **@test** • **@explain**"
      );
    }
  }

  return { send: send, init: init };

})();

/* Auto-init when DOM ready */
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", PEGACopilot.init);
} else {
  PEGACopilot.init();
}
```

---

## 4.3 Chat Section HTML (Rule-HTML-Section)

Add this HTML to your chat Section's HTML content:

```html
<!-- Copilot Chat Panel — add to your Harness/Section HTML -->
<style>
  #copilot-panel {
    display: flex; flex-direction: column;
    height: 100%; font-family: Arial, sans-serif;
    background: #f8f9fa; border-left: 3px solid #003366;
  }
  #copilot-header {
    background: #003366; color: white;
    padding: 10px 16px; font-weight: bold; font-size: 14px;
  }
  #copilot-log {
    flex: 1; overflow-y: auto; padding: 12px;
    display: flex; flex-direction: column; gap: 8px;
  }
  .cplt-bubble {
    padding: 10px 14px; border-radius: 10px;
    max-width: 85%; font-size: 13px; line-height: 1.5;
  }
  .cplt-user {
    background: #003366; color: white;
    align-self: flex-end; border-bottom-right-radius: 2px;
  }
  .cplt-bot {
    background: white; border: 1px solid #dee2e6;
    align-self: flex-start; border-bottom-left-radius: 2px;
  }
  .cplt-bubble code {
    background: #e9ecef; padding: 1px 5px;
    border-radius: 3px; font-size: 12px;
  }
  .cplt-badge {
    display: inline-block; font-size: 10px; padding: 2px 7px;
    border-radius: 10px; margin-bottom: 5px; font-weight: bold;
  }
  .cplt-badge-generate { background: #d4edda; color: #155724; }
  .cplt-badge-debug    { background: #fff3cd; color: #856404; }
  .cplt-badge-review   { background: #cce5ff; color: #004085; }
  .cplt-badge-test     { background: #e2d9f3; color: #4a235a; }
  .cplt-badge-mentor   { background: #d1ecf1; color: #0c5460; }
  #copilot-footer {
    padding: 10px; border-top: 1px solid #dee2e6; background: white;
    display: flex; gap: 8px;
  }
  #copilot-input {
    flex: 1; padding: 8px 12px; border: 1px solid #ced4da;
    border-radius: 6px; font-size: 13px; resize: none; height: 40px;
  }
  #copilot-send {
    background: #003366; color: white; border: none;
    padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 13px;
  }
  #copilot-send:hover { background: #0066cc; }
</style>

<div id="copilot-panel">
  <div id="copilot-header">🤖 PEGA Developer Copilot</div>
  <div id="copilot-log"></div>
  <div id="copilot-footer">
    <textarea id="copilot-input"
      placeholder="@generate Activity | @debug | @review | @test | or ask anything..."
      rows="1"></textarea>
    <button id="copilot-send" onclick="PEGACopilot.send()">Send</button>
  </div>
</div>

<!-- Include the JavaScript rule -->
<script src="/prweb/rule-file-text/Data-CopilotChat/CopilotChat.js"></script>
```

---

## 4.4 Embed in Your Developer Harness

In your developer harness/portal, add the chat Section as a **right-side panel**:

1. Open your Developer Portal Harness
2. Add a new **Column** (30% width, right side)
3. Insert the `CopilotChat` Section into that column
4. Set **Visible when**: a toggle property (e.g. `.pyCopilotOpen = true`)
5. Add a button in the header that sets `.pyCopilotOpen` = `true`/`false` to toggle

Pass the rule context via harness parameters:
```
pyRuleName  = <pyRuleName from the current open rule>
pyClassName = <pyClassName>
pyRuleSet   = <pyRuleSet>
```
