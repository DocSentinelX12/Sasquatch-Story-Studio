"""Curated named LLMs. Generic model selection is prohibited."""
from dataclasses import dataclass

@dataclass(frozen=True)
class LLMModelSpec:
    id: str
    official_source: str
    license: str
    strengths: tuple[str, ...]
    quality_tier: str
    commercial_review_required: bool = False

CURATED_LLMS = (
    LLMModelSpec("qwen3", "https://github.com/QwenLM/Qwen3", "Apache-2.0", ("reasoning", "instruction", "tool_use", "structured_output"), "high"),
    LLMModelSpec("gemma", "https://github.com/google-deepmind/gemma", "Apache-2.0", ("instruction", "structured_output", "local_inference"), "high"),
    LLMModelSpec("llama3.3", "https://github.com/meta-llama/llama-models", "Llama-3.3-Community", ("instruction", "reasoning", "long_context"), "high", True),
)

def get_llm(model_id: str) -> LLMModelSpec:
    for model in CURATED_LLMS:
        if model.id == model_id:
            return model
    raise KeyError(f"Unknown curated LLM: {model_id}")

def assert_curated(model: LLMModelSpec) -> None:
    if model.quality_tier == "generic" or not model.official_source or not model.license:
        raise RuntimeError(f"Unacceptable LLM registry entry: {model.id}")
