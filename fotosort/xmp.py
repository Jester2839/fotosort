"""Zápis hodnocení a klíčových slov pro Lightroom Classic.

RAW (i pár RAW+JPG) dostane sidecar `<název>.xmp` vedle sebe – Lightroom ho při importu načte
pro celý pár. Samotné JPG sidecar ignoruje, proto se XMP vloží přímo do souboru (APP1 segment).

Všechno, co zapíšeme, nese značku `x:xmptk="fotosort"`. Cizí XMP (např. už upravené
v Lightroomu) nikdy nepřepíšeme a undo maže jen to naše.
"""

from __future__ import annotations

import os
from pathlib import Path
from xml.sax.saxutils import escape

from .config import RAW_EXTS

MARK = "fotosort"
_XMP_HEADER = b"http://ns.adobe.com/xap/1.0/\x00"
_MARK_BYTES = f'x:xmptk="{MARK}"'.encode()

Keyword = tuple[str, ...]  # hierarchie, např. ("Fotosort", "Obsah", "Lidi")


def packet(rating: int, keywords: list[Keyword]) -> str:
    flat = sorted({k[-1] for k in keywords})
    hier = ["|".join(k) for k in keywords]
    li = lambda items: "".join(f"<rdf:li>{escape(i)}</rdf:li>" for i in items)  # noqa: E731
    return (
        f'<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="{MARK}">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about=""'
        ' xmlns:xmp="http://ns.adobe.com/xap/1.0/"'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
        ' xmlns:lr="http://ns.adobe.com/lightroom/1.0/"'
        f' xmp:Rating="{int(rating)}">'
        f"<dc:subject><rdf:Bag>{li(flat)}</rdf:Bag></dc:subject>"
        f"<lr:hierarchicalSubject><rdf:Bag>{li(hier)}</rdf:Bag></lr:hierarchicalSubject>"
        "</rdf:Description></rdf:RDF></x:xmpmeta>"
    )


def target(files: list[Path]) -> Path:
    """Kam se XMP zapíše: sidecar k RAW, jinak samotné JPG."""
    raw = next((f for f in files if f.suffix.lower() in RAW_EXTS), None)
    return raw.with_suffix(".xmp") if raw else files[0]


def write(files: list[Path], rating: int, keywords: list[Keyword]) -> Path | None:
    """Zapíše XMP. Vrací cestu, nebo None, když už tam je cizí XMP (nepřepisujeme)."""
    dst = target(files)
    data = packet(rating, keywords)
    if dst.suffix.lower() == ".xmp":
        if dst.exists() and not is_ours(dst):
            return None
        tmp = dst.with_name(dst.name + ".part")
        tmp.write_text('<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>' + data
                       + '<?xpacket end="w"?>', encoding="utf-8")
        os.replace(tmp, dst)
        return dst
    return dst if _jpeg_set(dst, data.encode("utf-8")) else None


def remove(path: Path) -> bool:
    """Odstraní naše XMP (smaže sidecar / vyjme segment z JPG). Cizí nechá být."""
    if not path.exists() or not is_ours(path):
        return False
    if path.suffix.lower() == ".xmp":
        path.unlink()
        return True
    return _jpeg_set(path, None)


def is_ours(path: Path) -> bool:
    if path.suffix.lower() == ".xmp":
        return _MARK_BYTES in path.read_bytes()[:4096]
    seg = _find_xmp(path.read_bytes())
    return seg is not None and seg[2]


# --- JPEG: APP1 segment s XMP ---------------------------------------------------------------

def _segments(data: bytes):
    """(začátek, konec, marker) segmentů hlavičky až po SOS. Data obrazu se nečtou."""
    if data[:2] != b"\xff\xd8":
        raise ValueError("není JPEG")
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            raise ValueError("poškozená hlavička JPEG")
        marker = data[pos + 1]
        if marker == 0xDA:  # SOS – dál už je obraz
            return
        length = int.from_bytes(data[pos + 2:pos + 4], "big")
        yield pos, pos + 2 + length, marker
        pos += 2 + length


def _find_xmp(data: bytes):
    """(začátek, konec, je_náš) prvního XMP segmentu, nebo None."""
    for start, end, marker in _segments(data):
        if marker == 0xE1 and data[start + 4:start + 4 + len(_XMP_HEADER)] == _XMP_HEADER:
            return start, end, _MARK_BYTES in data[start:end]
    return None


def _jpeg_set(path: Path, xmp: bytes | None) -> bool:
    """Vloží/nahradí náš XMP segment (xmp=None ho odstraní). Zachová čas změny souboru."""
    data = path.read_bytes()
    found = _find_xmp(data)
    if found and not found[2]:
        return False  # cizí XMP
    if found:
        data = data[:found[0]] + data[found[1]:]
    if xmp is not None:
        body = _XMP_HEADER + xmp
        if len(body) + 2 > 0xFFFF:
            raise ValueError("XMP je moc velké pro JPEG segment")
        segment = b"\xff\xe1" + (len(body) + 2).to_bytes(2, "big") + body
        # Za APP0 (JFIF) a APP1 (Exif), aby čtečky našly Exif tam, kde ho čekají.
        insert = 2
        for start, end, marker in _segments(data):
            if marker in (0xE0, 0xE1):
                insert = end
            else:
                break
        data = data[:insert] + segment + data[insert:]
    stat = path.stat()
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    return True
