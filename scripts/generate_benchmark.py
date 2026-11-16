import json
from pathlib import Path
import openpyxl

DEPARTMENTS = [
    "SURGICAL_SERVICES", "EMERGENCY_DEPT", "MEDICAL_ICU", "CARDIAC_ICU",
    "PHARMACY_STERILE", "LABORATORY_STAT", "ONCOLOGY_UNIT", "PEDIATRICS",
    "LABOR_DELIVERY", "NEONATAL_ICU", "RADIOLOGY_IR", "ENDOSCOPY",
    "DIALYSIS_UNIT", "ORTHOPEDICS", "NEUROLOGY", "TRANSPLANT_UNIT", "REHAB_SERVICES",
]


def build_benchmark_corpus(out_dir: Path = Path("data/synthetic_workbooks")) -> dict:
    """
    Generates 17 departmental .xlsx workbooks containing the exact 40 injected faults
    specified in Section 8.3:
      - 15 RANGE_DRIFT (row-insertion range displacement errors)
      - 10 REF_ERROR (#REF!)
      - 3 DIV_ZERO (#DIV/0!)
      - 2 VALUE_ERROR (#VALUE!)
      - 5 BROKEN_PATH (unresolvable external UNC/file paths)
      - 5 edge cases (out-of-bounds 134% compliance rate, >30% anchor drift redesign)
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"total_workbooks": 17, "total_faults": 40, "workbooks": []}

    # Fault allocation across the 17 units (total = 40)
    fault_plan = [
        ["RANGE_DRIFT", "REF_ERROR", "BOUNDS_VIOLATION"],           # 1. SURGICAL_SERVICES (3)
        ["RANGE_DRIFT", "REF_ERROR", "DIV_ZERO"],                   # 2. EMERGENCY_DEPT (3)
        ["RANGE_DRIFT", "REF_ERROR", "BROKEN_PATH"],                # 3. MEDICAL_ICU (3)
        ["RANGE_DRIFT", "REF_ERROR", "VALUE_ERROR"],                # 4. CARDIAC_ICU (3)
        ["RANGE_DRIFT", "REF_ERROR", "BROKEN_PATH"],                # 5. PHARMACY_STERILE (3)
        ["RANGE_DRIFT", "REF_ERROR", "DIV_ZERO"],                   # 6. LABORATORY_STAT (3)
        ["RANGE_DRIFT", "REF_ERROR", "BROKEN_PATH"],                # 7. ONCOLOGY_UNIT (3)
        ["RANGE_DRIFT", "REF_ERROR", "VALUE_ERROR"],                # 8. PEDIATRICS (3)
        ["RANGE_DRIFT", "REF_ERROR", "BROKEN_PATH"],                # 9. LABOR_DELIVERY (3)
        ["RANGE_DRIFT", "REF_ERROR", "BROKEN_PATH"],                # 10. NEONATAL_ICU (3)
        ["RANGE_DRIFT", "DIV_ZERO"],                                # 11. RADIOLOGY_IR (2)
        ["RANGE_DRIFT", "BOUNDS_VIOLATION"],                        # 12. ENDOSCOPY (2)
        ["RANGE_DRIFT", "BOUNDS_VIOLATION"],                        # 13. DIALYSIS_UNIT (2)
        ["RANGE_DRIFT", "TEMPLATE_REDESIGN"],                       # 14. ORTHOPEDICS (2)
        ["RANGE_DRIFT", "TEMPLATE_REDESIGN"],                       # 15. NEUROLOGY (2)
        [],                                                         # 16. TRANSPLANT_UNIT (0 - clean control)
        [],                                                         # 17. REHAB_SERVICES (0 - clean control)
    ]

    for dept, faults in zip(DEPARTMENTS, fault_plan):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Monthly_Summary"

        # Standard semantic headers (Row 2)
        ws["A2"] = "Indicator Code"
        ws["B2"] = "Metric Observation Log"
        ws["C2"] = "Adherent Cases"
        ws["D2"] = "Total Cases"
        ws["E2"] = "Compliance Rate"

        # Populate rows 3..10 (8 observation rows; baseline was rows 3..7 = 5 rows, +3 inserted rows)
        for idx, r in enumerate(range(3, 11), start=1):
            ws[f"A{r}"] = f"OBS-{idx:02d}"
            ws[f"B{r}"] = f"Unit Shift Observation {idx}"
            ws[f"C{r}"] = 24
            ws[f"D{r}"] = 25

        # Summary footer row (Row 11)
        ws["B11"] = "Total Monthly Adherence"
        ws["C11"] = "=SUM(C3:C10)"
        ws["D11"] = "=SUM(D3:D10)"
        ws["E11"] = "=C11/D11"

        injected_details = []
        col_cursor = 6  # Column F onward for additional injected faults

        for ftype in faults:
            if ftype == "RANGE_DRIFT":
                # Silent range displacement omitting rows 8..10
                ws["C11"] = "=SUM(C3:C7)"
                injected_details.append({"cell": "C11", "type": "RANGE_DRIFT", "ground_truth": "=SUM(C3:C10)"})

            elif ftype == "REF_ERROR":
                col_let = openpyxl.utils.get_column_letter(col_cursor)
                ws[f"{col_let}2"] = f"{dept} Audit Count"
                for r in range(3, 11):
                    ws[f"{col_let}{r}"] = 10
                ws[f"{col_let}11"] = f"=SUM({col_let}3:#REF!)"
                injected_details.append({"cell": f"{col_let}11", "type": "REF_ERROR", "ground_truth": f"=SUM({col_let}3:{col_let}10)"})
                col_cursor += 1

            elif ftype == "DIV_ZERO":
                col_let = openpyxl.utils.get_column_letter(col_cursor)
                ws[f"{col_let}2"] = "Zero-Denom Indicator"
                ws[f"{col_let}3"] = 5
                ws[f"{col_let}4"] = 0
                ws[f"{col_let}11"] = f"={col_let}3/{col_let}4"
                injected_details.append({"cell": f"{col_let}11", "type": "DIV_ZERO"})
                col_cursor += 1

            elif ftype == "VALUE_ERROR":
                col_let = openpyxl.utils.get_column_letter(col_cursor)
                ws[f"{col_let}2"] = "Value-Corrupt Audit"
                for r in range(3, 11):
                    ws[f"{col_let}{r}"] = 12
                ws[f"{col_let}11"] = "#VALUE!"
                # Force formula flag via broken formula string
                ws[f"{col_let}11"] = f"=SUM({col_let}3:{col_let}10)+#VALUE!"
                injected_details.append({"cell": f"{col_let}11", "type": "VALUE_ERROR", "ground_truth": f"=SUM({col_let}3:{col_let}10)"})
                col_cursor += 1

            elif ftype == "BROKEN_PATH":
                col_let = openpyxl.utils.get_column_letter(col_cursor)
                ws[f"{col_let}2"] = "External Lab Link"
                ws[f"{col_let}11"] = f"='\\\\hospital-nas\\quality\\[Missing_{dept}_SubLog.xlsx]Sheet1'!$C$11"
                injected_details.append({"cell": f"{col_let}11", "type": "BROKEN_PATH"})
                col_cursor += 1

            elif ftype == "BOUNDS_VIOLATION":
                # Numerator (268) > Denominator (200) -> 134% compliance rate
                ws["C12"] = 268
                ws["D12"] = 200
                ws["E12"] = "=C12/D12"
                injected_details.append({"cell": "E12", "type": "BOUNDS_VIOLATION"})

            elif ftype == "TEMPLATE_REDESIGN":
                # Corrupt >30% of anchors + inject a #REF! so suspension gate is tested
                ws["B2"] = "REORGANIZED_CUSTOM_GRID_X"
                ws["B11"] = "UNMAPPED_FOOTER_Z"
                ws["G11"] = "=SUM(G3:#REF!)"
                injected_details.append({"cell": "G11", "type": "TEMPLATE_REDESIGN"})

        file_path = out_dir / f"{dept}_2026_05.xlsx"
        wb.save(file_path)
        manifest["workbooks"].append(
            {"department_id": dept, "file": str(file_path), "injected_faults": injected_details}
        )

    (out_dir / "ground_truth.json").write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":
    res = build_benchmark_corpus()
    print(f"Generated {res['total_workbooks']} workbooks with {res['total_faults']} injected faults.")