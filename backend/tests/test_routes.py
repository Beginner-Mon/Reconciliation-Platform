"""Bảng định tuyến nằm ở HAI nơi và bắt buộc phải trùng khít.

`local.api_routes` trong infra/modules/aws/main.tf quyết định API Gateway gọi
Lambda nào; bốn danh sách trong api/handler.py quyết định Lambda đó chạy hàm nào.
Lệch một bên là 404 khó truy:

  - khai bên Python mà quên Terraform  -> API Gateway 404, Lambda không hề chạy
  - khai bên Terraform mà quên Python  -> Lambda chạy rồi trả 404 từ handler
  - xếp route vào SAI miền             -> Lambda nhận request nhưng không có route,
                                          và tệ hơn: có thể được cấp quyền thừa

Không có gì khác bắt được mấy lỗi này trước khi deploy. Test này đọc thẳng
main.tf và khoá lại — cùng cách devserver/pipeline.py đọc statemachine.asl.json
và test_devserver.py khoá nó.
"""

import json
import pathlib
import re

import pytest

from api import handler

MAIN_TF = (
    pathlib.Path(__file__).resolve().parents[2]
    / "infra"
    / "modules"
    / "aws"
    / "main.tf"
)

ROUTES_BY_DOMAIN = {
    "projects": handler.PROJECT_ROUTES,
    "documents": handler.DOCUMENT_ROUTES,
    "review": handler.REVIEW_ROUTES,
    "anchor": handler.ANCHOR_ROUTES,
    "process": handler.PROCESS_ROUTES,
}


def _hcl_block(text: str, name: str) -> str:
    """Cắt thân của block `<name> = { ... }`.

    Đếm ngoặc nhưng BỎ QUA ngoặc nằm trong chuỗi: route key chứa `{project_id}`
    nên đếm ngây thơ sẽ cắt nhầm ngay dòng đầu tiên.
    """
    marker = f"{name} = {{"
    start = text.index(marker) + len(marker)
    depth = 1
    in_string = False
    for index in range(start, len(text)):
        char = text[index]
        if char == '"':
            in_string = not in_string
        elif not in_string:
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start:index]
    raise AssertionError(f"Không tìm thấy block `{name}` trong main.tf")


def terraform_routes() -> dict[str, str]:
    block = _hcl_block(MAIN_TF.read_text(encoding="utf-8"), "api_routes")
    return dict(re.findall(r'"([^"]+)"\s*=\s*"(\w+)"', block))


def terraform_function_handlers() -> dict[str, str]:
    block = _hcl_block(MAIN_TF.read_text(encoding="utf-8"), "api_functions")
    handlers = {}
    for domain in re.findall(r"^\s{4}(\w+) = \{", block, re.M):
        inner = _hcl_block(block, domain)
        handlers[domain] = re.search(r'handler\s*=\s*"([^"]+)"', inner).group(1)
    return handlers


def route_keys(routes: list) -> set[str]:
    return {f"{method} {template}" for method, template, _ in routes}


def test_bon_mien_gop_lai_dung_bang_ROUTES():
    gop = [route for routes in ROUTES_BY_DOMAIN.values() for route in routes]
    assert len(gop) == len(handler.ROUTES)
    assert route_keys(gop) == route_keys(handler.ROUTES)


def test_khong_route_nao_nam_o_hai_mien():
    gop = [route for routes in ROUTES_BY_DOMAIN.values() for route in routes]
    keys = [f"{method} {template}" for method, template, _ in gop]
    trung = {key for key in keys if keys.count(key) > 1}
    assert not trung, f"Route nằm ở nhiều miền: {trung}"


def test_terraform_va_python_khai_cung_mot_tap_route():
    tf = set(terraform_routes())
    py = route_keys(handler.ROUTES)
    assert tf == py, (
        f"Chỉ có trong main.tf: {tf - py}\n"
        f"Chỉ có trong handler.py: {py - tf}"
    )


def test_moi_route_duoc_xep_dung_mien_o_ca_hai_noi():
    lech = {}
    for route_key, tf_domain in terraform_routes().items():
        py_domain = next(
            domain
            for domain, routes in ROUTES_BY_DOMAIN.items()
            if route_key in route_keys(routes)
        )
        if py_domain != tf_domain:
            lech[route_key] = f"main.tf={tf_domain} nhưng handler.py={py_domain}"
    assert not lech, lech


def test_moi_function_trong_terraform_tro_toi_handler_co_that():
    handlers = terraform_function_handlers()
    assert set(handlers) == set(ROUTES_BY_DOMAIN), (
        f"local.api_functions khai {set(handlers)}, "
        f"handler.py có {set(ROUTES_BY_DOMAIN)}"
    )
    for domain, dotted in handlers.items():
        assert dotted == f"api.handler.{domain}_handler", (
            f"Miền {domain} trỏ tới {dotted} — sai quy ước đặt tên"
        )
        assert callable(getattr(handler, f"{domain}_handler"))


def test_chi_process_project_goi_step_functions():
    """`states:StartExecution` là quyền tiêu tiền AI — chỉ `process_project` gọi nó.

    Miền `process` có thêm route dừng run, nhưng route đó chỉ đặt cờ trong
    DynamoDB. Thêm route vào PROCESS_ROUTES nghĩa là thêm code chạy dưới role có
    quyền StartExecution. Nếu có lý do thật thì sửa test này, nhưng phải là
    quyết định có ý thức.
    """
    import inspect

    from api import process

    assert route_keys(handler.PROCESS_ROUTES) == {
        "POST /projects/{project_id}/process",
        "POST /projects/{project_id}/process/stop",
    }
    assert "start_execution" not in inspect.getsource(process.stop_processing)


@pytest.mark.parametrize("domain", list(ROUTES_BY_DOMAIN))
def test_handler_cua_mien_tu_choi_route_ngoai_mien(domain):
    """Cô lập thật, không chỉ khai báo trên giấy.

    Định tuyến xảy ra TRƯỚC khi handler nghiệp vụ chạy, nên test này không cần
    AWS giả lập.
    """
    domain_handler = getattr(handler, f"{domain}_handler")
    ngoai_mien = [
        route
        for other, routes in ROUTES_BY_DOMAIN.items()
        if other != domain
        for route in routes
    ]

    for method, template, _ in ngoai_mien:
        # Thay {param} bằng giá trị bất kỳ để tạo path thật.
        path = re.sub(r"\{[^}]+\}", "x", template)
        response = domain_handler(
            {"requestContext": {"http": {"method": method}}, "rawPath": path, "body": None},
            None,
        )
        assert response["statusCode"] == 404, (
            f"{domain}_handler KHÔNG được phục vụ {method} {path}"
        )
        assert "Không có route" in json.loads(response["body"])["error"]


# --- Biến môi trường mà engine OCR cần phải có mặt trong Lambda -------------


def terraform_lambda_env() -> set[str]:
    block = _hcl_block(MAIN_TF.read_text(encoding="utf-8"), "lambda_env")
    return set(re.findall(r"^\s*(\w+)\s*=", block, re.M))


def test_gemini_api_key_khong_nam_dang_chu_thuong_trong_lambda_env():
    """GEMINI_API_KEY chữ thường lọt vào env của cả 10 Lambda là lộ bí mật.

    Key phải qua Secrets Manager (GEMINI_API_KEY_SECRET), code đọc lúc chạy.
    """
    assert "GEMINI_API_KEY" not in terraform_lambda_env()
    assert "GEMINI_API_KEY_SECRET" in terraform_lambda_env()


def test_moi_engine_app_cho_chon_deu_co_du_env_tren_lambda():
    """Giao diện cho chọn engine nào thì Lambda phải chạy được engine đó.

    Lỗi đã có thật: `APP_ENGINES` gồm `dococr` (cần `DOCAI_OCR_PROCESSOR_ID`)
    nhưng `lambda_env` chỉ truyền `DOCAI_PROCESSOR_ID` của Form Parser — engine
    mà app KHÔNG còn cho chọn. Deploy xong, bấm "Chạy lại với Document AI" là nổ
    "Thiếu DOCAI_PROJECT / DOCAI_PROCESSOR_ID" ngay trên production.

    Không test nào khác bắt được: pytest chạy offline nên không đọc Terraform,
    còn `terraform validate` không biết gì về registry engine bên Python.
    """
    from common import ocr_engines

    env_tren_lambda = terraform_lambda_env()

    thieu = {}
    for name in ocr_engines.APP_ENGINES:
        spec = ocr_engines.ENGINES[name]
        can = [spec["processor_env"]] if spec["processor_env"] else []
        if spec["cloud"] == "google":
            can.append("DOCAI_PROJECT")
        con_thieu = [bien for bien in can if bien not in env_tren_lambda]
        if con_thieu:
            thieu[name] = con_thieu

    assert not thieu, (
        f"engine app cho chọn nhưng Lambda thiếu biến môi trường: {thieu}. "
        f"Thêm vào `local.lambda_env` trong infra/modules/aws/main.tf."
    )


# --- Danh sách engine khai cứng bên frontend phải khớp APP_ENGINES ----------

FORMAT_TS = (
    pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "format.ts"
)


def test_frontend_khai_dung_bo_engine_ma_server_chap_nhan():
    """Bỏ `GET /ocr-engines` thì hai bên không còn tự đồng bộ nữa.

    Hai hằng số tĩnh không đáng một endpoint, nhưng đổi lại phải có test này:
    frontend khai cứng tên engine, server chỉ nhận đúng `APP_ENGINES`. Lệch một
    tên là menu hiện một lựa chọn mà bấm vào chắc chắn 400.

    Chỉ khoá TÊN. Nhãn hiển thị bên TS được phép khác `note` trong registry —
    một bên viết cho người đọc, một bên là mô tả kỹ thuật.
    """
    from common import ocr_engines

    nguon = FORMAT_TS.read_text(encoding="utf-8")
    khoi = _hcl_block_ts(nguon, "OCR_ENGINES")
    ten_frontend = re.findall(r'name:\s*"([^"]+)"', khoi)

    assert ten_frontend == list(ocr_engines.APP_ENGINES), (
        f"frontend khai {ten_frontend}, server nhận {list(ocr_engines.APP_ENGINES)}"
    )


def test_frontend_canh_bao_dung_engine_khong_ho_tro_tieng_viet():
    """Cảnh báo sai chỗ còn tệ hơn không có: người dùng chọn nhầm engine mất dấu
    cho chứng từ tiếng Việt mà tưởng là an toàn."""
    from common import ocr_engines

    khoi = _hcl_block_ts(FORMAT_TS.read_text(encoding="utf-8"), "OCR_ENGINES")
    cap = re.findall(r'name:\s*"([^"]+)"[\s\S]*?supportsVietnamese:\s*(true|false)', khoi)

    for ten, co in cap:
        assert (co == "true") is ocr_engines.ENGINES[ten]["supports_vietnamese"], ten


def _route_blocks(text: str) -> list[str]:
    """Cắt từng `resource \"aws_apigatewayv2_route\"` block."""
    blocks: list[str] = []
    needle = 'resource "aws_apigatewayv2_route"'
    pos = 0
    while True:
        idx = text.find(needle, pos)
        if idx == -1:
            break
        brace = text.find("{", idx)
        if brace == -1:
            break
        depth = 1
        in_str = False
        i = brace + 1
        while i < len(text):
            ch = text[i]
            if ch == '"' and text[i - 1] != "\\":
                in_str = not in_str
            elif not in_str:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        blocks.append(text[brace : i + 1])
                        pos = i + 1
                        break
            i += 1
        else:
            break
    return blocks


def test_moi_route_co_JWT_authorizer():
    """Mọi route phải có JWT, thiếu là lỗ hổng im lặng."""
    text = MAIN_TF.read_text(encoding="utf-8")
    blocks = _route_blocks(text)
    assert blocks, "không tìm thấy resource aws_apigatewayv2_route"
    for idx, block in enumerate(blocks):
        assert 'authorization_type = "JWT"' in block, f"route block {idx} thiếu authorization_type JWT"
        assert "authorizer_id" in block, f"route block {idx} thiếu authorizer_id"


def test_cors_cho_phep_authorization_header():
    """Thiếu authorization trong allow_headers là mọi request chết ở preflight."""
    text = MAIN_TF.read_text(encoding="utf-8")
    # tìm cors_configuration của API Gateway
    m = re.search(r'cors_configuration\s*\{[^}]*allow_headers\s*=\s*\[(.*?)\]', text, re.S)
    assert m, "không tìm thấy cors_configuration allow_headers"
    headers = m.group(1).lower()
    assert "authorization" in headers


def _hcl_block_ts(text: str, name: str) -> str:
    """Cắt thân của `export const <name> ... = [ ... ]` trong TypeScript."""
    start = text.index(f"const {name}")
    mo = text.index("[", start)
    depth = 0
    for index in range(mo, len(text)):
        if text[index] == "[":
            depth += 1
        elif text[index] == "]":
            depth -= 1
            if depth == 0:
                return text[mo : index + 1]
    raise AssertionError(f"Không tìm thấy mảng `{name}` trong format.ts")


def test_role_projects_du_quyen_de_xoa_project():
    block = _hcl_block(MAIN_TF.read_text(encoding="utf-8"), "api_functions")
    projects = _hcl_block(block, "projects")
    dynamodb = re.search(r"dynamodb\s*=\s*\[([^\]]*)\]", projects).group(1)
    s3 = re.search(r"\bs3\s*=\s*\[([^\]]*)\]", projects).group(1)

    for action in ("Scan", "UpdateItem", "DeleteItem"):
        assert f'"{action}"' in dynamodb, action
    assert '"DeleteObject"' in s3
    assert re.search(r"s3_list\s*=\s*true", projects)

    for domain in ("documents", "review", "process", "anchor"):
        assert re.search(r"s3_list\s*=\s*false", _hcl_block(block, domain)), domain
