import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from src.models import AnchoredContext, FaultEvent, FaultType, PatchProposal
from src.pipeline.parser import DependencyParser


class RepairAgent:
    """
    Filter 4: Bounded AI Formula Repair Agent + Sandboxed Compiler Pre-Check.
    - Enforces zero-PHI egress (only structural tokens & header/footer labels).
    - Computes C = 0.40 * S_anchor + 0.35 * S_AST_sim + 0.25 * S_compiler.
    - Suppresses proposals when C < 0.85, drift > 30%, or unresolvable path (NFR-08).
    """

    CONFIDENCE_THRESHOLD = 0.85
    MAX_DRIFT_PCT = 30.0

    @staticmethod
    def build_deidentified_prompt(fault: FaultEvent, ctx: AnchoredContext) -> Dict[str, Any]:
        """Constructs strictly de-identified payload (zero cell values or patient data)."""
        return {
            "fault_type": fault.fault_type.value,
            "target_coordinate": fault.cell_coordinate,
            "corrupted_formula_syntax": fault.corrupted_formula,
            "header_anchor": ctx.header_anchor,
            "footer_anchor": ctx.footer_anchor,
            "detected_row_shift": ctx.detected_row_shift,
            "historical_baseline_syntax": ctx.historical_baseline_formula,
        }

    @staticmethod
    def _levenshtein_tokens(a: List[str], b: List[str]) -> int:
        dp = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
        for i in range(len(a) + 1):
            dp[i][0] = i
        for j in range(len(b) + 1):
            dp[0][j] = j
        for i in range(1, len(a) + 1):
            for j in range(1, len(b) + 1):
                cost = 0 if a[i - 1] == b[j - 1] else 1
                dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
        return dp[-1][-1]

    @classmethod
    def sandbox_evaluate(cls, formula: str, sheet_cells: Dict[str, Any]) -> Tuple[bool, Optional[float]]:
        """Sandboxed Python formula compiler pre-check."""
        if not formula.startswith("=") or "#REF!" in formula or "#DIV/0!" in formula or "#VALUE!" in formula:
            return False, None
        if formula.count("(") != formula.count(")"):
            return False, None

        # Evaluate SUM(ColStart:ColEnd)
        m_sum = re.match(r"^=SUM\(([A-Z]+)(\d+):([A-Z]+)(\d+)\)$", formula.strip(), re.IGNORECASE)
        if m_sum:
            c1, r1, c2, r2 = m_sum.groups()
            if c1.upper() != c2.upper() or int(r1) > int(r2):
                return False, None
            total = 0.0
            for r in range(int(r1), int(r2) + 1):
                val = sheet_cells.get(f"{c1.upper()}{r}", {}).get("cached_value")
                if isinstance(val, (int, float)):
                    total += float(val)
            return True, total

        # Evaluate ratio =CellA/CellB
        m_div = re.match(r"^=([A-Z]+\d+)/([A-Z]+\d+)$", formula.strip(), re.IGNORECASE)
        if m_div:
            num_c, den_c = m_div.groups()
            num_v = sheet_cells.get(num_c.upper(), {}).get("cached_value")
            den_v = sheet_cells.get(den_c.upper(), {}).get("cached_value")
            if not isinstance(num_v, (int, float)) or not isinstance(den_v, (int, float)) or den_v == 0:
                return False, None
            return True, round(float(num_v) / float(den_v), 6)

        return False, None

    @classmethod
    def propose_repair(
        cls,
        fault: FaultEvent,
        ctx: AnchoredContext,
        sheet_cells: Dict[str, Any],
    ) -> Optional[PatchProposal]:
        # Guardrail 1: Template redesign > 30% drift -> suppress automation
        if ctx.drift_percentage > cls.MAX_DRIFT_PCT:
            return None

        # Guardrail 2: Unresolvable external UNC paths cannot be guessed
        if fault.fault_type == FaultType.BROKEN_PATH:
            return None

        # Build zero-PHI prompt struct
        _prompt_payload = cls.build_deidentified_prompt(fault, ctx)

        # Synthesize candidate patch from semantic anchors
        proposed_formula: Optional[str] = None
        rationale = ""

        if fault.fault_type == FaultType.RANGE_DRIFT and ctx.expected_range_formula:
            proposed_formula = ctx.expected_range_formula
            rationale = (
                f"Detected +{ctx.detected_row_shift} inserted row(s) ({', '.join(ctx.inserted_row_spans)}) "
                f"above '{ctx.footer_anchor}'. Expanded formula span to restore full table coverage."
            )
        elif fault.fault_type in (FaultType.REF_ERROR, FaultType.VALUE_ERROR) and ctx.expected_range_formula:
            proposed_formula = ctx.expected_range_formula
            rationale = (
                f"Reconstructed broken reference using semantic table bounds between "
                f"{ctx.header_coord} and {ctx.footer_coord}."
            )
        elif fault.fault_type == FaultType.DIV_ZERO:
            # Check if denominator cell is empty/zero without an obvious anchor fix -> low confidence
            proposed_formula = fault.corrupted_formula

        if not proposed_formula:
            return None

        # Sandboxed compiler pre-check
        passed, _eval_val = cls.sandbox_evaluate(proposed_formula, sheet_cells)
        s_compiler = 1.0 if passed else 0.0

        # Anchor match ratio
        s_anchor = ctx.matched_anchors / max(ctx.total_expected_anchors, 1)

        # Normalized token-level AST similarity against historical baseline
        prop_tokens = DependencyParser.tokenize_formula(proposed_formula)
        base_tokens = DependencyParser.tokenize_formula(ctx.historical_baseline_formula)
        max_len = max(len(prop_tokens), len(base_tokens), 1)
        dist = cls._levenshtein_tokens(prop_tokens, base_tokens)
        s_ast_sim = max(0.0, 1.0 - (dist / max_len))

        confidence = round(0.40 * s_anchor + 0.35 * s_ast_sim + 0.25 * s_compiler, 4)

        # Guardrail 3: Confidence gate >= 0.85 & compiler pre-check must pass
        if not passed or confidence < cls.CONFIDENCE_THRESHOLD:
            return None

        return PatchProposal(
            proposal_id=f"prp_{uuid.uuid4().hex[:8]}",
            fault_id=fault.fault_id,
            proposed_formula=proposed_formula,
            compiler_precheck="PASSED",
            confidence_score=confidence,
            s_anchor=round(s_anchor, 4),
            s_ast_sim=round(s_ast_sim, 4),
            s_compiler=s_compiler,
            original_formula=fault.corrupted_formula,
            rationale=rationale,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )