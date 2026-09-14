from studio.llm_registry import CURATED_LLMS, get_llm

def test_curated_llms_are_named_and_provenanced():
    assert {m.id for m in CURATED_LLMS} == {"qwen3", "gemma", "llama3.3"}
    assert all(m.quality_tier == "high" for m in CURATED_LLMS)
    assert all(m.official_source.startswith("https://github.com/") for m in CURATED_LLMS)

def test_unknown_llm_rejected():
    try:
        get_llm("generic-llm")
    except KeyError:
        return
    raise AssertionError("generic/unknown LLM accepted")
