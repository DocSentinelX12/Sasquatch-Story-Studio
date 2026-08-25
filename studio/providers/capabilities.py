"""Provider capability descriptors (PART 4).

Capabilities are declared from VERIFIED provider documentation only. An adapter
reports what its provider actually supports; the UI disables the rest.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderCapabilities:
    """Structured capability set for one provider adapter."""

    text_to_video: bool = False
    image_to_video: bool = False            # first-frame image conditioning
    last_frame: bool = False                # last-frame conditioning
    start_end_frames: bool = False          # first+last interpolation
    reference_images: bool = False          # extra identity/pose references
    video_extension: bool = False
    audio_generation: bool = False
    seed_support: bool = False
    camera_controls: bool = False
    local_reference_files: bool = False     # can consume local files (base64)
    url_reference_only: bool = False        # references must be public URLs
    cancel_supported: bool = False

    durations: tuple[float, ...] = ()
    resolutions: tuple[str, ...] = ()
    aspect_ratios: tuple[str, ...] = ()
    max_reference_slots: int = 0            # 0 = no reference support
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "text_to_video": self.text_to_video,
            "image_to_video": self.image_to_video,
            "last_frame": self.last_frame,
            "start_end_frames": self.start_end_frames,
            "reference_images": self.reference_images,
            "video_extension": self.video_extension,
            "audio_generation": self.audio_generation,
            "seed_support": self.seed_support,
            "camera_controls": self.camera_controls,
            "local_reference_files": self.local_reference_files,
            "url_reference_only": self.url_reference_only,
            "cancel_supported": self.cancel_supported,
            "durations": list(self.durations),
            "resolutions": list(self.resolutions),
            "aspect_ratios": list(self.aspect_ratios),
            "max_reference_slots": self.max_reference_slots,
            "notes": list(self.notes),
        }

    def validate_settings(self, settings: dict) -> list[str]:
        """Return capability errors for requested generation settings."""
        errors: list[str] = []
        duration = settings.get("duration_seconds")
        if duration is not None and self.durations and float(duration) not in [float(d) for d in self.durations]:
            errors.append(f"duration {duration}s not supported (allowed: {list(self.durations)})")
        resolution = settings.get("resolution")
        if resolution and self.resolutions and resolution not in self.resolutions:
            errors.append(f"resolution '{resolution}' not supported (allowed: {list(self.resolutions)})")
        aspect = settings.get("aspect_ratio")
        if aspect and self.aspect_ratios and aspect not in self.aspect_ratios:
            errors.append(f"aspect ratio '{aspect}' not supported (allowed: {list(self.aspect_ratios)})")
        if settings.get("seed") is not None and not self.seed_support:
            errors.append("seed is not supported by this provider")
        if settings.get("generate_audio") and not self.audio_generation:
            errors.append("audio generation is not supported by this provider")
        if settings.get("last_frame") and not (self.last_frame or self.start_end_frames):
            errors.append("last-frame conditioning is not supported by this provider")
        return errors
