import time
from pathlib import Path
from fastapi.testclient import TestClient
from scripts.generate_benchmark import build_benchmark_corpus
from src.main import app

client = TestClient(app)

MANAGER_HDRS = {"X-User-Id": "mgr_01", "X-User-Role": "Department_Manager"}
ASSOC_HDRS = {"X-User-Id": "assoc_01", "X-User-Role": "Quality_Associate"}
DIRECTOR_HDRS = {"X-User-Id": "dir_01", "X-User-Role": "Quality_Director"}


def test_full_17_workbook_benchmark_and_governance():
    manifest = build_benchmark_corpus(Path("data/synthetic_workbooks"))
    assert manifest["total_workbooks"] == 17
    assert manifest["total_faults"] == 40

    total_detected = 0
    proposed_patches = []
    start_time = time.perf_counter()

    # 1. Ingest all 17 departmental workbooks (FR-01, FR-02, FR-03, FR-04, NFR-04)
    for wb_entry in manifest["workbooks"]:
        dept = wb_entry["department_id"]
        fpath = Path(wb_entry["file"])
        with fpath.open("rb") as fh:
            resp = client.post(
                "/api/v1/workbooks/upload",
                headers=MANAGER_HDRS,
                data={"department_id": dept, "reporting_period": "2026-05"},
                files={"file": (fpath.name, fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
        assert resp.status_code == 200
        body = resp.json()
        upload_id = body["upload_id"]

        faults_resp = client.get(f"/api/v1/workbooks/{upload_id}/faults", headers=ASSOC_HDRS).json()
        total_detected += faults_resp["faults_detected"]

        gt_map = {item["cell"]: item for item in wb_entry["injected_faults"]}
        for item in faults_resp["items"]:
            if item["patch_proposal"] is not None:
                gt = gt_map.get(item["cell_coordinate"], {}).get("ground_truth")
                proposed_patches.append((item["patch_proposal"]["proposed_formula"], gt, item["patch_proposal"]["confidence_score"]))

        # Verify clean control units can complete full HITL Digest + Sign-Off flow (FR-05, NFR-03)
        if len(wb_entry["injected_faults"]) == 0:
            # Attempt sign-off BEFORE viewing digest -> must fail with 400
            bad_sign = client.post(
                f"/api/v1/workbooks/{upload_id}/sign-off",
                headers=ASSOC_HDRS,
                json={"digest_sha256": "wrong_hash", "rationale": "Attempting premature sign-off"},
            )
            assert bad_sign.status_code == 400

            digest = client.get(f"/api/v1/workbooks/{upload_id}/health-digest", headers=ASSOC_HDRS).json()
            good_sign = client.post(
                f"/api/v1/workbooks/{upload_id}/sign-off",
                headers=ASSOC_HDRS,
                json={"digest_sha256": digest["digest_sha256"], "rationale": "All clean indicators verified"},
            )
            assert good_sign.status_code == 200

    elapsed = time.perf_counter() - start_time

    # Assert 100% Fault Isolation Recall across all 40 injected faults (FR-02, FR-04)
    assert total_detected == 40

    # Assert >= 90% ground-truth equivalence on proposals meeting C >= 0.85 (FR-03, NFR-08)
    assert len(proposed_patches) >= 25
    exact_matches = sum(1 for prop, gt, conf in proposed_patches if prop == gt and conf >= 0.85)
    accuracy = exact_matches / len(proposed_patches)
    assert accuracy >= 0.90

    # Assert Latency well within 15.0s budget (NFR-04)
    assert elapsed < 15.0


def test_rbac_and_day5_director_exception_governance():
    # Manager attempting to call Associate adjudication endpoint -> HTTP 403 (NFR-06)
    r_forbidden = client.post(
        "/api/v1/faults/flt_nonexistent/adjudicate",
        headers=MANAGER_HDRS,
        json={"action": "ACCEPT", "rationale": "Unauthorized attempt"},
    )
    assert r_forbidden.status_code == 403

    # Associate publishing with bad Director exception token -> HTTP 403
    r_bad_tok = client.post(
        "/api/v1/scorecards/2026-05/publish",
        headers=ASSOC_HDRS,
        json={"allow_documented_exceptions": True, "exception_token": "forged_token"},
    )
    assert r_bad_tok.status_code == 403

    # Director issues valid exception approval -> Associate publishes scorecard (FR-06, NFR-01)
    exc_resp = client.post(
        "/api/v1/scorecards/2026-05/exception-approval",
        headers=DIRECTOR_HDRS,
        json={"department_id": "ORTHOPEDICS", "justification": "Template redesign escalated past Day 5"},
    )
    assert exc_resp.status_code == 200
    token = exc_resp.json()["exception_token"]

    pub_resp = client.post(
        "/api/v1/scorecards/2026-05/publish",
        headers=ASSOC_HDRS,
        json={"allow_documented_exceptions": True, "exception_token": token},
    )
    assert pub_resp.status_code == 200
    pub_data = pub_resp.json()
    assert pub_data["verified_metric_count"] > 0

    # Verify audit ledger entry exists and has SHA-256 hash chain (NFR-01)
    aud_resp = client.get(f"/api/v1/audit/{pub_data['audit_id']}", headers=DIRECTOR_HDRS)
    assert aud_resp.status_code == 200
    assert len(aud_resp.json()["entry_hash"]) == 64