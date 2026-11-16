# Contributing to QualiTrack-AI & CQ-ARP

Thank you for contributing to **QualiTrack-AI**! Please adhere to the project's engineering and clinical governance boundaries when submitting changes[cite: 5]:

## Development & Architectural Guardrails
1. **Zero-PHI Egress:** Never pass raw patient counts, medical record numbers, or free-text clinical notes into `RepairAgent` prompts or external model endpoints[cite: 5].
2. **Deterministic Math Only:** All compliance rate calculations (`0% <= rate <= 100%`) and AST sandbox evaluations must run deterministically in Python (`Filter 5`), never delegated to an LLM[cite: 5].
3. **Human-in-the-Loop Authority:** Only `HITLController` may transition metrics to `Associate-Verified` or write to the `AuditLedger`[cite: 5].

## Submitting Changes
1. Fork the repository and create a feature branch (`git checkout -b feature/your-feature`).
2. Add or update automated tests in `tests/test_qualitrack.py`.
3. Verify the full benchmark suite passes:
   ```bash
   pytest -v