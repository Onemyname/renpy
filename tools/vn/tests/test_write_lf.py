"""write_text_lf (repo.py): на любой ОС в файл уходит LF — .gitattributes требует
LF, и голый Path.write_text на Windows давал фантомные диффы (аудит 2026-08-21)."""

from vn.repo import write_text_lf


def test_write_text_lf_never_emits_crlf(tmp_path):
    p = tmp_path / "x.json"
    write_text_lf(p, '{\n "a": 1\n}\n')
    raw = p.read_bytes()
    assert b"\r" not in raw
    assert raw.endswith(b"}\n")
