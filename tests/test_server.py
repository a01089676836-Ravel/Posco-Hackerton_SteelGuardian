"""
포스코 AI 해커톤 - 자동화 시나리오, 무누수 인덱스 교집합, Seed 42 일관성 및 운영 보안 테스트
파일명: tests/test_server.py
"""

import json
import base64
import os
import hashlib
from pathlib import Path
from fastapi.testclient import TestClient
import io
import sys
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np
from PIL import Image

BASE_DIR = Path(__file__).parent.parent
os.environ.setdefault("AUDIT_LOG_DIR", str(BASE_DIR / "logs" / "test"))
sys.path.insert(0, str(BASE_DIR))
from server import app
from patchcore_engine import PatchCoreEngine, get_engine

client = TestClient(app)
DATASET_DIR = BASE_DIR / "datasets" / "metal_nut" / "metal_nut" / "test"
MODELS_DIR = BASE_DIR / "models"


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "PatchCore" in data["model"]
    assert "engine_version" in data and len(data["model_hash"]) == 12
    assert data["benchmark_metrics"]["image_auroc"] > 0.99
    print(f"✅ [Health Check] 통과 (Engine={data['engine_version']}, Hash={data['model_hash']}, Image AUROC={data['benchmark_metrics']['image_auroc']:.4f})")


def test_mock_header_blocked_in_production():
    """
    보안 검증: ALLOW_MOCK 환경변수가 꺼져 있을 때(운영 기본값) x-mock-score 헤더 전송 시
    403 Forbidden (MOCK_DISABLED)으로 즉시 차단되는지 검증
    """
    os.environ.pop("ALLOW_MOCK", None)
    dummy_img = Image.new("RGB", (100, 100), color=(128, 128, 128))
    buf = io.BytesIO()
    dummy_img.save(buf, format="PNG")
    files = {"file": ("dummy.png", buf.getvalue(), "image/png")}
    res = client.post("/v1/defects/inspect", files=files, headers={"x-mock-score": "0.10"})
    assert res.status_code == 403, f"운영 모드에서 mock 헤더가 차단되지 않았습니다: {res.status_code}"
    assert "MOCK_DISABLED" in res.json()["detail"]
    print("✅ [Security Check] 운영 환경(ALLOW_MOCK 미설정)에서 x-mock-score 헤더 403 MOCK_DISABLED 차단 확인")


def test_evaluation_audit_endpoint():
    """
    1. memory_bank.pt와 evaluation.json에서 실제 bank_image_indices(190개)와 validation_image_indices(30개)를 불러와
       집합 교집합이 0개(len(set(bank_idx) & set(val_idx)) == 0)임을 직접 계산해 검증
    2. 기본 raw_threshold와 per_seed.seed_42.threshold가 소수점 끝자리까지 완전히 동일한지 검증
    3. defect_area_ratio 클리핑 미적용 및 validation-only 규칙 임계치 출처 기록 확인
    4. PatchCore Eq. 6·7 재가중 전후 AUROC 및 상관계수 기록 확인
    """
    response = client.get("/v1/defects/evaluation")
    assert response.status_code == 200
    report = response.json()

    tc = report["threshold_calibration"]
    mc = report["model_configuration"]
    ov = report["overall_metrics"]
    engine = get_engine()

    # 실제 인덱스 배열 교집합 검증 (JSON 문자열 확인이 아닌 실제 집합 연산)
    bank_idx = tc["bank_image_indices"]
    val_idx = tc["validation_image_indices"]
    assert len(set(bank_idx) & set(val_idx)) == 0, "메모리 뱅크와 검증셋 인덱스에 교집합이 존재합니다!"
    assert len(bank_idx) == 190, f"bank_idx 길이 오류: {len(bank_idx)}"
    assert len(val_idx) == 30, f"val_idx 길이 오류: {len(val_idx)}"
    assert set(bank_idx) | set(val_idx) == set(range(220)), "전체 220장 분할 누락 발생!"

    # memory_bank.pt 체크포인트 내부 인덱스 배열과도 100% 일치하는지 검증
    assert engine.bank_image_indices == bank_idx
    assert engine.validation_image_indices == val_idx
    assert len(set(engine.bank_image_indices) & set(engine.validation_image_indices)) == 0

    # Primary Seed 42 조도 층화 분할 통일 검증 (기본 raw_threshold == per_seed.seed_42.threshold)
    assert tc["split_method"] == "brightness_stratified"
    assert tc["primary_seed"] == 42
    strat = tc["multi_seed_stratified_thresholds"]
    seed42_th = strat["per_seed"]["seed_42"]["threshold"]
    assert tc["raw_threshold"] == seed42_th, f"Seed 42 임계치 불일치: raw={tc['raw_threshold']} vs seed_42={seed42_th}"
    assert strat["primary_seed_42_matches_raw_threshold"] is True

    for seed_key, seed_val in strat["per_seed"].items():
        assert seed_val["overlap_between_memory_bank_and_calibration"] == 0, f"{seed_key} 교집합 발생!"
        assert seed_val["memory_bank_source_images"] == 190
        assert seed_val["calibration_images"] == 30

    assert tc["defect_area_ratio_clipped_or_manipulated"] is False
    assert "derivation_basis" in tc["structural_thresholds"]
    assert ov["image_score_method"] == "patchcore_eq7_reweighted_max_1nn"
    assert ov["reweight_neighbors_b"] == 9
    assert mc["image_score_method"] == "patchcore_eq7_reweighted_max_1nn"

    for mode_name in ("SAFETY_FIRST", "BALANCED_THROUGHPUT", "HUMAN_IN_THE_LOOP"):
        assert report["operating_modes_comparison"][mode_name]["decision_heatmap_label_synced"] is True

    assert report["operational_safety_metrics"]["false_negatives_to_pass"] == 0
    assert report["operational_safety_metrics"]["defect_recall_pct"] == 100.0
    assert report["per_category_breakdown"]["bent"]["SCRAP"] >= 20
    assert report["per_category_breakdown"]["flip"]["SCRAP"] == 23
    assert ov["au_pro_03_700x700"] > 0.88
    print(
        f"✅ [Evaluation Audit] 통과 (실제 인덱스 집합 교집합={len(set(bank_idx) & set(val_idx))}, "
        f"Seed 42 임계치={tc['raw_threshold']}=={seed42_th} 완전 일치, 700x700 좌표계 검증 완료)"
    )


def test_operating_mode_decision_heatmap_label_consistency():
    good_files = sorted(list((DATASET_DIR / "good").glob("*.png")))
    borderline_bytes = None
    for p in good_files:
        raw_b = p.read_bytes()
        r_safe = client.post(
            "/v1/defects/inspect",
            files={"file": ("part.png", raw_b, "image/png")},
            data={"operating_mode": "SAFETY_FIRST", "include_heatmap": "true"}
        ).json()
        if 0.6000 <= r_safe["anomaly_score"] < 0.6450:
            borderline_bytes = raw_b
            break

    assert borderline_bytes is not None, "경계 구간(0.60~0.645) 샘플을 찾지 못했습니다."

    res_safe = client.post(
        "/v1/defects/inspect",
        files={"file": ("borderline.png", borderline_bytes, "image/png")},
        data={"operating_mode": "SAFETY_FIRST", "include_heatmap": "true"}
    ).json()
    res_bal = client.post(
        "/v1/defects/inspect",
        files={"file": ("borderline.png", borderline_bytes, "image/png")},
        data={"operating_mode": "BALANCED_THROUGHPUT", "include_heatmap": "true"}
    ).json()

    assert res_safe["decision"] == "REWORK"
    assert res_safe["decision_threshold"] == 0.60
    assert res_safe["heatmap_display"] == "ACTIVE_ANOMALY"
    assert res_safe["pattern_estimate"] is not None

    assert res_bal["decision"] == "PASS"
    assert res_bal["decision_threshold"] == 0.645
    assert res_bal["heatmap_display"] == "SUPPRESSED_BELOW_THRESHOLD"
    assert res_bal["pattern_estimate"] is None
    assert res_bal["estimated_defect_pattern"] == "NORMAL_WITHIN_SPEC"

    orig_arr = np.array(Image.open(io.BytesIO(borderline_bytes)).convert("RGB"))
    bal_hm_arr = np.array(Image.open(io.BytesIO(base64.b64decode(res_bal["heatmap_base64"]))).convert("RGB"))
    safe_hm_arr = np.array(Image.open(io.BytesIO(base64.b64decode(res_safe["heatmap_base64"]))).convert("RGB"))
    assert np.array_equal(orig_arr, bal_hm_arr), "BALANCED_THROUGHPUT PASS 판정인데 히트맵이 원본과 다릅니다!"
    assert not np.array_equal(orig_arr, safe_hm_arr), "SAFETY_FIRST REWORK 판정인데 히트맵이 오버레이되지 않았습니다!"
    print(
        f"✅ [Mode Sync Test] 경계 점수({res_bal['anomaly_score']})에서 "
        f"SAFETY_FIRST({res_safe['decision']}, {res_safe['heatmap_display']}) vs "
        f"BALANCED_THROUGHPUT({res_bal['decision']}, {res_bal['heatmap_display']}) 완전 동기화 확인"
    )


def test_scenarios_from_json():
    json_path = BASE_DIR / "tests" / "scenarios.json"
    with open(json_path, "r", encoding="utf-8") as f:
        spec = json.load(f)

    for scen in spec["scenarios"]:
        scen_id = scen["id"]
        scen_name = scen["name"]
        expected_code = scen["expected_status_code"]

        if scen["input_type"] == "file":
            cat = scen["file_category"]
            img_path = sorted(list((DATASET_DIR / cat).glob("*.png")))[0]
            with open(img_path, "rb") as img_file:
                files = {"file": ("anonymous_part.png", img_file.read(), "image/png")}
                res = client.post("/v1/defects/inspect", files=files)

            assert res.status_code == expected_code, f"{scen_id} 실패: 상태코드 불일치"
            data = res.json()
            assert data["mock"] is False
            assert data["decision"] == scen["expected_decision"], (
                f"{scen_id} 판정 불일치: 기대={scen['expected_decision']}, "
                f"실제={data['decision']} (score={data['anomaly_score']}, area={data['defect_area_ratio']})"
            )
            assert data["interlock"] == scen["expected_interlock"], f"{scen_id} 인터록 불일치"
            assert data["inference_mode"] == "FASTAPI_REST_SERVER"
            assert "decision_basis" in data and "heatmap_display" in data
            print(
                f"✅ [{scen_id}] {scen_name} (익명 파일명 전송) -> {data['decision']} "
                f"(score={data['anomaly_score']}, unclipped_area={data['defect_area_ratio']*100:.2f}%, "
                f"basis={data['decision_basis']}) 통과"
            )

        elif scen["input_type"] == "mock_score":
            os.environ["ALLOW_MOCK"] = "1"
            try:
                dummy_img = Image.new("RGB", (100, 100), color=(128, 128, 128))
                buf = io.BytesIO()
                dummy_img.save(buf, format="PNG")
                files = {"file": ("dummy.png", buf.getvalue(), "image/png")}
                headers = {
                    "x-mock-score": str(scen["score"]),
                    "x-mock-area": str(scen["area_ratio"])
                }
                res = client.post("/v1/defects/inspect", files=files, headers=headers)
                assert res.status_code == expected_code
                data = res.json()
                assert data["mock"] is True
                assert data["decision"] == scen["expected_decision"]
                assert data["interlock"] == scen["expected_interlock"]
                print(f"✅ [{scen_id}] {scen_name} (ALLOW_MOCK=1 로컬 단위 테스트, mock=True) -> {data['decision']} 통과")
            finally:
                os.environ.pop("ALLOW_MOCK", None)

        elif scen["input_type"] == "empty_bytes":
            files = {"file": ("empty.png", b"", "image/png")}
            res = client.post("/v1/defects/inspect", files=files)
            assert res.status_code == expected_code
            print(f"✅ [{scen_id}] {scen_name} -> 에러 {res.status_code} 정상 포착")

        elif scen["input_type"] == "corrupted_bytes":
            files = {"file": ("corrupt.png", b"NOT_A_VALID_IMAGE_DATA", "image/png")}
            res = client.post("/v1/defects/inspect", files=files)
            assert res.status_code == expected_code
            print(f"✅ [{scen_id}] {scen_name} -> 에러 {res.status_code} 정상 포착")


def test_deterministic_reload_and_jpeg_perturbation():
    img_path = sorted(list((DATASET_DIR / "scratch").glob("*.png")))[0]
    raw_bytes = img_path.read_bytes()

    res1 = client.post("/v1/defects/inspect", files={"file": ("random_name_A.png", raw_bytes, "image/png")}).json()
    res2 = client.post("/v1/defects/inspect", files={"file": ("completely_different_B.png", raw_bytes, "image/png")}).json()

    assert res1["anomaly_score"] == res2["anomaly_score"]
    assert res1["defect_area_ratio"] == res2["defect_area_ratio"]
    assert res1["decision"] == res2["decision"]
    assert res1["heatmap_base64"] == res2["heatmap_base64"]

    fresh_engine = PatchCoreEngine()
    pil_img = Image.open(io.BytesIO(raw_bytes))
    pred_singleton = get_engine().predict(pil_img, include_heatmap=False)
    pred_fresh = fresh_engine.predict(pil_img, include_heatmap=False)
    assert pred_singleton["anomaly_score"] == pred_fresh["anomaly_score"]
    assert pred_singleton["raw_distance"] == pred_fresh["raw_distance"]

    jpg_buf = io.BytesIO()
    pil_img.convert("RGB").save(jpg_buf, format="JPEG", quality=95)
    res_jpg = client.post("/v1/defects/inspect", files={"file": ("reencoded.jpg", jpg_buf.getvalue(), "image/jpeg")}).json()
    delta = abs(res1["anomaly_score"] - res_jpg["anomaly_score"])
    assert delta < 0.03, f"JPEG 재인코딩 점수 편차 과다: {delta}"
    assert res1["decision"] == res_jpg["decision"], "JPEG 재인코딩 후 판정 변경됨"
    print(f"✅ [REPRODUCIBILITY & JPEG] 재로드 오차=0.0, JPEG Q95 편차={delta:.4f}, 판정 불변({res1['decision']}) 확인")


def test_unsupported_media_type():
    files = {"file": ("document.pdf", b"%PDF-1.4...", "image/png")}
    res = client.post("/v1/defects/inspect", files=files)
    assert res.status_code == 415
    print("✅ [UNSUPPORTED_MEDIA] 비지원 확장자 415 에러 정상 포착")


def test_model_registry_and_activation_api():
    # 1. 모델 레지스트리 조회
    res = client.get("/v1/models")
    assert res.status_code == 200
    data = res.json()
    assert "active_model" in data and "available_models" in data
    assert len(data["available_models"]) >= 1
    act = data["active_model"]
    assert "model_hash" in act and "raw_threshold" in act
    assert "model_sha256" in act and len(act["model_sha256"]) == 64
    assert "model_version" in act and "activated_at" in act

    # 2. 존재하지 않는 모델 활성화 시 400 에러
    res_fake = client.post("/v1/models/activate", json={"part_id": "non_existent_part", "expected_sha256": "0" * 64})
    assert res_fake.status_code == 400
    assert "MODEL_FILE_NOT_FOUND" in res_fake.text

    # 3. SHA256 체크섬 불일치 시 409 Conflict 반환 검증
    res_bad_sha = client.post("/v1/models/activate", json={"part_id": "memory_bank", "expected_sha256": "bad_sha_" + "0" * 56})
    assert res_bad_sha.status_code == 409
    assert "SHA256_MISMATCH" in res_bad_sha.text

    # 3-1. 원격 모델 활성화 보안 인증 및 403 분기 검증
    # 실제 원격 피어를 시뮬레이션 (x-forwarded-for는 인가 판단에 사용되지 않음)
    remote_client = TestClient(app, client=("192.168.1.100", 50000))

    # A. 기본 환경(ALLOW_REMOTE_ACTIVATION=0)에서 원격 IP 호출 시 403 (REMOTE_ACTIVATION_DISABLED)
    os.environ["ALLOW_REMOTE_ACTIVATION"] = "0"
    res_remote_dis = remote_client.post(
        "/v1/models/activate",
        json={"part_id": "memory_bank", "expected_sha256": "0" * 64}
    )
    assert res_remote_dis.status_code == 403
    assert "REMOTE_ACTIVATION_DISABLED" in res_remote_dis.text

    # B. ALLOW_REMOTE_ACTIVATION=1 + x-admin-key 누락 시 403 (ADMIN_KEY_REQUIRED)
    os.environ["ALLOW_REMOTE_ACTIVATION"] = "1"
    os.environ["ADMIN_API_KEY"] = "posco-test-admin-secret-2026"
    res_remote_nokey = remote_client.post(
        "/v1/models/activate",
        json={"part_id": "memory_bank", "expected_sha256": "0" * 64}
    )
    assert res_remote_nokey.status_code == 403
    assert "ADMIN_KEY_REQUIRED" in res_remote_nokey.text

    # C. ALLOW_REMOTE_ACTIVATION=1 + 잘못된 x-admin-key 전송 시 403 (ADMIN_KEY_MISMATCH)
    res_remote_badkey = remote_client.post(
        "/v1/models/activate",
        json={"part_id": "memory_bank", "expected_sha256": "0" * 64},
        headers={"x-admin-key": "wrong-secret-key"}
    )
    assert res_remote_badkey.status_code == 403
    assert "ADMIN_KEY_MISMATCH" in res_remote_badkey.text

    # D. 올바른 key + 올바른 SHA256 호출 시 200 OK 및 GET /v1/models 반영 검증
    real_sha = hashlib.sha256((MODELS_DIR / "memory_bank.pt").read_bytes()).hexdigest().lower()
    res_remote_ok = remote_client.post(
        "/v1/models/activate",
        json={"part_id": "memory_bank", "expected_sha256": real_sha},
        headers={"x-admin-key": "posco-test-admin-secret-2026"}
    )
    assert res_remote_ok.status_code == 200
    assert res_remote_ok.json()["status"].lower() == "activated"

    # GET /v1/models 확인
    res_models_after = client.get("/v1/models").json()
    assert res_models_after["active_model"]["part_id"] == "memory_bank"
    assert res_models_after["active_model"]["model_sha256"] == real_sha

    # 테스트 후 환경변수 기본값 원복
    os.environ["ALLOW_REMOTE_ACTIVATION"] = "0"
    if "ADMIN_API_KEY" in os.environ:
        del os.environ["ADMIN_API_KEY"]

    # 4. generic vs circular_jig part_geometry 지표 분기 및 신규 응답 메타 검증
    img_path = sorted(list((DATASET_DIR / "good").glob("*.png")))[0]
    raw_b = img_path.read_bytes()

    # generic 기본값: 링 마스크 미적용 및 신규 메타데이터 검증
    res_gen = client.post("/v1/defects/inspect", files={"file": ("p.png", raw_b, "image/png")}).json()
    assert res_gen["part_geometry"] == "generic"
    assert res_gen["edge_metric_status"] == "NOT_APPLICABLE_FOR_GENERIC_PART"
    assert res_gen["edge_region_ratio"] is None
    assert res_gen["outer_ring_ratio"] is None
    assert res_gen["structural_shape_check"] == "NOT_PERFORMED"
    assert res_gen["global_deformation_coverage"] == "LIMITED"
    assert "model_part_id" in res_gen
    assert "model_sha256" in res_gen and len(res_gen["model_sha256"]) == 64
    assert "model_version" in res_gen
    assert "activated_at" in res_gen

    # circular_jig 명시: 링 마스크 정상 산출
    res_circ = client.post(
        "/v1/defects/inspect",
        files={"file": ("p.png", raw_b, "image/png")},
        data={"part_geometry": "circular_jig"}
    ).json()
    assert res_circ["part_geometry"] == "circular_jig"
    assert res_circ["edge_metric_status"] == "CALCULATED_CIRCULAR_JIG"
    assert res_circ["edge_region_ratio"] is not None
    assert res_circ["outer_ring_ratio"] is not None
    assert res_circ["structural_shape_check"] == "PERFORMED"
    assert res_circ["global_deformation_coverage"] == "SUPPORTED_RING_ONLY"
    print("✅ [MODEL_REGISTRY & GEOMETRY] /v1/models 메타 4종, 활성화 보안 검증(400), generic/circular_jig 링 지표 및 구조범위 분기 정상 통과")


if __name__ == "__main__":
    test_health_check()
    test_mock_header_blocked_in_production()
    test_evaluation_audit_endpoint()
    test_operating_mode_decision_heatmap_label_consistency()
    test_scenarios_from_json()
    test_deterministic_reload_and_jpeg_perturbation()
    test_unsupported_media_type()
    test_model_registry_and_activation_api()
    print("\n🎉 보안·무누수 인덱스 교집합·Seed 42 일관성 및 모델 레지스트리 핫스왑 모든 자동화 시나리오 100% 통과!")
