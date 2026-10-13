"""Format-native redaction writers and the dispatcher the pipeline uses."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cleargate.core.errors import ErrorCode, RedactionError
from cleargate.core.models import Document, FileFormat, Finding


class FormatWriter:
    """Dispatch to the DOCX, PPTX, PDF or image writer by document format."""

    name = "format-writer"
    version = "0.6.0"

    def __init__(self) -> None:
        from cleargate.redact.writers.docx import DocxWriter
        from cleargate.redact.writers.image import ImageWriter
        from cleargate.redact.writers.pdf import PdfWriter
        from cleargate.redact.writers.pptx import PptxWriter

        self.by_fmt: dict[FileFormat, Any] = {
            FileFormat.DOCX: DocxWriter(),
            FileFormat.PPTX: PptxWriter(),
            FileFormat.PDF: PdfWriter(),
            FileFormat.PNG: ImageWriter(),
            FileFormat.JPEG: ImageWriter(),
            FileFormat.TIFF: ImageWriter(),
        }

    def versions(self) -> dict[str, str]:
        return {w.name: w.version for w in self.by_fmt.values()}

    def apply(
        self, src: Path, doc: Document, findings: list[Finding], out_dir: Path, ctx: Any
    ) -> Any:
        writer = self.by_fmt.get(doc.fmt)
        if writer is None:
            raise RedactionError(ErrorCode.REDACTION_FAILED, count=len(findings))
        return writer.apply(src, doc, findings, out_dir, ctx)

    def repair(
        self, path: Path, fmt: FileFormat, boxes: dict[tuple[str, Any], list[Any]], ctx: Any
    ) -> int:
        """Burn extra boxes that V2 located in output rasters (ADR-30). Returns boxes burned."""
        from cleargate.redact.writers.repair import repair_output

        return repair_output(path, fmt, boxes, ctx)
