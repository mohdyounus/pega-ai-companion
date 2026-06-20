# 🤖 PEGA AI Companion

> **Learn from your existing PEGA codebase. Generate new production-ready PEGA rules with AI.**

Built as an extension of [SimplilearnDevOps](https://github.com/Anuj-Agra/SimplilearnDevOps) — adds a full **round-trip engine** to the existing PEGA reverse-engineering toolkit.

---

## 🔁 How It Works

```
┌─────────────────────────────────────────────────────┐
│                  PEGA AI Companion                   │
├─────────────────┬───────────────────────────────────┤
│   LEARN Engine  │        GENERATE Engine             │
│  (reads your    │  (writes new rules grounded        │
│   PEGA export)  │   in YOUR codebase patterns)       │
└────────┬────────┴──────────────┬────────────────────┘
         │                       │
         ▼                       ▼
   Knowledge Base          .zip Rule Archive
   (ChromaDB, local)       (import via PEGA
                            Deployment Manager)
```

---

## 🚀 Quickstart

### 1. Install dependencies
```bash
pip install -r tools/requirements_extended.txt
```

### 2. Set your Anthropic API key
```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### 3. Learn from your PEGA app (run once)
```bash
# First run 'analyse' to generate rule JSON output (existing feature)
python tools/run.py analyse --config config/analysis_config.yaml

# Then index into the knowledge base
python tools/run_extended.py learn --analysis-dir ./workspaces/output
```

### 4. Generate a new PEGA rule
```bash
python tools/run_extended.py generate \
  --type Flow \
  --name KYC-AddressVerify \
  --desc "Verify customer address using a 3rd party REST API" \
  --package
```

### 5. Import into PEGA
Upload the generated `.zip` file via **PEGA Deployment Manager** or **App Studio → Import**.

---

## 📁 Project Structure

```
pega-ai-companion/
├── tools/
│   ├── knowledge/
│   │   ├── vector_store.py        # ChromaDB wrapper (local, persistent)
│   │   ├── embeddings.py          # sentence-transformers (zero API cost)
│   │   └── knowledge_builder.py   # LEARN phase orchestrator
│   ├── generator/
│   │   ├── rule_generator.py      # RAG + Claude Sonnet = new PEGA rules
│   │   ├── xml_formatter.py       # Jinja2 + lxml XML validation
│   │   ├── package_builder.py     # Builds PEGA .zip Rule Archive
│   │   └── templates/
│   │       ├── flow_template.xml
│   │       ├── datapage_template.xml
│   │       ├── activity_template.xml
│   │       └── harness_template.xml
│   ├── run_extended.py            # Extended CLI (learn / generate / package)
│   └── requirements_extended.txt
└── agents/
    └── 10_generator/
        └── system-prompt.md       # Agent 10: PEGA Code Generator
```

---

## 🧩 CLI Reference

### `learn` — Build the knowledge base
```bash
python tools/run_extended.py learn \
  --analysis-dir ./workspaces/output \   # JSON rule files from analyse phase
  --kb-dir ./knowledge_base \            # where to store the vector DB
  --batch-size 20                        # embedding batch size
  --force                                # re-index even if already in KB
```

### `generate` — Generate new PEGA rules
```bash
python tools/run_extended.py generate \
  --type Flow|DataPage|Activity|Harness \
  --name RULE-NAME \
  --desc "Natural language description" \
  --pega-class Work-KYC \               # optional, auto-inferred if omitted
  --n-similar 5 \                       # similar rules to retrieve for context
  --output-dir ./generated \
  --package                             # auto-package as .zip
```

### `package` — Package a result JSON into .zip
```bash
python tools/run_extended.py package \
  --input ./generated/KYC-AddressVerify_result.json \
  --ruleset-name MyRuleset \
  --ruleset-version 01-01-01
```

### `kb-status` — Check knowledge base stats
```bash
python tools/run_extended.py kb-status
```

---

## 💰 Cost Estimate

| Phase | Model used | Cost |
|---|---|---|
| Learn (200 rules) | Claude Haiku | ~$1.80 (one-time) |
| Each generation | Claude Sonnet | ~$0.03 per rule |
| Embeddings | Local (sentence-transformers) | **Free** |
| **12-month total** | | **~$26/year** |

---

## 🔐 Security

- API key is read from `ANTHROPIC_API_KEY` env variable — never hardcoded
- Knowledge base is stored locally in `./knowledge_base/` — never uploaded
- PEGA exports (`.bin`, `.zip`) are `.gitignore`d — never committed
- Generated XML includes `pyDeveloperNote` flagging AI generation for human review

---

## 🏗️ Architecture Decisions

| Decision | Reason |
|---|---|
| **sentence-transformers** for embeddings | Free, local, no API cost for learn phase |
| **ChromaDB** for vector store | Lightweight, file-based, no server needed |
| **Claude Haiku** for learn phase | 12× cheaper than Sonnet for simple summarisation |
| **Claude Sonnet** for generation | Best XML/code generation quality |
| **Jinja2 templates** for XML | Ensures structural correctness before LLM output validation |
| **RAG (5 similar rules)** | Grounds generation in YOUR codebase, not generic patterns |

---

## 📋 Prerequisites

- Python 3.10+
- Anthropic API key (`claude-haiku-4-5` + `claude-sonnet-4-20250514` access)
- PEGA analysis output (from the existing `recursive_analyser.py` pipeline)

---

## 🤝 Based On

This repo extends the PEGA reverse-engineering toolkit from [Anuj-Agra/SimplilearnDevOps](https://github.com/Anuj-Agra/SimplilearnDevOps).
