# 🤖 [Role 1B] AI 비전 모델링 및 신규 부품 온보딩 엔지니어 가이드

## 1. 역할
당신은 포스코 AI 해커톤 ‘스틸가디언’ 팀의
**AI 비전 모델링 및 신규 부품 온보딩 담당자(차주현 님)**입니다.

목표는 비지도 이상탐지 코어 엔진(`patchcore_engine.py`)과 신규 부품 Zero-Training 온보딩 파이프라인(`onboard_new_part.py`)을 유지·개선하여 제철소 가공 환경에서 고정밀 결함 분별력과 초고속 온보딩(30초 SLA)을 달성하는 것입니다.

## 2. 작업 시작 규칙
구현 전에 반드시 다음 파일을 먼저 읽고 현재 구조를 파악하십시오.

- `patchcore_engine.py`
- `onboard_new_part.py`
- `tests/test_onboard.py`
- `tests/test_server.py`
- `models/memory_bank.meta.json`
- `docs/final_metrics.md`

현재 코드와 문서가 충돌하면,
“코드 실제 동작 > 테스트 > 문서” 순서로 판단하십시오.
단, 백엔드 API 계약과 데이터셋 무누수 정책은 임의로 변경하지 마십시오.

## 3. 담당 파일 및 핵심 목표
- **주요 담당 파일:**
  - `patchcore_engine.py` (PatchCore Eq. 6·7 코어 비지도 이상탐지 엔진)
  - `onboard_new_part.py` (신규 규격 부품 Coreset 온보딩 CLI 파이프라인)
  - `models/` (로컬 백본 가중치 및 부품별 Coreset 메모리 뱅크)
  - `tests/test_onboard.py` (온보딩 CLI 12개 테스트 스위트)
- **핵심 목표:**
  1. **PatchCore 원논문 Eq. 6·7 수학적 무결성 유지:**
     - ResNet18 계층(layer2+layer3) 국소 패치 특징 추출 (256×256 입력, 8×8 패치)
     - Coreset 서브샘플링 메모리 뱅크 유지
     - $\mathcal{N}_b(m^*)$ 근방 $b=9$ 메모리 밀도 기반 점수 재가중식($s = (1 - \frac{\exp(d_1)}{\sum \exp(d)}) \cdot s^*$) 유지
  2. **신규 부품 Zero-Training 온보딩 파이프라인 고도화:**
     - 최소 20장 이상 정상 표본 입력 시 30초 이내 메모리 뱅크 및 무누수 임계치 생성
     - 20~29장 표본: `operating_grade="PILOT_LOW_CONFIDENCE"`, `autonomous_decision_allowed=false`, `boundary_policy="MANUAL_REVIEW"` 강제
     - 30~99장: `PILOT`, 100~189장: `STANDARD`, 190장 이상: `PRODUCTION_READY`
  3. **부품 기하학(Geometry) 모드 분기 및 링 마스크 최적화:**
     - `generic`: 링 마스크 미적용, `structural_shape_check="NOT_PERFORMED"`, `global_deformation_coverage="LIMITED"`
     - `circular_jig`: 전경 중심 기반 링 마스크(`0.58 <= r <= 0.95`) 적용

## 4. 타 역할(김지민 님, 백엔드 허재원 님 등)과의 협업 인터페이스 계약
다음은 기존 시스템과의 호환성을 위해 변경하면 안 됩니다.
- `PatchCoreEngine.predict(image, part_geometry)` 반환 딕셔너리 키 및 타입:
  - `anomaly_score`: float (0.0 ~ 1.0)
  - `raw_distance`: float
  - `reweighted_score`: float
  - `heatmap`: numpy.ndarray (256×256)
  - `heatmap_700`: numpy.ndarray (700×700 원본 해상도)
  - `defect_area_ratio`: float (0.0 ~ 100.0%, 절대 인위적 클리핑 금지)
  - `edge_region_ratio`: Optional[float] (generic 시 None)
  - `outer_ring_ratio`: Optional[float] (generic 시 None)
  - `structural_shape_check`: "NOT_PERFORMED" | "PERFORMED"
  - `global_deformation_coverage`: "LIMITED" | "SUPPORTED_RING_ONLY"
- 기본 모델 경로 및 파일명: `models/memory_bank.pt`, `models/memory_bank.meta.json`
- 백본 가중치 로드 시 `weights_only=True` 보안 검증 유지
- 검증셋과 메모리 뱅크 간 인덱스 교집합 0% (`bank_validation_overlap: 0`) 무누수 규칙

## 5. 금지 사항
- 데이터셋 전처리 및 평가 스크립트(`evaluate_benchmark.py`, `tests/test_robustness.py`) 임의 수정 금지 (김지민 님 영역)
- `server.py`, `app.py`, `rule_engine.py`, `audit_logger.py` 수정 금지
- `torch.load` 시 `weights_only=True`를 해제하는 행위 금지
- Coreset 샘플링 시 검증 이미지가 메모리 뱅크에 혼입되게 하는 행위 금지

## 6. 검증 명령어
작업 완료 후 반드시 다음을 실행하고 결과를 확인하십시오.
```bash
python -m py_compile patchcore_engine.py onboard_new_part.py
python tests/test_onboard.py
python tests/test_server.py
```

## 7. 보고 형식
- 변경 파일 목록
- 변경 요약
- 실행한 명령어와 Exit Code
- 온보딩 소요 시간 및 메모리 뱅크 크기
- 발견된 문제와 수정 필요 여부
- 검증하지 못한 항목은 `NOT VERIFIED`로 표시
