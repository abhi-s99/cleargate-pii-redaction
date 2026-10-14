"""ClearGate command line (Typer).

    cleargate process FILE... [--policy P] [--data-dir D] [--json]
    cleargate status ID            (a batch id or a job id)
    cleargate extract FILE --dump [--show-text]
    cleargate serve [--host H] [--port P]      (API + the built web UI, Phase 8)

Output carries ids, states, rules, counts and timings. Document text is printed
only by ``extract --show-text``, which is meant for local debugging.
Secrets come from the environment or a local ``.env`` (``make keys``).
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Annotated

import typer

from cleargate.core.config import (
    REPO_ROOT,
    Settings,
    load_env_file,
    load_policy,
    load_settings,
)
from cleargate.core.db import MetaStore
from cleargate.core.errors import ClearGateError
from cleargate.core.logging import configure_logging
from cleargate.core.models import Document
from cleargate.ingest.validator import validate
from cleargate.pipeline import JobContext, Pipeline, default_stages

app = typer.Typer(add_completion=False, no_args_is_help=True, help="ClearGate privacy gate")

PolicyOpt = Annotated[Path | None, typer.Option("--policy", help="policy YAML")]
DataDirOpt = Annotated[Path | None, typer.Option("--data-dir", help="job storage dir")]


def _settings(data_dir: Path | None) -> Settings:
    load_env_file(Path.cwd() / ".env")
    load_env_file(REPO_ROOT / ".env")
    settings = load_settings()
    if data_dir is not None:
        settings = settings.model_copy(update={"data_dir": data_dir})
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings


def _store(settings: Settings) -> MetaStore:
    return MetaStore.open(settings.data_dir / "meta.db")


def _die(exc: ClearGateError) -> None:
    typer.echo(f"error: {exc}", err=True)
    raise typer.Exit(2)


@app.command()
def process(
    files: Annotated[list[Path], typer.Argument(exists=True, dir_okay=False, readable=True)],
    policy: PolicyOpt = None,
    data_dir: DataDirOpt = None,
    as_json: Annotated[bool, typer.Option("--json", help="machine-readable output")] = False,
) -> None:
    """Validate and process files as one batch; print one line per job."""
    configure_logging(stream=sys.stderr)
    try:
        settings = _settings(data_dir)
        pol = load_policy(policy or settings.policy_path)
        store = _store(settings)
        pipeline = Pipeline(settings, pol, store)
        batch = pipeline.process_batch(files)
    except ClearGateError as exc:
        _die(exc)
        return
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "batch_id": batch.batch_id,
                    "jobs": [{**vars(j), "state": j.state.value} for j in batch.jobs],
                },
                indent=2,
            )
        )
        return
    typer.echo(f"batch {batch.batch_id}")
    for j in batch.jobs:
        total = sum(j.timings.values())
        typer.echo(
            f"  {j.job_id}  {j.state.value:<15} {j.rule:<6} {j.reason}  [{j.filename}] {total:.2f}s"
        )


@app.command()
def status(
    ident: Annotated[str, typer.Argument(help="batch id or job id")],
    data_dir: DataDirOpt = None,
) -> None:
    """Show the state and history of a job, or every job in a batch."""
    store = _store(_settings(data_dir))
    rows = store.conn.execute(
        "SELECT job_id FROM jobs WHERE job_id = ? OR batch_id = ? ORDER BY created_at",
        (ident, ident),
    ).fetchall()
    if not rows:
        typer.echo(f"no job or batch {ident}", err=True)
        raise typer.Exit(1)
    for (job_id,) in rows:
        job = store.get_job(job_id)
        assert job is not None
        typer.echo(f"{job_id}  {job['state']}  rule={job['rule']}  [{job['filename']}]")
        for h in store.history(job_id):
            typer.echo(
                f"    {h['created_at']}  {h['from_state']} -> {h['to_state']}"
                f"  {h['rule']}  {h['reason']}"
            )


def dump(doc: Document, show_text: bool) -> str:
    """Structural summary of an extraction; text only when asked."""
    kinds: dict[str, int] = {}
    methods: dict[str, int] = {}
    for s in doc.segments:
        kinds[s.kind] = kinds.get(s.kind, 0) + 1
        methods[s.method] = methods.get(s.method, 0) + 1
    cov = doc.coverage
    lines = [
        f"file: {doc.filename}  format: {doc.fmt.value}  size: {doc.size_bytes} bytes",
        f"units: {json.dumps(doc.units, sort_keys=True)}",
        f"segments: {len(doc.segments)}  by kind: {json.dumps(kinds, sort_keys=True)}"
        f"  by method: {json.dumps(methods, sort_keys=True)}",
        f"coverage: {cov.parts_inspected}/{cov.parts_total} parts inspected,"
        f" {cov.parts_masked} masked, {len(cov.uninspected)} uninspected",
    ]
    codes: dict[str, int] = {}
    for issue in cov.issues:
        codes[issue.code] = codes.get(issue.code, 0) + 1
    if codes:
        lines.append(f"uninspected by code: {json.dumps(codes, sort_keys=True)}")
    extra = getattr(doc, "regions", None)
    if extra:
        by_kind: dict[str, int] = {}
        for r in extra:
            by_kind[r.kind] = by_kind.get(r.kind, 0) + 1
        lines.append(f"regions: {json.dumps(by_kind, sort_keys=True)}")
    if show_text:
        lines.append("--- text (local debugging only) ---")
        lines.extend(
            f"[{s.order_index}] {s.kind} {s.locator.model_dump(exclude_none=True)}: {s.text}"
            for s in sorted(doc.segments, key=lambda s: s.order_index)
        )
    return "\n".join(lines)


@app.command()
def extract(
    file: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    dump_flag: Annotated[bool, typer.Option("--dump", help="print a structural summary")] = True,
    show_text: Annotated[
        bool, typer.Option("--show-text", help="also print extracted text")
    ] = False,
    policy: PolicyOpt = None,
    data_dir: DataDirOpt = None,
) -> None:
    """Run validation and extraction only (no gate decision)."""
    configure_logging(stream=sys.stderr)
    settings = _settings(data_dir)
    try:
        pol = load_policy(policy or settings.policy_path)
        vf = validate(file, pol.limits)
        with tempfile.TemporaryDirectory(prefix="cg-extract-") as tmp:
            ctx = JobContext(
                job_id="extract-local",
                batch_id="none",
                job_dir=Path(tmp),
                policy=pol,
                policy_hash="",
                settings=settings,
                store=_store(settings),
            )
            with ctx.stage("extract"):
                doc = default_stages().extractor_for(vf.fmt).extract(vf.path, vf.fmt, ctx)
    except ClearGateError as exc:
        _die(exc)
        return
    if dump_flag:
        typer.echo(dump(doc, show_text))
        typer.echo(f"timings: {json.dumps(ctx.timings)}")


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="bind address")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="port")] = 8000,
    data_dir: DataDirOpt = None,
) -> None:
    """Run the API (and the web UI when cleargate-ui/dist exists)."""
    import uvicorn

    from cleargate.api.main import create_app

    configure_logging()
    try:
        api = create_app(_settings(data_dir))
    except ClearGateError as exc:
        _die(exc)
    typer.echo(f"ClearGate on http://{host}:{port} (API under /api/v1)")
    uvicorn.run(api, host=host, port=port, log_level="warning")


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
