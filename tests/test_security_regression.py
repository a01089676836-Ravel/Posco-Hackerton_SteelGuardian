"""
보안·안정성 회귀 테스트 (데이터셋 불필요)
실행: python tests/test_security_regression.py
각 항목은 수정 전 코드에서 재현된 결함이 다시 나타나면 실패한다.
"""

import csv
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

TMP = Path(tempfile.mkdtemp(prefix="regtest_"))
os.environ["AUDIT_LOG_DIR"] = str(TMP / "logs")
for key in ("ALLOW_REMOTE_ACTIVATION", "ADMIN_API_KEY", "ADMIN_KEY", "ALLOW_MOCK"):
    os.environ.pop(key, None)

import torch
from fastapi.testclient import TestClient
from PIL import Image

import audit_logger
import server
from rule_engine import evaluate_defect

MODELS = BASE_DIR / "models"
BASE_PT = MODELS / "memory_bank.pt"
BASE_SHA = hashlib.sha256(BASE_PT.read_bytes()).hexdigest()
local = TestClient(server.app, client=("127.0.0.1", 50000), raise_server_exceptions=False)
remote = TestClient(server.app, client=("192.168.1.100", 50000), raise_server_exceptions=False)


def png(size=(64, 64)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (128, 128, 128)).save(buf, "PNG")
    return buf.getvalue()


def inspect(client=local, data=None, content=None, name="a.png"):
    fields = {"include_heatmap": "false", **(data or {})}
    return client.post("/v1/defects/inspect", files={"file": (name, content or png(), "image/png")}, data=fields)


def sha_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def add_model(name: str, meta: dict | None = None, ckpt: dict | None = None) -> str:
    """models/에 테스트 모델을 만들고 실제 SHA256을 반환한다. meta의 pt_sha256은 None이면 실제 값으로 채운다."""
    pt = MODELS / f"{name}.pt"
    if ckpt is None:
        shutil.copy(BASE_PT, pt)
    else:
        torch.save(ckpt, pt)
    digest = sha_of(pt)
    body = {"split": {"bank_validation_overlap": 0}, "output": {"pt_sha256": digest}} if meta is None else meta
    (MODELS / f"{name}.meta.json").write_text(json.dumps(body), encoding="utf-8")
    return digest


def activate(part_id: str, digest: str, client=local, headers=None):
    return client.post("/v1/models/activate", json={"part_id": part_id, "expected_sha256": digest}, headers=headers or {})


def restore_base_model():
    assert activate("memory_bank", BASE_SHA).status_code == 200


def test_forwarded_header_cannot_bypass_auth():
    res = activate("memory_bank", BASE_SHA, client=remote, headers={"x-forwarded-for": "127.0.0.1"})
    assert res.status_code == 403, res.status_code
    assert "REMOTE_ACTIVATION_DISABLED" in res.text


def test_meta_must_prove_no_leakage():
    digest = add_model("regtest_emptymeta", meta={})
    res = activate("regtest_emptymeta", digest)
    assert res.status_code == 400 and "INVALID_META_JSON" in res.text, res.text


def test_meta_must_match_model_file():
    digest = add_model("regtest_wrongsha", meta={"split": {"bank_validation_overlap": 0}, "output": {"pt_sha256": "0" * 64}})
    res = activate("regtest_wrongsha", digest)
    assert res.status_code == 409 and "META_MODEL_SHA_MISMATCH" in res.text, res.text


def test_real_checkpoint_leakage_rejected():
    ckpt = torch.load(BASE_PT, map_location="cpu", weights_only=True)
    ckpt["bank_image_indices"] = list(ckpt["validation_image_indices"])
    digest = add_model("regtest_leak", ckpt=ckpt)
    res = activate("regtest_leak", digest)
    assert res.status_code == 409 and "DATASET_LEAKAGE" in res.text, res.text


marker = TMP / "pickle_executed.txt"


class _Evil:
    def __reduce__(self):
        return (Path.write_text, (marker, "x"))


def test_malicious_pickle_not_executed():
    ckpt = torch.load(BASE_PT, map_location="cpu", weights_only=True)
    digest = add_model("regtest_pickle", ckpt={"memory_bank": ckpt["memory_bank"], "x": _Evil()})
    res = activate("regtest_pickle", digest)
    assert not marker.exists(), "체크포인트의 코드가 실행되었습니다"
    assert res.status_code == 400 and "MODEL_LOAD_FAILED" in res.text, res.text


def test_valid_model_activates_and_suffix_normalized():
    res = activate("memory_bank.pt", BASE_SHA)
    assert res.status_code == 200, res.text
    state = local.get("/v1/models").json()
    assert state["active_model"]["part_id"] == "memory_bank"
    assert any(m["is_active"] for m in state["available_models"]), "활성 모델 표시 없음"


def test_registry_hides_server_paths():
    active = local.get("/v1/models").json()["active_model"]
    assert "model_path" not in active
    assert not any("\\" in str(v) or str(v).startswith("/") for v in active.values())


def test_invalid_inputs_rejected():
    for data, code in (
        ({"operating_mode": "NOT_A_MODE"}, "INVALID_OPERATING_MODE"),
        ({"part_geometry": "bogus"}, "INVALID_PART_GEOMETRY"),
        ({"camera_id": "C" * 65}, "INVALID_CAMERA_ID"),
        ({"camera_id": "=cmd|calc"}, "INVALID_CAMERA_ID"),
    ):
        res = inspect(data=data)
        assert res.status_code == 400 and code in res.text, (data, res.status_code)
    assert inspect(data={"operating_mode": "HUMAN_IN_THE_LOOP", "part_geometry": "circular_jig", "camera_id": "STRESS_CAM_01"}).status_code == 200


def test_oversized_inputs_rejected_quickly():
    started = time.perf_counter()
    res = inspect(content=png((6000, 6000)))
    assert res.status_code == 413 and "IMAGE_TOO_LARGE" in res.text, res.status_code
    assert time.perf_counter() - started < 5
    limit = server.MAX_UPLOAD_BYTES
    server.MAX_UPLOAD_BYTES = 100
    try:
        res = inspect()
        assert res.status_code == 413 and "PAYLOAD_TOO_LARGE" in res.text, res.status_code
    finally:
        server.MAX_UPLOAD_BYTES = limit


def test_activation_audit_bounded_and_names_client():
    path = audit_logger.get_activation_csv_path()
    size_before = path.stat().st_size if path.exists() else 0
    activate("A" * 1_000_000, "0", client=remote)
    assert path.stat().st_size - size_before < 2000, "감사 로그 입력 길이가 제한되지 않았습니다"
    last = list(csv.DictReader(path.open(encoding="utf-8", newline="")))[-1]
    assert "client=192.168.1.100" in last["reason"], last["reason"]


def test_audit_failure_returns_503():
    original = server.log_inspection_audit
    def fail(_):
        raise OSError("disk full")
    server.log_inspection_audit = fail
    try:
        res = inspect()
    finally:
        server.log_inspection_audit = original
    assert res.status_code == 503 and "AUDIT_WRITE_FAILED" in res.text, res.status_code
    assert "decision" not in res.json()


def test_inference_does_not_block_other_requests():
    entered, release = threading.Event(), threading.Event()
    engine = server._ACTIVE_ENGINE
    original = engine.predict
    def slow(*args, **kwargs):
        entered.set()
        release.wait(20)
        return original(*args, **kwargs)
    engine.predict = slow
    try:
        with TestClient(server.app, client=("127.0.0.1", 50000)) as shared:
            worker = threading.Thread(target=lambda: inspect(client=shared))
            worker.start()
            assert entered.wait(10), "추론이 시작되지 않았습니다"
            started = time.perf_counter()
            result = {}
            health = threading.Thread(target=lambda: result.update(res=shared.get("/health")))
            health.start()
            health.join(5)
            blocked = health.is_alive()
            release.set()
            health.join(20)
            worker.join(30)
            assert not blocked, "추론 중 /health가 응답하지 못했습니다"
            assert result["res"].status_code == 200 and time.perf_counter() - started < 20
    finally:
        release.set()
        del engine.predict


def test_saturated_inference_returns_503():
    wait = server.INFERENCE_WAIT_SEC
    server.INFERENCE_WAIT_SEC = 0.1
    assert server._INFERENCE_SLOTS.acquire(timeout=5)
    try:
        res = inspect()
    finally:
        server._INFERENCE_SLOTS.release()
        server.INFERENCE_WAIT_SEC = wait
    assert res.status_code == 503 and "SERVER_BUSY" in res.text, res.status_code


def test_lock_retries_on_windows_delete_pending():
    target = TMP / "retry.csv"
    real_open, calls = os.open, []
    def flaky(path, flags, *args, **kwargs):
        if str(path).endswith(".lock") and not calls:
            calls.append(1)
            raise PermissionError(13, "delete pending")
        return real_open(path, flags, *args, **kwargs)
    audit_logger.os.open = flaky
    try:
        with audit_logger.interprocess_file_lock(target):
            assert target.with_suffix(".lock").exists(), "락 없이 진입했습니다"
    finally:
        audit_logger.os.open = real_open


def test_lock_timeout_raises_instead_of_writing_unlocked():
    target = TMP / "held.csv"
    target.with_suffix(".lock").write_text("")
    os.utime(target.with_suffix(".lock"))
    raised = False
    try:
        with audit_logger.interprocess_file_lock(target, timeout=5.0, hard_timeout=0.2):
            pass
    except TimeoutError:
        raised = True
    assert raised, "락을 얻지 못했는데 진입했습니다"
    target.with_suffix(".lock").unlink()


def test_read_recent_limit_zero_returns_all_newest_first():
    target = TMP / "recent.csv"
    for i in range(60):
        audit_logger.log_inspection_audit({"inspection_id": str(i), "decision": "PASS"}, csv_path=target)
    rows = audit_logger.read_recent_audit_logs(limit=0, csv_path=target)
    assert len(rows) == 60 and rows[0]["inspection_id"] == "59", len(rows)
    assert len(audit_logger.read_recent_audit_logs(csv_path=target)) == 50


def _decide(score, mode="HUMAN_IN_THE_LOOP", peak=0.5, area=0.0, **policy):
    thresholds = {"peak_severe_threshold": 0.65, "edge_involvement_threshold": 0.14, "area_severe_threshold": 0.16, **policy}
    return evaluate_defect(score, area, peak, 0.0, operating_mode=mode, structural_thresholds=thresholds)


def test_human_in_the_loop_review_band():
    assert _decide(0.57)["decision"] == "PASS"
    assert _decide(0.59)["decision"] == "MANUAL_REVIEW"
    assert _decide(0.59, peak=0.9)["decision"] == "MANUAL_REVIEW"
    assert "extreme_peak_patch_distance" in _decide(0.59, peak=0.9)["decision_basis"]
    assert _decide(0.62)["decision"] == "MANUAL_REVIEW"
    scrap = _decide(0.62, peak=0.9)
    assert scrap["decision"] == "SCRAP" and scrap["interlock"] is True
    assert _decide(0.70)["decision"] == "REWORK"
    assert _decide(0.70, peak=0.9)["decision"] == "SCRAP"


def test_other_modes_keep_decisions():
    safety = _decide(0.59, mode="SAFETY_FIRST")
    assert safety["decision"] == "PASS" and safety["manual_review_recommended"] is True
    assert _decide(0.62, mode="BALANCED_THROUGHPUT")["decision"] == "PASS"
    assert _decide(0.62, mode="SAFETY_FIRST")["decision"] == "REWORK"


def test_non_autonomous_model_never_acts_alone():
    assert _decide(0.57, mode="SAFETY_FIRST", autonomous_decision_allowed=False)["decision"] == "PASS"
    for score, peak in ((0.59, 0.5), (0.9, 0.9)):
        result = _decide(score, mode="SAFETY_FIRST", peak=peak, autonomous_decision_allowed=False)
        assert result["decision"] == "MANUAL_REVIEW" and result["interlock"] is False, result
    assert "extreme_peak_patch_distance" in _decide(0.9, mode="SAFETY_FIRST", peak=0.9, autonomous_decision_allowed=False)["decision_basis"]


def test_disabled_structural_check_requires_review():
    result = _decide(0.9, mode="SAFETY_FIRST", peak_severe_threshold=1e9)
    assert result["decision"] == "MANUAL_REVIEW" and "structural_check_disabled" in result["decision_basis"]
    assert _decide(0.59, mode="SAFETY_FIRST", peak_severe_threshold=1e9)["decision"] == "PASS"


def test_manual_review_result_shape():
    review, rework = _decide(0.59), _decide(0.70)
    assert set(review) == set(rework), set(review) ^ set(rework)
    assert review["heatmap_display"] == "ACTIVE_ANOMALY" and review["manual_review_recommended"] is True
    assert review["pattern_estimate"] is None and "자동 이송합니다" not in review["summary"]


def test_server_applies_autonomy_policy_and_audits_review():
    flip = BASE_DIR / "datasets" / "metal_nut" / "metal_nut" / "test" / "flip"
    image = sorted(flip.glob("*.png"))[0].read_bytes() if flip.exists() else png()
    digest = add_model("regtest_pilot", meta={
        "confidence_tier": "PILOT_LOW_CONFIDENCE",
        "autonomous_decision_allowed": False,
        "split": {"bank_validation_overlap": 0},
        "output": {"pt_sha256": sha_of(BASE_PT)}
    })
    try:
        res = activate("regtest_pilot", digest)
        assert res.status_code == 200 and res.json()["autonomous_decision_allowed"] is False, res.text
        assert local.get("/health").json()["confidence_tier"] == "PILOT_LOW_CONFIDENCE"
        assert local.get("/v1/models").json()["active_model"]["autonomous_decision_allowed"] is False
        body = inspect(content=image).json()
        assert body["confidence_tier"] == "PILOT_LOW_CONFIDENCE" and body["autonomous_decision_allowed"] is False
        assert body["interlock"] is False and body["decision"] in ("PASS", "MANUAL_REVIEW"), body["decision"]
        if flip.exists():
            assert body["decision"] == "MANUAL_REVIEW", body["anomaly_score"]
            rows = list(csv.DictReader(audit_logger.get_audit_csv_path().open(encoding="utf-8", newline="")))
            assert rows[-1]["inspection_id"] == body["inspection_id"] and rows[-1]["decision"] == "MANUAL_REVIEW"

        digest = add_model("regtest_nofield", meta={"split": {"bank_validation_overlap": 0}, "output": {"pt_sha256": sha_of(BASE_PT)}})
        res = activate("regtest_nofield", digest)
        assert res.status_code == 200 and res.json()["autonomous_decision_allowed"] is False, res.text
        assert res.json()["confidence_tier"] == "UNKNOWN"
    finally:
        restore_base_model()
    state = local.get("/health").json()
    assert state["autonomous_decision_allowed"] is True and state["confidence_tier"] == "PRODUCTION_READY"


def test_mock_area_limit_lives_in_server_only():
    os.environ["ALLOW_MOCK"] = "1"
    try:
        def decide(area):
            res = local.post(
                "/v1/defects/inspect",
                files={"file": ("a.png", png(), "image/png")},
                headers={"x-mock-score": "0.7", "x-mock-area": str(area)},
            )
            return res.json()["decision"]
        assert decide(0.03) == "SCRAP" and decide(0.029) == "REWORK"
    finally:
        os.environ.pop("ALLOW_MOCK", None)
    # 룰 엔진 자체에는 테스트 전용 기준이 없어야 한다.
    assert evaluate_defect(0.7, 0.03, 0.0, 0.0)["decision"] == "REWORK"


def test_openapi_lists_every_route():
    spec = BASE_DIR / "docs" / "openapi.yaml"
    if not spec.exists():  # role_3에는 openapi.yaml이 없다.
        return
    documented = set(re.findall(r"(?m)^  (/\S+):$", spec.read_text(encoding="utf-8")))
    routes = {r.path for r in server.app.routes} - {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}
    assert documented == routes, documented ^ routes


def main() -> int:
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    try:
        for test in tests:
            try:
                test()
                print(f"PASS {test.__name__}")
            except BaseException as e:
                failed += 1
                print(f"FAIL {test.__name__}: {type(e).__name__}: {str(e)[:200]}")
    finally:
        for path in MODELS.glob("regtest_*"):
            path.unlink()
        restore_base_model()
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
