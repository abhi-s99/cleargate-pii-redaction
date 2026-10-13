"""Draw detected regions for human review: python scripts/show_regions.py FILE [--out DIR]

Writes one PNG per PDF page or embedded image that has regions, with face boxes in red
and unreadable regions in orange, to ``out/regions/<file stem>/`` (git-ignored). This is
a local review aid for the team: the images contain document content, so they stay in
``out/`` and are never committed or shared.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from cleargate.core.config import load_env_file, load_policy, load_settings  # noqa: E402
from cleargate.extract.image import open_image  # noqa: E402
from cleargate.ingest.validator import validate  # noqa: E402
from cleargate.pipeline import JobContext, default_stages  # noqa: E402

COLOURS = {"face": (220, 0, 0), "unreadable": (255, 140, 0)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "out" / "regions")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env")
    settings = load_settings()
    settings = settings.model_copy(update={"data_dir": ROOT / "out" / "smoke-data"})
    policy = load_policy(settings.policy_path)
    vf = validate(args.file, policy.limits)
    with tempfile.TemporaryDirectory() as tmp:
        ctx = JobContext("regions", "none", Path(tmp), policy, "", settings, None)  # type: ignore[arg-type]
        doc = default_stages().extractor_for(vf.fmt).extract(args.file, vf.fmt, ctx)
    out = args.out / args.file.stem
    out.mkdir(parents=True, exist_ok=True)
    by_target: dict[tuple[str, int | None], list[object]] = {}
    for region in doc.regions:
        by_target.setdefault((region.locator.part, region.locator.page), []).append(region)
    written = 0
    for (part, page), regions in sorted(
        by_target.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0)
    ):
        if part == "page" and page:
            with pymupdf.open(args.file) as pdf:
                pix = pdf[page - 1].get_pixmap(dpi=policy.ocr.dpi, alpha=False)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            name = f"page-{page:02d}.png"
        else:
            with zipfile.ZipFile(args.file) as zf:
                img = open_image(zf.read(part)).convert("RGB")
            name = part.replace("/", "_") + ".png"
        draw = ImageDraw.Draw(img)
        for r in regions:
            box = r.locator.bbox  # type: ignore[attr-defined]
            draw.rectangle(box, outline=COLOURS[r.kind], width=6)  # type: ignore[attr-defined]
        img.save(out / name)
        written += 1
        print(
            f"{name}: "
            + ", ".join(
                f"{r.kind}(area={r.area_ratio:.3f}, conf={r.mean_conf}, words={r.word_count})"  # type: ignore[attr-defined]
                for r in regions
            )
        )
    print(f"show_regions: wrote {written} image(s) to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
