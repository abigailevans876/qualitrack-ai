from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class Role(str, Enum):
    MANAGER = "Department_Manager"
    ASSOCIATE = "Quality_Associate"
    DIRECTOR = "Quality_Director"


class FaultType(str, Enum):
    REF_ERROR = "REF_ERROR"
    DIV_ZERO = "DIV_ZERO"
    VALUE_ERROR = "VALUE_ERROR"
    BROKEN_PATH = "BROKEN_PATH"
    RANGE_DRIFT = "RANGE_DRIFT"
    BOUNDS_VIOLATION = "BOUNDS_VIOLATION"


class MetricState(str, Enum):
    PENDING_REVIEW = "Pending-Review"
    AUTO_VALIDATED = "Auto-Validated"
    AI_PATCH_PROPOSED = "AI-Patch-Proposed"
    MANUAL_TRIAGE_REQUIRED = "Manual-Triage-Required"
    ASSOCIATE_VERIFIED = "Associate-Verified"
    SUBMISSION_REJECTED = "Submission-Rejected"


class WorkbookStatus(str, Enum):
    PROCESSING = "PROCESSING"
    IN_REVIEW = "IN_REVIEW"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class FaultEvent(BaseModel):
    fault_id: str
    upload_id: str
    department_id: str
    sheet_name: str
    cell_coordinate: str
    corrupted_formula: str
    fault_type: FaultType
    detected_at: str


class AnchoredContext(BaseModel):
    fault_id: str
    sheet_name: str
    target_coordinate: str
    header_anchor: str
    header_coord: str
    footer_anchor: str
    footer_coord: str
    detected_row_shift: int
    inserted_row_spans: List[str]
    historical_baseline_formula: str
    expected_range_formula: Optional[str] = None
    total_expected_anchors: int
    matched_anchors: int
    drift_percentage: float


class PatchProposal(BaseModel):
    proposal_id: str
    fault_id: str
    proposed_formula: str
    compiler_precheck: str  # PASSED | FAILED
    confidence_score: float
    s_anchor: float
    s_ast_sim: float
    s_compiler: float
    original_formula: str
    rationale: str
    generated_at: str


class AdjudicateRequest(BaseModel):
    action: str = Field(..., pattern="^(ACCEPT|OVERRIDE|REJECT_PATCH)$")
    override_formula: Optional[str] = None
    rationale: str = Field(..., min_length=5)


class SignOffRequest(BaseModel):
    digest_sha256: str
    rationale: str = Field(..., min_length=5)


class RejectWorkbookRequest(BaseModel):
    rationale: str = Field(..., min_length=5)


class ExceptionApprovalRequest(BaseModel):
    department_id: str
    justification: str = Field(..., min_length=5)


class PublishScorecardRequest(BaseModel):
    allow_documented_exceptions: bool = False
    exception_token: Optional[str] = None