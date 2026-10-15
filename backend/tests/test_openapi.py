"""docs/openapi.yaml phải mô tả ĐÚNG API đang chạy.

Tài liệu API viết tay rất dễ lệch khỏi code mà không ai biết. Các test dưới đây
khoá file đó vào những thứ code đã có sẵn:

- tập đường dẫn phải trùng `ROUTES` trong api/handler.py (test_routes.py đã khoá
  ROUTES với Terraform, nên cũng trùng API Gateway);
- mỗi đường dẫn phải nằm đúng thẻ của miền (Lambda) phục vụ nó;
- các danh sách giá trị (trạng thái, loại chứng từ, engine OCR, quyết định
  duyệt...) phải trùng hằng số trong code;
- phản hồi THẬT của các hàm xử lý, chạy trên AWS giả lập, phải có mã trạng thái
  được khai và thân khớp schema được khai. Trường API trả mà file không liệt kê
  cũng bị bắt, trừ khi schema ghi `additionalProperties: true`.
"""
import json
import pathlib
import re

import yaml

from api import documents, handler, review, views
from common import ocr_engines
from core.rules import SEVERITY_ORDER
from schemas.document import COLUMN_ROLES, DOCUMENT_ROLES
from schemas.registry import DOCUMENT_TYPES

SPEC_FILE = pathlib.Path(__file__).resolve().parents[2] / "docs" / "openapi.yaml"
METHODS = ("get", "post", "put", "patch", "delete")
MIEN = {
    "projects": handler.PROJECT_ROUTES,
    "documents": handler.DOCUMENT_ROUTES,
    "review": handler.REVIEW_ROUTES,
    "anchor": handler.ANCHOR_ROUTES,
    "process": handler.PROCESS_ROUTES,
}
MA_LOI = {"400", "401", "404", "409", "500"}
KIEU = {"string": str, "boolean": bool, "object": dict, "array": list}

P = "/projects/{project_id}"
D = "/projects/{project_id}/documents/{document_id}"
R = "/reconciliations/{reconciliation_id}"


def tai() -> dict:
    return yaml.safe_load(SPEC_FILE.read_text(encoding="utf-8"))


def cac_thao_tac(doc: dict) -> dict:
    """{"POST /projects": (path item, operation), ...}"""
    out = {}
    for path, item in doc["paths"].items():
        for method in METHODS:
            if method in item:
                out[f"{method.upper()} {path}"] = (item, item[method])
    return out


def theo_ref(doc: dict, node):
    """Đi theo `$ref` nội bộ cho tới khi gặp nội dung thật."""
    while isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"]
        assert ref.startswith("#/"), f"chỉ dùng $ref nội bộ: {ref}"
        node = doc
        for part in ref[2:].split("/"):
            assert part in node, f"$ref trỏ tới chỗ không có: {ref}"
            node = node[part]
    return node


def moi_ref(node):
    if isinstance(node, dict):
        if "$ref" in node:
            yield node["$ref"]
        for value in node.values():
            yield from moi_ref(value)
    elif isinstance(node, list):
        for value in node:
            yield from moi_ref(value)


def enum_cua(doc: dict, ten: str) -> set:
    return set(doc["components"]["schemas"][ten]["enum"])


def truong_cua(doc: dict, schema: dict) -> tuple[dict, bool]:
    """Gộp `properties` qua `allOf`. Trả thêm cờ: schema có cho trường lạ không."""
    schema = theo_ref(doc, schema)
    truong = dict(schema.get("properties") or {})
    cho_la = schema.get("additionalProperties") is not None
    for con in schema.get("allOf", []):
        them, la = truong_cua(doc, con)
        truong.update(them)
        cho_la = cho_la or la
    return truong, cho_la


def kiem(doc: dict, schema: dict, gia_tri, duong: str) -> None:
    """Kiểm `gia_tri` theo một schema OpenAPI 3.0, đủ cho những gì file này dùng."""
    schema = theo_ref(doc, schema)
    if gia_tri is None:
        assert schema.get("nullable") is True, f"{duong}: null nhưng schema không cho"
        return
    for con in schema.get("allOf", []):
        kiem_khong_bat_truong_la(doc, con, gia_tri, duong)
    kieu = schema.get("type")
    if kieu in KIEU:
        assert isinstance(gia_tri, KIEU[kieu]), f"{duong}: cần {kieu}, nhận {type(gia_tri).__name__}"
    elif kieu == "integer":
        assert isinstance(gia_tri, int) and not isinstance(gia_tri, bool), f"{duong}: cần integer, nhận {gia_tri!r}"
    elif kieu == "number":
        assert isinstance(gia_tri, (int, float)) and not isinstance(gia_tri, bool), f"{duong}: cần number, nhận {gia_tri!r}"
    if "enum" in schema:
        assert gia_tri in schema["enum"], f"{duong}: {gia_tri!r} không nằm trong {schema['enum']}"
    if isinstance(gia_tri, dict):
        for ten in schema.get("required", []):
            assert ten in gia_tri, f"{duong}: thiếu trường bắt buộc `{ten}`"
        truong, cho_la = truong_cua(doc, schema)
        for ten, v in gia_tri.items():
            if ten in truong:
                kiem(doc, truong[ten], v, f"{duong}.{ten}")
            elif isinstance(schema.get("additionalProperties"), dict):
                kiem(doc, schema["additionalProperties"], v, f"{duong}.{ten}")
            else:
                assert cho_la, f"{duong}: API trả trường `{ten}` mà file OpenAPI không liệt kê"
    if isinstance(gia_tri, list) and "items" in schema:
        for i, v in enumerate(gia_tri):
            kiem(doc, schema["items"], v, f"{duong}[{i}]")


def kiem_khong_bat_truong_la(doc: dict, schema: dict, gia_tri, duong: str) -> None:
    """Một nhánh của `allOf` chỉ thấy một phần trường, nên không tự kết luận trường lạ."""
    schema = theo_ref(doc, schema)
    kiem(doc, {**schema, "additionalProperties": schema.get("additionalProperties", True)}, gia_tri, duong)


def goi(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    event = {
        "requestContext": {"http": {"method": method}},
        "rawPath": path,
        "body": json.dumps(body) if body is not None else None,
    }
    response = handler.lambda_handler(event, None)
    return response["statusCode"], json.loads(response["body"])


class HopDong:
    """Gọi API thật rồi so mã trạng thái và thân phản hồi với file OpenAPI."""

    def __init__(self):
        self.doc = tai()
        self.thao_tac = cac_thao_tac(self.doc)
        self.da_goi = set()

    def goi(self, method: str, mau: str, body: dict | None = None, mong: int | None = None, **tham_so) -> dict:
        status, than = goi(method, mau.format(**tham_so), body)
        khoa = f"{method} {mau}"
        phan_hoi = self.thao_tac[khoa][1]["responses"]
        assert str(status) in phan_hoi, f"{khoa} trả {status} mà file OpenAPI không khai mã này: {than}"
        if mong is not None:
            assert status == mong, f"{khoa}: mong {mong}, nhận {status}: {than}"
        schema = theo_ref(self.doc, phan_hoi[str(status)])["content"]["application/json"]["schema"]
        kiem(self.doc, schema, than, f"{khoa} -> {status}")
        self.da_goi.add(khoa)
        return than


def dat_file(s3_key: str) -> None:
    from common.s3 import BUCKET, get_s3

    get_s3().put_object(Bucket=BUCKET, Key=s3_key, Body=b"%PDF-1.4 " + s3_key.encode())


def danh_dau_da_xu_ly(document_id: str, du_lieu: dict) -> None:
    from common.dynamodb import update_document

    update_document(
        document_id,
        status="VALIDATED",
        step="validate",
        step_status="done",
        document_type=du_lieu["document_type"],
        role=du_lieu["role"],
        extraction=du_lieu,
        validation={"valid": True, "schema_errors": [], "rule_errors": [], "flags": [], "warnings": [], "comparison_incomplete": False},
    )


def bang_hang(don_gia: int) -> list[dict]:
    return [
        {
            "columns": [
                {"header": "Tên hàng", "role": "item_name"},
                {"header": "SL", "role": "quantity"},
                {"header": "Đơn giá", "role": "unit_price"},
            ],
            "rows": [{"Tên hàng": "Laptop Dell XPS", "SL": 100, "Đơn giá": don_gia}],
        }
    ]


DON_HANG = {
    "document_type": "purchase_order", "role": "order", "doc_number": "PO-2026-001",
    "seller": "ABC Technology", "currency": "VND", "total_amount": 125000000, "tables": bang_hang(1250000),
}
HOA_DON = {
    "document_type": "invoice", "role": "billing", "doc_number": "INV-001", "order_reference": "PO-2026-001",
    "seller": "ABC Technology", "currency": "VND", "total_amount": 128000000, "tables": bang_hang(1280000),
}


# ---------------------------------------------------------------- cấu trúc của file


def test_la_openapi_3_va_co_thong_tin_co_ban():
    doc = tai()
    assert str(doc["openapi"]).startswith("3.0")
    assert doc["info"]["title"] and doc["info"]["version"]


def test_khai_dung_tap_route_cua_handler():
    trong_code = {f"{method} {template}" for method, template, _ in handler.ROUTES}
    assert set(cac_thao_tac(tai())) == trong_code
    assert len(trong_code) == 15


def test_moi_route_nam_dung_the_cua_mien_phuc_vu_no():
    thao_tac = cac_thao_tac(tai())
    for mien, routes in MIEN.items():
        for method, template, _ in routes:
            assert thao_tac[f"{method} {template}"][1]["tags"] == [mien], f"{method} {template}"


def test_operation_id_co_du_va_khong_trung():
    ids = [op["operationId"] for _, op in cac_thao_tac(tai()).values()]
    assert len(ids) == len(set(ids)) == 15


def test_tham_so_duong_dan_duoc_khai_du_va_dung():
    doc = tai()
    for khoa, (item, op) in cac_thao_tac(doc).items():
        trong_duong_dan = set(re.findall(r"\{(\w+)\}", khoa))
        khai = [theo_ref(doc, p) for p in (item.get("parameters") or []) + (op.get("parameters") or [])]
        assert {p["name"] for p in khai if p["in"] == "path"} == trong_duong_dan, khoa
        assert all(p["required"] is True for p in khai if p["in"] == "path"), khoa


def test_moi_ref_tro_toi_cho_co_that():
    doc = tai()
    for ref in moi_ref(doc):
        theo_ref(doc, {"$ref": ref})


def test_moi_route_doi_ma_dang_nhap():
    doc = tai()
    assert doc["security"] == [{"bearerAuth": []}]
    scheme = doc["components"]["securitySchemes"]["bearerAuth"]
    assert (scheme["type"], scheme["scheme"]) == ("http", "bearer")
    for khoa, (_, op) in cac_thao_tac(doc).items():
        assert "security" not in op, f"{khoa} không được tự bỏ kiểm đăng nhập"


def test_moi_route_co_phan_hoi_thanh_cong_va_loi_dung_dang():
    doc = tai()
    for khoa, (_, op) in cac_thao_tac(doc).items():
        ma = set(op["responses"])
        assert any(m.startswith("2") for m in ma), khoa
        loi = {m for m in ma if not m.startswith("2")}
        assert loi <= MA_LOI, khoa
        assert {"401", "500"} <= loi, khoa
        for m in loi - {"401"}:
            schema = theo_ref(doc, op["responses"][m])["content"]["application/json"]["schema"]
            assert schema == {"$ref": "#/components/schemas/Error"}, f"{khoa} {m}"


def test_cac_danh_sach_gia_tri_trung_hang_so_trong_code():
    doc = tai()
    schemas = doc["components"]["schemas"]
    assert enum_cua(doc, "DocumentType") == set(DOCUMENT_TYPES)
    assert enum_cua(doc, "DocumentRole") == set(DOCUMENT_ROLES)
    assert enum_cua(doc, "ColumnRole") == set(COLUMN_ROLES)
    assert enum_cua(doc, "Severity") == set(SEVERITY_ORDER)
    assert enum_cua(doc, "OcrEngine") == set(ocr_engines.APP_ENGINES)
    assert enum_cua(doc, "DocumentStatus") == set(views.STATUS_STEPS_DONE) | {"FAILED"}
    assert set(schemas["ReviewRequest"]["properties"]["decision"]["enum"]) == set(review.DECISIONS)
    assert schemas["CreateDocumentsRequest"]["properties"]["files"]["maxItems"] == documents.MAX_FILES_PER_REQUEST
    assert set(schemas["Document"]["properties"]["step"]["enum"]) - {None} == set(views.STEP_SEQUENCE)


def test_schema_Document_co_dung_cac_truong_ma_api_tra():
    truong = set(tai()["components"]["schemas"]["Document"]["properties"])
    assert truong == set(views.DOCUMENT_FIELDS) | {"needs_confirmation", "view_url"}


# ---------------------------------------------------------------- phản hồi thật so với file


def test_phan_hoi_that_cua_ca_15_route_khop_file_openapi(aws, started_executions):
    hd = HopDong()

    du_an = hd.goi("POST", "/projects", {"name": "Hợp đồng API"}, mong=201)
    pid = du_an["project_id"]
    hd.goi("POST", "/projects", {}, mong=400)
    hd.goi("GET", "/projects", mong=200)
    hd.goi("GET", P, mong=404, project_id="prj-khong-co")

    tao = hd.goi("POST", P + "/documents", {"files": [{"file_name": "po.pdf"}, {"file_name": "hd.pdf"}]}, mong=201, project_id=pid)
    hd.goi("POST", P + "/documents", {"files": []}, mong=400, project_id=pid)
    did = tao["documents"][0]["document_id"]
    hd.goi("GET", P + "/documents", mong=200, project_id=pid)
    hd.goi("GET", P, mong=200, project_id=pid)
    hd.goi("GET", D + "/ocr", mong=404, project_id=pid, document_id=did)

    hd.goi("PATCH", D, {}, mong=400, project_id=pid, document_id=did)
    hd.goi("PUT", P + "/anchor", {}, mong=400, project_id=pid)
    hd.goi("POST", P + "/process/stop", mong=409, project_id=pid)
    hd.goi("POST", P + "/process", mong=400, project_id=pid)  # file chưa được tải lên S3

    doi_chieu = hd.goi("POST", P + "/reconcile", mong=200, project_id=pid)
    rid = doi_chieu["reconciliation_id"]
    hd.goi("GET", R, mong=200, reconciliation_id=rid)
    hd.goi("GET", R, mong=404, reconciliation_id="rec-khong-co")
    hd.goi("POST", R + "/review", {"decision": "CHO_QUA"}, mong=400, reconciliation_id=rid)
    hd.goi("POST", R + "/review", {"decision": "APPROVED"}, mong=409, reconciliation_id=rid)  # không so chứng từ nào

    for muc in tao["documents"]:
        dat_file(muc["s3_key"])
    bat_dau = hd.goi("POST", P + "/process", mong=202, project_id=pid)
    hd.goi("GET", P, mong=200, project_id=pid)  # lúc này có `run`
    hd.goi("POST", P + "/process", mong=409, project_id=pid)  # đang có lượt chạy
    hd.goi("DELETE", D, mong=409, project_id=pid, document_id=did)
    hd.goi("DELETE", P, mong=409, project_id=pid)
    dung = hd.goi("POST", P + "/process/stop", mong=202, project_id=pid)
    assert dung["status"] == "STOPPING"

    # Lượt bị dừng kết thúc ở bước đối chiếu của luồng; gọi thẳng worker để mở khoá project.
    from workers.reconcile import lambda_handler as ket_thuc_luot

    ket_thuc_luot({"project_id": pid, "run_id": bat_dau["run_id"]}, None)
    hd.goi("DELETE", D, mong=200, project_id=pid, document_id=did)
    hd.goi("DELETE", P, mong=200, project_id=pid)

    con_thieu = set(hd.thao_tac) - hd.da_goi
    assert not con_thieu, "còn route chưa được gọi thử: " + ", ".join(sorted(con_thieu))


def test_phan_hoi_that_cua_luong_sua_va_duyet_khop_file_openapi(aws):
    hd = HopDong()
    pid = hd.goi("POST", "/projects", {"name": "Luồng duyệt"}, mong=201)["project_id"]
    tao = hd.goi("POST", P + "/documents", {"files": [{"file_name": "po.pdf"}, {"file_name": "hd.pdf"}]}, mong=201, project_id=pid)
    po, hoa_don = (muc["document_id"] for muc in tao["documents"])
    danh_dau_da_xu_ly(po, DON_HANG)
    danh_dau_da_xu_ly(hoa_don, HOA_DON)

    hd.goi("PATCH", D, {"fields": {"buyer": "Công ty TNHH XYZ"}}, mong=200, project_id=pid, document_id=hoa_don)
    hd.goi("PATCH", D, {"fields": {"document_type": "invoice"}}, mong=400, project_id=pid, document_id=hoa_don)
    hd.goi("PUT", P + "/anchor", {"document_id": po}, mong=200, project_id=pid)
    hd.goi("PUT", P + "/anchor", {"document_id": "doc-khong-co"}, mong=404, project_id=pid)

    rid = hd.goi("POST", P + "/reconcile", mong=200, project_id=pid)["reconciliation_id"]
    chi_tiet = hd.goi("GET", R, mong=200, reconciliation_id=rid)
    assert chi_tiet["discrepancies"], "hai chứng từ lệch tiền và đơn giá, phải có mâu thuẫn để kiểm schema Discrepancy"
    hd.goi("GET", P, mong=200, project_id=pid)  # lúc này có `latest_reconciliation`

    hd.goi("POST", R + "/review", {"decision": "REJECTED", "comment": "lệch tiền"}, mong=200, reconciliation_id=rid)
    hd.goi("POST", R + "/review", {"decision": "APPROVED"}, mong=409, reconciliation_id=rid)  # đã có quyết định

    hd.goi("POST", P + "/process", mong=200, project_id=pid)  # không còn gì để xử lý, chỉ đối chiếu lại
