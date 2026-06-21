# PEGA Developer Copilot — Project Handover

> **GitHub:** https://github.com/mohdyounus/pega-ai-companion  
> **Branch:** `master`  
> **Status:** Working — chat UI running, 669 RMS rules indexed  
> **Last updated:** June 2026

---

## What This Project Is

A **GitHub Copilot for PEGA developers** — an AI assistant that:
1. Learns from a real PEGA application export (JAR/ZIP file)
2. Indexes all rules into a local vector knowledge base (ChromaDB)
3. Provides a web chat UI at `http://localhost:8000` where developers can ask questions, get rule recommendations, generate rule specs, debug, review, and write tests — all using their actual codebase as context (RAG)

The system is currently trained on **RMS_020106** (a Rail Management System PEGA application with 3,414 rules).

---

## Project Structure

```
pega-ai-companion/
├── .env                          # ANTHROPIC_API_KEY=sk-ant-...
├── tools/
│   ├── chat_server.py            # FastAPI web app (the chat UI — START HERE)
│   ├── run_extended.py           # CLI entry point for parse/learn/generate/recommend
│   ├── requirements_extended.txt # Python dependencies
│   ├── parser/
│   │   ├── pega_export_parser.py # Orchestrates full parse pipeline
│   │   ├── jar_extractor.py      # Extracts .jar/.zip PEGA exports
│   │   ├── contents_parser.py    # Parses META-INF/contents.txt
│   │   ├── bin_parser.py         # Decodes .bin rule files (string extraction fallback)
│   │   └── section_parser.py     # Fingerprints Section/Harness rules from rule names
│   ├── knowledge/
│   │   ├── knowledge_builder.py  # Enriches rules with Claude, stores in ChromaDB
│   │   ├── vector_store.py       # ChromaDB wrapper
│   │   └── embeddings.py         # fastembed + _HashEmbedder fallback
│   └── generator/
│       ├── rule_generator.py     # RAG + Claude rule generation
│       ├── xml_formatter.py      # Jinja2 XML templates with json5 fallback
│       ├── package_builder.py    # Produces HTML guide bundle (not binary JAR)
│       └── templates/            # Jinja2 XML templates per rule type
├── knowledge_base/               # ChromaDB files (669 rules indexed — DO NOT DELETE)
├── workspaces/
│   ├── output/                   # 124,373 parsed JSON rule files from RMS
│   └── learn_input/              # 671 focused rules used for learn phase
├── generated/                    # Output from generate command
└── pega_integration/             # Specs for building copilot 100% inside PEGA
    ├── README.md                 # Build checklist
    ├── 01_data_model.md          # PEGA class/property specs
    ├── 02_connect_rest_claude.md # Connect-REST to Anthropic Claude config
    ├── 03_activities.md          # 6 activity specs with system prompts
    └── 04_rest_service_and_js.md # REST Service + full CopilotChat.js + HTML
```

---

## How to Run

### Prerequisites
```powershell
pip install fastapi uvicorn anthropic chromadb fastembed python-dotenv lxml json5
```

### 1. Start the Chat Web App
```powershell
cd pega-ai-companion
$env:PYTHONPATH = ".\tools"
$env:PYTHONIOENCODING = "utf-8"
python tools/chat_server.py
# Open http://localhost:8000
```

### 2. CLI Commands
```powershell
$env:PYTHONPATH = ".\tools"
$env:PYTHONIOENCODING = "utf-8"

# Parse a new PEGA export (JAR or ZIP)
python tools/run_extended.py parse --export-dir C:\path\to\extracted\export

# Build knowledge base from parsed rules
python tools/run_extended.py --kb-dir .\knowledge_base learn --analysis-dir .\workspaces\learn_input

# Recommend a section for a requirement
python tools/run_extended.py --kb-dir .\knowledge_base recommend -r "list of occurrences with search filters"

# Generate a rule spec
python tools/run_extended.py --kb-dir .\knowledge_base generate --type Activity --name ValidateParticipant --desc "Validate participant licence and update case status"

# Check knowledge base status
python tools/run_extended.py --kb-dir .\knowledge_base kb-status
```

---

## Architecture

```
PEGA Export (.zip/.jar)
        │
        ▼
[parse] PegaExportParser
  ├── jar_extractor     → unzip outer ZIP, find rules JAR
  ├── contents_parser   → read contents.txt (128k rules)
  ├── bin_parser        → decode .bin → string extraction (javaobj fallback)
  └── section_parser    → fingerprint Section/Harness by rule name keywords
        │
        ▼  JSON files in workspaces/output/
        │
[learn] KnowledgeBuilder
  ├── Filter to focused rule types (Section/Harness/Activity/Flow/DataPage/...)
  ├── Enrich each rule with Claude Haiku (cheap: ~$0.001/rule)
  ├── Embed with fastembed / _HashEmbedder fallback
  └── Store in ChromaDB (knowledge_base/)
        │
        ▼  669 rules indexed
        │
[chat_server.py / recommend / generate]
  ├── User query → EmbeddingEngine → VectorStore.query() → top-4 similar rules
  ├── RAG context injected into Claude system prompt
  ├── Intent detected: Generate / Debug / Review / Test / Recommend / Mentor
  └── Claude Haiku responds → JSON → browser renders markdown
```

---

## Key Technical Details & Bugs Fixed

### PEGA Binary Format
- PEGA exports are ZIP files → inside is a `.jar` (also a ZIP) → inside are `.bin` rule files
- Large exports (like RMS) have an **outer ZIP** wrapping the rules JAR — must extract first
- `.bin` files have a PEGA proprietary header; Java serialization magic `0xACED 0x0005` found by scanning forward ~406KB into the file
- `javaobj-py3` fails on PEGA custom Java objects → **string extraction fallback** used (regex scan for printable chars)
- `contents.txt` format: `RULE-TYPE CLASS RULENAME #TIMESTAMP * RuleSet:Version * Available * LastUpdated * binfile`

### Windows-Specific Issues Fixed
- **Path length**: `sentence-transformers` (PyTorch) fails on Windows long paths → use `fastembed` instead
- **fastembed ONNX download fails** on restricted networks → `_HashEmbedder` fallback (n-gram hashing, 384-dim, no download needed)
- **Illegal filename chars** in rule names (`!`, `@`, etc.) → sanitized in `_rule_json_path()`
- **Encoding**: `cp1252` doesn't support emojis → removed from all print statements; use `PYTHONIOENCODING=utf-8`

### ChromaDB
- Duplicate ID error when same rule name exists across multiple classes/rulesets
- **Fix**: ID = `{rule_type}_{pega_class}_{ruleset}_{rule_name}` (max 200 chars)
- Must deduplicate within each batch before calling `upsert_batch()`
- Use `store.query()` not `store.search()` — returns `rule_id`, `document`, `metadata`, `distance`

### Claude API
- Model: `claude-haiku-4-5` (learn + chat), `claude-sonnet-4-5` for high-quality generation
- `max_tokens=2048` for chat, `max_tokens=8000` for XML generation
- LLM responses with embedded XML break `json.loads()` → use `json5` + regex fallback in `xml_formatter.py`

### PEGA Import Format
- PEGA Application Import Wizard only accepts **binary JAR** (Java-serialized `.bin`)
- Cannot replicate binary format without Java runtime + PEGA private serialization
- **Workaround**: `package_builder.py` outputs an **HTML creation guide** + XML blueprint + README — developer manually creates the rule in PEGA Designer Studio

### Chat Server
- SSE streaming (`ReadableStream.getReader()`) caused **silent failures** in Chrome/Edge
- **Fix**: switched to plain `POST /chat` returning `{"intent": "...", "text": "..."}` JSON → `response.json()` in frontend
- Intent detection uses keyword matching on the user message

---

## What's Working

| Feature | Status |
|---------|--------|
| Parse PEGA JAR/ZIP export | ✅ Working (tested with RMS 128k rules) |
| Learn / index rules to ChromaDB | ✅ Working (669 rules indexed) |
| Recommend sections by requirement | ✅ Working (CLI + chat) |
| Generate rule spec (Activity/Flow/Section) | ✅ Working (HTML guide bundle output) |
| Web chat UI at localhost:8000 | ✅ Working |
| RAG context injection per query | ✅ Working |
| Intent detection (Generate/Debug/Review/Test/Recommend/Mentor) | ✅ Working |
| Multi-turn conversation history | ✅ Working (last 6 turns) |
| Import generated rules into PEGA directly | ❌ Not possible (binary format restriction) |
| Streaming responses in browser | ❌ Removed — plain JSON more reliable |

---

## What's Not Done Yet (Next Steps)

### High Priority
1. **`recommend` intent in chat** — currently only detected via `@recommend` keyword or "which section". Should also detect "I need a section that..." style queries
2. **Rule context auto-suggest** — when user types a rule name in the context bar, autocomplete from the 669 indexed rules
3. **Better error messages** — if Claude returns an error (rate limit, bad key), surface it clearly in the UI
4. **`start.bat` / `start.ps1` launcher** — one-click startup script for non-technical users

### Medium Priority
5. **Re-parse with better bin extraction** — the `_HashEmbedder` fallback produces lower quality embeddings than fastembed. If ONNX download works, much better semantic search
6. **Generate → PEGA** — write a Java utility (separate project) that takes the XML blueprint and creates proper `.bin` files using PEGA's public API (Pega Platform REST API v1 can create rules via `/api/v1/rules`)
7. **Debug intent with clipboard context** — let developer paste clipboard XML into the chat for context-aware debugging
8. **Test case generation** — currently generates PegaUnit descriptions; could generate actual `.bin` test rule files

### Future / Nice to Have
9. **PEGA-native version** — full copilot built inside PEGA using `pega_integration/` specs (Connect-REST → Claude, Activities as agents, JavaScript chat panel embedded in Developer Harness)
10. **Streaming responses** — use `EventSource` (GET with query param) instead of `fetch` POST to get token-by-token streaming working reliably
11. **Export the knowledge base** — allow the trained 669-rule ChromaDB to be shared/deployed with the app so others don't need to re-parse RMS

---

## PEGA-Native Architecture (Future)

See `pega_integration/` folder for full specs. Summary:

```
Developer in PEGA Designer Studio
        │  (click slider button in Developer Harness)
        ▼
CopilotChat.js (JavaScript section embedded in Harness)
        │  HTTP POST to PEGA REST Service
        ▼
PEGA REST Service  →  Activity: Copilot-ChatOrchestrator
        │
        ├─ Copilot-DetectIntent    (When rule / Activity)
        ├─ Copilot-RAGLookup       (calls Python /recommend endpoint OR uses Data Pages)
        ├─ Copilot-CallClaude      (Connect-REST → Anthropic API)
        └─ Copilot-FormatResponse  (returns JSON to JS)
        │
        ▼
Chat bubble rendered in Harness section
```

The `02_connect_rest_claude.md` has the exact Anthropic endpoint, headers, and request body mapping for PEGA Connect-REST rules.

---

## Data on Disk (Local — Not in Git)

| Path | Contents | Size |
|------|----------|------|
| `knowledge_base/` | ChromaDB vector store — 669 rules | ~50MB |
| `workspaces/output/` | 124,373 JSON rule files from RMS parse | ~2GB |
| `workspaces/learn_input/` | 671 focused rules used for learn | ~5MB |
| `C:\Users\MohammeY\Downloads\RMS_Export_Extracted\` | Extracted RMS rules JAR | ~300MB |

> ⚠️ `knowledge_base/` is in `.gitignore`. Copy it separately when handing over.

---

## Environment Variables

```env
# .env (in project root — never commit this)
ANTHROPIC_API_KEY=sk-ant-api03-...
```

---

## Tested With

- **Python 3.13** on Windows 11
- **RMS_020106_20260621T004707_GMT.zip** — 97MB PEGA export, 128,236 rules total, 3,414 actionable rules
- **Anthropic**: `claude-haiku-4-5` for chat/learn, `claude-sonnet-4-5` for generation
- **ChromaDB 0.4.x** with `_HashEmbedder` (fastembed ONNX download not available on this machine)
