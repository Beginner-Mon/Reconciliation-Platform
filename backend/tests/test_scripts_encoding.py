import codecs
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[2] / "infra" / "scripts"


@pytest.mark.parametrize("script", sorted(SCRIPTS.glob("*.ps1")), ids=lambda p: p.name)
def test_script_co_ky_tu_ngoai_ascii_phai_co_bom(script):
    content = script.read_bytes()
    if any(byte > 127 for byte in content):
        assert content.startswith(codecs.BOM_UTF8), (
            f"{script.name}: script có ký tự ngoài ASCII phải có BOM UTF-8 để PS 5.1 đọc đúng"
        )
        content.decode("utf-8-sig")
