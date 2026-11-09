# POSCO Smart Factory AI Defect Inspection API Contract

## 1. 개요 (Overview)
본 문서는 포스코 제철 가공 공정의 체결용 금속 부품(Metal Nut) 표면 품질 검사를 위한 실시간 비지도 이상탐지 REST API 규격서입니다.

- **기본 접속 URL:** `http://127.0.0.1:8000` (단일 PC 로컬) 또는 `http://<호스트_IP>:8000` (`0.0.0.0` 바인딩 시 동일 LAN/Wi-Fi 외부 접속 지원)
- **버전:** `v1` (서버 `1.3.0`, 엔진 `1.2.1-eq7-stratified-offline`)
- **데이터 포맷:** JSON (응답), multipart/form-data (요청)

---

## 2. 왜 이 API 구조인가? (Design Rationale)
1. **단일 의사결정 진입점 (`rule_engine.py`) 기반 판정-히트맵-라벨 완전 동기화:**
   - 운영 모드별 임계치(`SAFETY_FIRST: 0.600`, `BALANCED_THROUGHPUT: 0.645`, `HUMAN_IN_THE_LOOP: 0.600`)에 따라 `decision == "PASS"`일 경우 `heatmap_display: "SUPPRESSED_BELOW_THRESHOLD"` 및 `pattern_estimate: null`로 동기화하여 판정과 시각화 간 모순을 원천 차단합니다.
2. **클리핑 없는 실제 결함 면적(`defect_area_ratio`) + 다중 특징 근거(`decision_basis`):**
   - `defect_area_ratio`에 어떠한 인위적 상·하한 클리핑도 가하지 않으며, 검증셋(`train/good` 30장, 메모리 뱅크 190장과 교집합 0%) 통계에서 유도된 `peak_patch_distance`, `edge_region_ratio`, `defect_area_ratio` 다중 특징 조합으로 `REWORK`와 `SCRAP`을 분기합니다.
3. **자동 판정을 보류하는 `MANUAL_REVIEW`:**
   - 아래 경우 라인 정지 없이 2차 육안 판정으로 분리하며, 위치 확인을 위해 히트맵은 `ACTIVE_ANOMALY`로 표시합니다.

   | 조건 | 판정 | `decision_basis` |
   |---|---|---|
   | 모델 메타의 `autonomous_decision_allowed`가 `true`가 아니고 점수 0.58 이상 | `MANUAL_REVIEW` (구조 근거가 있어도 SCRAP 아님) | `autonomous_decision_not_allowed` + 구조 근거 |
   | `HUMAN_IN_THE_LOOP`, 점수 0.58 이상 0.65 미만 | `MANUAL_REVIEW` (단, 0.60 이상에 구조 근거가 있으면 `SCRAP`) | `borderline_confidence_zone`, `human_review_required` + 구조 근거 |
   | 구조 임계치 없이 온보딩한 모델, 점수가 운영 임계치 이상 | `MANUAL_REVIEW` | `structural_check_disabled`, `surface_vs_structural_not_determined` |

   - `SAFETY_FIRST`, `BALANCED_THROUGHPUT`의 경계 점수는 자동 판정 허용 모델에서 기존과 같습니다 (`PASS`이면 `manual_review_recommended: true`).
   - 클라이언트는 `PASS`만 합격으로 처리해야 합니다.
4. **PatchCore 원논문 Eq. 6·7 ($\mathcal{N}_b(m^*)$ 근방 밀도 재가중) 정밀 구현:**
   - 최대 1-NN 거리를 갖는 테스트 패치 $m^{\text{test},*}$의 최근접 메모리 패치 $m^*$를 찾고, 메모리 뱅크 내부에서 $m^*$의 $b=9$개 최근접 이웃 $\mathcal{N}_b(m^*)$과의 거리로 재가중한 점수를 반환합니다.

---

## 3. 엔드포인트 명세

### 3.1 헬스체크 (Health Check)
- **URL:** `GET /health`
- **응답:**
```json
{
  "status": "healthy",
  "active_part_id": "metal_nut_default",
  "active_model_file": "memory_bank.pt",
  "confidence_tier": "PRODUCTION_READY",
  "autonomous_decision_allowed": true,
  "model": "PatchCore-ResNet18-Coreset-Eq7",
  "engine_version": "1.2.1-eq7-stratified-offline",
  "model_hash": "4d118c709f01",
  "threshold_source": "train/good_30_val_split (seed=42 brightness_stratified, Zero Overlap)",
  "raw_threshold": 0.4362,
  "version": "1.3.0",
  "device": "cpu",
  "benchmark_metrics": { "image_auroc": 0.9971 },
  "timestamp": "2026-11-06T12:00:00+00:00"
}
```

### 3.2 공식 검증 감사 리포트 조회 (Evaluation Audit Report)
- **URL:** `GET /v1/defects/evaluation`
- **설명:** `results/evaluation.json`에 저장된 5-Seed 교집합 0% 무누수 검증(`overlap_between_memory_bank_and_calibration: 0`), 원논문 Eq. 6·7 재가중 전후 AUROC 비교, 운영 모드별 동기화 검증 및 `700×700` 원본 좌표계 지표를 반환합니다.

### 3.3 결함 검사 (Inspect Defect)
- **URL:** `POST /v1/defects/inspect`
- **Content-Type:** `multipart/form-data`
- **요청 파라미터:**
  - `file`: 이미지 파일 (PNG, JPG, JPEG, BMP, WEBP 필수, 기본 한도 20MB·16MP)
  - `camera_id` (선택): 검사 카메라 식별자 (영문, 숫자, `_ . : -` 조합 64자 이내, 기본값: `CAM_FINISHING_01`)
  - `operating_mode` (선택): 운영 임계치 모드 (`SAFETY_FIRST` | `BALANCED_THROUGHPUT` | `HUMAN_IN_THE_LOOP`, 기본값: `SAFETY_FIRST`)
  - `part_geometry` (선택): 부품 기하 모드 (`generic` [기본값: 국소 이상 최적화, 링 마스크 미적용] | `circular_jig` [원형 너트 전용 링 마스크])
  - `include_heatmap` (선택): 결함 히트맵 base64 포함 여부 (기본값: `true`)

- **성공 응답 (200 OK):**
```json
{
  "inspection_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "timestamp": "2026-11-06T12:00:00Z",
  "camera_id": "CAM_FINISHING_01",
  "part_id": "metal_nut_default",
  "model_part_id": "metal_nut_default",
  "model_sha256": "4d118c709f018279439869152887ee64adfba992356f26b01c928583a6569949",
  "model_version": "1.0.0",
  "activated_at": "2026-11-06T12:00:00Z",
  "confidence_tier": "PRODUCTION_READY",
  "autonomous_decision_allowed": true,
  "part_geometry": "generic",
  "structural_shape_check": "NOT_PERFORMED",
  "global_deformation_coverage": "LIMITED",
  "mock": false,
  "decision": "SCRAP",
  "decision_threshold": 0.6,
  "decision_basis": [
    "extreme_peak_patch_distance"
  ],
  "heatmap_display": "ACTIVE_ANOMALY",
  "reason_code": "CRITICAL_SHAPE_DEFORMATION",
  "anomaly_score": 0.7421,
  "normalized_anomaly_score": 0.7421,
  "raw_anomaly_score": 0.5612,
  "raw_distance": 0.5612,
  "raw_max_1nn_score": 0.6318,
  "raw_top1_eq6": 0.6318,
  "peak_patch_distance": 0.6318,
  "defect_area_ratio": 0.0412,
  "edge_region_ratio": null,
  "outer_ring_ratio": null,
  "edge_metric_status": "NOT_APPLICABLE_FOR_GENERIC_PART",
  "structural_defect_likelihood": 0.842,
  "estimated_defect_pattern": "STRUCTURAL_DEFORMATION_ESTIMATE (rule-based: bent/flip/outer-thread)",
  "pattern_estimate": "STRUCTURAL_DEFORMATION_ESTIMATE (rule-based: bent/flip/outer-thread)",
  "manual_review_recommended": false,
  "operating_mode": "SAFETY_FIRST",
  "interlock": true,
  "summary": "치명적 구조/외곽 변형 추정(STRUCTURAL_DEFORMATION_ESTIMATE) 감지! 비상 인터록을 발령하고 즉시 폐기 처리합니다.",
  "engine_version": "1.2.1-eq7-stratified-offline",
  "model_hash": "4d118c709f01",
  "threshold_source": "train/good_30_val_split (seed=42 brightness_stratified, Zero Overlap)",
  "inference_mode": "FASTAPI_REST_SERVER",
  "heatmap_base64": "iVBORw0KGgoAAAANSUhEUgAA..."
}
```

- **오류 응답:**

| 상태 코드 | detail 접두어 | 조치 |
|---|---|---|
| 400 | `EMPTY_FILE`, `CORRUPTED_IMAGE`, `INVALID_OPERATING_MODE`, `INVALID_PART_GEOMETRY`, `INVALID_CAMERA_ID` | 입력 수정 |
| 403 | `MOCK_DISABLED` | 운영 환경에서 mock 헤더 제거 |
| 413 | `PAYLOAD_TOO_LARGE`, `IMAGE_TOO_LARGE` | 크기·해상도 축소 |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | 지원 형식 사용 |
| 503 | `SERVER_BUSY` | 잠시 후 재시도 |
| 503 | `AUDIT_WRITE_FAILED` | 판정 미반환. 원인 조치 후 재검사 |

- **서버 환경변수:** `MAX_UPLOAD_BYTES`(기본 20MB), `MAX_IMAGE_PIXELS`(기본 16000000), `MAX_CONCURRENT_INFERENCES`(기본 1), `INFERENCE_WAIT_SEC`(기본 30)

### 3.4 모델 레지스트리 조회 (Model Registry)
- **URL:** `GET /v1/models`
- **설명:** 현재 서버에 활성화된 부품 모델 정보와 `models/` 내 사용 가능한 모델 목록(SHA256, confidence_tier, split_overlap 등)을 반환합니다.

### 3.5 모델 원자적 핫스왑 활성화 (Activate Model)
- **URL:** `POST /v1/models/activate`
- **요청 Body:**
```json
{
  "part_id": "custom_part_bank",
  "expected_sha256": "5c5f6608680e353ac786303db434a58d521959f1d2e3925434335b9149210551"
}
```
- **보안 검증:** 실패 시 기존 모델을 그대로 유지합니다.

| 상태 코드 | detail 접두어 | 조건 |
|---|---|---|
| 400 | `EMPTY_PART_ID`, `INVALID_PART_ID`, `PATH_TRAVERSAL_DETECTED`, `MODEL_FILE_NOT_FOUND` | 대상 모델 지정 오류 |
| 400 | `MISSING_META_JSON`, `INVALID_META_JSON` | 메타 파일 없음, 필수 필드(`split.bank_validation_overlap`, `output.pt_sha256`) 없음 |
| 400 | `MODEL_LOAD_FAILED` | 체크포인트 손상 또는 코드 실행 가능 객체 포함 (`weights_only=True` 로드 실패) |
| 403 | `FORBIDDEN: ...` | 원격 호출 권한 없음. `x-forwarded-for`는 인가 판단에 사용하지 않음 |
| 409 | `SHA256_MISMATCH` | `expected_sha256`과 실제 파일 불일치 |
| 409 | `META_MODEL_SHA_MISMATCH` | 메타의 `output.pt_sha256`과 실제 파일 불일치 |
| 409 | `DATASET_LEAKAGE_OVERLAP_DETECTED` | 메타 또는 체크포인트 실제 인덱스에서 교집합 감지 |
| 409 | `MODEL_CHANGED_DURING_ACTIVATION` | 검증 중 파일 변경 |

활성화 감사 로그의 `reason`에는 `|client=<호출자 IP>`가 함께 기록됩니다.
