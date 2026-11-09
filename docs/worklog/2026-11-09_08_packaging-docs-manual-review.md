# 작업 기록 08: 패키징, 문서 정합성, 수동 검토 경로

- **일자:** 2026-11-09
- **담당:** 허재원
- **요청:** 2순위, 3순위를 진행한 뒤 1순위를 서브에이전트로 수정
- **번호(#):** 작업 기록 01과 같음

## 1. 패키징 (#19)

| 항목 | 수정 전 | 수정 후 |
|---|---:|---:|
| 경량 ZIP | 162.6MB, PASS | **8.1MB**, PASS |
| 20MB 초과 시 | 통과 | FAIL |
| FAIL 시 종료 코드 | 0 | 1 |

- 경량 ZIP에서 `datasets/`를 제외한다. 전체 ZIP은 205.8MB이며 데이터셋을 포함한다.
- `scratch` 제외 규칙을 프로젝트 최상위로 한정해, 데이터셋의 `test/scratch`가 더는 빠지지 않는다.
- `.cache`와 `docs/worklog`를 ZIP에서 제외한다.
- 신규 테스트: `tests/test_package_submission.py` (6/6 통과)
- `main()`은 다운로드 폴더를 임시 경로로 바꿔 시험했다. `check_zip` 결과 0 FAIL, 0 WARN

**한계:** role_2에는 `app.py` 등이 없어 이 폴더에서 만든 ZIP은 완성품이 아니다. 최종 제출은 통합 폴더에서 다시 만들어야 한다.

## 2. 문서 정합성 (#26)

| 파일 | 수정 |
|---|---|
| `docs/openapi.yaml` | 1.3.0, 엔드포인트 5개 전체, 오류 응답. 라우트 일치 여부를 회귀 테스트로 고정 |
| `README.md` | 기본 바인딩 127.0.0.1, SHA 불일치 409, 활성화 보안 정책, 테스트 목록, 경량 ZIP 구성 |
| role_2 `ROLE_GUIDE.md` | 테스트 목록, `check_zip` 경로, 오류 코드 |
| role_3 `ROLE_GUIDE.md` | 반환 키 `action`, `interlock`, CSV 컬럼 `inspection_id`, 없는 `logs/README.md` 참조 제거 |
| `docs/roles/` 가이드 사본 | 위 가이드와 동일하게 맞춤 |

## 3. 수동 검토 경로 (#6~#9)

서브에이전트가 구현하고, 메인에서 코드 검토와 재검증을 진행했다.

### 판정 규칙 (위에서부터 적용)

| 순서 | 조건 | 판정 |
|---:|---|---|
| 1 | 자동 판정 불허 모델, 점수 0.58 이상 | `MANUAL_REVIEW` |
| 2 | `HUMAN_IN_THE_LOOP`, 점수 0.58~0.65 | `MANUAL_REVIEW`. 단 0.60 이상이고 구조 근거가 있으면 SCRAP |
| 3 | 점수가 모드 임계치 미만 | PASS |
| 4 | 구조 임계치 없이 온보딩한 모델, 임계치 이상 | `MANUAL_REVIEW` |
| 5 | 그 외 | 기존 REWORK 또는 SCRAP |

`MANUAL_REVIEW`는 인터록을 켜지 않고 히트맵을 표시한다.

### 구현 방식

- `evaluate_defect` 시그니처, 임계치 값, 감사 CSV 헤더, `patchcore_engine.py`는 변경하지 않았다.
- 서버가 메타데이터의 `autonomous_decision_allowed`를 `engine.structural_thresholds`에 주입하면, 엔진이 이를 룰 엔진으로 전달한다. 값이 없거나 메타를 읽을 수 없으면 자동 판정 불허로 처리한다.
- 응답에 `confidence_tier`, `autonomous_decision_allowed`를 추가했다.
- 별도 대기 큐는 만들지 않았다. 응답과 감사 로그의 `MANUAL_REVIEW` 값으로 구분한다.

### 판정 분포 (실제 92장, `generic`, `scratch` 없음)

| 모드 | 카테고리 | PASS | REWORK | SCRAP | MANUAL_REVIEW |
|---|---|---:|---:|---:|---:|
| SAFETY_FIRST | good | 19 | 3 | 0 | 0 |
| | bent | 0 | 4 | 21 | 0 |
| | color | 0 | 13 | 9 | 0 |
| | flip | 0 | 0 | 23 | 0 |
| BALANCED_THROUGHPUT | good | 21 | 1 | 0 | 0 |
| | bent | 0 | 4 | 21 | 0 |
| | color | 1 | 12 | 9 | 0 |
| | flip | 0 | 0 | 23 | 0 |
| HUMAN_IN_THE_LOOP | good | 19 | 0 | 0 | 3 |
| | bent | 0 | 4 | 21 | 0 |
| | color | 0 | 12 | 9 | 1 |
| | flip | 0 | 0 | 23 | 0 |

| 항목 | SAFETY_FIRST | BALANCED_THROUGHPUT | HUMAN_IN_THE_LOOP |
|---|---:|---:|---:|
| 수정 전후 판정 변경 | 0건 | 0건 | 4건 (모두 REWORK→MANUAL_REVIEW) |
| 불량의 PASS 유출 | 0건 | 1건 | 0건 |

불량 70장 기준이므로 공식 93장 지표로 쓸 수 없다.

## 4. 검증

임시 복사본에서 Python 3.13으로 실행했다.

| 항목 | 결과 |
|---|---|
| 회귀 테스트 (role_2, role_3 복사본) | 23/23 통과 |
| `test_package_submission.py` | 6/6 통과 |
| `test_server.py` (실제 데이터) | 8개 중 6개 통과. 실패 2개는 `scenarios.json`, `scratch` 누락 |
| `test_audit.py`, `test_offline_airgap.py` (`scratch` 대체) | 통과, 5/5 통과 |
| 저신뢰 메타 모델로 실제 flip 이미지 검사 | `MANUAL_REVIEW`, 인터록 꺼짐, 기본 모델 복구 정상 |
| 공용 파일 해시 | 동일 |

**미검증:** 실제 대시보드 연동, 실제 온보딩 산출물(`evaluate_benchmark.py` 없음), `circular_jig` 전수 비교, 실제 `scratch` 이미지, Python 3.12, 수정 후 200건 부하 재측정

## 5. 남은 위험

- **`role_4/app.py`와 함께 쓰면 안 된다.** 공유 폴더의 `app.py`에는 `MANUAL_REVIEW` 처리가 없어(`app.py:634-638`) "정상 합격"으로 표시된다. 주현규의 수정본이 반영된 뒤 합쳐야 한다.
- **자동 판정 불허 모델은 심각한 파손에도 라인이 자동으로 멈추지 않는다.** 근거만 `decision_basis`에 남기고 사람이 판정한다.
- **구조 임계치 없이 온보딩한 모델은 자동 REWORK가 나오지 않는다.** `onboard_new_part.py:96-97`의 "표면 결함은 자동 선별" 안내와 달라 Role 1 확인이 필요하다.
- **`evaluation.json`의 HUMAN_IN_THE_LOOP 수치는 이번 동작을 반영하지 않는다.** 예를 들어 `manual_review_queue_count` 등은 Role 1 재산출이 필요하다.
