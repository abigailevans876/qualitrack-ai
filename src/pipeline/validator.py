import re
from typing import Any, Dict, Optional, Tuple


class ConstraintValidator:
    """
    Filter 5: Joint Commission Deterministic Constraint Validator.
    Enforces 0.0 <= rate <= 1.0 (0% to 100%) and numerator <= denominator
    across BOTH candidate patches and syntax-healthy formulas.
    """

    @staticmethod
    def validate_rate_formula(
        formula: str,
        evaluated_value: Optional[float],
        sheet_cells: Dict[str, Any],
    ) -> Tuple[bool, Optional[str], Optional[float], Optional[float]]:
        """
        Returns (is_valid, violation_reason, numerator, denominator).
        """
        numerator: Optional[float] = None
        denominator: Optional[float] = None

        m_div = re.match(r"^=([A-Z]+\d+)/([A-Z]+\d+)$", str(formula).strip(), re.IGNORECASE)
        if m_div:
            num_c, den_c = m_div.groups()
            num_v = sheet_cells.get(num_c.upper(), {}).get("cached_value")
            den_v = sheet_cells.get(den_c.upper(), {}).get("cached_value")
            if isinstance(num_v, (int, float)) and isinstance(den_v, (int, float)):
                numerator = float(num_v)
                denominator = float(den_v)
                if denominator <= 0:
                    return False, "Denominator must be greater than zero", numerator, denominator
                evaluated_value = numerator / denominator
                if numerator > denominator:
                    return (
                        False,
                        f"BOUNDS_VIOLATION: Numerator ({numerator}) exceeds Denominator ({denominator})",
                        numerator,
                        denominator,
                    )

        if evaluated_value is not None and isinstance(evaluated_value, (int, float)):
            # If formula is a rate/ratio formula, enforce 0.0 <= rate <= 1.0
            if m_div or "rate" in str(formula).lower():
                if evaluated_value < 0.0 or evaluated_value > 1.0:
                    return (
                        False,
                        f"BOUNDS_VIOLATION: Rate {evaluated_value * 100:.1f}% outside [0%, 100%]",
                        numerator,
                        denominator,
                    )

        return True, None, numerator, denominator