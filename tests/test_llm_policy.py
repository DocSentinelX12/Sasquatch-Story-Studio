import pytest

from studio.adapters import AdapterInfo
from studio.llm import LLMPolicy, LLMRequest, LLMRouter, CANONICAL_LLM_INSTRUCTION


class FakeLLM:
    def __init__(self, *, verified: bool, local: bool):
        capabilities = ["llm", "interpret"]
        if local:
            capabilities.append("local")
        self.info = AdapterInfo(
            id="test-llm",
            version="1",
            license="test",
            capabilities=tuple(capabilities),
            verified=verified,
        )


def test_unverified_llm_cannot_route():
    router = LLMRouter([FakeLLM(verified=False, local=True)])
    try:
        router.choose("interpret")
    except RuntimeError:
        return
    raise AssertionError("unverified LLM was routed")


def test_verified_local_llm_is_preferred():
    local = FakeLLM(verified=True, local=True)
    remote = FakeLLM(verified=True, local=False)
    router = LLMRouter([remote, local], LLMPolicy(prefer_local=True))
    assert router.choose("interpret") is local


def test_remote_policy_is_rejected_even_if_explicitly_requested():
    with pytest.raises(ValueError):
        LLMPolicy(allow_remote=True)


def test_paid_api_policy_is_rejected():
    with pytest.raises(ValueError):
        LLMPolicy(allow_paid_api=True)


def test_request_requires_canonical_source():
    request = LLMRequest(
        task="interpret",
        system_instruction=CANONICAL_LLM_INSTRUCTION,
        user_input="A story",
        canonical_source="A story",
    )
    assert request.canonical_source == request.user_input


def test_request_rejects_non_object_structured_schema():
    request = LLMRequest(
        task="interpret",
        system_instruction=CANONICAL_LLM_INSTRUCTION,
        user_input="A story",
        canonical_source="A story",
        output_schema={"type": "array"},
    )
    with pytest.raises(ValueError):
        request.validate()
