import json

from src.llm import LLMClient, LLMResult


class FakeLLM(LLMClient):
    """Deterministic stand-in: no network, no key."""
    def __init__(self, text=None, ok=True, error=""):
        super().__init__(api_key="x", use_cache=False, enabled=True)
        self.text, self.ok, self.err = text, ok, error
        self.calls = 0

    def chat(self, messages, json_mode=True, max_tokens=500):
        self.calls += 1
        if not self.ok:
            return LLMResult(False, error=self.err or "ConnectionError", model="fake")
        return LLMResult(True, self.text, 0.01, model="fake")


def good_llm_text(pid):
    return json.dumps({"can_answer": True, "sentences": [
        {"text": "Check the API keys page for the key status and expiry.", "sources": [pid]}]})
