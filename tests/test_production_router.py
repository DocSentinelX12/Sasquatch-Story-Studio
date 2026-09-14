from pathlib import Path

from studio.adapters import AdapterInfo
from studio.production import ProductionRequest, ProductionResponse, ProductionRouter


class StubAdapter:
    def __init__(self, adapter_id, capabilities, quality_tier, review=False):
        self.info = AdapterInfo(adapter_id, "1", "MIT", tuple(capabilities), True)
        self.quality_tier = quality_tier
        self.commercial_use_review_required = review
        self.is_local = True
        self.uses_paid_service = False
        self.uses_paid_api = False

    def execute(self, request: ProductionRequest) -> ProductionResponse:
        return ProductionResponse(self.info.id, (str(Path("output.bin")),), {"engine_id": self.info.id})


def test_animate_accepts_video_generation_engines():
    router = ProductionRouter([
        StubAdapter("blender", ("animation",), "professional_3d"),
        StubAdapter("wan2.2", ("video_generation",), "very_high"),
    ])
    assert router.choose("animation").info.id == "blender"
    assert router.choose(("animation", "video_generation")).info.id == "wan2.2"


def test_sound_music_uses_music_engine():
    router = ProductionRouter([StubAdapter("ace-step-1.5", ("music", "sfx"), "very_high")])
    assert router.choose(("music", "sfx")).info.id == "ace-step-1.5"


def test_commercial_review_engine_is_not_auto_selected():
    router = ProductionRouter([
        StubAdapter("ltx-video", ("video_generation",), "high", review=True),
    ])
    try:
        router.choose(("animation", "video_generation"))
    except RuntimeError as exc:
        assert "No verified zero-cost" in str(exc)
    else:
        raise AssertionError("commercial-review engine was selected without explicit approval")


def test_commercial_review_engine_can_be_explicitly_enabled():
    router = ProductionRouter(
        [StubAdapter("ltx-video", ("video_generation",), "high", review=True)],
        allow_commercial_review_required=True,
    )
    assert router.choose(("animation", "video_generation")).info.id == "ltx-video"
