"""
chat_server.py
Simple FastAPI chat server for PEGA Developer Copilot.
Run: python tools/chat_server.py
Open: http://localhost:8000
"""
from __future__ import annotations
import json
import logging
import os
import sys
from pathlib import Path

# Auto-load .env
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).parent))

import anthropic
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from knowledge.vector_store import VectorStore
from knowledge.embeddings import EmbeddingEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("copilot-chat")

KB_DIR = str(Path(__file__).parent.parent / "knowledge_base")

# ── ADO Wiki config ───────────────────────────────────────────────────────────
ADO_ORG     = os.environ.get("AZURE_DEVOPS_ORG_URL", "https://dev.azure.com/nztasd")
ADO_PROJECT = os.environ.get("AZURE_DEVOPS_PROJECT", "SharedDelivery")
ADO_WIKI_ID = os.environ.get("AZURE_DEVOPS_WIKI_ID", "SharedDelivery.wiki")
ADO_PAT     = os.environ.get("AZURE_DEVOPS_PAT", "")

app = FastAPI(title="PEGA Developer Copilot")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Lazy-load KB ─────────────────────────────────────────────────────────────
_store: VectorStore | None = None
_embedder: EmbeddingEngine | None = None

def get_store():
    global _store
    if _store is None:
        _store = VectorStore(persist_dir=KB_DIR)
    return _store

def get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = EmbeddingEngine(cache_dir=KB_DIR)
    return _embedder

# ── Request model ─────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    rule_name: str = ""
    rule_class: str = ""
    rule_set: str = ""
    history: list[dict] = []

# ── Intent detection ──────────────────────────────────────────────────────────
def detect_intent(msg: str) -> str:
    m = msg.lower()
    if any(k in m for k in ["generat", "create", "build", "new rule", "add rule"]):
        return "Generate"
    if any(k in m for k in ["debug", "fix", "error", "failing", "broken", "why is"]):
        return "Debug"
    if any(k in m for k in ["review", "check", "best practice", "check in", "is this"]):
        return "Review"
    if any(k in m for k in ["test", "unit test", "test case", "scenario"]):
        return "Test"
    if any(k in m for k in ["recommend", "which section", "what section", "what layout",
                              "show me a section", "similar section"]):
        return "Recommend"
    return "Mentor"

# ── RAG lookup ────────────────────────────────────────────────────────────────
def rag_lookup(query: str, rule_type: str | None = None, n: int = 3) -> list[dict]:
    try:
        store = get_store()
        embedder = get_embedder()
        vec = list(embedder.embed_batch([{"description": query, "rule_name": "q", "rule_type": ""}]))[0]
        return store.query(vec, n_results=n, rule_type_filter=rule_type)
    except Exception as e:
        logger.warning(f"RAG lookup failed: {e}")
        return []

def format_similar(results: list[dict]) -> str:
    if not results:
        return ""
    lines = ["\n**Similar rules from your codebase:**"]
    for r in results:
        meta = r.get("metadata", {})
        rid = r.get("rule_id", "")
        name = rid.split("_")[-1] if "_" in rid else rid
        lines.append(f"- `{name}` ({meta.get('rule_type','?')} on {meta.get('pega_class','?')}): "
                     f"{r.get('document','')[:120]}")
    return "\n".join(lines)

# ── System prompts per intent ─────────────────────────────────────────────────
SYSTEM_PROMPTS = {
    "Generate": """You are a PEGA rule generator. When asked to create a rule:
1. State the rule type, name, class, ruleset
2. List all steps (for Activities) or properties (for Data Pages) 
3. Note dependencies and things to verify
4. Keep it practical and specific to PEGA 8.x conventions.
Current context: {context}""",

    "Debug": """You are a PEGA debugging expert. Identify:
1. The likely root cause
2. Which specific step/property is causing the issue
3. The exact fix needed
Focus on: null checks, page context errors, missing conditions, class mismatches.
Current context: {context}""",

    "Review": """You are a PEGA code reviewer. Score the rule on:
NAMING / REUSE / ERROR-HANDLING / PERFORMANCE / SECURITY
Rate each: PASS / WARN / FAIL with a specific fix for WARN/FAIL.
Current context: {context}""",

    "Test": """You are a PEGA test engineer. Generate PegaUnit test cases:
- Name: TC_<RuleName>_<Scenario>
- Setup: clipboard properties to set
- Expected result: what the clipboard should contain after
- Assertion: specific property + expected value
Current context: {context}""",

    "Recommend": """You are a PEGA UI architect. Based on the similar sections shown,
recommend which pattern to reuse or base a new section on.
Include: layout type, controls needed, data source, visible-when, repeating structure.
Be specific — reference actual rule names from the codebase context.
Current context: {context}""",

    "Mentor": """You are a PEGA platform mentor. Answer clearly and practically.
- Use PEGA terminology correctly
- Reference standard patterns (Obj-Open, Obj-Save, Data Pages, Sections)
- Give concrete examples when possible
- If unsure, say so and suggest where to look in PEGA docs
Current context: {context}""",
}

# ── Chat endpoint (plain JSON – works in all browsers) ────────────────────────
@app.post("/chat")
def chat(req: ChatRequest):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"intent": "Error", "text": "ANTHROPIC_API_KEY not set in .env file."}

    intent = detect_intent(req.message)

    # RAG: get similar rules as context
    rule_type_filter = "Section" if intent == "Recommend" else None
    similar = rag_lookup(req.message, rule_type=rule_type_filter, n=4)
    rag_context = format_similar(similar)

    # Build context string
    ctx_parts = []
    if req.rule_name:  ctx_parts.append(f"Open rule: {req.rule_name}")
    if req.rule_class: ctx_parts.append(f"Class: {req.rule_class}")
    if req.rule_set:   ctx_parts.append(f"RuleSet: {req.rule_set}")
    if not ctx_parts:  ctx_parts.append("No rule currently open")
    context_str = " | ".join(ctx_parts)

    system = SYSTEM_PROMPTS[intent].format(context=context_str)

    messages = []
    for turn in req.history[-6:]:
        messages.append({"role": turn["role"], "content": turn["content"]})

    user_content = req.message
    if rag_context:
        user_content += "\n" + rag_context
    messages.append({"role": "user", "content": user_content})

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=2048,
            system=system,
            messages=messages,
        )
        text = response.content[0].text
    except Exception as e:
        text = f"Error calling Claude: {e}"

    return {"intent": intent, "text": text}

# ── KB status endpoint ────────────────────────────────────────────────────────
@app.get("/kb-status")
def kb_status():
    try:
        store = get_store()
        count = store.count()
        types = store.list_rule_types()
        return {"count": count, "rule_types": types, "status": "ready"}
    except Exception as e:
        return {"count": 0, "rule_types": [], "status": f"error: {e}"}

# ── Wiki Agent endpoints ───────────────────────────────────────────────────────
class WikiRequest(BaseModel):
    instruction: str
    page_path: str = ""
    author: str = "PEGA LSA"

class WikiPushRequest(BaseModel):
    page_path: str
    markdown: str

@app.post("/wiki/generate")
async def wiki_generate(req: WikiRequest):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY not set"}
    if not ADO_PAT:
        return {"error": "AZURE_DEVOPS_PAT not set in .env"}
    try:
        import asyncio
        from wiki.wiki_agent import WikiAgent
        agent = WikiAgent(ADO_ORG, ADO_PROJECT, ADO_WIKI_ID, ADO_PAT, api_key, KB_DIR)
        # Run blocking IO in thread pool so server stays responsive
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: agent.generate(req.instruction, req.page_path or None, req.author)
        )
        return result
    except Exception as e:
        logger.exception("Wiki generate error")
        return {"error": str(e)}

@app.post("/wiki/push")
def wiki_push(req: WikiPushRequest):
    if not ADO_PAT:
        return {"error": "AZURE_DEVOPS_PAT not set in .env"}
    try:
        from wiki.wiki_writer import WikiWriter
        writer = WikiWriter(ADO_ORG, ADO_PROJECT, ADO_WIKI_ID, ADO_PAT)
        result = writer.create_or_update(req.page_path, req.markdown)
        return {"status": "ok", "path": req.page_path, "id": result.get("id")}
    except Exception as e:
        logger.exception("Wiki push error")
        return {"error": str(e)}

@app.get("/wiki/pages")
def wiki_pages():
    if not ADO_PAT:
        return {"error": "AZURE_DEVOPS_PAT not set"}
    try:
        from wiki.wiki_reader import WikiReader
        reader = WikiReader(ADO_ORG, ADO_PROJECT, ADO_WIKI_ID, ADO_PAT)
        return {"pages": reader.list_pages()}
    except Exception as e:
        return {"error": str(e)}

# ── Chat UI ───────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def index():
    return HTML_PAGE

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PEGA Developer Copilot</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', Arial, sans-serif; background: #0d1117; color: #e6edf3; height: 100vh; display: flex; flex-direction: column; }

  /* Header */
  #header { background: #161b22; border-bottom: 1px solid #30363d; padding: 12px 20px; display: flex; align-items: center; gap: 12px; }
  #header h1 { font-size: 16px; font-weight: 600; color: #58a6ff; }
  #kb-status { font-size: 12px; color: #8b949e; margin-left: auto; }
  #kb-status.ready { color: #3fb950; }

  /* Context bar */
  #context-bar { background: #161b22; border-bottom: 1px solid #30363d; padding: 8px 20px; display: flex; gap: 10px; flex-wrap: wrap; }
  .ctx-field { display: flex; align-items: center; gap: 6px; font-size: 12px; }
  .ctx-field label { color: #8b949e; }
  .ctx-field input { background: #0d1117; border: 1px solid #30363d; color: #e6edf3; padding: 3px 8px; border-radius: 4px; font-size: 12px; width: 180px; }
  .ctx-field input:focus { outline: none; border-color: #58a6ff; }

  /* Chat log */
  #log { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 14px; }
  .bubble { max-width: 85%; padding: 12px 16px; border-radius: 10px; font-size: 14px; line-height: 1.6; }
  .bubble.user { background: #1f6feb; align-self: flex-end; border-bottom-right-radius: 3px; }
  .bubble.bot  { background: #161b22; border: 1px solid #30363d; align-self: flex-start; border-bottom-left-radius: 3px; }
  .bubble.bot code { background: #0d1117; padding: 1px 5px; border-radius: 3px; font-size: 13px; color: #79c0ff; font-family: 'Consolas', monospace; }
  .bubble.bot pre { background: #0d1117; padding: 12px; border-radius: 6px; overflow-x: auto; margin: 8px 0; }
  .bubble.bot pre code { background: none; padding: 0; color: #e6edf3; }
  .bubble.bot strong { color: #58a6ff; }
  .bubble.bot ul, .bubble.bot ol { padding-left: 20px; }
  .bubble.bot li { margin: 3px 0; }
  .bubble.bot h1,.bubble.bot h2,.bubble.bot h3 { color: #58a6ff; margin: 10px 0 5px; font-size: 14px; }
  .bubble.bot table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 13px; }
  .bubble.bot th { background: #21262d; padding: 6px 10px; border: 1px solid #30363d; text-align: left; }
  .bubble.bot td { padding: 5px 10px; border: 1px solid #30363d; }

  /* Intent badge */
  .badge { display: inline-block; font-size: 10px; padding: 2px 8px; border-radius: 10px; margin-bottom: 8px; font-weight: 600; letter-spacing: 0.5px; }
  .badge-Generate  { background: #1a4731; color: #3fb950; }
  .badge-Debug     { background: #3d2b00; color: #e3b341; }
  .badge-Review    { background: #0c2d6b; color: #58a6ff; }
  .badge-Test      { background: #2d1b69; color: #a371f7; }
  .badge-Recommend { background: #1a3a4d; color: #39d0f0; }
  .badge-Mentor    { background: #2a1f3d; color: #d2a8ff; }

  /* Input area */
  #footer { padding: 14px 20px; background: #161b22; border-top: 1px solid #30363d; display: flex; gap: 10px; align-items: flex-end; }
  #input { flex: 1; background: #0d1117; border: 1px solid #30363d; color: #e6edf3; padding: 10px 14px; border-radius: 8px; font-size: 14px; resize: none; min-height: 44px; max-height: 120px; font-family: inherit; }
  #input:focus { outline: none; border-color: #58a6ff; }
  #send { background: #1f6feb; color: white; border: none; padding: 10px 20px; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 500; white-space: nowrap; }
  #send:hover { background: #388bfd; }
  #send:disabled { background: #21262d; color: #6e7681; cursor: not-allowed; }

  /* Suggestions */
  #suggestions { display: flex; gap: 8px; flex-wrap: wrap; padding: 8px 20px 0; }
  .sug { background: #21262d; border: 1px solid #30363d; color: #8b949e; padding: 4px 12px; border-radius: 14px; font-size: 12px; cursor: pointer; }
  .sug:hover { border-color: #58a6ff; color: #58a6ff; }

  /* Tabs */
  #tabs { display: flex; background: #161b22; border-bottom: 1px solid #30363d; padding: 0 20px; }
  .tab { padding: 10px 18px; font-size: 13px; color: #8b949e; cursor: pointer; border-bottom: 2px solid transparent; }
  .tab.active { color: #58a6ff; border-bottom-color: #58a6ff; }
  .tab-panel { display: none; flex: 1; flex-direction: column; overflow: hidden; }
  .tab-panel.active { display: flex; }

  /* Wiki panel */
  #wiki-panel { padding: 20px; gap: 14px; overflow-y: auto; }
  #wiki-instruction { width: 100%; background: #0d1117; border: 1px solid #30363d; color: #e6edf3; padding: 10px 14px; border-radius: 8px; font-size: 14px; resize: vertical; min-height: 80px; font-family: inherit; }
  #wiki-instruction:focus { outline: none; border-color: #58a6ff; }
  #wiki-path { width: 100%; background: #0d1117; border: 1px solid #30363d; color: #e6edf3; padding: 8px 12px; border-radius: 6px; font-size: 13px; font-family: 'Consolas', monospace; }
  #wiki-path:focus { outline: none; border-color: #58a6ff; }
  .wiki-row { display: flex; gap: 10px; align-items: center; }
  .wiki-label { font-size: 12px; color: #8b949e; white-space: nowrap; }
  #wiki-generate { background: #1f6feb; color: white; border: none; padding: 10px 20px; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 500; }
  #wiki-generate:hover { background: #388bfd; }
  #wiki-generate:disabled { background: #21262d; color: #6e7681; cursor: not-allowed; }
  #wiki-preview { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; font-size: 13px; line-height: 1.7; white-space: pre-wrap; font-family: 'Consolas', monospace; min-height: 200px; display: none; overflow-x: auto; }
  #wiki-actions { display: none; gap: 10px; }
  #wiki-push { background: #238636; color: white; border: none; padding: 10px 20px; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 500; }
  #wiki-push:hover { background: #2ea043; }
  #wiki-copy { background: #21262d; color: #e6edf3; border: 1px solid #30363d; padding: 10px 16px; border-radius: 8px; cursor: pointer; font-size: 14px; }
  #wiki-status { font-size: 13px; color: #3fb950; display: none; }
  .doc-type-btn { background: #21262d; border: 1px solid #30363d; color: #8b949e; padding: 5px 14px; border-radius: 14px; font-size: 12px; cursor: pointer; }
  .doc-type-btn.selected { background: #1f3a6e; border-color: #58a6ff; color: #58a6ff; }
  #related-pages { font-size: 12px; color: #8b949e; padding: 8px 0; }
  #related-pages a { color: #58a6ff; text-decoration: none; }

  /* Cursor blink */
  .cursor { display: inline-block; width: 2px; height: 14px; background: #58a6ff; animation: blink 1s infinite; vertical-align: middle; margin-left: 2px; }
  @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }

  /* Scrollbar */
  #log::-webkit-scrollbar, #wiki-panel::-webkit-scrollbar { width: 6px; }
  #log::-webkit-scrollbar-track, #wiki-panel::-webkit-scrollbar-track { background: #0d1117; }
  #log::-webkit-scrollbar-thumb, #wiki-panel::-webkit-scrollbar-thumb { background: #30363d; border-radius: 3px; }
</style>
</head>
<body>

<div id="header">
  <svg width="20" height="20" viewBox="0 0 16 16" fill="#58a6ff"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
  <h1>PEGA Developer Copilot</h1>
  <div id="kb-status">&#x23F3; Loading...</div>
</div>

<div id="tabs">
  <div class="tab active" onclick="switchTab('chat')">&#x1F4AC; Chat</div>
  <div class="tab" onclick="switchTab('wiki')">&#x1F4DD; Wiki Agent</div>
</div>

<!-- ── CHAT PANEL ─────────────────────────────── -->
<div id="chat-panel" class="tab-panel active" style="flex-direction:column;">
  <div id="context-bar">
    <div class="ctx-field"><label>Rule Name</label><input id="ctx-rule" placeholder="e.g. PROCESSINCOMINGEMAILS"></div>
    <div class="ctx-field"><label>Class</label><input id="ctx-class" placeholder="e.g. WKTAAPP-RMS-WORK"></div>
    <div class="ctx-field"><label>RuleSet</label><input id="ctx-ruleset" placeholder="e.g. RMS"></div>
  </div>
  <div id="suggestions">
    <span class="sug" onclick="fillInput('@recommend a section to show a list of occurrences with filters')">&#x1F50D; Recommend section</span>
    <span class="sug" onclick="fillInput('@generate an Activity to validate participant details and update case')">&#x26A1; Generate activity</span>
    <span class="sug" onclick="fillInput('@review the current activity for best practices')">&#x2705; Review rule</span>
    <span class="sug" onclick="fillInput('@debug why my activity fails when attachment list is empty')">&#x1F41B; Debug issue</span>
    <span class="sug" onclick="fillInput('@test write unit test cases for the current activity')">&#x1F9EA; Write tests</span>
    <span class="sug" onclick="fillInput('how does Obj-Open work in PEGA activities?')">&#x1F4D6; Mentor</span>
  </div>
  <div id="log"></div>
  <div id="footer">
    <textarea id="input" placeholder="Ask anything... @generate @debug @review @test @recommend or just ask a question" rows="1"></textarea>
    <button id="send" onclick="sendMessage()">Send</button>
  </div>
</div>

<!-- ── WIKI AGENT PANEL ───────────────────────── -->
<div id="wiki-panel" class="tab-panel" style="flex-direction:column;overflow-y:auto;padding:20px;gap:14px;">

  <div style="font-size:13px;color:#8b949e;">
    Describe what document you want to create or update. The agent will generate a fully structured document with Mermaid diagrams and links to related wiki pages, then push it to Azure DevOps Wiki.
  </div>

  <div>
    <div class="wiki-label" style="margin-bottom:6px;">Document type</div>
    <div style="display:flex;gap:8px;">
      <span class="doc-type-btn selected" onclick="selectDocType(this,'hld')">&#x1F3D7; HLD</span>
      <span class="doc-type-btn" onclick="selectDocType(this,'tdd')">&#x2699;&#xFE0F; Technical Design</span>
      <span class="doc-type-btn" onclick="selectDocType(this,'adr')">&#x1F4CB; ADR</span>
    </div>
  </div>

  <div>
    <div class="wiki-label" style="margin-bottom:6px;">Your instruction</div>
    <textarea id="wiki-instruction" placeholder="e.g. Create a high level design for the SCT DL9 integration with the Driver Licensing Register API, including case design, data model, and sequence diagram"></textarea>
  </div>

  <div>
    <div class="wiki-label" style="margin-bottom:6px;">Wiki page path (optional — auto-generated if empty)</div>
    <input id="wiki-path" type="text" placeholder="/Home - Waka Kotahi wiki/SCT-DL9/SCT-DL9-HLD">
  </div>

  <div class="wiki-row">
    <button id="wiki-generate" onclick="generateWikiDoc()">&#x2728; Generate Document</button>
    <span id="wiki-status"></span>
  </div>

  <div id="related-pages"></div>

  <div id="wiki-preview"></div>

  <div id="wiki-actions" style="display:none;flex-direction:row;gap:10px;padding-top:8px;">
    <button id="wiki-push" onclick="pushToWiki()">&#x1F680; Push to Azure DevOps Wiki</button>
    <button id="wiki-copy" onclick="copyMarkdown()">&#x1F4CB; Copy Markdown</button>
  </div>

</div>

<script>
  var conversationHistory = [];
  var busy = false;
  var wikiMarkdown = '';
  var wikiPath = '';
  var selectedDocType = 'hld';

  // Check KB status on load
  fetch('/kb-status').then(r => r.json()).then(d => {
    var el = document.getElementById('kb-status');
    if (d.status === 'ready') {
      el.textContent = '&#x2705; KB: ' + d.count + ' rules';
      el.style.color = '#3fb950';
    } else {
      el.textContent = '&#x26A0;&#xFE0F; KB: ' + d.status;
    }
  });

  // Tab switching
  function switchTab(name) {
    document.querySelectorAll('.tab').forEach(function(t,i) {
      t.classList.toggle('active', (i===0&&name==='chat')||(i===1&&name==='wiki'));
    });
    document.getElementById('chat-panel').classList.toggle('active', name==='chat');
    document.getElementById('wiki-panel').classList.toggle('active', name==='wiki');
  }

  // Doc type selection
  function selectDocType(el, type) {
    document.querySelectorAll('.doc-type-btn').forEach(function(b){ b.classList.remove('selected'); });
    el.classList.add('selected');
    selectedDocType = type;
  }

  // Welcome message
  addBubble('bot', null, `👋 **Welcome to PEGA Developer Copilot**

Your RMS knowledge base is loaded with **669 rules** from your codebase.

**What I can do:**
- 🔍 **@recommend** — find the best existing section/harness for your requirement
- ⚡ **@generate** — create a new rule spec based on your codebase patterns  
- 🐛 **@debug** — diagnose why a rule is failing
- ✅ **@review** — check a rule against PEGA best practices
- 🧪 **@test** — generate PegaUnit test cases
- 📖 **Ask anything** — I'm your PEGA mentor

_Set the rule context fields above if you're working on a specific rule._`);

  function fillInput(text) {
    document.getElementById('input').value = text;
    document.getElementById('input').focus();
  }

  function addBubble(role, id, content) {
    var log = document.getElementById('log');
    var div = document.createElement('div');
    div.className = 'bubble ' + role;
    if (id) div.id = id;
    if (content) div.innerHTML = renderMarkdown(content);
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    return div;
  }

  function renderMarkdown(text) {
    // Code blocks
    text = text.replace(/```([\\s\\S]*?)```/g, function(_, code) {
      return '<pre><code>' + escHtml(code.trim()) + '</code></pre>';
    });
    // Inline code
    text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Bold
    text = text.replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>');
    // Headers
    text = text.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    text = text.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    text = text.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    // Table rows
    text = text.replace(/^\\|(.+)\\|$/gm, function(line) {
      if (line.match(/^\\|[-| ]+\\|$/)) return '<tr class="sep"></tr>';
      var cells = line.split('|').slice(1,-1);
      var tag = line.includes('---') ? '' : '<tr>' + cells.map(c => '<td>' + c.trim() + '</td>').join('') + '</tr>';
      return tag;
    });
    text = text.replace(/(<tr>.*?<\\/tr>\\n?)+/gs, '<table>$&</table>');
    // Lists
    text = text.replace(/^- (.+)$/gm, '<li>$1</li>');
    text = text.replace(/(<li>.*<\\/li>\\n?)+/gs, '<ul>$&</ul>');
    text = text.replace(/^\\d+\\. (.+)$/gm, '<li>$1</li>');
    // Line breaks
    text = text.replace(/\\n\\n/g, '<br><br>');
    text = text.replace(/\\n/g, '<br>');
    return text;
  }

  function escHtml(text) {
    return text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function sendMessage() {
    if (busy) return;
    var input = document.getElementById('input');
    var msg = input.value.trim();
    if (!msg) return;

    busy = true;
    input.value = '';
    input.disabled = true;
    document.getElementById('send').disabled = true;

    addBubble('user', null, escHtml(msg));

    var thinkId = 'think-' + Date.now();
    var botBubble = addBubble('bot', thinkId, '');
    var accumulated = '';
    var intentBadge = '';

    var ruleName   = document.getElementById('ctx-rule').value.trim();
    var ruleClass  = document.getElementById('ctx-class').value.trim();
    var ruleSet    = document.getElementById('ctx-ruleset').value.trim();

    // Show thinking indicator
    botBubble.innerHTML = '<span style="color:#8b949e;font-style:italic">&#x23F3; Thinking...</span>';

    fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg, rule_name: ruleName, rule_class: ruleClass, rule_set: ruleSet, history: conversationHistory })
    }).then(function(response) {
      if (!response.ok) throw new Error('HTTP ' + response.status);
      return response.json();
    }).then(function(data) {
      var log = document.getElementById('log');
      var badge = data.intent ? '<span class="badge badge-' + data.intent + '">' + data.intent.toUpperCase() + '</span><br>' : '';
      var text = data.text || '_(empty response)_';
      botBubble.innerHTML = badge + renderMarkdown(text);
      log.scrollTop = log.scrollHeight;

      conversationHistory.push({ role: 'user', content: msg });
      conversationHistory.push({ role: 'assistant', content: text });
      if (conversationHistory.length > 12) conversationHistory = conversationHistory.slice(-12);

      busy = false;
      input.disabled = false;
      document.getElementById('send').disabled = false;
      input.focus();
    }).catch(function(err) {
      botBubble.innerHTML = '&#x274C; Error: ' + err.message;
      busy = false;
      input.disabled = false;
      document.getElementById('send').disabled = false;
    });
  }

  // Enter to send (Shift+Enter for newline)
  document.getElementById('input').addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });

  // Auto-resize textarea
  document.getElementById('input').addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 120) + 'px';
  });

  // ── Wiki Agent functions ────────────────────────────────────────────────────
  function generateWikiDoc() {
    var instruction = document.getElementById('wiki-instruction').value.trim();
    if (!instruction) { alert('Please enter an instruction.'); return; }

    var btn = document.getElementById('wiki-generate');
    var statusEl = document.getElementById('wiki-status');
    var previewEl = document.getElementById('wiki-preview');
    var actionsEl = document.getElementById('wiki-actions');
    var relatedEl = document.getElementById('related-pages');

    btn.disabled = true;
    btn.textContent = '⏳ Generating...';
    statusEl.style.display = 'none';
    previewEl.style.display = 'none';
    actionsEl.style.display = 'none';
    relatedEl.innerHTML = '';
    wikiMarkdown = '';

    fetch('/wiki/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        instruction: instruction,
        page_path: document.getElementById('wiki-path').value.trim(),
        author: 'PEGA LSA'
      })
    }).then(function(r) { return r.json(); })
    .then(function(data) {
      btn.disabled = false;
      btn.textContent = '✨ Generate Document';

      if (data.error) {
        statusEl.textContent = '❌ ' + data.error;
        statusEl.style.color = '#f85149';
        statusEl.style.display = 'block';
        return;
      }

      wikiMarkdown = data.markdown;
      wikiPath = data.page_path;

      // Show suggested path
      document.getElementById('wiki-path').value = data.page_path;

      // Show related pages
      if (data.related_pages && data.related_pages.length > 0) {
        relatedEl.innerHTML = '<strong style="color:#8b949e;font-size:12px;">Related pages found and linked:</strong><br>' +
          data.related_pages.map(function(p) {
            return '<a href="' + p.link + '" target="_blank">' + p.path.split('/').pop() + '</a>';
          }).join(' &bull; ');
      }

      // Show preview (raw markdown)
      previewEl.textContent = wikiMarkdown;
      previewEl.style.display = 'block';
      actionsEl.style.display = 'flex';
    })
    .catch(function(err) {
      btn.disabled = false;
      btn.textContent = '✨ Generate Document';
      statusEl.textContent = '❌ Error: ' + err.message;
      statusEl.style.color = '#f85149';
      statusEl.style.display = 'block';
    });
  }

  function pushToWiki() {
    if (!wikiMarkdown || !wikiPath) return;
    var pushBtn = document.getElementById('wiki-push');
    var statusEl = document.getElementById('wiki-status');
    pushBtn.disabled = true;
    pushBtn.textContent = '⏳ Pushing...';
    statusEl.style.display = 'none';

    fetch('/wiki/push', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ page_path: wikiPath, markdown: wikiMarkdown })
    }).then(function(r) { return r.json(); })
    .then(function(data) {
      pushBtn.disabled = false;
      pushBtn.textContent = '🚀 Push to Azure DevOps Wiki';
      if (data.error) {
        statusEl.textContent = '❌ ' + data.error;
        statusEl.style.color = '#f85149';
      } else {
        statusEl.textContent = '✅ Published to Wiki: ' + data.path;
        statusEl.style.color = '#3fb950';
      }
      statusEl.style.display = 'block';
    })
    .catch(function(err) {
      pushBtn.disabled = false;
      pushBtn.textContent = '🚀 Push to Azure DevOps Wiki';
      statusEl.textContent = '❌ ' + err.message;
      statusEl.style.color = '#f85149';
      statusEl.style.display = 'block';
    });
  }

  function copyMarkdown() {
    if (!wikiMarkdown) return;
    navigator.clipboard.writeText(wikiMarkdown).then(function() {
      var btn = document.getElementById('wiki-copy');
      btn.textContent = '✅ Copied!';
      setTimeout(function(){ btn.textContent = '📋 Copy Markdown'; }, 2000);
    });
  }
</script>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn
    print("\n" + "="*50)
    print("  PEGA Developer Copilot")
    print("  Open: http://localhost:8000")
    print("="*50 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
