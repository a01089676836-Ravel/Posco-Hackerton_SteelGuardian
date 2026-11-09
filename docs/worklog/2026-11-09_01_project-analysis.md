# 작업 기록 01: 프로젝트 이해 및 고도화 대상 분석

- **일자:** 2026-11-09
- **담당:** 허재원 (`role_2_backend_security`, `role_3_mes_domain`)
- **요청:** 프로젝트를 이해하고, 담당 파트에서 어떤 작업을 하면 되는지 분석
- **코드 변경:** 없음. 프로젝트에 추가한 파일은 이 문서뿐이며, 재현은 프로젝트 밖의 임시 복사본에서 진행

## 1. 담당 범위

| 시점 | 내용 |
|---|---|
| 초기 판단 | README 16행, `SteelGuardian_Master_Hub.html` 550·1092·1098행, 참가신청서를 근거로 Role 2·3으로 판단 |
| 1차 지시 | `role_2_backend_security`만 수정 |
| 확정 | 팀장 확인 결과 **role_2와 role_3 폴더를 담당·수정** |

- role_1, role_4는 읽기만 하고, 필요한 변경은 5절의 전달 사항으로 남긴다.
- 작업을 처리할 때마다 이 폴더(`docs/worklog/`)에 기록을 추가한다.

## 2. 프로젝트 요약

**스틸가디언(SteelGuardian)** 은 K-뉴딜/POSCO 해커톤 출품작으로, 금속 부품 표면 결함을 정상 이미지 학습만으로 검출해 PASS/REWORK/SCRAP을 판정한다.

```text
이미지 → server.py (검증, 활성 모델 선택)
       → patchcore_engine.py (ResNet18 + PatchCore 이상 점수, 히트맵)
       → rule_engine.py (운영 모드별 임계치, 3단계 판정, 인터록)
       → audit_logger.py (MES 감사 CSV)
       → app.py (Streamlit 대시보드)
```

| 역할 | 담당 | 주요 파일 |
|---|---|---|
| Role 1 AI/비전 | 김지민, 차주현 | `patchcore_engine.py`, `onboard_new_part.py` |
| **Role 2 백엔드·보안** | **허재원** | `server.py`, `package_submission.py`, `*.bat`, `.env*` |
| **Role 3 도메인 룰·감사** | **허재원** | `rule_engine.py`, `audit_logger.py`, `logs/` |
| Role 4 대시보드 | 주현규 | `app.py` |
| Role 5 PM·지표 | 전종현 | 발표, 지표 총괄 |

**폴더 구조상 주의점**
- git 저장소가 아니다. role 폴더 4개는 약 200MB짜리 사본이고 공용 소스 폴더가 없다.
- role_2와 role_3의 `server.py`, `rule_engine.py`, `audit_logger.py`, `patchcore_engine.py`는 현재 동일하다. 한쪽만 고치면 내용이 어긋난다.

## 3. 검증 방법과 한계

- 임시 복사본에 `requirements.lock.txt`를 설치해 실행했다.
- 기준 환경인 Python 3.12가 이 PC에 없어 **Python 3.13**을 사용했다.
- 재현에 쓴 악성 모델 파일 등은 임시 복사본 안에서만 만들었다.

**NOT VERIFIED:** `test_live_server_endpoints.py`, `test_stress_load.py`, `test_offline_airgap.py`, `check_ports.bat`, `setup_and_run.bat` 전체 흐름, Python 3.12 환경, Linux 환경

### 기존 테스트 기준선

| 테스트 | 결과 | 원인 |
|---|---|---|
| `tests/test_server.py` (role_2 원본 상태) | **실패** | `results/evaluation.json`이 없어 3번째 테스트에서 중단 |
| 위 파일을 role_1에서 임시 복사한 뒤 함수별 실행 | 6개 통과, 2개 실패 | `tests/scenarios.json` 없음(전체 폴더 공통), `test/scratch` 이미지 없음 |
| `tests/test_audit.py` | **실패** | `scratch` 이미지가 없어 `len(sample_files) * 3 == 21` 단언에서 중단. 6개 단계 중 3단계에서 멈추므로 200건 동시성 단계까지 가지 못함 |

- 데이터셋에는 `scratch`가 없다. role 폴더 4개 모두 불량 70장(bent 25, color 22, flip 23)으로, 문서의 93장과 다르다.
- `package_submission.py`의 `EXCLUDE_DIRS`에 `scratch`가 있어 경로 어디에 있든 제외한다. **이것이 누락 원인일 가능성이 높지만, 패키징 이력이 없어 확정하지는 못했다.**

## 4. 발견 사항

재현 열의 `재현`은 실행해서 확인한 것, `코드`는 코드를 읽고 판단한 것이다.

### P0: 보안·안전 결함

| # | 문제 | 위치 | 근거 | 재현 |
|---|---|---|---|---|
| 1 | **원격 활성화 인증 우회.** `x-forwarded-for: 127.0.0.1`만 보내면 키 없이 모델을 교체할 수 있다 | `server.py:157-159` | 원격 호출: 헤더 없음 403, 헤더 위조 **200** | 재현 |
| 2 | **모델 파일로 임의 코드 실행.** 체크포인트를 `weights_only=False`로 로드한다. SHA256 기대값은 호출자가 주는 값이고 `/v1/models`에서 인증 없이 얻을 수 있어 변조 방어가 되지 않는다 | `patchcore_engine.py:99` | 악성 `.pt` 활성화 시 200 응답과 함께 코드 실행. 실제 `memory_bank.pt`는 `weights_only=True`로 로드 가능 | 재현 |
| 3 | **무누수 검증이 실패 시 통과.** overlap 필드가 없으면 0으로 간주하고, 메타 값만 믿으며 `.pt`와의 연결도 확인하지 않는다 | `server.py:231` | 빈 메타 `{}` 200, 메타의 SHA 불일치 200, 실제 누수 체크포인트 200 | 재현 |
| 4 | **업로드 크기·해상도 제한 없음.** | `server.py:345`, `patchcore_engine.py:166` | 120KB짜리 6000×6000 PNG 처리에 **25.9초** (일반 이미지 0.17초) | 재현 |
| 5 | **추론이 이벤트 루프를 막음.** `async def` 안에서 동기 추론과 파일 I/O를 실행한다 | `server.py:309-451` | 대형 이미지 처리 중 `/health` 응답 **24.9초** | 재현 |

### P1: 판정 정책과 문서의 불일치 (Role 3 중심)

| # | 문제 | 위치 | 근거 | 재현 |
|---|---|---|---|---|
| 6 | **`HUMAN_IN_THE_LOOP`가 사실상 없음.** 모드 분기와 대기 큐가 없고 `SAFETY_FIRST`와 판정이 같다. 0.59점은 "자동 이송" PASS다 | `rule_engine.py:64-86` | 점수 0.59·0.62에서 두 모드 결과 동일 | 재현 |
| 7 | **`MANUAL_REVIEW` 판정이 반환되지 않음.** 계약에는 있는 값이다 | `rule_engine.py` | 코드에 분기 없음 | 코드 |
| 8 | **`autonomous_decision_allowed=False`를 무시.** README는 저신뢰 모델의 수동 검토가 필수라고 하지만 읽는 코드가 없고, 응답에도 등급이 없다 | `server.py`, `rule_engine.py` | 해당 메타로도 자동 판정, `confidence_tier` 없음 | 재현 |
| 9 | 온보딩 모델은 구조 임계치가 비활성이라 형상 파손이 문서의 수동 검토가 아니라 **REWORK**로 분류될 수 있다 | `rule_engine.py:100-129`, `onboard_new_part.py:362-368` | 온보딩 모델로 실행하지는 않음 | 코드 |
| 10 | **SCRAP 1건마다 라인 비상 정지.** 연속 N회 같은 조건이 없다. `generic` 모드는 형상 검사를 안 했다고 응답하면서 `CRITICAL_SHAPE_DEFORMATION`을 낼 수 있다 | `rule_engine.py:130-142` | 실제 현장 정책 확인 필요 | 코드 |
| 11 | 입력값 미검증. 잘못된 모드·기하 값과 100KB `camera_id`가 200으로 처리되어 감사 로그에 남는다 | `server.py:313-315` | `NOT_A_MODE`, `bogus` 모두 200 | 재현 |
| 12 | 프로덕션 규칙에 테스트 전용 분기가 있다 (`mock_area_exceeded_scrap_limit`). 구조 임계치 기본값도 파일마다 다르다 (0.565/0.06과 0.6487/0.16) | `rule_engine.py:14-18,96-98`, `patchcore_engine.py:119-123` | | 코드 |

### P1: 감사 로그 (Role 3)

| # | 문제 | 위치 | 근거 | 재현 |
|---|---|---|---|---|
| 13 | **인증 없이 로그 부풀리기.** 검증 전에 입력을 기록한다 | `server.py:171` | 원격 1MB `part_id` 1회에 로그 1,000,073바이트 증가 | 재현 |
| 14 | **활성화 감사에 행위자가 없음.** 누가 모델을 바꿨는지 알 수 없다 | `audit_logger.py:134-142` | 헤더에 client 관련 컬럼 없음 | 재현 |
| 15 | 감사 쓰기 실패 시 판정 결과가 일반 500으로 사라진다 | `server.py:450` | 쓰기 실패 주입 시 500 | 재현 |
| 16 | **락 구멍.** 락 파일 생성 중 `PermissionError`가 나면 락 없이 진행하고, 5초 지난 락은 다른 프로세스가 지운다. 비정상 종료로 남은 락은 다음 쓰기를 막는다 | `audit_logger.py:90-99` | 400건 중 무락 진입 1회(2차 `msvcrt` 락 덕분에 유실 없음, 400/400), 남은 락으로 5.0초 지연 | 재현 |
| 17 | 전체 파일을 락 안에서 읽는다. 대시보드는 `limit=0`으로 호출한다 | `audit_logger.py:206-210` | 20만 행에서 618ms (limit=50) | 재현 |
| 18 | 로테이션, `fsync`, 위변조 탐지(해시 체인)가 없다. 전체 모델 SHA, 판정 근거도 기록하지 않는다 | `audit_logger.py` | "무결성"이 현재는 동시 쓰기 무유실만 의미 | 코드 |

### P2: 배포·운영·문서

| # | 문제 | 위치 | 근거 | 재현 |
|---|---|---|---|---|
| 19 | **경량 ZIP이 162.6MB인데 PASS.** 목표는 20MB. 데이터셋이 포함되고, 크기 검사가 없으며, FAIL이어도 종료 코드가 0이다 | `package_submission.py` | ZIP 162.6MB, `check_zip` 0 FAIL | 재현 |
| 20 | **`.env`의 보안 설정이 적용되지 않음.** 서버에 `.env` 로더가 없고 bat은 HOST/PORT 4개만 읽는다 | `setup_and_run.bat:16-23` | `ALLOW_REMOTE_ACTIVATION`, `ADMIN_API_KEY` 참조 없음 | 코드 |
| 21 | 데모 관리자 키가 예시 파일에 고정되어 ZIP에 포함되고, 시크릿 검사는 `example` 파일을 건너뛴다 | `.env.demo_lan.example:18`, `package_submission.py:108` | ZIP 포함, 검출 0건 | 재현 |
| 22 | 테스트가 실패해도 서버를 기동한다 | `setup_and_run.bat:107` | | 코드 |
| 23 | `/v1/models`가 서버 절대경로를 인증 없이 노출한다. 예외 원문도 응답에 포함된다. 키 비교가 상수 시간이 아니다 | `server.py:101,188,263` | 절대경로 노출 확인 | 재현 |
| 24 | `part_id="x.pt"`로 활성화하면 활성 표시가 전부 `False`가 된다 | `server.py:124,271` | `[False]` | 재현 |
| 25 | 활성화 시 검증한 파일과 로드하는 파일을 따로 읽는다 (TOCTOU) | `server.py:250,260` | `new_engine.model_hash` 대조로 해결 가능 | 코드 |
| 26 | **문서 불일치** (아래 표) | | | 코드 |

| 항목 | 문서 | 실제 코드 |
|---|---|---|
| BALANCED 임계치 | `api.md`: 0.635 | 0.645 |
| SHA 불일치 응답 | README, `api.md`: 400 | 409 |
| 기본 바인딩 | README: 0.0.0.0 | 127.0.0.1 |
| 룰 엔진 반환 키 | ROLE_GUIDE: `action_plan`, `interlock_triggered` | `action`, `interlock` |
| 감사 컬럼 | ROLE_GUIDE: `trace_id` | `inspection_id` |
| `check_zip` 경로 | 루트 | `tests/check_zip.py` |
| 테스트 수 | "14개 시나리오" | 함수 8개 + 없는 `scenarios.json` |
| `openapi.yaml` | v1.0.0, 경로 2개 | 엔드포인트 5개 |
| 없는 참조 | `logs/README.md` | 없음 |

### 문제가 아닌 것으로 확인 / 지금 하지 않을 것

- **`/v1/models`의 매번 SHA 계산:** 모델 1개 기준 23ms로, 지금은 고칠 필요가 없다.
- **`LRUModelCache`, Prometheus, Triton:** 단일 라인 전제에서는 필요가 없다. 혼류 라인 요구가 생기면 검토한다.
- **CORS:** 명시적 origin만 허용하고 있어 정상이다.

## 5. 다른 담당자 전달 사항

| 대상 | 내용 |
|---|---|
| 김지민, 차주현 (Role 1) | `patchcore_engine.py:99`를 `weights_only=True`로 변경. 실제 `memory_bank.pt`는 로드 가능함을 확인했으나 온보딩 산출물은 미확인 |
| 김지민, 차주현 (Role 1) | 원본 데이터의 `test/scratch` 23장과 `scenarios.json` 보유 여부 확인 |
| 주현규 (Role 4) | `app.py:634-638`이 SCRAP·REWORK 외 판정을 전부 **"정상 합격"으로 표시**한다. `MANUAL_REVIEW` 도입 전에 수정 필수 |
| 주현규 (Role 4) | `app.py:593`의 타임아웃 5초를 넘기면 로컬 엔진으로 폴백한다. 핫스왑 후라면 다른 모델로 판정할 수 있고 불일치 경고도 뜨지 않는다 |
| 주현규 (Role 4) | `app.py:386-390`의 핫스왑 버튼은 서버 측에서 루프백으로 호출한다. LAN 시연 시 `:8501` 접속자가 키 없이 모델을 교체할 수 있다 (코드 판단) |
| 전종현 (PM) | `final_metrics`의 "치명 형상 변형은 수동 검토 이송"이 현재 코드와 다르다. 불량 93장 기준 지표는 현재 폴더 데이터로 재현할 수 없다 |

## 6. 제안 작업 순서

| 단계 | 작업 | 폴더 | 대상 | 규모 |
|---|---|---|---|---|
| 0 | 기준선 복구: 데이터·테스트 자산 확보, 두 폴더 동기화 방식 결정 | 2, 3 | 기준선 | 소 |
| 1 | 보안 수정 + 회귀 테스트 | 2 | #1, 2, 3, 13, 21, 23, 25 | 중 |
| 2 | 서버 안정화: 크기·해상도 제한, 스레드풀 추론, 입력 검증, 503 응답 | 2 | #4, 5, 11, 15, 24 | 중 |
| 3 | 감사 로그 강화: 락 재작성, 행위자 기록, tail 읽기, fsync, 로테이션 | 3 | #14, 16, 17, 18 | 중 |
| 4 | 판정 정책: 수동 검토 경로, 신뢰 등급 반영, 인터록 정책 | 2, 3 | #6, 7, 8, 9, 10, 12 | 대 (Role 4 협의) |
| 5 | 패키징·실행 스크립트·문서 정합성 | 2, 3 | #19, 20, 22, 26 | 소~중 |

**주의**
- 단계 1의 #1을 고치면 `test_server.py`가 `x-forwarded-for`로 원격 호출을 흉내 내는 부분을 `TestClient(client=(...))` 방식으로 바꿔야 한다.
- `ROLE_GUIDE`는 응답 스키마, CSV 헤더, `OPERATING_MODE_THRESHOLDS`를 변경 금지로 정한다. 응답 필드는 추가만 하고, 감사 컬럼 추가는 기존 CSV와 헤더가 어긋나므로 전환 방법을 함께 정한다.

## 7. 결정이 필요한 사항

1. **role_2와 role_3 사본 관리:** 단계 0에서 공용 파일을 어떻게 맞출지 결정 (제안: 파일별 소유 폴더를 정해 수정한 뒤 다른 폴더로 복사, 동일 여부를 해시로 검사)
2. **git 도입 여부:** 현재 변경 이력이 없어 되돌리기와 팀 공유가 어렵다 (제안: 도입, 팀장 협의)
3. **`MANUAL_REVIEW` 도입 범위:** 대시보드 수정이 함께 필요하다 (제안: Role 4와 일정을 맞춘 뒤 진행)
4. **인터록 정책:** 1회 정지를 유지할지, 연속 N회 조건을 둘지 (현장 기준 또는 팀 합의 필요)
5. **경량 ZIP의 데이터셋:** 제외하면 20MB 목표를 맞추지만 ZIP만으로는 테스트를 돌릴 수 없다 (제안: 경량본 제외, 전체본 포함)
