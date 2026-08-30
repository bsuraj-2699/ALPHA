"""Model Provider Layer tests.

Config-driven single-provider resolution (primary + fallback), the
guardrail/rate-limit wrapper, and the architectural guarantee that agents
contain no vendor-specific LLM logic (only the provider module imports
litellm/instructor).
"""

from __future__ import annotations

from pathlib import Path

import pydantic
import pytest
from packages.agents import guardrails
from packages.agents.llm_provider import (
    DEFAULT_FALLBACK_MODEL,
    DEFAULT_PRIMARY_MODEL,
    instructor_retry_policy,
    is_model_retired_error,
)
from packages.agents.model_provider import (
    ChatProvider,
    FailoverChatProvider,
    GuardedChatProvider,
    LiteLLMChatProvider,
    get_chat_provider,
)


@pytest.fixture
def clean_env(monkeypatch):
    for k in (
        "LLM_API_KEY", "LLM_API_BASE", "LLM_MODEL", "LLM_FALLBACK_MODEL",
        "LLM_MAX_REQUESTS_PER_MINUTE", "LLM_MAX_CONCURRENCY",
        "LLM_MAX_PROMPT_CHARS", "LLM_MAX_OUTPUT_CHARS",
    ):
        monkeypatch.delenv(k, raising=False)
    guardrails.reset()
    return monkeypatch


def test_offline_when_no_key(clean_env):
    p = get_chat_provider("meta/llama-3.3-70b-instruct")
    assert isinstance(p, LiteLLMChatProvider)
    assert p.name == "offline"
    assert p.model == "meta/llama-3.3-70b-instruct"


def test_configured_yields_guarded_failover(clean_env):
    clean_env.setenv("LLM_API_KEY", "nvapi-test")
    p = get_chat_provider()
    assert isinstance(p, GuardedChatProvider)
    assert isinstance(p.inner, FailoverChatProvider)
    # Default primary THEN fallback, in that order. Asserted against the
    # constants rather than literals: which NIM models this account can invoke
    # is deployment config, and hardcoding ids here just drifts.
    assert [x.model for x in p.inner.providers] == [
        DEFAULT_PRIMARY_MODEL,
        DEFAULT_FALLBACK_MODEL,
    ]
    assert isinstance(p, ChatProvider)


def test_primary_and_fallback_are_config_driven(clean_env):
    clean_env.setenv("LLM_API_KEY", "nvapi-test")
    clean_env.setenv("LLM_MODEL", "meta/llama-3.1-8b-instruct")
    clean_env.setenv("LLM_FALLBACK_MODEL", "google/gemma-2-27b-it")
    p = get_chat_provider()
    assert [x.model for x in p.inner.providers] == [
        "meta/llama-3.1-8b-instruct",
        "google/gemma-2-27b-it",
    ]


def test_single_model_when_primary_equals_fallback(clean_env):
    clean_env.setenv("LLM_API_KEY", "nvapi-test")
    clean_env.setenv("LLM_MODEL", "meta/llama-3.3-70b-instruct")
    clean_env.setenv("LLM_FALLBACK_MODEL", "meta/llama-3.3-70b-instruct")
    p = get_chat_provider()
    assert isinstance(p.inner, LiteLLMChatProvider)


async def test_failover_tries_fallback_on_failure():
    class _Out(pydantic.BaseModel):
        ok: bool

    class _Boom(LiteLLMChatProvider):
        async def complete(self, **kw):
            raise ConnectionError("primary down")

    class _Works(LiteLLMChatProvider):
        async def complete(self, **kw):
            return _Out(ok=True)

    fp = FailoverChatProvider([_Boom(model="a"), _Works(model="b")])
    out = await fp.complete(
        response_model=_Out, messages=[{"role": "user", "content": "hi"}],
        max_tokens=10, temperature=0.0,
    )
    assert out.ok is True


async def test_failover_raises_only_when_all_fail():
    class _Boom(LiteLLMChatProvider):
        async def complete(self, **kw):
            raise RuntimeError("boom")

    fp = FailoverChatProvider([_Boom(model="a"), _Boom(model="b")])
    with pytest.raises(RuntimeError):
        await fp.complete(
            response_model=dict, messages=[], max_tokens=1, temperature=0.0
        )


async def test_guarded_provider_sanitises_output(clean_env):
    class _Narrative(pydantic.BaseModel):
        narrative: str
        confidence: float

    class _Inner(LiteLLMChatProvider):
        async def complete(self, **kw):
            return _Narrative(narrative="x" * 50 + "\x07", confidence=2.5)

    clean_env.setenv("LLM_MAX_OUTPUT_CHARS", "10")
    guarded = GuardedChatProvider(_Inner(model="m"))
    out = await guarded.complete(
        response_model=_Narrative, messages=[{"role": "user", "content": "hi"}],
        max_tokens=10, temperature=0.0,
    )
    assert len(out.narrative) <= 10
    assert "\x07" not in out.narrative
    assert out.confidence == 1.0


def test_agents_have_no_vendor_sdk_imports():
    """Guardrail: business-logic agents must not import litellm/instructor
    directly — only the provider layer may."""
    agents_dir = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    allow = {"model_provider.py", "llm_provider.py", "_llm_helpers.py"}
    for py in agents_dir.rglob("*.py"):
        if py.name in allow or "tests" in py.parts:
            continue
        text = py.read_text(encoding="utf-8")
        if "import litellm" in text or "import instructor" in text:
            offenders.append(py.name)
    assert offenders == [], f"vendor SDK imported in agents: {offenders}"


# --- retired model (HTTP 410) fast-fail ------------------------------------


class _Retired(Exception):
    """Stand-in for the litellm/openai error raised for a withdrawn model id."""

    def __init__(self, status_code: int = 410) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def test_detects_410_direct_and_wrapped():
    assert is_model_retired_error(_Retired()) is True
    # instructor/litellm re-raise, so the 410 is often only in the cause chain.
    try:
        try:
            raise _Retired()
        except _Retired as inner:
            raise RuntimeError("instructor gave up") from inner
    except RuntimeError as outer:
        assert is_model_retired_error(outer) is True


def test_non_410_errors_are_not_treated_as_retired():
    assert is_model_retired_error(_Retired(429)) is False
    assert is_model_retired_error(_Retired(404)) is False
    assert is_model_retired_error(ConnectionError("down")) is False
    assert is_model_retired_error(None) is False


def test_retired_error_detection_survives_cyclic_cause():
    a = _Retired(500)
    b = RuntimeError("b")
    a.__cause__ = b
    b.__cause__ = a
    assert is_model_retired_error(a) is False  # terminates, no infinite loop


async def test_retry_policy_does_not_retry_a_retired_model():
    """A 410 must cost exactly one attempt, not the full instructor budget."""
    attempts = 0

    async def _call():
        nonlocal attempts
        attempts += 1
        raise _Retired()

    with pytest.raises(_Retired):
        async for attempt in instructor_retry_policy(3):
            with attempt:
                await _call()
    assert attempts == 1


async def test_retry_policy_still_retries_schema_failures():
    attempts = 0

    async def _call():
        nonlocal attempts
        attempts += 1
        raise ValueError("schema mismatch")

    with pytest.raises(Exception):
        async for attempt in instructor_retry_policy(3):
            with attempt:
                await _call()
    assert attempts == 3


async def test_failover_reaches_fallback_after_a_retired_primary():
    class _Out(pydantic.BaseModel):
        ok: bool

    class _Gone(LiteLLMChatProvider):
        async def complete(self, **kw):
            raise _Retired()

    class _Works(LiteLLMChatProvider):
        async def complete(self, **kw):
            return _Out(ok=True)

    fp = FailoverChatProvider([_Gone(model="retired"), _Works(model="live")])
    out = await fp.complete(
        response_model=_Out, messages=[{"role": "user", "content": "hi"}],
        max_tokens=10, temperature=0.0,
    )
    assert out.ok is True
