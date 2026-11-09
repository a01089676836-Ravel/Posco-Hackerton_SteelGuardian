"""Profile a folder of normal part images before PatchCore onboarding."""

import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np
from PIL import Image


SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("good_dir", type=Path, help="Folder of normal part images")
    args = parser.parse_args()
    if not args.good_dir.is_dir():
        parser.error(f"Image folder does not exist: {args.good_dir}")

    files = sorted(
        path for path in args.good_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )
    resolutions = Counter()
    color_modes = Counter()
    invalid_images = []
    brightness = []

    for path in files:
        try:
            with Image.open(path) as image:
                width, height = image.size
                mode = image.mode
                mean_brightness = float(np.asarray(image.convert("RGB").convert("L")).mean())
        except (OSError, Image.DecompressionBombError):
            invalid_images.append(path.name)
            continue
        resolutions[f"{width}x{height}"] += 1
        color_modes[mode] += 1
        brightness.append(mean_brightness)

    brightness_percentiles = {}
    if brightness:
        percentiles = (0, 10, 25, 50, 75, 90, 100)
        brightness_percentiles = {
            f"p{percentile}": round(float(value), 3)
            for percentile, value in zip(percentiles, np.percentile(brightness, percentiles))
        }

    within_role_range = 20 <= len(brightness) <= 220
    report = {
        "supported_files": len(files),
        "valid_images": len(brightness),
        "invalid_images": invalid_images,
        "resolution_counts": dict(resolutions),
        "original_color_mode_counts": dict(color_modes),
        "image_mean_brightness_percentiles_0_to_255": brightness_percentiles,
        "within_role_image_count_range": within_role_range,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if within_role_range and not invalid_images else 1


if __name__ == "__main__":
    raise SystemExit(main())
