# Windows 오프라인(망분리) 환경 구축 및 런타임 가이드 (`SETUP_WINDOWS.md`)

본 문서는 외부 인터넷이 차단된 공장/보안 망분리(Air-Gapped) Windows PC에서 **SteelGuardian** 시스템을 설치·검증·기동하기 위한 기준 환경과 트러블슈팅 절차를 정의합니다.

---

## 1. 기준 Python 환경 (Python 3.12 64-bit)

오프라인 패키지 폴더(`wheels/`)에 포함된 C 확장 바이너리(`torch`, `torchvision`, `numpy`, `scipy`, `pillow`, `pydantic_core` 등)는 **Windows 64-bit + Python 3.12 (`cp312-cp312-win_amd64`)** ABI를 기준으로 빌드되어 있습니다.

- **Python 3.12.x (64-bit)**: `wheels/` 폴더를 통해 인터넷 없이 즉시 설치 및 실행 가능
- **Python 3.11 / 3.13**: `setup_and_run.bat`가 경고를 출력한 뒤 진행을 시도하나, 오프라인 환경(`--no-index`)에서는 C 확장 패키지 ABI 불일치로 설치가 실패할 수 있음

### Python 3.12 공식 설치 파일 안내
실행 대상 PC에 Python 3.12 64-bit가 설치되어 있지 않은 경우, 사전에 인터넷이 연결된 PC에서 공식 설치 파일을 내려받아 반입합니다.

- **릴리스 페이지**: `https://www.python.org/downloads/release/python-31210/`
- **설치 파일명**: `python-3.12.10-amd64.exe` (Windows installer, 64-bit, 약 25.4 MB)
- **무결성(SHA256) 검증 명령어 (Windows PowerShell / CMD)**:
  ```cmd
  certutil -hashfile python-3.12.10-amd64.exe SHA256
  ```
  *(설치 전 `python.org` 공식 릴리스 페이지 하단 Files 표의 MD5/SHA256 및 Sigstore 서명과 대조하십시오. 설치 시 **"Add python.exe to PATH"** 및 **"py launcher"** 옵션을 체크합니다.)*

---

## 2. 배포물별 포함 범위 및 오프라인 지원 수준

| 배포물 | 포함 구성 | 용도 | 인터넷 필요 여부 |
|---|---|---|---|
| `Downloads\posco_hackathon` (또는 `wheels/` 포함 폴더) | 소스 + 로컬 모델(`resnet18`, `memory_bank`) + `wheels/`(103개 `.whl`) + 설정 | **완전 오프라인 설치 및 시연** | **불필요** (Python 3.12 64-bit 기준) |
| `code.zip` | 소스 + 로컬 모델(`resnet18_imagenet_v1.pth` 46.8MB, `memory_bank.pt`) + 문서 | 오프라인 AI 추론 시연 (패키지 사전 설치 환경 또는 `wheels/` 별도 결합) | 추론 시 불필요 (최초 `pip` 설치 시 `wheels/` 폴더 또는 인터넷 필요) |
| `code_lightweight.zip` | 소스 + 코어셋(`memory_bank.pt`) + `requirements.txt` / `requirements.lock.txt` | **해커톤 제출 및 경량 배포** | 최초 패키지 설치 및 `resnet18` 백본 가중치 최초 로드 시 필요 |
| `wheels/` | 사전 다운로드된 103개 `.whl` 패키지 (`cp312-win_amd64` 및 `py3-none-any`) | 오프라인 패키지 설치소 (Wheelhouse) | **불필요** |

---

## 3. 오프라인 Wheelhouse 및 런타임 사전 점검 절차

실제 설치를 수행하기 전에 `wheels/` 폴더만으로 의존성이 모두 해결되는지 `--dry-run`으로 즉시 확인할 수 있습니다.

### 3.1 Wheelhouse 의존성 해결 검증 (`--dry-run`)
```cmd
.venv\Scripts\pip.exe install --no-index --find-links=wheels -r requirements.lock.txt --dry-run
```

### 3.2 클린 Windows 환경 런타임(DLL) 및 추론 실측 순서
1. **PyTorch 코어 로드 확인**:
   ```cmd
   .venv\Scripts\python.exe -c "import torch; print(torch.__version__)"
   ```
2. **TorchVision 로드 확인**:
   ```cmd
   .venv\Scripts\python.exe -c "import torchvision; print(torchvision.__version__)"
   ```
3. **외부 인터넷 소켓 차단(Air-Gap) 상태에서 FastAPI 및 이미지 1장 추론 확인**:
   ```cmd
   .venv\Scripts\python.exe tests\test_offline_airgap.py
   ```

---

## 4. 조건부 조치: Windows DLL 로드 오류 (`VC++ Redistributable`)

Python 3.12 공식 설치본은 기본 `vcruntime140.dll`을 포함하지만, 포맷 직후의 일부 클린 Windows 환경에서 `import torch` 실행 시 아래와 같은 오류가 재현될 수 있습니다:

```text
ImportError: DLL load failed while importing _C: 지정된 모듈을 찾을 수 없습니다. (WinError 126)
```

### 대응 원칙
재현되지 않는 환경에 불필요한 런타임 설치 파일을 강제하지 않으며, **위 오류가 실제로 발생한 경우에 한하여** 아래 Microsoft 공식 재배포 패키지를 설치합니다.

- **대상 패키지**: Microsoft Visual C++ 2015–2022 Redistributable (x64) (`vc_redist.x64.exe`, 약 13.9 MB, Windows 10/11 64-bit 지원)
- **공식 안내 URL**: `https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist`

---

## 5. 감사 로그(Audit Trail) 운영·테스트 분리 정책

공장 MES 감사 로그는 품질 추적 증적(Evidence)이므로 자동화 테스트 데이터와 섞이지 않도록 격리합니다.

- **운영 감사 로그**: `logs/inspection_audit.csv`, `logs/model_activation_audit.csv`
- **테스트 격리 로그**: `AUDIT_LOG_DIR=logs/test` 환경변수 설정 시 `logs/test/inspection_audit_test.csv` 및 `logs/test/model_activation_audit_test.csv`에만 기록됨
- `setup_and_run.bat`, `tests/test_server.py`, `tests/test_offline_airgap.py`는 모두 기본적으로 `AUDIT_LOG_DIR=logs/test`를 사용하여 운영 감사 로그(`logs/inspection_audit.csv`)를 오염시키지 않습니다.
