"""Render source/result page pairs for human visual review of a corpus run."""

from __future__ import annotations

import argparse
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageOps

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def main() -> int:
    """Render every corpus session into one labelled before/after image per page."""
    arguments = _parse_arguments()
    for session_dir in sorted(path for path in arguments.corpus_dir.iterdir() if path.is_dir()):
        sources = list(session_dir.glob("source.*"))
        result = session_dir / "anonymized.pdf"
        if len(sources) != 1 or not result.is_file():
            continue
        before_pages = _render(sources[0])
        after_pages = _render(result)
        if len(before_pages) != len(after_pages):
            raise ValueError(f"Different page counts in {session_dir.name}.")
        review_dir = session_dir / "review"
        review_dir.mkdir(exist_ok=True)
        for page_number, (before, after) in enumerate(zip(before_pages, after_pages, strict=True), start=1):
            _write_pair(before, after, review_dir / f"page-{page_number:03}.png", session_dir.name)
    return 0


def _render(path: Path) -> list[Image.Image]:
    if path.suffix.lower() in _IMAGE_SUFFIXES:
        with Image.open(path) as image:
            return [ImageOps.exif_transpose(image).convert("RGB")]
    document = pdfium.PdfDocument(str(path))
    try:
        return [document[index].render(scale=1).to_pil().convert("RGB") for index in range(len(document))]
    finally:
        document.close()


def _write_pair(before: Image.Image, after: Image.Image, destination: Path, title: str) -> None:
    target_height = max(before.height, after.height)
    before.thumbnail((1200, target_height))
    after.thumbnail((1200, target_height))
    header = 46
    canvas = Image.new("RGB", (before.width + after.width + 12, target_height + header), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((12, 12), f"{title}: до", fill="black")
    draw.text((before.width + 24, 12), "после", fill="black")
    canvas.paste(before, (0, header))
    canvas.paste(after, (before.width + 12, header))
    canvas.save(destination)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-dir", type=Path, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
