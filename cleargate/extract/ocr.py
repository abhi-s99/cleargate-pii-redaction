"""Tesseract OCR wrapper (TR-EX-04, TR-EX-05, TR-EX-08, ADR-03, ADR-26).

* ``OcrEngine.ocr(image, dpi_tag)`` runs ``image_to_data`` with ``--oem 1 --psm 3`` and
  returns words (text, confidence, box, block/par/line ids), lines grouped by
  ``(block, par, line)``, and per-block statistics for unreadable-region analysis.
* Results are cached by ``sha256(raster bytes) + dpi + tesseract version`` (TR-EX-08), plus
  the config and a parser version, because cached entries hold derived block statistics.
  The cache holds document text, so on disk it is Fernet-encrypted with the vault key
  (ADR-26); without a key only the in-process cache is used.
* A per-call timeout turns into ``OCR_TIMEOUT``; a missing binary into
  ``OCR_UNAVAILABLE``. Callers mark the part uninspected (fail closed).
* ``unreadable_blocks`` applies TR-EX-05: a block covering at least ``min_area_ratio`` of
  the raster whose mean word confidence is below ``max_mean_conf``, or where at least 40 %
  of its words are below ``word_conf_floor``.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pytesseract
from cryptography.fernet import Fernet, InvalidToken
from PIL import Image

from cleargate.core.errors import ErrorCode, OcrError

TESS_CONFIG = "--oem 1 --psm 3"
# Bump whenever parse_data changes: cached results store derived block statistics.
PARSER_VERSION = "2"
LOW_WORD_SHARE = 0.40
Box = tuple[int, int, int, int]  # left, top, right, bottom (pixels)


@dataclass
class OcrWord:
    text: str
    conf: float
    box: Box
    block: int
    par: int
    line: int


@dataclass
class OcrLine:
    text: str
    confs: list[float]
    box: Box
    block: int
    words: list[OcrWord] = field(default_factory=list)


@dataclass
class OcrBlock:
    block: int
    box: Box
    words: int
    mean_conf: float
    low_share: float


@dataclass
class OcrResult:
    width: int
    height: int
    lines: list[OcrLine]
    blocks: list[OcrBlock]
    engine: str
    seconds: float
    cached: bool = False

    @property
    def word_count(self) -> int:
        return sum(len(line.words) for line in self.lines)

    @property
    def mean_conf(self) -> float | None:
        confs = [c for line in self.lines for c in line.confs]
        return sum(confs) / len(confs) if confs else None

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str) -> OcrResult:
        d = json.loads(text)
        lines = [
            OcrLine(
                text=ln["text"],
                confs=ln["confs"],
                box=tuple(ln["box"]),
                block=ln["block"],
                words=[OcrWord(**{**w, "box": tuple(w["box"])}) for w in ln["words"]],
            )
            for ln in d["lines"]
        ]
        blocks = [OcrBlock(**{**b, "box": tuple(b["box"])}) for b in d["blocks"]]
        return cls(d["width"], d["height"], lines, blocks, d["engine"], d["seconds"], True)


def _union(boxes: list[Box]) -> Box:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def parse_data(
    data: dict[str, list[object]],
    width: int,
    height: int,
    engine: str,
    seconds: float,
    word_conf_floor: float = 60,
) -> OcrResult:
    words: list[OcrWord] = []
    for i, raw in enumerate(data["text"]):
        text = str(raw).strip()
        conf = float(str(data["conf"][i]))
        if not text or conf < 0:
            continue
        left, top = int(str(data["left"][i])), int(str(data["top"][i]))
        w, h = int(str(data["width"][i])), int(str(data["height"][i]))
        words.append(
            OcrWord(
                text,
                conf,
                (left, top, left + w, top + h),
                int(str(data["block_num"][i])),
                int(str(data["par_num"][i])),
                int(str(data["line_num"][i])),
            )
        )
    grouped: dict[tuple[int, int, int], list[OcrWord]] = {}
    for w_ in words:
        grouped.setdefault((w_.block, w_.par, w_.line), []).append(w_)
    lines = [
        OcrLine(
            " ".join(x.text for x in ws),
            [x.conf for x in ws],
            _union([x.box for x in ws]),
            key[0],
            ws,
        )
        for key, ws in sorted(grouped.items(), key=lambda kv: (kv[1][0].box[1], kv[0]))
    ]
    by_block: dict[int, list[OcrWord]] = {}
    for w_ in words:
        by_block.setdefault(w_.block, []).append(w_)
    blocks = []
    for b, ws in sorted(by_block.items()):
        # Single characters (RACI letters, bullets) get low confidence however clean the
        # scan is (Architecture D2) and would make tidy tables look unreadable (ADR-27).
        scored = [x for x in ws if len(x.text) >= 2] or ws
        blocks.append(
            OcrBlock(
                block=b,
                box=_union([x.box for x in ws]),
                words=len(ws),
                mean_conf=sum(x.conf for x in scored) / len(scored),
                low_share=sum(1 for x in scored if x.conf < word_conf_floor) / len(scored),
            )
        )
    return OcrResult(width, height, lines, blocks, engine, round(seconds, 3))


def unreadable_blocks(
    result: OcrResult, *, min_area_ratio: float, max_mean_conf: float
) -> list[OcrBlock]:
    """TR-EX-05 candidates (``low_share`` was computed with the policy's word_conf_floor)."""
    area = max(result.width * result.height, 1)
    out = []
    for b in result.blocks:
        ratio = (b.box[2] - b.box[0]) * (b.box[3] - b.box[1]) / area
        if ratio >= min_area_ratio and (
            b.mean_conf < max_mean_conf or b.low_share >= LOW_WORD_SHARE
        ):
            out.append(b)
    return out


def raster_key(image: Image.Image, dpi_tag: str, engine: str) -> str:
    h = hashlib.sha256()
    h.update(f"{image.mode}:{image.size[0]}x{image.size[1]}:".encode())
    h.update(image.tobytes())
    h.update(f"|{dpi_tag}|{engine}|{TESS_CONFIG}|parser{PARSER_VERSION}".encode())
    return h.hexdigest()


class OcrEngine:
    """One engine per process. Thread-safe memory cache; optional encrypted disk cache."""

    def __init__(
        self,
        tesseract_cmd: str | None,
        *,
        cache_dir: Path | None = None,
        cache_key: str | None = None,
        timeout_s: int = 120,
        word_conf_floor: float = 60,
    ) -> None:
        self.cmd = tesseract_cmd
        self.cache_dir = cache_dir
        self.cipher = Fernet(cache_key.encode()) if cache_key and cache_dir else None
        self.timeout_s = timeout_s
        self.word_conf_floor = word_conf_floor
        self._memory: dict[str, str] = {}
        self._lock = threading.Lock()
        self._version: str | None = None

    @property
    def version(self) -> str:
        if self._version is None:
            if not self.cmd:
                raise OcrError(ErrorCode.OCR_UNAVAILABLE)
            pytesseract.pytesseract.tesseract_cmd = self.cmd
            try:
                self._version = str(pytesseract.get_tesseract_version())
            except (pytesseract.TesseractNotFoundError, OSError):
                raise OcrError(ErrorCode.OCR_UNAVAILABLE) from None
        return self._version

    def available(self) -> bool:
        try:
            return bool(self.version)
        except OcrError:
            return False

    def _cache_get(self, key: str) -> OcrResult | None:
        with self._lock:
            hit = self._memory.get(key)
        if hit is None and self.cipher and self.cache_dir:
            path = self.cache_dir / f"{key}.ocr"
            if path.is_file():
                try:
                    hit = self.cipher.decrypt(path.read_bytes()).decode()
                except InvalidToken:
                    hit = None
        return OcrResult.from_json(hit) if hit else None

    def _cache_put(self, key: str, result: OcrResult) -> None:
        payload = result.to_json()
        with self._lock:
            self._memory[key] = payload
        if self.cipher and self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_dir / f"{key}.tmp"
            tmp.write_bytes(self.cipher.encrypt(payload.encode()))
            tmp.replace(self.cache_dir / f"{key}.ocr")

    def ocr(self, image: Image.Image, dpi_tag: str) -> OcrResult:
        engine = f"tesseract-{self.version}"
        img = image if image.mode in ("L", "RGB") else image.convert("RGB")
        key = raster_key(img, dpi_tag, engine)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        start = time.perf_counter()
        try:
            data = pytesseract.image_to_data(
                img,
                config=TESS_CONFIG,
                lang="eng",
                output_type=pytesseract.Output.DICT,
                timeout=self.timeout_s,
            )
        except RuntimeError as exc:
            if "timeout" in str(exc).lower():
                raise OcrError(ErrorCode.OCR_TIMEOUT, page=0, timeout_s=self.timeout_s) from None
            raise OcrError(ErrorCode.OCR_UNAVAILABLE) from None
        except (pytesseract.TesseractNotFoundError, pytesseract.TesseractError, OSError):
            raise OcrError(ErrorCode.OCR_UNAVAILABLE) from None
        result = parse_data(
            data, img.width, img.height, engine, time.perf_counter() - start, self.word_conf_floor
        )
        self._cache_put(key, result)
        return result
