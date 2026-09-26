import pytest


@pytest.fixture(autouse=True)
def no_live_llm(monkeypatch):
    for key in ("GEMINI_API_KEY", "LOCAL_LLM_URL", "LLM_PROVIDER"):  # tests never call a real model or spend quota
        monkeypatch.delenv(key, raising=False)
