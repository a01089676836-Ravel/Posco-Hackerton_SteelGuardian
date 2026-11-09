# 👥 POSCO 스마트팩토리 AI 팀 역할별 개발 분장 및 에이전트 인수인계 가이드

본 문서는 팀원 각자가 자신의 전문성과 경험을 살려 독립적으로 AI 코딩 에이전트(Claude Code, Antigravity, Cursor 등)를 운용하고, 각자의 파트를 안정적으로 고도화(Develop)할 수 있도록 설계된 역할 분장 체계입니다.

모든 역할 문서는 다음 **8대 엄격 표준**에 따라 구성되어 있습니다:
1. **역할:** 해당 포지션의 미션과 책임
2. **작업 시작 규칙:** 구현 전 반드시 읽어야 할 선행 파일과 판단 기준
3. **목표:** 해당 파트의 핵심 기술 달성 지표
4. **절대 변경 금지 계약:** 타 역할과의 결합을 깨뜨리지 않는 불변 API/스키마 규격
5. **구현 시 우선순위:** 안전하고 점진적인 개발 단계
6. **금지 사항:** 타 역할 침범, 비인가 파일 수정, 과장 표현 등 원천 금지 규칙
7. **검증:** 작업 후 반드시 실행해야 하는 검증 명령어 스위트
8. **보고 형식:** 에이전트가 작업 완료 시 출력해야 하는 검증 보고 서식

---

## 1. 역할별 분장 개요 총괄표

| 역할 번호 및 명칭 | 담당 팀원 | 주요 담당 파일 | 인터페이스 계약 (입출력) | 가이드 상세 문서 |
| :--- | :--- | :--- | :--- | :--- |
| **[Role 1A] 데이터 엔지니어링 & 벤치마크 평가** | **김지민** | `evaluate_benchmark.py`<br>`tests/test_robustness.py`<br>`datasets/metal_nut`<br>`results/` | 5-Seed 조도 층화 분할 무누수(Overlap=0) 및 7대 섭동 평가 | [가이드 바로가기](ROLE_DATA_ENGINEERING_BENCHMARK.md) |
| **[Role 1B] AI 비전 모델링 & 온보딩** | **차주현** | `patchcore_engine.py`<br>`onboard_new_part.py`<br>`models/` | `PatchCoreEngine.predict()` 반환 dict 규격 및 Coreset SLA | [가이드 바로가기](ROLE_AI_VISION_MODELING.md) |
| **[Role 2] 백엔드 및 시스템 보안** | **허재원** | `server.py`<br>`package_submission.py`<br>`.env*`, `*.bat` | `POST /v1/defects/inspect` 응답 JSON 스펙 준수 | [가이드 바로가기](ROLE_BACKEND_SECURITY.md) |
| **[Role 3] 도메인 룰 및 MES 감사** | **허재원** | `rule_engine.py`<br>`audit_logger.py`<br>`logs/` | `evaluate_defect()` 및 CSV 감사 무결성 준수 | [가이드 바로가기](ROLE_MES_DOMAIN_ENGINEER.md) |
| **[Role 4] 프론트엔드 및 관제 UI** | **주현규** | `app.py`<br>`tests/test_streamlit_cache.py` | FastAPI REST API 호출 및 화면 렌더링 동기화 | [가이드 바로가기](ROLE_FRONTEND_UI_ENGINEER.md) |
| **[Role 5] PM 및 발표·지표 총괄** | **전종현 (팀장)** | `docs/final_metrics.md`<br>`README.md`<br>`docs/SETUP_WINDOWS.md` | 수치 단일 진실 공급원(SSOT) 및 심사 질의 방어 | [가이드 바로가기](ROLE_PM_PRESENTATION_LEAD.md) |

---

## 2. 각 팀원에게 전달 및 에이전트 구동 방법

1. **역할별 배포 ZIP 파일 전달:**
   - 다운로드 폴더(`~/Downloads/` 또는 `%USERPROFILE%\Downloads\`)에 생성된 각 역할 전용 ZIP 파일(`role_1_ai_vision.zip` ~ `role_5_pm_presentation.zip`)을 해당 팀원에게 전달합니다.
   - 각 ZIP 파일 루트에는 해당 역할의 가이드 MD 파일이 포함되어 있습니다.
2. **에이전트(Claude Code, Antigravity, Cursor 등) 기동 시 프롬프트 주입:**
   - 각 역할 MD 파일의 내용을 그대로 에이전트의 첫 프롬프트 또는 `.cursorrules` / `GEMINI.md` / `CLAUDE.md`로 주입합니다.
3. **인터페이스 계약(Contract) 불변 원칙 준수:**
   - 내부 로직은 자유롭게 리팩토링 및 고도화하되, 타 역할과 맞닿아 있는 **함수 반환 키 및 API JSON 스펙은 절대 임의 변경하지 않도록** 에이전트에 지시합니다.
