from __future__ import annotations

from pathlib import Path
import hashlib
import json

from PIL import Image


SOURCE = Path(__file__).with_name("output.png")
VALIDATION = Path(__file__).with_name("validation")


def edge_metrics(values: list[int]) -> dict[str, int]:
    return {
        "length": len(values),
        "min": min(values),
        "max": max(values),
        "zero": sum(value == 0 for value in values),
        "nonzero": sum(value > 0 for value in values),
        "opaque_255": sum(value == 255 for value in values),
    }


def main() -> None:
    VALIDATION.mkdir(parents=True, exist_ok=True)
    raw = SOURCE.read_bytes()
    with Image.open(SOURCE) as opened:
        opened.load()
        image = opened.copy()
        source_format = opened.format

    if image.mode != "RGBA":
        raise RuntimeError(f"Expected RGBA, got {image.mode}")

    width, height = image.size
    alpha = image.getchannel("A")
    alpha_values = list(alpha.getdata())
    pixels = alpha.load()

    def threshold_bbox(threshold: int) -> list[int] | None:
        mask = alpha.point(lambda value: 255 if value >= threshold else 0)
        box = mask.getbbox()
        return list(box) if box else None

    top = [pixels[x, 0] for x in range(width)]
    bottom = [pixels[x, height - 1] for x in range(width)]
    left = [pixels[0, y] for y in range(height)]
    right = [pixels[width - 1, y] for y in range(height)]

    # Largest exact integer 25:19 rectangle centered in the returned source.
    unit = min(width // 25, height // 19)
    crop_width = unit * 25
    crop_height = unit * 19
    left_x = (width - crop_width) // 2
    top_y = (height - crop_height) // 2
    crop_box = (left_x, top_y, left_x + crop_width, top_y + crop_height)
    card = image.crop(crop_box).resize((1000, 760), Image.Resampling.LANCZOS)
    card_path = VALIDATION / "card-centered-25x19-1000x760.png"
    card.save(card_path, format="PNG")
    card_alpha = card.getchannel("A")
    card_alpha_values = list(card_alpha.getdata())
    card_pixels = card_alpha.load()

    def card_threshold_bbox(threshold: int) -> list[int] | None:
        mask = card_alpha.point(lambda value: 255 if value >= threshold else 0)
        box = mask.getbbox()
        return list(box) if box else None

    backgrounds = {
        "black": (0, 0, 0, 255),
        "white": (255, 255, 255, 255),
        "deep-blue-gray": (24, 34, 52, 255),
    }
    composite_paths: dict[str, str] = {}
    for name, color in backgrounds.items():
        base = Image.new("RGBA", card.size, color)
        composite = Image.alpha_composite(base, card).convert("RGB")
        path = VALIDATION / f"sourceover-{name}-1000x760.png"
        composite.save(path, format="PNG")
        composite_paths[name] = path.as_posix()

    metrics = {
        "source": SOURCE.as_posix(),
        "source_sha256": hashlib.sha256(raw).hexdigest().upper(),
        "png_signature_valid": raw.startswith(b"\x89PNG\r\n\x1a\n"),
        "format": source_format,
        "mode": image.mode,
        "size": [width, height],
        "corners_alpha": {
            "top_left": pixels[0, 0],
            "top_right": pixels[width - 1, 0],
            "bottom_left": pixels[0, height - 1],
            "bottom_right": pixels[width - 1, height - 1],
        },
        "edges_alpha": {
            "top": edge_metrics(top),
            "bottom": edge_metrics(bottom),
            "left": edge_metrics(left),
            "right": edge_metrics(right),
        },
        "alpha_counts": {
            "total": len(alpha_values),
            "zero": sum(value == 0 for value in alpha_values),
            "1_to_15": sum(1 <= value <= 15 for value in alpha_values),
            "16_to_63": sum(16 <= value <= 63 for value in alpha_values),
            "64_to_127": sum(64 <= value <= 127 for value in alpha_values),
            "128_to_239": sum(128 <= value <= 239 for value in alpha_values),
            "240_to_254": sum(240 <= value <= 254 for value in alpha_values),
            "opaque_255": sum(value == 255 for value in alpha_values),
        },
        "alpha_bbox": {
            "gte_1": threshold_bbox(1),
            "gte_16": threshold_bbox(16),
            "gte_64": threshold_bbox(64),
            "gte_128": threshold_bbox(128),
            "gte_240": threshold_bbox(240),
        },
        "deterministic_card_preview": {
            "crop_box_left_top_right_bottom": list(crop_box),
            "crop_size": [crop_width, crop_height],
            "resize": [1000, 760],
            "resampler": "Pillow Image.Resampling.LANCZOS",
            "path": card_path.as_posix(),
            "mode": card.mode,
            "corners_alpha": {
                "top_left": card_pixels[0, 0],
                "top_right": card_pixels[999, 0],
                "bottom_left": card_pixels[0, 759],
                "bottom_right": card_pixels[999, 759],
            },
            "alpha_counts": {
                "total": len(card_alpha_values),
                "zero": sum(value == 0 for value in card_alpha_values),
                "1_to_15": sum(1 <= value <= 15 for value in card_alpha_values),
                "16_to_63": sum(16 <= value <= 63 for value in card_alpha_values),
                "64_to_127": sum(64 <= value <= 127 for value in card_alpha_values),
                "128_to_239": sum(128 <= value <= 239 for value in card_alpha_values),
                "240_to_254": sum(240 <= value <= 254 for value in card_alpha_values),
                "opaque_255": sum(value == 255 for value in card_alpha_values),
            },
            "alpha_bbox": {
                "gte_1": card_threshold_bbox(1),
                "gte_16": card_threshold_bbox(16),
                "gte_64": card_threshold_bbox(64),
                "gte_128": card_threshold_bbox(128),
                "gte_240": card_threshold_bbox(240),
            },
        },
        "sourceover_backgrounds_rgba": {
            name: list(color) for name, color in backgrounds.items()
        },
        "sourceover_paths": composite_paths,
        "validation_png_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest().upper()
            for path in [
                card_path,
                *(VALIDATION / f"sourceover-{name}-1000x760.png" for name in backgrounds),
            ]
        },
    }
    metrics_path = VALIDATION / "metrics.json"
    metrics_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
