import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import HTTPException
from src.models import (
    AdjudicateRequest,
    MetricState,
    RejectWorkbookRequest,
    SignOffRequest,
    WorkbookStatus,
)
from src.pipeline.repair_agent import RepairAgent
from src.pipeline.validator import ConstraintValidator


class HITLController:
    """
    Synchronous Human-in-the-Loop Governance Controller & Append-Only AuditLedger.
    Exclusively authorized to transition metrics to Associate-Verified and publish scorecards.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def append_audit_event(
        self,
        event_type: str,
        reviewer_id: str,
        reviewer_role: str,
        rationale: str,
        upload_id: Optional[str] = None,
        fault_id: Optional[str] = None,
        original_formula: Optional[str] = None,
        final_formula: Optional[str] = None,
        source_file_sha256: Optional[str] = None,
    ) -> str:
        cur = self.conn.execute(
            "SELECT entry_hash FROM audit_ledger ORDER BY rowid DESC LIMIT 1"
        )
        row = cur.fetchone()
        prev_hash = row["entry_hash"] if row else "0" * 64

        audit_id = f"aud_{uuid.uuid4().hex[:10]}"
        ts = datetime.now(timezone.utc).isoformat()
        canonical = json.dumps(
            {
                "audit_id": audit_id,
                "prev_hash": prev_hash,
                "event_type": event_type,
                "upload_id": upload_id,
                "fault_id": fault_id,
                "reviewer_id": reviewer_id,
                "original_formula": original_formula,
                "final_formula": final_formula,
                "rationale": rationale,
                "source_file_sha256": source_file_sha256,
                "timestamp": ts,
            },
            sort_keys=True,
        )
        entry_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        self.conn.execute(
            """
            INSERT INTO audit_ledger (
                audit_id, prev_hash, entry_hash, event_type, upload_id, fault_id,
                reviewer_id, reviewer_role, original_formula, final_formula,
                rationale, source_file_sha256, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                prev_hash,
                entry_hash,
                event_type,
                upload_id,
                fault_id,
                reviewer_id,
                reviewer_role,
                original_formula,
                final_formula,
                rationale,
                source_file_sha256,
                ts,
            ),
        )
        return audit_id

    def get_health_digest(self, upload_id: str, user: dict) -> Dict[str, Any]:
        wb = self.conn.execute(
            "SELECT * FROM workbooks WHERE upload_id = ?", (upload_id,)
        ).fetchone()
        if not wb:
            raise HTTPException(status_code=404, detail="Workbook not found")

        clean_rows = self.conn.execute(
            """
            SELECT metric_id, indicator_name, verified_formula, evaluated_value, numerator, denominator
            FROM metrics
            WHERE upload_id = ? AND state = ? AND superseded = 0
            ORDER BY metric_id
            """,
            (upload_id, MetricState.AUTO_VALIDATED.value),
        ).fetchall()

        summary = [dict(r) for r in clean_rows]
        digest_sha256 = hashlib.sha256(
            json.dumps({"upload_id": upload_id, "metrics": summary}, sort_keys=True).encode("utf-8")
        ).hexdigest()

        self.conn.execute(
            "UPDATE workbooks SET digest_sha256 = ?, digest_viewed = 1 WHERE upload_id = ?",
            (digest_sha256, upload_id),
        )
        audit_id = self.append_audit_event(
            event_type="DIGEST_VIEWED",
            reviewer_id=user["user_id"],
            reviewer_role=user["role"].value,
            rationale=f"Viewed Metric Health Digest ({len(summary)} Auto-Validated metrics)",
            upload_id=upload_id,
            source_file_sha256=wb["file_sha256"],
        )
        self.conn.commit()
        return {
            "upload_id": upload_id,
            "department_id": wb["department_id"],
            "digest_sha256": digest_sha256,
            "total_clean_metrics": len(summary),
            "metrics_summary": summary,
            "audit_id": audit_id,
        }

    def adjudicate_fault(
        self,
        fault_id: str,
        req: AdjudicateRequest,
        user: dict,
        sheet_cells_cache: Dict[str, Any],
    ) -> Dict[str, Any]:
        fault = self.conn.execute(
            "SELECT * FROM faults WHERE fault_id = ?", (fault_id,)
        ).fetchone()
        if not fault:
            raise HTTPException(status_code=404, detail="Fault not found")

        wb = self.conn.execute(
            "SELECT * FROM workbooks WHERE upload_id = ?", (fault["upload_id"],)
        ).fetchone()
        proposal = json.loads(fault["patch_proposal_json"]) if fault["patch_proposal_json"] else None
        sheet_cells = sheet_cells_cache.get(fault["upload_id"], {}).get(fault["sheet_name"], {})

        if req.action == "REJECT_PATCH":
            self.conn.execute(
                "UPDATE faults SET status = ?, patch_proposal_json = NULL WHERE fault_id = ?",
                (MetricState.MANUAL_TRIAGE_REQUIRED.value, fault_id),
            )
            self.conn.execute(
                "UPDATE metrics SET state = ? WHERE fault_id = ?",
                (MetricState.MANUAL_TRIAGE_REQUIRED.value, fault_id),
            )
            audit_id = self.append_audit_event(
                event_type="PATCH_REJECTED",
                reviewer_id=user["user_id"],
                reviewer_role=user["role"].value,
                rationale=req.rationale,
                upload_id=fault["upload_id"],
                fault_id=fault_id,
                original_formula=fault["corrupted_formula"],
                final_formula=None,
                source_file_sha256=wb["file_sha256"],
            )
            self.conn.commit()
            return {"fault_id": fault_id, "state": MetricState.MANUAL_TRIAGE_REQUIRED.value, "audit_id": audit_id}

        if req.action == "ACCEPT":
            if not proposal:
                raise HTTPException(status_code=400, detail="No AI patch proposal available to accept")
            chosen_formula = proposal["proposed_formula"]
        else:  # OVERRIDE
            if not req.override_formula:
                raise HTTPException(status_code=400, detail="override_formula is required for OVERRIDE")
            chosen_formula = req.override_formula

        # Re-verify compiler pre-check and Filter 5 bounds before Associate-Verified commit
        ok, eval_val = RepairAgent.sandbox_evaluate(chosen_formula, sheet_cells)
        if not ok:
            raise HTTPException(status_code=400, detail="Formula failed sandboxed compiler pre-check")

        valid_bounds, reason, num, den = ConstraintValidator.validate_rate_formula(
            chosen_formula, eval_val, sheet_cells
        )
        if not valid_bounds:
            raise HTTPException(status_code=400, detail=reason)

        self.conn.execute(
            "UPDATE faults SET status = ? WHERE fault_id = ?",
            (MetricState.ASSOCIATE_VERIFIED.value, fault_id),
        )
        self.conn.execute(
            """
            UPDATE metrics
            SET state = ?, verified_formula = ?, evaluated_value = ?, numerator = ?, denominator = ?
            WHERE fault_id = ?
            """,
            (MetricState.ASSOCIATE_VERIFIED.value, chosen_formula, eval_val, num, den, fault_id),
        )

        audit_id = self.append_audit_event(
            event_type=f"FAULT_{req.action}",
            reviewer_id=user["user_id"],
            reviewer_role=user["role"].value,
            rationale=req.rationale,
            upload_id=fault["upload_id"],
            fault_id=fault_id,
            original_formula=fault["corrupted_formula"],
            final_formula=chosen_formula,
            source_file_sha256=wb["file_sha256"],
        )
        self.conn.commit()
        return {
            "fault_id": fault_id,
            "state": MetricState.ASSOCIATE_VERIFIED.value,
            "verified_formula": chosen_formula,
            "evaluated_value": eval_val,
            "audit_id": audit_id,
        }

    def batch_sign_off(self, upload_id: str, req: SignOffRequest, user: dict) -> Dict[str, Any]:
        wb = self.conn.execute(
            "SELECT * FROM workbooks WHERE upload_id = ?", (upload_id,)
        ).fetchone()
        if not wb:
            raise HTTPException(status_code=404, detail="Workbook not found")
        if not wb["digest_viewed"] or wb["digest_sha256"] != req.digest_sha256:
            raise HTTPException(
                status_code=400,
                detail="Must view current Metric Health Digest and supply matching digest_sha256 before sign-off.",
            )

        # Ensure no unresolved faults remain
        open_faults = self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM faults WHERE upload_id = ? AND status != ?",
            (upload_id, MetricState.ASSOCIATE_VERIFIED.value),
        ).fetchone()["cnt"]
        if open_faults > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot sign off workbook while {open_faults} fault(s) remain unverified.",
            )

        self.conn.execute(
            """
            UPDATE metrics
            SET state = ?
            WHERE upload_id = ? AND state = ? AND superseded = 0
            """,
            (MetricState.ASSOCIATE_VERIFIED.value, upload_id, MetricState.AUTO_VALIDATED.value),
        )
        self.conn.execute(
            "UPDATE workbooks SET status = ? WHERE upload_id = ?",
            (WorkbookStatus.COMPLETED.value, upload_id),
        )
        audit_id = self.append_audit_event(
            event_type="WORKBOOK_BATCH_SIGNOFF",
            reviewer_id=user["user_id"],
            reviewer_role=user["role"].value,
            rationale=req.rationale,
            upload_id=upload_id,
            source_file_sha256=wb["file_sha256"],
        )
        self.conn.commit()
        return {"upload_id": upload_id, "status": WorkbookStatus.COMPLETED.value, "audit_id": audit_id}

    def reject_workbook(self, upload_id: str, req: RejectWorkbookRequest, user: dict) -> Dict[str, Any]:
        wb = self.conn.execute(
            "SELECT * FROM workbooks WHERE upload_id = ?", (upload_id,)
        ).fetchone()
        if not wb:
            raise HTTPException(status_code=404, detail="Workbook not found")

        self.conn.execute(
            "UPDATE workbooks SET status = ?, rejection_note = ?, superseded = 1 WHERE upload_id = ?",
            (WorkbookStatus.REJECTED.value, req.rationale, upload_id),
        )
        self.conn.execute(
            """
            UPDATE metrics
            SET state = ?, superseded = 1
            WHERE upload_id = ? AND state != ?
            """,
            (MetricState.SUBMISSION_REJECTED.value, upload_id, MetricState.ASSOCIATE_VERIFIED.value),
        )
        audit_id = self.append_audit_event(
            event_type="WORKBOOK_REJECTED",
            reviewer_id=user["user_id"],
            reviewer_role=user["role"].value,
            rationale=req.rationale,
            upload_id=upload_id,
            source_file_sha256=wb["file_sha256"],
        )
        self.conn.commit()
        return {"upload_id": upload_id, "status": WorkbookStatus.REJECTED.value, "audit_id": audit_id}

    def publish_scorecard(
        self, period: str, req: PublishScorecardRequest, user: dict, valid_exception_tokens: set
    ) -> Dict[str, Any]:
        verified_rows = self.conn.execute(
            """
            SELECT m.*, w.file_sha256
            FROM metrics m
            JOIN workbooks w ON m.upload_id = w.upload_id
            WHERE m.reporting_period = ? AND m.state = ? AND m.superseded = 0
            ORDER BY m.department_id, m.metric_id
            """,
            (period, MetricState.ASSOCIATE_VERIFIED.value),
        ).fetchall()

        if not verified_rows:
            raise HTTPException(status_code=400, detail="No Associate-Verified metrics ready for publication")

        if req.allow_documented_exceptions:
            if not req.exception_token or req.exception_token not in valid_exception_tokens:
                raise HTTPException(status_code=403, detail="Invalid or missing Director exception-approval token")

        prev_pub = self.conn.execute(
            "SELECT MAX(version) AS v FROM scorecards WHERE reporting_period = ?", (period,)
        ).fetchone()["v"]
        version = (prev_pub or 0) + 1

        payload = [dict(r) for r in verified_rows]
        master_hash = hashlib.sha256(
            json.dumps({"period": period, "version": version, "metrics": payload}, sort_keys=True).encode("utf-8")
        ).hexdigest()
        pub_id = f"pub_{uuid.uuid4().hex[:8]}"
        ts = datetime.now(timezone.utc).isoformat()

        self.conn.execute(
            """
            INSERT INTO scorecards (publication_id, reporting_period, version, master_audit_hash, payload_json, published_by, published_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (pub_id, period, version, master_hash, json.dumps(payload), user["user_id"], ts),
        )
        audit_id = self.append_audit_event(
            event_type="SCORECARD_PUBLISHED" if version == 1 else "SCORECARD_AMENDED",
            reviewer_id=user["user_id"],
            reviewer_role=user["role"].value,
            rationale=f"Published scorecard period {period} v{version}",
        )
        self.conn.commit()
        return {
            "publication_id": pub_id,
            "reporting_period": period,
            "version": version,
            "master_audit_hash": master_hash,
            "verified_metric_count": len(payload),
            "audit_id": audit_id,
        }