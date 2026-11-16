# QualiTrack AI

QualiTrack AI is an intelligent data-quality and governance platform for validating, repairing, and governing structured spreadsheet-driven workflows. It combines ingestion, parsing, rule validation, AI-assisted repair, and policy enforcement into a single pipeline designed for operational trust and explainability.

The project is structured to support enterprise-style quality control for workbook-based data intake, with emphasis on traceability, human-in-the-loop review, role-based access control, and deterministic benchmarking.

## Why QualiTrack AI?

Modern data pipelines often fail silently: bad workbook formats, malformed rows, policy violations, and untracked manual overrides create quality debt. QualiTrack AI addresses this by creating a transparent, auditable pipeline that:

- ingests workbook files from operational sources
- parses and normalizes content into structured records
- validates results against domain-specific rules
- repairs common defects through targeted automated logic
- enforces governance rules and access boundaries
- supports human review when automation cannot resolve uncertainty

## Core capabilities

- Data intake and parsing for workbook-style inputs
- Rule-based validation and anomaly detection
- Repair workflows to correct frequent quality issues
- Role-based governance, access enforcement, and approval states
- Human-in-the-loop intervention for escalated cases
- Deterministic benchmark generation for repeatable evaluation
- API-driven integration and automated validation suite

## Architecture overview

QualiTrack AI is organized around a modular processing pipeline and governance layer:

- `src/main.py` — entry point for service orchestration and API wiring
- `src/models.py` — domain models, enums, and request/response schemas
- `src/database.py` — persistence layer and operational state management
- `src/pipeline/` — ingestion, parsing, validation, repair, and quality analysis stages
- `src/governance/` — RBAC controls and HITL state transitions

The platform is designed to balance automation with accountability: the system may repair issues automatically, but governance safeguards ensure high-risk or sensitive operations remain visible and reviewable.

## Repository structure

```text
qualitrack-ai/
├── README.md
├── LICENSE
├── CONTRIBUTING.md
├── .gitignore
├── requirements.txt
├── data/
│   └── synthetic_workbooks/
├── docs/
├── scripts/
│   └── generate_benchmark.py
├── src/
│   ├── main.py
│   ├── models.py
│   ├── database.py
│   ├── pipeline/
│   │   ├── anchor_engine.py
│   │   ├── ingestion.py
│   │   ├── parser.py
│   │   ├── repair_agent.py
│   │   └── validator.py
│   └── governance/
│       ├── hitl_controller.py
│       └── rbac.py
├── tests/
│   └── test_qualitrack.py
└── .github/

