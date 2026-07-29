"""Static regression checks for the IR-only Web annotation timeline."""

from pathlib import Path


HTML = (
    Path(__file__).resolve().parent.parent
    / "web_server"
    / "static"
    / "annotate.html"
).read_text(encoding="utf-8")


def test_navigation_is_hard_wired_to_ir():
    assert "function navIR(d){var imgs=camImgs.IR||[]" in HTML
    assert "showCam('IR')" in HTML
    assert "function navIR(d){navCur(d);}" not in HTML
    assert "camImgs[camKey]" not in HTML


def test_visible_images_only_update_from_timestamp_match():
    assert "IR is the sole timeline" in HTML
    assert "/api/browse/match" in HTML
    assert "token!==frameRequestToken" in HTML
    assert "loadAnn(md.ir.ts,token)" in HTML
