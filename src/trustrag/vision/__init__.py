"""Conditional vision (§9): a pre-filtered, 3-way decision over images.

Vision is conditional, not blanket — `decide` routes each `ImageRef` to text /
ocr / vision / skip before any model is touched, and `describe_image` shapes an
injected `VisionPlugin`'s output into an EU-ready `VisionRecord` only for the
images that earn a vision call.
"""

from trustrag.vision.describe import FakeVision, VisionRecord, describe_image
from trustrag.vision.prefilter import VisionDecision, VisionPrefilterConfig, decide

__all__ = [
    "FakeVision",
    "VisionDecision",
    "VisionPrefilterConfig",
    "VisionRecord",
    "decide",
    "describe_image",
]
