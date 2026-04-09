from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import imagehash
from PIL import Image, ImageChops, ImageOps

from .config import ChangeDetectionConfig


@dataclass
class ComparisonResult:
    previous_path: str
    current_path: str
    phash_distance: int
    dhash_distance: int
    mean_diff: float
    changed_ratio: float
    classification: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _prepare(path: Path, size: tuple[int, int] = (256, 256)) -> Image.Image:
    image = Image.open(path).convert("RGB")
    image = ImageOps.exif_transpose(image)
    return image.resize(size)


def _diff_metrics(previous: Image.Image, current: Image.Image) -> tuple[float, float]:
    diff = ImageChops.difference(previous, current).convert("L")
    histogram = diff.histogram()
    pixel_count = diff.size[0] * diff.size[1]
    weighted_sum = sum(index * count for index, count in enumerate(histogram))
    mean_diff = weighted_sum / (255 * pixel_count)

    threshold = 16
    changed_pixels = sum(histogram[threshold:])
    changed_ratio = changed_pixels / pixel_count
    return mean_diff, changed_ratio


def compare_images(
    previous_path: Path,
    current_path: Path,
    thresholds: ChangeDetectionConfig,
) -> ComparisonResult:
    previous = _prepare(previous_path)
    current = _prepare(current_path)

    phash_distance = int(imagehash.phash(previous) - imagehash.phash(current))
    dhash_distance = int(imagehash.dhash(previous) - imagehash.dhash(current))
    mean_diff, changed_ratio = _diff_metrics(previous, current)

    if (
        phash_distance <= thresholds.phash_same_threshold
        and dhash_distance <= thresholds.dhash_same_threshold
        and mean_diff <= thresholds.mean_diff_same_threshold
        and changed_ratio <= thresholds.changed_ratio_same_threshold
    ):
        classification = "same"
    elif (
        phash_distance <= thresholds.phash_minor_threshold
        and dhash_distance <= thresholds.dhash_minor_threshold
        and mean_diff <= thresholds.mean_diff_minor_threshold
        and changed_ratio <= thresholds.changed_ratio_minor_threshold
    ):
        classification = "minor_change"
    else:
        classification = "major_change"

    return ComparisonResult(
        previous_path=str(previous_path),
        current_path=str(current_path),
        phash_distance=phash_distance,
        dhash_distance=dhash_distance,
        mean_diff=round(mean_diff, 6),
        changed_ratio=round(changed_ratio, 6),
        classification=classification,
    )
