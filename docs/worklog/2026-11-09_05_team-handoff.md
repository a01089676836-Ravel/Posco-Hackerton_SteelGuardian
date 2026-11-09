# 작업 기록 05: 팀원 전달 문서 작성

- **일자:** 2026-11-09
- **담당:** 허재원
- **요청:** 팀원에게 전달할 내용을 md 파일로 Hackerton 폴더에 정리
- **코드 변경:** 없음

## 작업 내용

- `Hackerton/팀원_전달사항_2026-11-09.md`를 작성했다. 담당자별 요청, 공통 서버 변경 사항, 검증 범위를 담았다.
- 전달 전에 다른 role 폴더를 읽어 확인했고 수정하지는 않았다.

## 확인 결과

- `scenarios.json`, `evaluate_benchmark.py`는 role_1~5 어느 폴더에도 없다.
- `role_5_pm_presentation`에는 데이터셋이 없어, `scratch` 이미지가 있는 폴더도 없다.
- role_4의 `tests/test_server.py`, `tests/test_offline_airgap.py`, `.env.demo_lan.example`에 이전 동작을 전제로 한 내용이 남아 있다. 그중 `test_server.py`는 role_2 파일 복사로, 나머지는 직접 수정으로 처리하도록 전달 문서에 적었다.

## 미확인

- 문서를 팀원에게 실제로 전달하지는 않았다. 전달은 허재원이 진행한다.
