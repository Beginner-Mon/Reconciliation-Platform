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


def test_chi_mot_route_duy_nhat_goi_step_functions():
    """`states:StartExecution` là quyền tiêu tiền AI — chỉ được ở đúng một chỗ.

    Thêm route vào PROCESS_ROUTES nghĩa là mở rộng phạm vi quyền đó. Nếu có lý do
    thật thì sửa test này, nhưng phải là quyết định có ý thức.
    """
    assert route_keys(handler.PROCESS_ROUTES) == {"POST /projects/{project_id}/process"}


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
