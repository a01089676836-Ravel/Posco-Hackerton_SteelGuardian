"""
패키징 규칙 검증 (표준 라이브러리만 사용)
실행: python tests/test_package_submission.py
"""

import sys
import tempfile
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import package_submission as ps

SCRATCH_IMAGE = Path("datasets/metal_nut/metal_nut/test/scratch/000.png")


def make_zip(path: Path, files: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return path


def test_lightweight_keeps_code_and_core_model():
    for name in ("server.py", "models/memory_bank.pt", "models/memory_bank.meta.json", "tests/test_server.py", "docs/api.md", ".env.example"):
        assert not ps.should_exclude(Path(name), True), name


def test_lightweight_drops_heavy_and_private_files():
    for name in ("datasets/metal_nut/readme.txt", "wheels/torch.whl", "models/resnet18_imagenet_v1.pth", ".env", "logs/inspection_audit.csv", "docs/worklog/a.md", "scratch/tmp.py"):
        assert ps.should_exclude(Path(name), True), name


def test_full_package_keeps_dataset_scratch_category():
    assert not ps.should_exclude(SCRATCH_IMAGE, False)
    assert ps.should_exclude(Path("scratch/tmp.py"), False)
    assert ps.should_exclude(Path("datasets/metal_nut/.cache/a.json"), False)


def test_audit_fails_when_lightweight_exceeds_limit(tmp: Path):
    original = ps.LIGHTWEIGHT_MAX_BYTES
    ps.LIGHTWEIGHT_MAX_BYTES = 1
    try:
        report = ps.audit_zip_security(make_zip(tmp / "big.zip", {"server.py": "x"}), True)
    finally:
        ps.LIGHTWEIGHT_MAX_BYTES = original
    assert report["size_limit_exceeded"] and report["security_verdict"] == "FAIL"


def test_audit_detects_env_style_key_in_example(tmp: Path):
    report = ps.audit_zip_security(make_zip(tmp / "key.zip", {".env.demo_lan.example": "ADMIN_API_KEY=real-looking-key-123\n"}), True)
    assert report["security_verdict"] == "FAIL"
    assert "real-looking-key-123" not in str(report), "리포트에 키 원문이 남았습니다"


def test_audit_allows_commented_key_and_full_scratch(tmp: Path):
    files = {".env.demo_lan.example": "# ADMIN_API_KEY=\n", SCRATCH_IMAGE.as_posix(): "x"}
    assert ps.audit_zip_security(make_zip(tmp / "ok.zip", files), False)["security_verdict"] == "PASS"


def main() -> int:
    failed = 0
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    with tempfile.TemporaryDirectory() as d:
        for test in tests:
            try:
                test(Path(d)) if test.__code__.co_argcount else test()
                print(f"PASS {test.__name__}")
            except Exception as e:
                failed += 1
                print(f"FAIL {test.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
