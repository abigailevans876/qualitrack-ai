import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
from openpyxl.formula import Tokenizer
from src.models import FaultEvent, FaultType


CELL_REF_RE = re.compile(r"\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?")
EXTERNAL_PATH_RE = re.compile(r"(\\\\[^\]]+|\[[^\]]+\.xls[xm]?\])", re.IGNORECASE)


class DependencyParser:
    """Filter 2: Formula AST Tokenizer, Cell Dependency DAG builder, and Explicit Fault Scanner."""

    @staticmethod
    def tokenize_formula(formula: str) -> List[str]:
        if not isinstance(formula, str) or not formula.startswith("="):
            return []
        try:
            tok = Tokenizer(formula)
            return [t.value for t in tok.items]
        except Exception:
            return re.findall(r"[A-Z_]+|\d+|[():,+\-/*=]|#REF!|#DIV/0!|#VALUE!|#N/A", formula)

    @classmethod
    def build_dag_and_isolate_faults(
        cls,
        upload_id: str,
        department_id: str,
        sheet_matrix: Dict[str, Dict[str, Any]],
    ) -> Tuple[Dict[str, List[str]], List[FaultEvent], List[Dict[str, Any]]]:
        dag: Dict[str, List[str]] = {}
        faults: List[FaultEvent] = []
        healthy_formulas: List[Dict[str, Any]] = []
        now_iso = datetime.now(timezone.utc).isoformat()

        for sheet_name, sdata in sheet_matrix.items():
            cells = sdata["cells"]
            for coord, cinfo in cells.items():
                if not cinfo["is_formula"]:
                    continue

                raw = str(cinfo["raw"])
                cached = str(cinfo["cached_value"]) if cinfo["cached_value"] is not None else ""
                node_key = f"{sheet_name}!{coord}"

                # Build dependency edges
                refs = CELL_REF_RE.findall(raw)
                dag[node_key] = [f"{sheet_name}!{r}" for r in refs]

                fault_type = None
                if "#REF!" in raw or "#REF!" in cached:
                    fault_type = FaultType.REF_ERROR
                elif "#DIV/0!" in raw or "#DIV/0!" in cached:
                    fault_type = FaultType.DIV_ZERO
                elif "#VALUE!" in raw or "#VALUE!" in cached:
                    fault_type = FaultType.VALUE_ERROR
                elif EXTERNAL_PATH_RE.search(raw):
                    fault_type = FaultType.BROKEN_PATH

                if fault_type:
                    faults.append(
                        FaultEvent(
                            fault_id=f"flt_{uuid.uuid4().hex[:8]}",
                            upload_id=upload_id,
                            department_id=department_id,
                            sheet_name=sheet_name,
                            cell_coordinate=coord,
                            corrupted_formula=raw,
                            fault_type=fault_type,
                            detected_at=now_iso,
                        )
                    )
                else:
                    healthy_formulas.append(
                        {
                            "sheet_name": sheet_name,
                            "cell_coordinate": coord,
                            "raw_formula": raw,
                            "cached_value": cinfo["cached_value"],
                        }
                    )

        return dag, faults, healthy_formulas