"""Đổi chứng từ gốc phải đối chiếu lại NGAY với gốc mới.

`PUT /anchor` lưu gốc rồi gọi đối chiếu. `api/anchor.py` từng import
`invoke_reconcile` trong thân hàm, nên dev server và test không vá được: lời gọi
rơi vào Lambda thật, ném lỗi, lỗi bị nuốt, API vẫn trả 200 và giao diện vẫn hiện
gốc cũ.
"""

import importlib
import pathlib
import re

from common import reconcile_client
from test_openapi import DON_HANG, HOA_DON, danh_dau_da_xu_ly, goi

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def module_api_goi_doi_chieu() -> list[str]:
    return sorted(
        f"api.{p.stem}"
        for p in (BACKEND / "api").glob("*.py")
        if "invoke_reconcile" in p.read_text(encoding="utf-8")
    )


def test_doi_goc_thi_doi_chieu_lai_ngay_voi_goc_moi(aws):
    _, du_an = goi("POST", "/projects", {"name": "Đổi gốc"})
    pid = du_an["project_id"]
    _, tao = goi("POST", f"/projects/{pid}/documents", {"files": [{"file_name": "po.pdf"}, {"file_name": "hd.pdf"}]})
    po, hoa_don = (muc["document_id"] for muc in tao["documents"])
    danh_dau_da_xu_ly(po, DON_HANG)
    danh_dau_da_xu_ly(hoa_don, HOA_DON)

    _, cu = goi("POST", f"/projects/{pid}/reconcile")
    assert cu["groups"][0]["anchor_document_id"] == po

    status, than = goi("PUT", f"/projects/{pid}/anchor", {"document_id": hoa_don})
    assert status == 200
    moi = than["reconciliation"]
    assert moi is not None, "đổi gốc phải trả lượt đối chiếu mới, không phải null"
    assert moi["reconciliation_id"] != cu["reconciliation_id"]
    assert moi["groups"][0]["anchor_document_id"] == hoa_don

    _, chi_tiet = goi("GET", f"/projects/{pid}")
    assert chi_tiet["latest_reconciliation"]["reconciliation_id"] == moi["reconciliation_id"]
    assert chi_tiet["latest_reconciliation"]["is_stale"] is False


def test_moi_module_api_goi_doi_chieu_deu_duoc_test_va():
    for ten in module_api_goi_doi_chieu():
        module = importlib.import_module(ten)
        assert hasattr(module, "invoke_reconcile"), (
            f"{ten} phải import invoke_reconcile ở MỨC MODULE; import trong thân hàm thì test và dev server không vá được"
        )
        assert module.invoke_reconcile is not reconcile_client.invoke_reconcile, (
            f"{ten}.invoke_reconcile chưa được vá — thêm {ten!r} vào doi_chieu_tai_cho trong tests/conftest.py"
        )


def test_dev_server_va_doi_chieu_o_moi_module_api_goi_no():
    nguon = (BACKEND / "devserver" / "pipeline.py").read_text(encoding="utf-8")
    dong = re.search(r"for module in \(([^)]*)\):\n\s+module\.invoke_reconcile = invoke_reconcile", nguon)
    assert dong, "không thấy vòng vá invoke_reconcile trong devserver/pipeline.py"
    da_va = {ten.strip() for ten in dong.group(1).split(",") if ten.strip()}
    for ten in module_api_goi_doi_chieu():
        bien = re.search(rf"import {re.escape(ten)} as (\w+)", nguon)
        assert bien and bien.group(1) in da_va, (
            f"devserver/pipeline.py chưa vá invoke_reconcile của {ten}: đổi gốc, xoá chứng từ hay đối chiếu sẽ gọi Lambda thật"
        )
