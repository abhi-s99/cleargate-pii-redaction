"""Image analysis and the standalone image extractor (TR-EX-06, TR-EX-30).

``detect_faces`` runs OpenCV Haar cascades (frontal, profile, mirrored profile) on a
downscaled grey copy and returns boxes in source pixels, merged when they overlap.
``prepare_for_ocr`` upscales small images 2x (TR-EX-12). ``ink_ratio`` measures how
much of a raster is non-background, so "no text found" on a page with pixels can be
told apart from a blank page (Architecture D1).
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps

from cleargate.core.models import Document, FileFormat, Locator
from cleargate.extract.base import DocBuilder, analyse_raster
from cleargate.extract.metadata import exif_fields

Box = tuple[int, int, int, int]
FACE_MAX_SIDE = 1200
_CASCADES: dict[str, cv2.CascadeClassifier] = {}


def _cascade(name: str) -> cv2.CascadeClassifier:
    if name not in _CASCADES:
        _CASCADES[name] = cv2.CascadeClassifier(cv2.data.haarcascades + name)  # type: ignore[attr-defined]
    return _CASCADES[name]


def _overlaps(a: Box, b: Box) -> bool:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return smaller > 0 and inter / smaller > 0.3


def merge_boxes(boxes: list[Box]) -> list[Box]:
    merged: list[Box] = []
    for box in sorted(boxes):
        for i, m in enumerate(merged):
            if _overlaps(box, m):
                merged[i] = (
                    min(box[0], m[0]),
                    min(box[1], m[1]),
                    max(box[2], m[2]),
                    max(box[3], m[3]),
                )
                break
        else:
            merged.append(box)
    return merged


YUNET_MODEL = Path(__file__).with_name("models") / "face_detection_yunet_2023mar.onnx"
YUNET_MAX_SIDE = 2000
YUNET_SCORE = 0.6


def detect_faces_yunet(image: Image.Image) -> list[Box]:
    """OpenCV YuNet (ADR-27): finds small faces in screenshots that Haar misses."""
    rgb = np.array(image.convert("RGB"))
    scale = min(1.0, YUNET_MAX_SIDE / max(rgb.shape[:2]))
    if scale < 1.0:
        rgb = cv2.resize(rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    h, w = bgr.shape[:2]
    detector = cv2.FaceDetectorYN.create(str(YUNET_MODEL), "", (w, h), YUNET_SCORE, 0.3, 5000)
    _, faces = detector.detect(bgr)
    if faces is None:
        return []
    return [
        (
            int(f[0] / scale),
            int(f[1] / scale),
            int((f[0] + f[2]) / scale),
            int((f[1] + f[3]) / scale),
        )
        for f in faces
    ]


def detect_faces(image: Image.Image) -> list[Box]:
    """Union of YuNet and the TR-EX-06 Haar cascades, merged."""
    return merge_boxes(detect_faces_yunet(image) + detect_faces_haar(image))


def detect_faces_haar(image: Image.Image) -> list[Box]:
    grey = np.array(ImageOps.grayscale(image))
    scale = min(1.0, FACE_MAX_SIDE / max(grey.shape))
    if scale < 1.0:
        grey = cv2.resize(grey, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    grey = cv2.equalizeHist(grey)
    min_side = max(24, int(min(grey.shape) * 0.04))
    found: list[Box] = []
    for name, flip in (
        ("haarcascade_frontalface_default.xml", False),
        ("haarcascade_profileface.xml", False),
        ("haarcascade_profileface.xml", True),
    ):
        src = cv2.flip(grey, 1) if flip else grey
        hits = _cascade(name).detectMultiScale(
            src, scaleFactor=1.1, minNeighbors=6, minSize=(min_side, min_side)
        )
        for x, y, w, h in hits if len(hits) else []:
            if flip:
                x = src.shape[1] - x - w
            found.append(
                (int(x / scale), int(y / scale), int((x + w) / scale), int((y + h) / scale))
            )
    return found


NONTEXT_MAX_SIDE = 1300


def nontext_regions(
    image: Image.Image, word_boxes: list[tuple[Box, str, float]], *, min_area_ratio: float
) -> list[tuple[Box, list[float]]]:
    """Connected non-text ink regions covering at least ``min_area_ratio`` of the raster
    (TR-EX-05, second clause). Recognised word boxes are blanked first. Returns each
    region's box (source px) and the confidences of words (2+ chars) centred inside it.
    """
    grey = np.array(ImageOps.grayscale(image))
    scale = min(1.0, NONTEXT_MAX_SIDE / max(grey.shape))
    if scale < 1.0:
        grey = cv2.resize(grey, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    background = float(np.median(grey))
    ink = (np.abs(grey.astype(np.int16) - background) > 40).astype(np.uint8)
    pad = max(2, int(6 * scale))
    for (x0, y0, x1, y1), _, _ in word_boxes:
        ink[
            max(0, int(y0 * scale) - pad) : int(y1 * scale) + pad,
            max(0, int(x0 * scale) - pad) : int(x1 * scale) + pad,
        ] = 0
    k = max(3, int(min(grey.shape) * 0.012))
    joined = cv2.dilate(ink, np.ones((k, k), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(joined)
    area = grey.shape[0] * grey.shape[1]
    out: list[tuple[Box, list[float]]] = []
    for x, y, w, h, _ in stats[1:count]:
        if w * h / area < min_area_ratio or float(ink[y : y + h, x : x + w].mean()) < 0.02:
            continue
        box = (int(x / scale), int(y / scale), int((x + w) / scale), int((y + h) / scale))
        confs = [
            conf
            for (bx0, by0, bx1, by1), text, conf in word_boxes
            if len(text) >= 2
            and box[0] <= (bx0 + bx1) / 2 <= box[2]
            and box[1] <= (by0 + by1) / 2 <= box[3]
        ]
        out.append((box, confs))
    return out


def ink_ratio(image: Image.Image) -> float:
    """Share of pixels clearly darker than the page background (sampled)."""
    grey = ImageOps.grayscale(image)
    grey.thumbnail((600, 600))
    arr = np.asarray(grey, dtype=np.uint8)
    background = float(np.median(arr))
    return float(np.mean(arr < background - 40))


def prepare_for_ocr(image: Image.Image) -> Image.Image:
    """RGB, alpha flattened on white, 2x upscale when the short side is < 1000 px."""
    if image.mode in ("RGBA", "LA", "P"):
        rgba = image.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, "white")
        canvas.paste(rgba, mask=rgba.getchannel("A"))
        image = canvas
    elif image.mode != "RGB":
        image = image.convert("RGB")
    if min(image.size) < 1000:
        image = image.resize((image.width * 2, image.height * 2), Image.Resampling.LANCZOS)
    return image


def open_image(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


class ImageExtractor:
    """PNG/JPEG/TIFF: EXIF metadata segments, then OCR and faces on every frame."""

    name = "image-extractor"
    version = "0.3.0"

    def supports(self, fmt: FileFormat) -> bool:
        return fmt in (FileFormat.PNG, FileFormat.JPEG, FileFormat.TIFF)

    def extract(self, path: Path, fmt: FileFormat, ctx: Any) -> Document:
        b = DocBuilder.for_job(ctx, path, fmt)
        b.doc.extractors[self.name] = self.version
        with Image.open(path) as img:
            meta_loc = Locator(part="image:exif")
            b.register(meta_loc, inspected=True)
            for key, value in exif_fields(img):
                b.add("metadata", value, Locator(part="image:exif", xpath=key))
            frames = getattr(img, "n_frames", 1)
            for i in range(frames):
                img.seek(i)
                frame = img.copy()
                loc = Locator(part="image", page=i + 1, image_ref="image")
                analyse_raster(b, frame, loc, dpi_tag="native", prepare=prepare_for_ocr)
        b.doc.units = {"images": frames}
        return b.build()
