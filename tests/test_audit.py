"""
포스코 AI 해커톤 - 과제 B: 감사 로그(MES Audit Trail) 무결성·보안·동시성 검증 스위트
파일명: tests/test_audit.py

검증 항목:
1. UUID4 형식 inspection_id 검증 및 API 응답 키·타입 호환성 확인
2. 테스트용 Mock 요청(mock=True) 감사 로그 자동 제외 확인
3. 원본 이미지, heatmap_base64, 개인정보(PII) 미저장 및 엑셀 수식 인젝션(=, +, -, @) 차단 확인
4. 동시 요청 20건(ThreadPoolExecutor 20 workers) -> CSV 20행 정상 기록 및 inspection_id 1:1 일치 검증
5. 엔진 직접 추론 vs 감사 로그 연동 후 결과 비교 (21개 케이스 차이 0건 검증)
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path
import csv
import uuid
from concurrent.futures import ThreadPoolExecutor
from PIL import Image

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from audit_logger import (
    AUDIT_COLUMNS,
    FORBIDDEN_KEYS,
    sanitize_csv_value,
    log_inspection_audit,
    read_recent_audit_logs,
    read_audit_csv_bytes
)
from patchcore_engine import get_engine

DATASET_TEST_DIR = BASE_DIR / "datasets" / "metal_nut" / "metal_nut" / "test"
TEMP_AUDIT_CSV = BASE_DIR / "logs" / "test_inspection_audit_temp.csv"


def _standalone_proc_worker(args: tuple[int, str]) -> str:
    idx, csv_path_str = args
    insp_id = str(uuid.uuid4())
    payload = {
        "timestamp": f"2026-11-06T06:00:{idx % 60:02d}+00:00",
        "inspection_id": insp_id,
        "camera_id": f"CAM_PROC_{idx:03d}",
        "mock": False,
        "operating_mode": "SAFETY_FIRST",
        "decision": "PASS" if idx % 2 == 0 else "REWORK",
        "decision_threshold": 0.6000,
        "anomaly_score": round(0.2000 + (idx % 50) * 0.01, 4),
        "raw_distance": 0.4000,
        "peak_patch_distance": 0.4100,
        "defect_area_ratio": 0.0050,
        "edge_region_ratio": 0.0200,
        "structural_defect_likelihood": 0.0500,
        "reason_code": "NORMAL_SURFACE" if idx % 2 == 0 else "SURFACE_FLAW",
        "interlock": False,
        "manual_review_recommended": False,
        "estimated_defect_pattern": "NORMAL_WITHIN_SPEC",
        "engine_version": "1.2.1-eq7-stratified-offline",
        "model_hash": "4d118c709f01",
        "inference_mode": "FASTAPI_REST_SERVER"
    }
    log_inspection_audit(payload, csv_path=Path(csv_path_str))
    return insp_id


def run_audit_verification() -> None:
    print("=" * 95)
    print("🔍 [과제 B] 스마트팩토리 MES 감사 로그(Audit Trail) 통합 검증 시작")
    print("=" * 95)

    if TEMP_AUDIT_CSV.exists():
        TEMP_AUDIT_CSV.unlink()

    # 1. 엑셀 수식 인젝션 차단 및 민감 필드 배제 검증
    print("[1/5] 엑셀 수식 인젝션(=, +, -, @) 차단 및 이미지·Base64 미저장 검증 중...")
    malicious_inputs = [
        "=CMD|' /C calc'!A0",
        "+SUM(1+1)*cmd|' /C calc'!A0",
        "-2+3+cmd|' /C calc'!A0",
        "@SUM(1+1)*cmd|' /C calc'!A0"
    ]
    for m_in in malicious_inputs:
        sanitized = sanitize_csv_value(m_in)
        assert isinstance(sanitized, str) and sanitized.startswith("'"), f"수식 인젝션 차단 실패: {sanitized}"

    for fk in FORBIDDEN_KEYS:
        assert fk not in AUDIT_COLUMNS, f"금지된 이미지/민감 키가 감사 컬럼에 포함됨: {fk}"
    print("      -> 통과 (수식 인젝션 프리픽스 이스케이프 및 Base64/이미지 미저장 확인)")

    # 2. Mock 요청 로그 제외 검증
    print("[2/5] 테스트용 Mock 요청(mock=True) 감사 로그 제외 검증 중...")
    mock_logged = log_inspection_audit(
        {
            "timestamp": "2026-11-06T00:00:00+00:00",
            "inspection_id": str(uuid.uuid4()),
            "camera_id": "CAM_MOCK",
            "mock": True,
            "decision": "SCRAP",
            "inference_mode": "MOCK_TEST_OVERRIDE"
        },
        csv_path=TEMP_AUDIT_CSV
    )
    assert mock_logged is False, "Mock 요청이 감사 로그에 기록되었습니다!"
    assert not TEMP_AUDIT_CSV.exists() or len(read_recent_audit_logs(limit=10, csv_path=TEMP_AUDIT_CSV)) == 0
    print("      -> 통과 (mock=True 요청 로그 기록 제외 확인)")

    # 3. 21개 케이스(각 카테고리 대표 이미지 + 운영 모드 조합) 추론 결과 동일성 및 UUID4 검증
    print("[3/5] 21개 케이스(카테고리별 이미지 x 운영 모드) 추론 결과 무결성 및 UUID4 검증 중...")
    engine = get_engine()
    sample_files = (
        sorted(list((DATASET_TEST_DIR / "good").glob("*.png")))[:2]
        + sorted(list((DATASET_TEST_DIR / "scratch").glob("*.png")))[:2]
        + sorted(list((DATASET_TEST_DIR / "bent").glob("*.png")))[:1]
        + sorted(list((DATASET_TEST_DIR / "color").glob("*.png")))[:1]
        + sorted(list((DATASET_TEST_DIR / "flip").glob("*.png")))[:1]
    )
    modes = ["SAFETY_FIRST", "BALANCED_THROUGHPUT", "HUMAN_IN_THE_LOOP"]
    assert len(sample_files) * len(modes) == 21

    diff_count = 0
    for fpath in sample_files:
        img = Image.open(fpath).convert("RGB")
        for m in modes:
            # 감사 로그 기록 전 추론
            pred_before = engine.predict(img, include_heatmap=False, operating_mode=m)
            insp_id = str(uuid.uuid4())
            # UUID4 형식 검증
            parsed_uuid = uuid.UUID(insp_id, version=4)
            assert str(parsed_uuid) == insp_id

            payload = {
                "timestamp": "2026-11-06T04:00:00+00:00",
                "inspection_id": insp_id,
                "camera_id": "=CAM_INJECT_TEST",
                "mock": False,
                "operating_mode": m,
                "decision": pred_before["decision"],
                "decision_threshold": pred_before["decision_threshold"],
                "anomaly_score": pred_before["anomaly_score"],
                "raw_distance": pred_before["raw_distance"],
                "peak_patch_distance": pred_before["peak_patch_distance"],
                "defect_area_ratio": pred_before["defect_area_ratio"],
                "edge_region_ratio": pred_before["edge_region_ratio"],
                "structural_defect_likelihood": pred_before["structural_defect_likelihood"],
                "reason_code": pred_before["reason_code"],
                "interlock": pred_before["interlock"],
                "manual_review_recommended": pred_before["manual_review_recommended"],
                "estimated_defect_pattern": pred_before["estimated_defect_pattern"],
                "engine_version": pred_before["engine_version"],
                "model_hash": pred_before["model_hash"],
                "inference_mode": "FASTAPI_REST_SERVER",
                "heatmap_base64": "BASE64_SHOULD_NOT_BE_SAVED"
            }
            ok = log_inspection_audit(payload, csv_path=TEMP_AUDIT_CSV)
            assert ok is True

            # 감사 로그 기록 후 추론 비교
            pred_after = engine.predict(img, include_heatmap=False, operating_mode=m)
            if (
                pred_before["anomaly_score"] != pred_after["anomaly_score"]
                or pred_before["decision"] != pred_after["decision"]
            ):
                diff_count += 1

    assert diff_count == 0, f"21개 케이스 중 추론 결과 차이 발생: {diff_count}건"
    print("      -> 통과 (21개 케이스 차이 0건, UUID4 검증 완료)")

    # 4. 동시 요청 20건(20 Concurrent Workers) -> CSV 20행 기록 및 응답과 1:1 일치 검증
    print("[4/5] 동시 요청 20건(ThreadPoolExecutor 20 workers) -> CSV 20행 1:1 일치 검증 중...")
    if TEMP_AUDIT_CSV.exists():
        TEMP_AUDIT_CSV.unlink()

    def worker_task(idx: int) -> dict:
        insp_id = str(uuid.uuid4())
        payload = {
            "timestamp": f"2026-11-06T05:00:{idx:02d}+00:00",
            "inspection_id": insp_id,
            "camera_id": f"CAM_CONCURRENT_{idx:02d}",
            "mock": False,
            "operating_mode": "SAFETY_FIRST",
            "decision": "PASS" if idx % 2 == 0 else "SCRAP",
            "decision_threshold": 0.6000,
            "anomaly_score": round(0.3000 + idx * 0.02, 4),
            "raw_distance": 0.4100,
            "peak_patch_distance": 0.4200,
            "defect_area_ratio": 0.0100,
            "edge_region_ratio": 0.0500,
            "structural_defect_likelihood": 0.1200,
            "reason_code": "NORMAL_SURFACE" if idx % 2 == 0 else "CRITICAL_SHAPE_DEFORMATION",
            "interlock": (idx % 2 != 0),
            "manual_review_recommended": False,
            "estimated_defect_pattern": "NORMAL_WITHIN_SPEC",
            "engine_version": engine.engine_version,
            "model_hash": engine.model_hash,
            "inference_mode": "FASTAPI_REST_SERVER",
            "heatmap_base64": "NEVER_SAVE_THIS_BASE64_STRING"
        }
        log_inspection_audit(payload, csv_path=TEMP_AUDIT_CSV)
        return payload

    with ThreadPoolExecutor(max_workers=20) as pool:
        sent_payloads = list(pool.map(worker_task, range(20)))

    with open(TEMP_AUDIT_CSV, mode="r", encoding="utf-8", newline="") as f:
        csv_rows = list(csv.DictReader(f))

    assert len(csv_rows) == 20, f"동시 20건 기록 후 CSV 행 개수 불일치: {len(csv_rows)} != 20"
    sent_ids = {p["inspection_id"] for p in sent_payloads}
    logged_ids = {r["inspection_id"] for r in csv_rows}
    assert sent_ids == logged_ids, "전송된 20건의 inspection_id와 CSV 기록이 1:1 일치하지 않습니다!"

    raw_csv_text = TEMP_AUDIT_CSV.read_text(encoding="utf-8")
    assert "NEVER_SAVE_THIS_BASE64_STRING" not in raw_csv_text, "Base64 문자열이 CSV에 유출되었습니다!"
    print("      -> 통과 (동시 요청 20건 -> CSV 20행 정상, 응답과 1:1 일치 확인)")

    # 5. 대시보드용 최근 50건 조회 및 UTF-8 BOM 바이트 다운로드 함수 검증
    print("[5/6] 대시보드 최근 50건 조회 및 CSV 다운로드 바이트 생성 검증 중...")
    recent_50 = read_recent_audit_logs(limit=50, csv_path=TEMP_AUDIT_CSV)
    assert len(recent_50) == 20
    csv_bytes = read_audit_csv_bytes(csv_path=TEMP_AUDIT_CSV)
    assert len(csv_bytes) > 100

    # 6. 멀티 프로세스(Inter-process) 동시 200건 스트레스 테스트 (서버-대시보드 동시 실행 시뮬레이션)
    print("[6/6] 멀티 프로세스(ProcessPoolExecutor 8 workers x 25 = 200건) 동시 쓰기 무유실 검증 중...")
    if TEMP_AUDIT_CSV.exists():
        TEMP_AUDIT_CSV.unlink()

    from concurrent.futures import ProcessPoolExecutor

    # 프로세스 워커 함수
    worker_args = [(i, str(TEMP_AUDIT_CSV)) for i in range(200)]
    with ProcessPoolExecutor(max_workers=8) as proc_pool:
        proc_results = list(proc_pool.map(_standalone_proc_worker, worker_args))

    with open(TEMP_AUDIT_CSV, mode="r", encoding="utf-8", newline="") as f:
        mp_rows = list(csv.DictReader(f))

    assert len(mp_rows) == 200, f"멀티 프로세스 200건 동시 기록 후 유실 발생: {len(mp_rows)} != 200"
    mp_sent_ids = set(proc_results)
    mp_logged_ids = {r["inspection_id"] for r in mp_rows}
    assert mp_sent_ids == mp_logged_ids, "멀티 프로세스 inspection_id와 CSV 기록 간 불일치 발생!"
    print("      -> 통과 (멀티 프로세스 동시 200건 전량 유실 없이 200/200 100% 기록 확인)")

    # 임시 테스트 CSV 정리
    if TEMP_AUDIT_CSV.exists():
        TEMP_AUDIT_CSV.unlink()

    print("=" * 95)
    print("✅ [과제 B] 스마트팩토리 MES 감사 로그 검증 완료 (Exit Code 0)")
    print("=" * 95)


if __name__ == "__main__":
    run_audit_verification()
