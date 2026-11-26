"""Vyrobí falešnou kartu Sony a6700 pro testy."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image


def _image_with_date(path: Path, taken: datetime, fmt: str) -> None:
    img = Image.new("RGB", (64, 48), (120, 90, 60))
    exif = img.getexif()
    stamp = taken.strftime("%Y:%m:%d %H:%M:%S")
    if fmt == "TIFF":  # Pillow do TIFFu EXIF sub-IFD nezapíše; IFD0 DateTime stačí na test
        img.save(path, fmt, tiffinfo={306: stamp})
        return
    exif.get_ifd(0x8769)[0x9003] = stamp  # DateTimeOriginal
    img.save(path, fmt, exif=exif)


def add_photo(card: Path, number: int, taken: datetime, raw: bool = True, jpg: bool = True) -> None:
    folder = card / "DCIM" / "100MSDCF"
    folder.mkdir(parents=True, exist_ok=True)
    if raw:  # ARW je TIFF, pro EXIF test stačí
        _image_with_date(folder / f"DSC{number:05d}.ARW", taken, "TIFF")
    if jpg:
        _image_with_date(folder / f"DSC{number:05d}.JPG", taken, "JPEG")


def add_video(card: Path, number: int, taken: datetime) -> None:
    folder = card / "PRIVATE" / "M4ROOT" / "CLIP"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"C{number:04d}.MP4").write_bytes(b"\x00" * 2048)
    (folder / f"C{number:04d}M01.XML").write_text(
        f'<NonRealTimeMeta><CreationDate value="{taken.isoformat()}+02:00"/></NonRealTimeMeta>',
        encoding="utf-8",
    )
