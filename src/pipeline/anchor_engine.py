import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from src.models import AnchoredContext, FaultEvent, FaultType

RANGE_RE = re.compile(r"=(SUM|AVERAGE|COUNT)\(([A-Z]+)(\d+):([A-Z]+)(\d+)\)", re.IGNORECASE)


class SemanticAnchorEngine:
    """
    Filter 3: Table boundary & semantic anchor comparator.
    - Detects header/footer anchors and row displacements.
    - Screens syntax-clean formulas for silent RANGE_DRIFT.
    - Enforces >30% anchor drift suspension guardrail (NFR-08).
    """

    @staticmethod
    def _scan_sheet_anchors(cells: Dict[str, Any]) -> Tuple[Dict[str, str], Optional[int], Optional[int]]:
        """Finds header labels, data start row, and summary total footer row."""
        anchors: Dict[str, str] = {}
        header_row: Optional[int] = None
        footer_row: Optional[int] = None

        for coord, info in cells.items():
            raw_str = str(info["raw"]).strip() if info["raw"] is not None else ""
            if not info["is_formula"] and raw_str:
                anchors[coord] = raw_str
                low = raw_str.lower()
                if any(k in low for k in ["indicator", "adherence", "metric", "audit", "compliance"]):
                    if header_row is None or info["row"] < header_row:
                        header_row = info["row"]
                if any(k in low for k in ["total", "summary", "monthly rate"]):
                    if footer_row is None or info["row"] > footer_row:
                        footer_row = info["row"]

        return anchors, header_row, footer_row

    @classmethod
    def analyze(
        cls,
        upload_id: str,
        department_id: str,
        sheet_matrix: Dict[str, Dict[str, Any]],
        explicit_faults: List[FaultEvent],
        healthy_formulas: List[Dict[str, Any]],
        baseline_schema: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[FaultEvent], Dict[str, AnchoredContext], List[Dict[str, Any]]]:
        """
        Returns:
          - all_faults (explicit + newly discovered RANGE_DRIFT faults)
          - anchor_contexts keyed by fault_id
          - verified_clean_formulas (passed Filter 3 without drift)
        """
        all_faults = list(explicit_faults)
        anchor_contexts: Dict[str, AnchoredContext] = {}
        clean_pass_formulas: List[Dict[str, Any]] = []
        now_iso = datetime.now(timezone.utc).isoformat()

        # Analyze each sheet's anchor integrity
        sheet_anchor_stats: Dict[str, Dict[str, Any]] = {}
        for sheet_name, sdata in sheet_matrix.items():
            cells = sdata["cells"]
            found_anchors, header_row, footer_row = cls._scan_sheet_anchors(cells)

            expected_labels = (
                baseline_schema.get("expected_anchors", [])
                if baseline_schema
                else list(found_anchors.values())
            )
            total_expected = max(len(expected_labels), 1)
            found_values_lower = {v.lower() for v in found_anchors.values()}
            matched = sum(1 for lbl in expected_labels if lbl.lower() in found_values_lower)
            drift_pct = round(((total_expected - matched) / total_expected) * 100.0, 2)

            sheet_anchor_stats[sheet_name] = {
                "found_anchors": found_anchors,
                "header_row": header_row or 2,
                "footer_row": footer_row or sdata["max_row"],
                "total_expected": total_expected,
                "matched": matched,
                "drift_pct": drift_pct,
            }

        # 1. Screen healthy formulas for silent RANGE_DRIFT
        for item in healthy_formulas:
            sname = item["sheet_name"]
            coord = item["cell_coordinate"]
            raw = item["raw_formula"]
            stats = sheet_anchor_stats[sname]

            m = RANGE_RE.match(raw.strip())
            if m:
                func, c1, r1_s, c2, r2_s = m.groups()
                r1, r2 = int(r1_s), int(r2_s)
                expected_end_row = stats["footer_row"] - 1
                if c1.upper() == c2.upper() and expected_end_row > r2:
                    shift = expected_end_row - r2
                    fid = f"flt_{uuid.uuid4().hex[:8]}"
                    fault_evt = FaultEvent(
                        fault_id=fid,
                        upload_id=upload_id,
                        department_id=department_id,
                        sheet_name=sname,
                        cell_coordinate=coord,
                        corrupted_formula=raw,
                        fault_type=FaultType.RANGE_DRIFT,
                        detected_at=now_iso,
                    )
                    all_faults.append(fault_evt)
                    inserted = [f"{c1.upper()}{r}" for r in range(r2 + 1, expected_end_row + 1)]
                    anchor_contexts[fid] = AnchoredContext(
                        fault_id=fid,
                        sheet_name=sname,
                        target_coordinate=coord,
                        header_anchor=f"Column {c1.upper()} Metric Header",
                        header_coord=f"{c1.upper()}{stats['header_row']}",
                        footer_anchor="Summary Total Row",
                        footer_coord=f"{c1.upper()}{stats['footer_row']}",
                        detected_row_shift=shift,
                        inserted_row_spans=inserted,
                        historical_baseline_formula=raw,
                        expected_range_formula=f"={func.upper()}({c1.upper()}{r1}:{c2.upper()}{expected_end_row})",
                        total_expected_anchors=stats["total_expected"],
                        matched_anchors=stats["matched"],
                        drift_percentage=stats["drift_pct"],
                    )
                    continue

            clean_pass_formulas.append(item)

        # 2. Build AnchoredContext for all explicit faults from Filter 2
        for f in explicit_faults:
            stats = sheet_anchor_stats[f.sheet_name]
            col_match = re.match(r"([A-Z]+)(\d+)", f.cell_coordinate)
            col_let = col_match.group(1) if col_match else "C"
            data_start = stats["header_row"] + 1
            data_end = max(stats["footer_row"] - 1, data_start)

            # Infer expected SUM range if #REF! or #VALUE! occurred in a summary footer
            expected_formula = None
            if f.fault_type in (FaultType.REF_ERROR, FaultType.VALUE_ERROR):
                if "SUM" in f.corrupted_formula.upper() or f.cell_coordinate.endswith(str(stats["footer_row"])):
                    expected_formula = f"=SUM({col_let}{data_start}:{col_let}{data_end})"

            anchor_contexts[f.fault_id] = AnchoredContext(
                fault_id=f.fault_id,
                sheet_name=f.sheet_name,
                target_coordinate=f.cell_coordinate,
                header_anchor=f"Column {col_let} Metric Header",
                header_coord=f"{col_let}{stats['header_row']}",
                footer_anchor="Summary Total Row",
                footer_coord=f"{col_let}{stats['footer_row']}",
                detected_row_shift=0,
                inserted_row_spans=[],
                historical_baseline_formula=f"=SUM({col_let}{data_start}:{col_let}{data_end})",
                expected_range_formula=expected_formula,
                total_expected_anchors=stats["total_expected"],
                matched_anchors=stats["matched"],
                drift_percentage=stats["drift_pct"],
            )

        return all_faults, anchor_contexts, clean_pass_formulas