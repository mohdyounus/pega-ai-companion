"""
templates.py
Document templates for PEGA LSA documentation.
Used by WikiAgent to structure generated content.
"""
from __future__ import annotations
from datetime import date


def hld_template(feature: str, author: str = "PEGA LSA") -> str:
    today = date.today().strftime("%d %B %Y")
    return f"""# {feature} — High Level Design

| | |
|---|---|
| **Author** | {author} |
| **Date** | {today} |
| **Status** | Draft |
| **Version** | 0.1 |

---

## 1. Overview

> _Provide a concise description of the feature, its business purpose, and scope._

**Business Need:**

**In Scope:**

**Out of Scope:**

---

## 2. Architecture Diagram

```mermaid
graph TD
    A[User / Portal] -->|Request| B[PEGA Case]
    B --> C[Integration Layer]
    C --> D[External API / System]
    D -->|Response| C
    C --> B
    B --> E[Outcome / Decision]
```

---

## 3. Case Design

### Case Types

| Case Type | Class | Description |
|-----------|-------|-------------|
| | | |

### Case Lifecycle / Flow

```mermaid
stateDiagram-v2
    [*] --> New
    New --> Pending_Review: Submit
    Pending_Review --> Approved: Approve
    Pending_Review --> Rejected: Reject
    Approved --> [*]
    Rejected --> [*]
```

### Stages and Steps

---

## 4. Data Model

### Key Properties

| Property | Type | Class | Description |
|----------|------|-------|-------------|
| | | | |

### Data Model Diagram

```mermaid
erDiagram
    CASE ||--o{{ PARTICIPANT : has
    CASE {{
        string pyID
        string pyLabel
        string pyStatusWork
    }}
    PARTICIPANT {{
        string Name
        string ID
    }}
```

---

## 5. Integration Design

### External Systems

| System | Direction | Protocol | Purpose |
|--------|-----------|----------|---------|
| | | REST/SOAP | |

### Sequence Diagram

```mermaid
sequenceDiagram
    actor User
    participant PEGA
    participant ExternalAPI
    User->>PEGA: Initiates request
    PEGA->>ExternalAPI: API call
    ExternalAPI-->>PEGA: Response
    PEGA-->>User: Outcome
```

### Connect-REST / Data Page Details

---

## 6. UI Design

### Sections / Harnesses

| Rule Name | Class | Purpose |
|-----------|-------|---------|
| | | |

### Portal / Channel

---

## 7. Security & Access Control

### Access Groups / Roles

| Role | Access Level | Restriction |
|------|-------------|-------------|
| | | |

### Data Sensitivity

---

## 8. Non-Functional Requirements

| Requirement | Target | Notes |
|-------------|--------|-------|
| Performance | | |
| Availability | | |
| Scalability | | |
| Auditing | | |

---

## 9. Related Documents

> _Links to related wiki pages, designs, and specs_

- 

---

## 10. Open Questions / Decisions

| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | | | Open |

---

## 11. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | {today} | {author} | Initial draft |
"""


def tdd_template(feature: str, author: str = "PEGA LSA") -> str:
    today = date.today().strftime("%d %B %Y")
    return f"""# {feature} — Technical Design Document

| | |
|---|---|
| **Author** | {author} |
| **Date** | {today} |
| **Status** | Draft |

---

## 1. Purpose
## 2. Technical Architecture
## 3. Activity / Flow Design
## 4. Data Page Design
## 5. Decision Logic (When / Declare)
## 6. Error Handling
## 7. Performance Considerations
## 8. Unit Test Cases
## 9. Related Documents
"""


def adr_template(decision: str, author: str = "PEGA LSA") -> str:
    today = date.today().strftime("%d %B %Y")
    return f"""# ADR: {decision}

| | |
|---|---|
| **Date** | {today} |
| **Author** | {author} |
| **Status** | Proposed |

## Context
## Decision
## Consequences
## Alternatives Considered
"""


TEMPLATES = {
    "hld": hld_template,
    "tdd": tdd_template,
    "adr": adr_template,
}


def get_template(doc_type: str, title: str, author: str = "PEGA LSA") -> str:
    fn = TEMPLATES.get(doc_type.lower())
    if fn:
        return fn(title, author)
    return hld_template(title, author)
