# SteelGuardian Role 1A 검증 결과

2026-11-09 · macOS arm64 CPU · Python 3.12.1 · PyTorch 2.14.0 · torchvision 0.29.0

## 데이터셋 무결성

Hugging Face의 기존 MVTec AD `metal_nut` 스냅샷 `8db7371c35a94709cbb3e69ac69f80d2716e2f8a`에서 `scratch` 테스트 이미지 23장과 정답 마스크 23장을 직접 다운로드해 복구했다. 복구 후 PNG **428개 전부**의 SHA-256이 원본 스냅샷 메타데이터와 일치했다.

| 경로 | 복구 전 | 복구 후 |
| --- | ---: | ---: |
| `test/scratch/*.png` | 0 | 23 |
| `ground_truth/scratch/*_mask.png` | 0 | 23 |

복구 후 정상 학습 220장, 테스트 115장(정상 22장, 불량 93장), 정답 마스크 93장을 확인했다. [테스트 이미지 원본](https://huggingface.co/datasets/MSherbinii/mvtec-ad-metal-nut/tree/8db7371c35a94709cbb3e69ac69f80d2716e2f8a/metal_nut/test/scratch) · [정답 마스크 원본](https://huggingface.co/datasets/MSherbinii/mvtec-ad-metal-nut/tree/8db7371c35a94709cbb3e69ac69f80d2716e2f8a/metal_nut/ground_truth/scratch)

## 재실행 결과

| 항목 | 검증 결과 | 종료 코드 |
| --- | --- | ---: |
| `python evaluate_benchmark.py` | 테스트 115장 완료(63.1초). 시드 42·7·123·2026·999 모두 뱅크 190장·캘리브레이션 30장, 교집합 0. Seed 42 임계치 0.4362 일치 | 0 |
| `test_camera_robustness_suite()` | 원본 115장과 7개 단일 섭동 805건 완료. 7개 조건 모두 원본에서 SCRAP이었던 bent·flip 44장의 판정을 유지했고 정상 부품의 SCRAP은 0건 | 0 |

벤치마크에서 Image AUROC는 0.9971, SAFETY_FIRST Recall은 100%(93/93), Precision은 96.88%, F1은 0.9841이었다. 강건성 Recall은 조도 10% 감소, +2° 회전, JPEG Q70에서 98.92%(92/93)였고 나머지 네 조건은 100%였다.

격리된 작업 폴더에서 메모리 뱅크를 다시 만들고 두 평가에 동일한 뱅크(해시 `c81bede171f7`)를 사용했다. 이번 출력은 [evaluation.json](role1a_rerun/evaluation.json)과 [robustness_report.json](role1a_rerun/robustness_report.json)에 있다. 기존 기준 결과와 구분해 보관했다.

| 조건 | 이상 점수 | 판정 |
| --- | ---: | --- |
| 원본 | 0.6013 | REWORK |
| 조도 10% 감소 | 0.5773 | PASS |
| 회전 +2° | 0.4042 | PASS |
| JPEG Q70 | 0.5718 | PASS |

`SAFETY_FIRST` 임계치 0.6000 인근의 샘플에서 세 조건 모두 불량 통과가 발생했다. 조도 저하와 회전 사례는 차광과 지그 정렬 검토 근거다.

## 신규 부품 프로파일링과 온보딩 검증

신규 부품 실물 이미지가 제공되지 않아 기존 `train/good` 이미지로 입력 20장과 220장을 검증했다. 두 경우 모두 원본 700×700 RGB였고 손상 파일은 0개였다. 프로파일링과 기존 온보딩 CLI는 각각 종료 코드 0을 반환했다.

| 입력 | 평균 조도 중앙값 | 메모리 뱅크 / 검증 | 교집합 | 온보딩 CLI 실측 |
| ---: | ---: | ---: | ---: | ---: |
| 20장 | 57.689 | 15 / 5 | 0 | 4.52초 |
| 220장 | 57.788 | 187 / 33 | 0 | 13.30초 |

## 5개 시드 테스트 Recall

시드마다 정상 220장을 메모리 뱅크 190장과 캘리브레이션 30장으로 나눴다. 모든 분할의 교집합은 0장이었다. 각 뱅크의 Eq.7 점수에 해당 분할에서 산출한 임계치를 적용하고 동일한 원본 테스트 115장(불량 93장)을 평가했다. SAFETY_FIRST는 원점수 임계치를 정규화 점수 0.60에 대응시키며, 이 단계에서 PASS 여부가 결정된다. Seed 42의 미검출·오탐 건수는 기존 규칙 엔진을 호출하는 전체 벤치마크와 일치했다.

| Seed | 원점수 임계치 | 검출 | Recall | 미검출 파일 |
| ---: | ---: | ---: | ---: | --- |
| 42 | 0.4362 | 93/93 | 100.00% | 0건 |
| 7 | 0.4428 | 92/93 | 98.92% | `color/004.png` |
| 123 | 0.4252 | 93/93 | 100.00% | 0건 |
| 2026 | 0.4423 | 93/93 | 100.00% | 0건 |
| 999 | 0.4463 | 91/93 | 97.85% | `scratch/000.png`, `scratch/022.png` |

**관측 범위는 97.85%~100.00%**였다. 시드별 결과는 [seed_recall.json](role1a_rerun/seed_recall.json)에 저장했다.

### 미검출 사례 분석

5개 시드의 원본 테스트 점수 575개를 별도 작업 폴더에서 재산출했다. 이전 검증의 임계치, 검출 건수, 미검출 및 오탐 목록과 모두 일치했다.

| Seed | 미검출 파일 | Eq.7 원점수 | 임계치 | 점수 − 임계치 |
| ---: | --- | ---: | ---: | ---: |
| 7 | `color/004.png` | 0.435726 | 0.4428 | −0.007074 |
| 999 | `scratch/000.png` | 0.440647 | 0.4463 | −0.005653 |
| 999 | `scratch/022.png` | 0.442474 | 0.4463 | −0.003826 |

Seed 42의 `color/004.png` 점수도 임계치보다 0.000887 높았다. 같은 테스트셋에서 미검출 0건을 만들 수 있는 4자리 임계치를 계산했을 때 Seed 7은 0.4357에서 검출 93/93, 정상 오탐 4/22(기존 3/22)였다. Seed 999는 0.4406에서 검출 93/93, 정상 오탐 3/22였다. 이 값은 테스트 점수로 사후 산출한 민감도 분석이다. 독립 검증셋에서의 성능은 확인되지 않았고, 배포 임계치에는 반영하지 않았다.

## 발표 문서 정정

`docs/final_metrics.md`와 `README.md`에 시드별 실측 범위를 반영했다. 픽셀 지표는 원래 벤치마크 결과와 재실행 모두 Pixel AUROC 0.9640, AU-PRO@0.3 0.9040, Pixel IoU 0.5912였다. Seed 42 처리량 모드 Recall은 97.85%(91/93)로 정정했다.

## 변경 파일

- `evaluate_benchmark.py`에 테스트 범주별 이미지 수와 정답 마스크 매칭 검사 추가
- `profile_new_part.py`에 원본 해상도·색상 모드·조도 분포·손상 파일을 JSON으로 출력하는 CLI 추가
- `ROLE_GUIDE.md`와 `docs/roles/ROLE_DATA_ENGINEERING_BENCHMARK.md`의 JSON 검증 명령 및 프로파일러 사용법 수정
- `datasets/metal_nut/metal_nut/{test,ground_truth}/scratch/`에 PNG 46개 복구
- `results/role1a_rerun/`에 재실행 JSON 2개 저장
- `evaluate_benchmark.py`에 시드별 SAFETY_FIRST Recall 산출 추가. 기존 `evaluation.json` 구조를 유지하고 `seed_recall.json`을 별도로 생성
- `README.md`와 `docs/final_metrics.md`의 발표 수치 정정
- `results/role1a_verification.md`에 위 검증 결과 기록
