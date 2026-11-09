# POSCO Smart Factory AI Defect Inspection System (`v1.3.0-model-registry-hot-swap`)
> **포스코 AI 해커톤 2026** — 비지도 학습(PatchCore Eq. 6·7) 기반 금속 부품 표면 결함 실시간 검사, 모델 레지스트리 핫스왑 및 다중 특징 3단계 공정 제어 시스템

[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-REST_API-green.svg)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-SCADA_Dashboard-red.svg)](https://streamlit.io/)
[![PatchCore](https://img.shields.io/badge/PatchCore-CVPR_2022_Eq.6·7-orange.svg)](https://arxiv.org/abs/2106.08265)

---

## 1. 프로젝트 개요 (Overview)
- **팀명:** 스틸가디언 (SteelGuardian)
- **팀 구성:**
  - **전종현 (팀장):** 프로젝트 총괄, 아키텍처 설계, 일정 관리, 최종 발표 ([Role 5] PM·지표 총괄)
  - **김지민 & 차주현:** MVTec AD 데이터셋 엔지니어링, PatchCore 모델링, 섭동 강건성 평가 ([Role 1] AI/비전 모델링)
  - **허재원:** FastAPI 백엔드 추론 REST API, 핫스왑 보안 및 MES 감사 로그 ([Role 2] 백엔드·보안, [Role 3] 도메인 룰)
  - **주현규:** Streamlit 실시간 디지털 관제 대시보드 UI, 조업자 UX ([Role 4] 프론트엔드·관제 UI)
- **역할별 에이전트 인수인계 가이드:**
  - 📊 **[Role 1A] 데이터 엔지니어링 & 벤치마크 평가 (김지민):** [docs/roles/ROLE_DATA_ENGINEERING_BENCHMARK.md](docs/roles/ROLE_DATA_ENGINEERING_BENCHMARK.md)
  - 🤖 **[Role 1B] AI 비전 모델링 & 온보딩 (차주현):** [docs/roles/ROLE_AI_VISION_MODELING.md](docs/roles/ROLE_AI_VISION_MODELING.md)
  - 🔒 **[Role 2] 백엔드 및 시스템 보안 (허재원):** [docs/roles/ROLE_BACKEND_SECURITY.md](docs/roles/ROLE_BACKEND_SECURITY.md)
  - 🏭 **[Role 3] 도메인 룰 및 MES 감사 (허재원):** [docs/roles/ROLE_MES_DOMAIN_ENGINEER.md](docs/roles/ROLE_MES_DOMAIN_ENGINEER.md)
  - 🖥️ **[Role 4] 프론트엔드 및 관제 UI (주현규):** [docs/roles/ROLE_FRONTEND_UI_ENGINEER.md](docs/roles/ROLE_FRONTEND_UI_ENGINEER.md)
  - 📊 **[Role 5] PM 및 발표·지표 총괄 (전종현 팀장):** [docs/roles/ROLE_PM_PRESENTATION_LEAD.md](docs/roles/ROLE_PM_PRESENTATION_LEAD.md)
  - 👥 **[전체 역할 총괄 인덱스]:** [docs/roles/README.md](docs/roles/README.md)
- **검증 환경 (Verified Environment):**
  - **OS / CPU:** Windows 10/11 x64, AMD Ryzen 5 5500U CPU (GPU 불필요, CPU 단일 추론 평균 103.4ms, P95 112.5ms)
  - **Python:** Python 3.11 / 3.12 호환 (`requirements.txt` 범용 호환 버전 및 `requirements.lock.txt` 정확한 고정 버전 병행 제공)
  - **오프라인 가중치 무결성:** `models/resnet18_imagenet_v1.pth` (`SHA256: 08d627238e25...`, `weights_only=True` 검증 로드) 및 `models/memory_bank.pt` 내장

---

## 2. 왜 이 API 및 시스템 구조인가? (Design Rationale)
1. **단일 의사결정 진입점 (`rule_engine.py`) 및 운영 모드 3종 분리:**
   - 현장 조업 조건에 맞춰 `SAFETY_FIRST`(불량 유출 `FN=0` 최우선, 임계치 `0.600`), `BALANCED_THROUGHPUT`(정상 재검 최소화, 임계치 `0.645`), `HUMAN_IN_THE_LOOP`(경계 점수 `0.58~0.65` 구간 2차 육안 확인 권고 플래그 `manual_review_recommended=true`)를 지원합니다.
   - `decision == "PASS"`일 때 히트맵을 `SUPPRESSED_BELOW_THRESHOLD`로 동기화하고 패턴 추정을 `NORMAL_WITHIN_SPEC`으로 일원화하여 판정과 시각화 간 불일치를 원천 차단합니다.
2. **Primary Seed(42) 조도 층화 분할 단일화 및 교집합 0% 보장:**
   - 기본 메모리 뱅크(190장, `bank_image_indices`)와 기본 검증셋(30장, `validation_image_indices`) 분할을 `seed=42` 조도 층화 분할(`brightness_stratified`) 하나로 통일하여 기본 `raw_threshold`와 `per_seed.seed_42` 임계치가 100% 일치하며, 교집합은 `0`장(`bank_validation_overlap: 0`)입니다.
3. **부품 기하학(Geometry) 분리 정책 및 기능 범위 한계 명시:**
   - **국소 텍스처 이상 최적화:** 본 시스템의 PatchCore 엔진은 국소 표면 결함(스크래치, 찍힘, 균열, 변색) 탐지에 최적화되어 있습니다.
   - **기능 범위 한계 명시:** 전역 형상 변형(Global Deformation), 규격 치수 불량(Dimensional Tolerance), 기구 조립 논리 오류(Assembly Logic Error)는 현재 패치 기반 비지도 학습 범위 밖입니다. 이에 따라 `part_geometry="generic"` 응답에는 `structural_shape_check="NOT_PERFORMED"` 및 `global_deformation_coverage="LIMITED"`가 명시됩니다.
   - **원형 너트 전용 마스크:** 원형 너트 데모 시에는 `part_geometry="circular_jig"`로 지정하여 전경 중심 기반 링 마스크(`0.58 <= r <= 0.95`, `structural_shape_check="PERFORMED"`)를 선택 적용합니다.
   - **로드맵:** 추후 OpenCV Contour 외곽선 기하 해석 모듈(Contour Geometric Analysis Module)을 연동하여 전역 변형 및 치수 공차 검사를 단일 파이프라인으로 확장할 예정입니다.
4. **API-Streamlit 상태 동기화 및 무결성 검증:**
   - 모든 검사 응답에 `model_part_id`, `model_sha256`, `model_version`, `activated_at` 메타데이터를 포함합니다.
   - Streamlit 대시보드는 검사 결과 렌더링 전 `GET /v1/models`를 호출하여 현재 활성 모델과 inspect 응답 모델을 실시간 대조하며, 불일치 발생 시 즉각 시각적 경고 배너를 띄워 잘못된 모델 판정 신뢰를 방지합니다.
5. **운영 보안 및 유연한 네트워크 바인딩 (로컬 전용 및 동일 LAN 타 기기 시연 지원):**
   - 운영 API에서는 `x-mock-score` 헤더 전송 시 즉시 `403 Forbidden (MOCK_DISABLED)`으로 차단합니다.
   - **타 기기/외부 시연 지원:** 기본 설정으로 FastAPI와 Streamlit이 `0.0.0.0`에 바인딩되어 동일 Wi-Fi/LAN의 다른 노트북·태블릿·심사위원 PC에서도 `http://<서버_IP>:8501` 및 `http://<서버_IP>:8000`으로 즉시 접속 가능합니다.
   - **단일 PC 로컬 격리:** 공용 Wi-Fi 등에서 외부 접속을 완전 차단하고 단독으로 실행하려면 `.env`에서 `API_HOST=127.0.0.1`, `STREAMLIT_HOST=127.0.0.1`로 설정하십시오.
   - Streamlit 좌측 사이드바의 **[🌐 네트워크 및 API 서버 연결]** 설정창에서 원격 서버의 FastAPI URL을 실시간으로 변경하여 연동할 수 있습니다.

---

## 3. 실행 및 검증 가이드 (Quick Start)

### 1) 가상환경 생성 및 패키지 설치
- **기준 검증 환경:** Windows 10/11 64-bit, **Python 3.12.10 64-bit** (`cp312-win_amd64` wheelhouse 기준. 상세 가이드는 [`docs/SETUP_WINDOWS.md`](docs/SETUP_WINDOWS.md) 참조)

#### 배포물별 포함 구성 및 오프라인 지원 범위
| 배포물 | 포함 구성 | 용도 | 인터넷 필요 여부 |
| :--- | :--- | :--- | :---: |
| **`code.zip`** (및 `Downloads\posco_hackathon`) | 소스 · 모델(`resnet18`, `memory_bank`) · `wheels/`(103개) · Python 설치 안내([`docs/SETUP_WINDOWS.md`](docs/SETUP_WINDOWS.md)) | **완전 오프라인 시연** | **불필요** |
| **`code_lightweight.zip`** | 소스 · 코어셋(`memory_bank.pt`) · `requirements.txt` / `requirements.lock.txt` | **제출 · 경량 배포** | **최초 설치 필요** |
| **`wheels/`** | 사전 다운로드된 103개 wheel (`cp312-win_amd64` 및 순수 Python wheel) | **오프라인 설치 (Wheelhouse)** | **불필요** |

```bash
python -m venv .venv
.\.venv\Scripts\activate

# 방법 A: 오프라인 사전 검증(--dry-run) 및 로컬 설치 (wheels 폴더 내장 시, 인터넷 불필요)
pip install --no-index --find-links=wheels -r requirements.lock.txt --dry-run
pip install --no-index --find-links=wheels -r requirements.lock.txt

# 방법 B: 온라인 환경에서 잠금 파일 기반 100% 동일 버전 설치
pip install -r requirements.lock.txt

# 방법 C: 범용 호환 설치
pip install -r requirements.txt

# [참고] 오프라인 wheelhouse 재생성 명령:
# pip download -d wheels -r requirements.lock.txt
```

### 1-1) 포트 충돌 사전 점검 (선택)
8000번(FastAPI) 또는 8501번(Streamlit) 포트가 이미 사용 중인지 점검합니다.
```bash
check_ports.bat
```
- 점유 중인 프로세스가 감지되면 PID와 종료 명령어(`taskkill /PID <pid> /F`)를 안내하며, `.env` 파일에서 `API_PORT`나 `STREAMLIT_PORT`를 변경할 수 있습니다.

### 2) 자동화 검증 스위트 실행
```bash
# 1. 서버 기능·보안·모델 레지스트리·기하학 분기 검증
python tests/test_server.py

# 2. 신규 부품 Zero-Training 온보딩 CLI 검증 (12개 항목)
python tests/test_onboard.py

# 3. MES 감사 로그 무결성·동시성 20건 검증
python tests/test_audit.py

# 4. 카메라 악조건 강건성 스트레스 테스트 (7개 단일 섭동 독립 시나리오)
python tests/test_robustness.py
```

### 3) 백엔드 REST API 서버 및 대시보드 실행
```bash
# [권장: 타 노트북/태블릿 접속 및 로컬 동시 가용 (기본값: 0.0.0.0)]
uvicorn server:app --host 0.0.0.0 --port 8000
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
# -> 로컬 접속: http://localhost:8501
# -> 동일 Wi-Fi/LAN 타 노트북 접속: http://<내_IP>:8501 (FastAPI: http://<내_IP>:8000)

# [단일 PC 로컬 전용 Loopback (공용 Wi-Fi 외부 노출 차단 시)]
uvicorn server:app --host 127.0.0.1 --port 8000
streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```
- 원클릭 원터치 실행: 폴더 내 `setup_and_run.bat` 더블클릭 (자동으로 `.env`의 `API_HOST`와 `STREAMLIT_HOST`를 반영하여 기동)

---

## 4. 신규 부품 Zero-Training 온보딩 (`onboard_new_part.py`)
제철소 라인에 새로운 규격의 부품이 투입될 때 GPU 역전파(Backpropagation) 재학습 없이 **정상 이미지 폴더만으로 Coreset 메모리 뱅크와 무누수 캘리브레이션 임계치를 자동 생성**합니다.

```bash
python onboard_new_part.py \
  --good-dir datasets/metal_nut/metal_nut/train/good \
  --output models/custom_part_bank.pt \
  --coreset-size 3000 \
  --val-ratio 0.15 \
  --seed 42 \
  --overwrite
```

### 운영 신뢰도 등급 (Confidence Tier) 및 처리 시간
| 투입 정상 이미지 수 | 운영 신뢰도 등급 | 자동 판정 허용 | 임계치 불확실성 및 조업 정책 | 처리 시간 (실측) |
| :---: | :---: | :---: | :--- | :---: |
| **20 ~ 29장** | `PILOT_LOW_CONFIDENCE` | ❌ **불허 (`False`)** | 소표본 분산 불확실성 높음 → **모든 경계 및 이상 의심 결과 수동 검토(`MANUAL_REVIEW`) 필수** | **16.80초** (목표 30초 이내 달성) |
| **30 ~ 99장** | `PILOT` | ✅ 허용 (`True`) | 통계 기준치 만족, 경계구간(0.58~0.65) 사람 2차 검증 병행 파일럿 라인 적합 | ~22초 |
| **100 ~ 189장** | `STANDARD` | ✅ 허용 (`True`) | 조도 층화 분할 통계 안정화, 표준 공정 자동 선별에 즉시 적용 가능 | ~32초 |
| **190장 이상** | `PRODUCTION_READY` | ✅ 허용 (`True`) | 190장 이상 확보로 포스코 제철소 양산 라인 완전 자동화 적용 기준 충족 | **41.63초** (220장 전수 실측) |

- **운영 이미지 수 가이드라인:**
  - **권장 최소 운영 이미지 수:** **30장 이상** (`PILOT` 등급 확보)
  - **권장 안정 운영 이미지 수:** **100장 이상** (`STANDARD` 등급 이상 확보)
  - 20~29장 구간은 분산 추정 오차가 크므로 자동 조업 승인을 차단하고 `MANUAL_REVIEW`로만 운영합니다.
- *주의: "30초 온보딩"은 20~30장 파일럿 기준 목표치(실측 16.8초)이며, 220장 전수 처리 시에는 41.63초가 소요됩니다.*

---

## 5. 실시간 모델 레지스트리 및 핫스왑 활성화 (`/v1/models`)

### 1) 사용 가능한 모델 목록 조회 (`GET /v1/models`)
서버가 현재 로드하고 있는 활성 모델 정보와 `models/` 디렉터리에 생성된 모든 부품 모델 목록(SHA256, 신뢰도 등급, 검증셋 교집합 여부)을 반환합니다.

### 2) 안전한 무중단 모델 핫스왑 (`POST /v1/models/activate`)
운영 중인 API 서버를 재기동하지 않고 새 부품 모델로 원자적(Atomic) 교체합니다.
```bash
curl -X POST "http://127.0.0.1:8000/v1/models/activate" \
  -H "Content-Type: application/json" \
  -d '{"part_id": "custom_part_bank", "expected_sha256": "<파일_SHA256_해시>"}'
```
- **보안 검증 정책:**
  1. **SHA256 불일치 차단:** 파일 변조나 손상 감지 시 `400 Bad Request` 반환.
  2. **Zero-Leakage 검증:** `.meta.json`의 `bank_validation_overlap != 0`일 경우 `409 Conflict`로 즉시 거부.
  3. **실패 시 롤백 보장:** 새 모델 로드 실패 시 기존 모델을 100% 유지하며, 활성화 성공/실패 이력은 `logs/model_activation_audit.csv`에 영속 기록됩니다.
  4. **스레드 안전성:** 모델 교체 중 들어온 검사 요청은 Lock을 통해 이전 모델 또는 신규 모델로 안전하게 직렬화 처리됩니다.

---

## 6. 다품종 운영 한계와 확장 설계 (Multi-Part Scalability)
- **현재 버전 운영 전제:** 현재 시스템은 단일 라인·단일 활성 모델 운영 전제로 구현되었으며, 해커톤 데모에서는 단일 활성 모델 기준 성능(CPU 추론 평균 103.4ms, P95 112.5ms 지연 시간)만 공식 검증되었습니다.
- **다중 라인 동시 검사 확장 아키텍처:** 다품종 혼류 생산 라인을 위한 `ModelRegistry` + `LRUModelCache` (Top-K 인메모리 캐싱, 부품별 세분화 RLock, Prometheus 메트릭 수집) 상세 설계는 [`docs/MULTI_PART_LRU_CACHE_DESIGN.md`](docs/MULTI_PART_LRU_CACHE_DESIGN.md)를 참조하십시오.

---

## 7. 공식 최종 메트릭스 및 발표 수치 동기화
심사위원 질의 및 발표 슬라이드 수치 정합성을 위한 공식 팩트 시트는 [`docs/final_metrics.md`](docs/final_metrics.md)에 정리되어 있습니다:
- **지연 시간:** CPU 평균 103.4ms, P95 112.5ms (기존 오기 24.3ms 정정 완료)
- **불량 검출 Recall:** Primary Seed 42 기준 100.0% (5-Seed 42/7/123/2026/999 교차 검증 시 97.85%~100.0% 신뢰구간)
- **정상 폐기 오판:** 0.0% (0/22건, 단 불량 유출 방지를 위해 정상품 13.6%가 REWORK 안전 이송)
- **카메라 악조건 고위험군 유지율:** 44/44 (100.00%, 원본 SCRAP 판정 44장 대상)

---

## 8. 학술 인용 (Academic References)
- **데이터셋:** Bergmann et al., *"MVTec AD — A Comprehensive Real-World Dataset for Unsupervised Anomaly Detection"*, CVPR 2019 (DOI: 10.1109/CVPR.2019.00982).
- **알고리즘:** Roth et al., *"Towards Total Recall in Industrial Anomaly Detection (PatchCore)"*, CVPR 2022.
