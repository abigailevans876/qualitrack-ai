# QualiTrack-AI & CQ-ARP

**Automated Clinical Quality Performance Metric Validation & Formula Reconciliation Pipeline**

## 1. Project Purpose
Acute-care hospitals track operational compliance indicators mandated by The Joint Commission (TJC) across 17 decentralized clinical departments using desktop Microsoft Excel workbooks. Routine row insertions, moved network files, and manual edits trigger explicit formula errors (`#REF!`, `#DIV/0!`, `#VALUE!`) and silent denominator drift (`RANGE_DRIFT`)[cite: 1, 5].

**QualiTrack-AI** eliminates manual spreadsheet debugging while preserving strict clinical governance:
* **QualiTrack-AI (Enterprise Platform):** Provides upload portals, role-based access control (RBAC), a Human-in-the-Loop (HITL) review workbench, an append-only SHA-256 audit ledger, and executive compliance scorecards.
* **CQ-ARP (Core Processing Engine):** A 5-stage Pipe-and-Filter subsystem that ingests `.xlsx` files, parses formula Abstract Syntax Trees (ASTs), detects semantic table boundary drift, proposes confidence-gated (`>= 0.85`) formula patches, and enforces deterministic regulatory bounds (`0% <= rate <= 100%`).

---

## 2. Solution Architecture Summary
QualiTrack-AI implements the **Data Intelligence** reference architecture using a **Pipe-and-Filter Processing Engine (CQ-ARP)** coupled with a **Service-Oriented Governance Layer**:
1. **Filter 1 (`IngestionWorker`):** Streams binary `.xlsx`/`.xlsm` files via `openpyxl`, strips VBA macros, and computes a SHA-256 file digest[cite: 5].
2. **Filter 2 (`DependencyParser`):** Tokenizes formulas into ASTs, builds an in-memory cell dependency DAG, and isolates `#REF!`, `#DIV/0!`, `#VALUE!`, and broken external UNC paths[cite: 5].
3. **Filter 3 (`SemanticAnchorEngine`):** Maps header/footer table anchors to detect unexpanded ranges (`RANGE_DRIFT`) and halts automation if anchor drift exceeds `30%`[cite: 5].
4. **Filter 4 (`RepairAgent`):** Synthesizes candidate patches using de-identified structural context, executes a sandboxed Python compiler pre-check, and suppresses proposals scoring below `0.85`[cite: 5].
5. **Filter 5 (`ConstraintValidator`):** Deterministically enforces `0% <= rate <= 100%` and `numerator <= denominator` across both repaired and healthy cells[cite: 5].
6. **HITL Controller & Audit Ledger:** Enforces RBAC roles (`Department_Manager`, `Quality_Associate`, `Quality_Director`), requires `DIGEST_VIEWED` verification before batch sign-off, and records every action in a hash-chained `AuditLedger`[cite: 5].

---

## 3. Repository Structure
## ```text
qualitrack-ai/
├── README.md                   # Project documentation, setup, run, and evaluation guide
├── LICENSE                     # MIT License
├── CONTRIBUTING.md             # Contribution rules & architectural guardrails
├── .gitignore                  # Excludes local SQLite DB, venv, and cache artifacts
├── requirements.txt            # Python dependencies
├── data/
│   └── synthetic_workbooks/    # 17 synthetic departmental .xlsx files + ground_truth.json
├── docs/                       # Solution Design Report PDF, Presentation, & GenAI Log
├── scripts/
│   └── generate_benchmark.py   # Deterministic generator for the 17 workbooks & 40 faults
├── src/
│   ├── main.py                 # FastAPI REST API Gateway
│   ├── models.py               # Pydantic schemas, roles, and state enums
│   ├── database.py             # SQLite schema & NFR-07 verification trigger
│   ├── pipeline/               # CQ-ARP Filters 1–5
│   └── governance/             # RBAC enforcement & HITL state machine
└── tests/
    └── test_qualitrack.py      # Automated validation suite (FR-01..06 & NFR-01..08)