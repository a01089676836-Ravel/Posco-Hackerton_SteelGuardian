import hashlib
import sys
from pathlib import Path

# 프로젝트 루트 경로 추가
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import streamlit as st
from patchcore_engine import PatchCoreEngine

# app.py와 동일한 캐시 함수
@st.cache_resource
def cached_engine(model_path_str: str, model_sha256: str) -> PatchCoreEngine:
    return PatchCoreEngine(model_path=Path(model_path_str))

def test_cache_behavior():
    model_path = BASE_DIR / "models" / "memory_bank.pt"
    if not model_path.exists():
        print("Model file not found, skipping.")
        return

    sha1 = hashlib.sha256(model_path.read_bytes()).hexdigest()
    sha2 = "dummy_different_sha256_hash_value"

    print("[1] 동일 키(path, sha1) 호출 시 인스턴스 재사용 확인...")
    eng1 = cached_engine(str(model_path), sha1)
    eng2 = cached_engine(str(model_path), sha1)
    assert eng1 is eng2, "동일 파라미터는 동일 캐시 인스턴스를 반환해야 합니다."
    print("  -> PASS: 동일 인스턴스 반환 확인")

    print("[2] 모델 해시 변경 시(sha2) 신규 인스턴스 생성 확인...")
    eng3 = cached_engine(str(model_path), sha2)
    assert eng3 is not eng1, "해시 변경 시 새 엔진 인스턴스가 반환되어야 합니다."
    print("  -> PASS: 해시 변경 시 새 엔진 생성 확인")

    print("[3] st.cache_resource.clear() 호출 후 캐시 무효화 확인...")
    st.cache_resource.clear()
    eng4 = cached_engine(str(model_path), sha1)
    assert eng4 is not eng1, "캐시 초기화 후 새 인스턴스가 반환되어야 합니다."
    print("  -> PASS: 캐시 초기화 후 새 인스턴스 재생성 확인")

    print("🎉 Streamlit 캐시 안전성 및 무효화 테스트 통과!")

if __name__ == "__main__":
    test_cache_behavior()
