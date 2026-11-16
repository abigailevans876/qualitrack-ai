import hashlib
import io
from typing import Any, Dict, Tuple
import openpyxl


class IngestionWorker:
    """Filter 1: Binary .xlsx/.xlsm stream reader, macro sanitizer, SHA-256 digest."""

    @staticmethod
    def ingest(file_bytes: bytes, filename: str) -> Tuple[str, Dict[str, Any], openpyxl.Workbook]:
        if not filename.lower().endswith((".xlsx", ".xlsm")):
            raise ValueError("Unsupported file format. Only .xlsx and .xlsm are accepted.")

        file_sha256 = hashlib.sha256(file_bytes).hexdigest()

        # Load with keep_vba=False to strip executable VBA macros safely
        wb_formulas = openpyxl.load_workbook(
            io.BytesIO(file_bytes), data_only=False, keep_vba=False
        )
        wb_values = openpyxl.load_workbook(
            io.BytesIO(file_bytes), data_only=True, keep_vba=False
        )

        sheet_matrix: Dict[str, Dict[str, Any]] = {}
        for sheet_name in wb_formulas.sheetnames:
            ws_f = wb_formulas[sheet_name]
            ws_v = wb_values[sheet_name]
            cells = {}
            for row in ws_f.iter_rows():
                for cell in row:
                    val_cached = ws_v[cell.coordinate].value
                    if cell.value is not None or val_cached is not None:
                        cells[cell.coordinate] = {
                            "row": cell.row,
                            "col": cell.column,
                            "col_letter": openpyxl.utils.get_column_letter(cell.column),
                            "raw": cell.value,
                            "cached_value": val_cached,
                            "is_formula": isinstance(cell.value, str) and cell.value.startswith("="),
                        }
            sheet_matrix[sheet_name] = {
                "max_row": ws_f.max_row,
                "max_col": ws_f.max_column,
                "cells": cells,
            }

        return file_sha256, sheet_matrix, wb_formulas