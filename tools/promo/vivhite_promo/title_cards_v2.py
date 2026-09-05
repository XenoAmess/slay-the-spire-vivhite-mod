"""Vivhite v2 explainer-card specifications for xAR 0.2.1.

This module is deliberately a project-side factory.  It only constructs
public :mod:`xar_promo.layout` and :mod:`xar_promo.visuals` value objects; it
does not resolve fonts or assets, render an image, or start a process.

The xAR ``TitleCardSpec`` describes pixels but has no timeline duration.  A
``MechanismTitleCardCue`` therefore keeps the director's maximum three-second
mechanism-card duration beside, rather than inside, the reusable xAR object.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real

from xar_promo.layout import SafeArea, WrapPolicy
from xar_promo.visuals import (
    BackgroundSpec,
    Box,
    CanvasSpec,
    ImageElement,
    LayerGroup,
    Palette,
    PanelElement,
    TextElement,
    TextStyle,
    TitleCardSpec,
)


FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080
SAFE_MARGIN_HORIZONTAL = 120
SAFE_MARGIN_VERTICAL = 90

DEFAULT_DURATION_SECONDS = 2.5
MAX_MECHANISM_CARD_SECONDS = 3.0

DEFAULT_BUTTERFLY_ASSET_KEY = "vivhite_blue_butterfly_v2"
CHINESE_TITLE_FONT_KEY = "vivhite_title_zh_v2"
ENGLISH_SUBTITLE_FONT_KEY = "vivhite_subtitle_en_v2"

DEEP_INDIGO_RGBA = (15, 10, 46, 255)
INDIGO_PANEL_RGBA = (27, 18, 66, 238)
GOLD_RGBA = (215, 177, 83, 255)
TITLE_RGBA = (248, 241, 224, 255)
SUBTITLE_RGBA = (154, 190, 235, 255)
TRANSPARENT_RGBA = (0, 0, 0, 0)


@dataclass(frozen=True, slots=True)
class MechanismTitleCardCue:
    """One caller-timed v2 mechanism card and its xAR visual spec."""

    cue_id: str
    duration_seconds: float
    title_card: TitleCardSpec

    def __post_init__(self) -> None:
        cue_id = _trimmed_text(self.cue_id, "cue_id")
        duration = _mechanism_duration(self.duration_seconds)
        if not isinstance(self.title_card, TitleCardSpec):
            raise TypeError("title_card must be an xAR TitleCardSpec")
        object.__setattr__(self, "cue_id", cue_id)
        object.__setattr__(self, "duration_seconds", duration)


def create_title_card_spec_v2(
    chinese_title: str,
    english_subtitle: str,
    *,
    butterfly_asset_key: str = DEFAULT_BUTTERFLY_ASSET_KEY,
) -> TitleCardSpec:
    """Construct the 1920x1080 Vivhite explainer-page visual.

    The caller must bind the two exported font keys to resolved fonts and the
    butterfly key to an approved transparent blue-butterfly asset before
    rendering with xAR.  Keeping those resources injected preserves xAR's
    fail-closed public contract and avoids hidden font or artwork fallbacks.
    """

    title = _trimmed_text(chinese_title, "chinese_title")
    subtitle = _trimmed_text(english_subtitle, "english_subtitle")
    butterfly_key = _trimmed_text(butterfly_asset_key, "butterfly_asset_key")

    palette = Palette(
        {
            "deep_indigo": DEEP_INDIGO_RGBA,
            "indigo_panel": INDIGO_PANEL_RGBA,
            "gold": GOLD_RGBA,
            "title": TITLE_RGBA,
            "subtitle": SUBTITLE_RGBA,
            "transparent": TRANSPARENT_RGBA,
        }
    )
    safe_area = SafeArea.from_margins(
        frame_width=FRAME_WIDTH,
        frame_height=FRAME_HEIGHT,
        left=SAFE_MARGIN_HORIZONTAL,
        top=SAFE_MARGIN_VERTICAL,
        right=SAFE_MARGIN_HORIZONTAL,
        bottom=SAFE_MARGIN_VERTICAL,
    )
    canvas = CanvasSpec(
        width=FRAME_WIDTH,
        height=FRAME_HEIGHT,
        safe_area=safe_area,
        palette=palette,
        background=BackgroundSpec(kind="solid", color_role="deep_indigo"),
    )

    # xAR 0.2.1 intentionally exposes deterministic rectangles rather than a
    # project-specific vector language.  These thin panels form the gold
    # geometric frame while remaining fully inside the 120/90 safe margins.
    panels = (
        PanelElement(
            Box(280, 300, 1640, 780),
            "indigo_panel",
            outline_role="gold",
            outline_width=2,
        ),
        PanelElement(Box(180, 180, 820, 184), "gold"),
        PanelElement(Box(1100, 180, 1740, 184), "gold"),
        PanelElement(Box(180, 896, 820, 900), "gold"),
        PanelElement(Box(1100, 896, 1740, 900), "gold"),
        PanelElement(Box(180, 180, 184, 260), "gold"),
        PanelElement(Box(1736, 180, 1740, 260), "gold"),
        PanelElement(Box(180, 820, 184, 900), "gold"),
        PanelElement(Box(1736, 820, 1740, 900), "gold"),
    )
    butterflies = (
        ImageElement(
            butterfly_key,
            Box(188, 410, 316, 538),
            fit_mode="contain",
            opacity=230,
            contain_color_role="transparent",
        ),
        ImageElement(
            butterfly_key,
            Box(1604, 542, 1732, 670),
            fit_mode="contain",
            opacity=205,
            contain_color_role="transparent",
        ),
    )
    texts = (
        TextElement(
            title,
            Box(360, 400, 1560, 570),
            TextStyle(
                font_key=CHINESE_TITLE_FONT_KEY,
                color_role="title",
                line_height_px=112,
                max_lines=2,
                alignment="center",
                vertical_alignment="center",
                wrap_policy=WrapPolicy(
                    prefer_break_after=frozenset({"：", "，", "、"}),
                    prefer_whitespace=False,
                ),
            ),
        ),
        TextElement(
            subtitle,
            Box(440, 600, 1480, 700),
            TextStyle(
                font_key=ENGLISH_SUBTITLE_FONT_KEY,
                color_role="subtitle",
                line_height_px=48,
                max_lines=2,
                alignment="center",
                vertical_alignment="top",
            ),
        ),
    )
    return TitleCardSpec(
        canvas=canvas,
        layers=LayerGroup(panels=panels, images=butterflies, texts=texts),
    )


def create_mechanism_title_card_v2(
    cue_id: str,
    chinese_title: str,
    english_subtitle: str,
    *,
    duration_seconds: float = DEFAULT_DURATION_SECONDS,
    butterfly_asset_key: str = DEFAULT_BUTTERFLY_ASSET_KEY,
) -> MechanismTitleCardCue:
    """Construct a caller-timed mechanism card capped at three seconds."""

    return MechanismTitleCardCue(
        cue_id=cue_id,
        duration_seconds=duration_seconds,
        title_card=create_title_card_spec_v2(
            chinese_title,
            english_subtitle,
            butterfly_asset_key=butterfly_asset_key,
        ),
    )


def _trimmed_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{label} must be a non-empty trimmed string")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{label} must not contain control characters")
    return value


def _mechanism_duration(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError("duration_seconds must be a real number")
    duration = float(value)
    if not math.isfinite(duration) or not 0 < duration <= MAX_MECHANISM_CARD_SECONDS:
        raise ValueError(
            "duration_seconds must be finite, positive, and no greater than "
            f"{MAX_MECHANISM_CARD_SECONDS:g}"
        )
    return duration


__all__ = [
    "CHINESE_TITLE_FONT_KEY",
    "DEFAULT_BUTTERFLY_ASSET_KEY",
    "DEFAULT_DURATION_SECONDS",
    "DEEP_INDIGO_RGBA",
    "ENGLISH_SUBTITLE_FONT_KEY",
    "FRAME_HEIGHT",
    "FRAME_WIDTH",
    "GOLD_RGBA",
    "MAX_MECHANISM_CARD_SECONDS",
    "MechanismTitleCardCue",
    "SAFE_MARGIN_HORIZONTAL",
    "SAFE_MARGIN_VERTICAL",
    "create_mechanism_title_card_v2",
    "create_title_card_spec_v2",
]
