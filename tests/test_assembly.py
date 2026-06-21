"""Tests for assembly.py ffmpeg invocation correctness."""

from pathlib import Path
from unittest.mock import patch

from reelpilot import assembly
from reelpilot.assembly import _escape_ass_path


def test_escape_ass_path_escapes_all_special_chars():
    p = Path("D:/A1 Projects/short-maker/out/file.ass")
    out = assembly._escape_ass_path(p)

    assert "\\:" in out, f"drive colon not escaped: {out!r}"

    space_count = str(p).count(" ")
    escaped_space_count = out.count("\\ ")
    assert escaped_space_count == space_count, (
        f"expected {space_count} escaped spaces, got {escaped_space_count}: {out!r}"
    )

    raw = str(p).replace("\\", "/")
    assert "\\:" not in raw
    colon_positions = [i for i, c in enumerate(raw) if c == ":"]
    for i in colon_positions:
        assert i + 2 <= len(out), f"truncated escaped output: {out!r}"
        assert out[i:i + 2] == "\\:", f"colon at {i} not escaped: {out!r}"

    assert "\\" not in out.replace("\\:", "").replace("\\ ", "").replace(
        "\\,", ""
    ).replace("\\'", "").replace("\\[", "").replace("\\]", "").replace(
        "\\;", ""
    ), f"raw backslashes left in output: {out!r}"


def test_burn_captions_uses_escaped_path_in_filter(tmp_path):
    v = tmp_path / "v.mp4"
    a = tmp_path / "a.m4a"
    v.write_bytes(b"")
    a.write_bytes(b"")

    ass_dir = tmp_path / "sub dir"
    ass_dir.mkdir()
    ass = ass_dir / "captions.ass"
    ass.write_text("[Script Info]\n", encoding="utf-8")

    out = tmp_path / "out.mp4"

    # Pre-create the fake temp ASS file so write_bytes/read_bytes round-trip
    # works without touching the real OS temp dir.
    fake_tmp = tmp_path / "reelpilot_tmp.ass"
    fake_tmp.write_bytes(b"")

    with patch.object(assembly.tempfile, "mkstemp") as mock_mkstemp, \
         patch.object(assembly, "subprocess") as mock_sub, \
         patch.object(assembly.os, "close"):
        mock_mkstemp.return_value = (7, str(fake_tmp))
        try:
            assembly.burn_captions(v, a, ass, out)
        except Exception:
            pass

    assert mock_sub.run.called, "subprocess.run was not invoked"
    cmd = mock_sub.run.call_args[0][0]

    assert "-vf" in cmd, f"-vf not in cmd: {cmd!r}"
    vf_idx = cmd.index("-vf")
    vf_value = cmd[vf_idx + 1]

    # New behavior: the ass= argument should reference the temp copy, NOT
    # the original ass path.
    assert str(ass) not in vf_value, (
        f"original ass path leaked into -vf value: {vf_value!r}"
    )
    assert str(fake_tmp) in vf_value.replace("\\", "/"), (
        f"temp ass path not in -vf value: {vf_value!r}"
    )

    # The temp path must be wrapped in escaped single quotes so ffmpeg 8.x's
    # filter-graph parser treats the whole `ass=` value as one token and
    # doesn't try to split at the `\:` of a Windows drive letter.
    expected_outer = f"\\'{_escape_ass_path(fake_tmp)}\\'"
    assert expected_outer in vf_value, (
        f"escaped-quoted wrapper missing around ass= value: "
        f"expected {expected_outer!r} in {vf_value!r}"
    )
    # Sanity: the value starts with `\'` (opening quote) and ends with `\'`
    # (closing quote) wrapping the ass path.
    ass_seg = vf_value.split("ass=", 1)[1]
    assert ass_seg.startswith("\\'"), (
        f"ass= value missing opening escaped quote: {ass_seg!r}"
    )
    assert ass_seg.endswith("\\'"), (
        f"ass= value missing closing escaped quote: {ass_seg!r}"
    )

    # Temp file cleanup: the fake tmp file we created should have been
    # removed by the try/finally in burn_captions.
    assert not fake_tmp.exists(), "temp ass file was not cleaned up"