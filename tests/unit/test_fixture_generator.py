"""The fixture generator is deterministic and its committed output is current."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from tests.fixtures import make_fixtures
from tests.fixtures.manifest import SYNTHETIC


def test_regenerated_manifest_matches_committed(tmp_path: Path) -> None:
    make_fixtures.main(["make_fixtures", str(tmp_path)])
    fresh = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    committed = json.loads((SYNTHETIC / "manifest.json").read_text(encoding="utf-8"))
    assert fresh == committed


def test_regenerated_rasters_are_pixel_identical(tmp_path: Path) -> None:
    make_fixtures.main(["make_fixtures", str(tmp_path)])
    with Image.open(tmp_path / "planted.png") as a, Image.open(SYNTHETIC / "planted.png") as b:
        assert a.tobytes() == b.tobytes()


def test_planted_values_are_invented_and_typed() -> None:
    manifest = json.loads((SYNTHETIC / "manifest.json").read_text(encoding="utf-8"))
    ids = [i["id"] for i in manifest["items"]]
    assert len(ids) == len(set(ids))
    assert {i["channel"] for i in manifest["items"]} <= {"native", "ocr", "metadata", "image-only"}
    assert len(manifest["items"]) >= 60
    assert manifest["regions"]
    assert manifest["decoys"]
