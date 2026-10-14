"""Draft gold files for the annotators: ``python -m eval.draft_gold`` (TRD section 9).

Runs detection on the real samples and writes ``eval/gold/<file>.jsonl.draft`` (git-ignored)
in the gold format, one line per redacting finding, ``"note": "system-draft"``. The draft
holds offsets and the SHA-256 of the segment text, never the value itself; annotators open
the document, correct the lines (add misses, delete false positives), and save the result
as ``<file>.jsonl``.

Annotation protocol (TRD section 9): annotator A labels from scratch **before** opening the
draft; annotator B reviews A's labels against the draft and the system output and records
disagreements. Items added only after seeing the draft are marked ``"note": "post-draft"``
so the anchoring effect can be reported.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

from cleargate.core.config import REPO_ROOT, load_env_file, load_policy
from cleargate.core.db import MetaStore
from cleargate.ingest.storage import existing_job_dir
from cleargate.pipeline import Pipeline, is_region, load_doc
from eval.harness import REDACTING, make_settings
from eval.run_eval import GOLD_DIR


def main(argv: list[str] | None = None) -> int:
    from tests.conftest import SAMPLE_FILES, find_samples_dir

    del argv
    samples = find_samples_dir()
    if samples is None:
        print("draft_gold: sample files not present (samples/ or Data/)")
        return 2
    load_env_file(REPO_ROOT / ".env")
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cleargate-draft-") as tmp:
        settings = make_settings(Path(tmp))
        store = MetaStore.open(settings.data_dir / "meta.db")
        pipeline = Pipeline(settings, load_policy(), store)
        try:
            batch = pipeline.process_batch([samples / n for n in SAMPLE_FILES])
            for job in batch.jobs:
                jdir = existing_job_dir(settings.data_dir, job.job_id)
                doc, findings = load_doc(pipeline.vault.load_state(jdir))
                segs = {s.segment_id: s for s in doc.segments}
                lines = []
                for f in findings:
                    if f.decision not in REDACTING or is_region(f) or f.segment_id not in segs:
                        continue
                    seg = segs[f.segment_id]
                    loc = seg.locator.model_dump(exclude_none=True, exclude={"bbox"})
                    lines.append(
                        {
                            "doc": job.filename,
                            "locator": loc,
                            "text_sha256": hashlib.sha256(seg.text.encode()).hexdigest(),
                            "start": f.start,
                            "end": f.end,
                            "type": f.entity_type.value,
                            "note": "system-draft",
                        }
                    )
                out = GOLD_DIR / f"{job.filename}.jsonl.draft"
                out.write_text(
                    "".join(json.dumps(x, sort_keys=True) + "\n" for x in lines),
                    encoding="utf-8",
                    newline="\n",
                )
                print(f"draft_gold: {job.filename}: {len(lines)} draft lines")
        finally:
            pipeline.close()
            store.close()
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO_ROOT))
    raise SystemExit(main())
