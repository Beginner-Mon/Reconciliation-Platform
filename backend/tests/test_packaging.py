"""Mỗi Lambda một gói riêng — và bảng gói phải khớp khít với Terraform.

Khai bên Python mà quên Terraform thì `terraform apply` trỏ vào một file zip
không tồn tại. Khai bên Terraform mà quên Python thì script build không dựng gói
cho function đó, và lần deploy sau nó chạy bằng zip cũ — sai theo kiểu không ai
nhìn thấy. Cùng cách `test_routes.py` khoá bảng route.
"""

import pathlib
import re

import pytest

from packaging import APP_MODULES, PACKAGES

MAIN_TF = (
    pathlib.Path(__file__).resolve().parents[2]
    / "infra"
    / "modules"
    / "aws"
    / "main.tf"
)


def _khoi(text: str, ten: str) -> str:
    """Cắt thân block `<ten> = { ... }`, bỏ qua ngoặc nằm trong chuỗi."""
    moc = f"{ten} = {{"
    dau = text.index(moc) + len(moc)
    sau = 1
    trong_chuoi = False
    for i in range(dau, len(text)):
        c = text[i]
        if c == '"':
            trong_chuoi = not trong_chuoi
        elif not trong_chuoi:
            if c == "{":
                sau += 1
            elif c == "}":
                sau -= 1
                if sau == 0:
                    return text[dau:i]
    raise AssertionError(f"Không thấy block `{ten}` trong main.tf")


def ten_function_terraform() -> set[str]:
    nguon = MAIN_TF.read_text(encoding="utf-8")
    workers = re.findall(r"^\s{4}([\w-]+) = \{", _khoi(nguon, "workers"), re.M)
    apis = re.findall(r"^\s{4}([\w-]+) = \{", _khoi(nguon, "api_functions"), re.M)
    return set(workers) | {f"api-{ten}" for ten in apis}


def test_bang_goi_khop_khit_voi_terraform():
    tf = ten_function_terraform()
    py = set(PACKAGES)

    assert tf == py, (
        f"Chỉ có trong main.tf: {tf - py}\nChỉ có trong packaging.py: {py - tf}"
    )


def test_moi_goi_khai_ro_phai_co_module_nhung_gi():
    """Danh sách này là thứ script build dùng để kiểm gói vừa dựng.

    Bỏ trống thì gói thiếu thư viện vẫn build trót lọt, và chỉ chết lúc chạy
    thật — với import lười (Google nằm trong thân hàm) thì càng khó thấy.
    """
    for ten, spec in PACKAGES.items():
        assert spec["phai_co_module"], ten
        assert isinstance(spec["requires"], list), ten


def test_khong_goi_nao_khai_boto3():
    """Runtime python3.11 của Lambda đã có sẵn boto3/botocore — 20 MB.

    Khai lại là mỗi function cõng thêm 20 MB cho việc chẳng thay đổi gì.
    """
    for ten, spec in PACKAGES.items():
        for goi in spec["requires"]:
            assert not goi.lower().startswith(("boto3", "botocore")), ten


def test_chi_hai_worker_can_thu_vien_google():
    """Đây là cả điểm của việc tách gói: 8/10 function không đụng tới Google.

    Thêm Google vào gói khác là gói đó phình từ 9 MB lên ~50 MB, và cold start
    của chính nó dài ra theo.
    """
    co_google = {
        ten
        for ten, spec in PACKAGES.items()
        if any("google" in goi for goi in spec["requires"])
    }
    assert co_google == {"ocr", "extract"}


def test_worker_khong_keo_ca_goi_workers_vao():
    """`workers/__init__.py` phải RỖNG.

    Nó từng làm `from .reconcile import run_reconciliation`, mà Python chạy
    `__init__.py` cho MỌI lần import `workers.xxx`. Nghĩa là `workers.ocr` kéo
    theo `core/` -> `schemas/` -> pydantic, dù ocr không hề dùng. Với gói riêng
    thì ocr và mark-failed phải sạch pydantic.
    """
    import workers

    nguon = pathlib.Path(workers.__file__).read_text(encoding="utf-8")
    co_code = [
        dong
        for dong in nguon.splitlines()
        if dong.strip() and not dong.strip().startswith("#")
    ]
    assert not co_code, f"workers/__init__.py phải rỗng, đang có: {co_code}"


def test_code_ung_dung_chep_het_vao_moi_goi():
    """150 KB — tách ra không tiết kiệm gì mà phải bổ `common/` thành nhiều mảnh."""
    backend = pathlib.Path(__file__).resolve().parents[1]

    assert set(APP_MODULES) == {"api", "common", "core", "schemas", "workers"}
    for ten in APP_MODULES:
        assert (backend / ten / "__init__.py").exists(), ten

    tong = sum(
        p.stat().st_size for ten in APP_MODULES for p in (backend / ten).rglob("*.py")
    )
    assert tong < 1_000_000, f"code ứng dụng đã {tong / 1024:.0f} KB — cân nhắc chia"


@pytest.mark.parametrize("ten", sorted(PACKAGES))
def test_ten_goi_dung_dang_dat_ten_file(ten):
    """Script build ghi ra `artifacts/<tên>.zip`, Terraform đọc đúng đường đó."""
    assert re.fullmatch(r"[a-z][a-z0-9-]*", ten), ten


# --- Thư viện nạp NGAY lúc import: thiếu là chết cold start ----------------

# Runtime python3.11 của Lambda có sẵn, không gói nào phải khai.
RUNTIME_CO_SAN = {"boto3", "botocore"}


def _import_ngay() -> dict[str, str]:
    """Thư viện bên thứ ba được import ở MỨC MODULE của code ứng dụng.

    Đây là thứ quyết định gói có chạy nổi hay không: thiếu một cái là Lambda
    chết ngay lúc cold start, trước khi handler chạy dòng đầu tiên.

    SUY RA bằng AST chứ không khai tay — khai tay đúng là chỗ đã sai: bảng gói
    ban đầu bỏ `pydantic` khỏi ocr/mark-failed vì tôi đọc nhầm chuỗi import
    `common/__init__ -> ai_clients -> schemas -> pydantic`.

    Import LƯỜI (google nằm trong thân hàm ở `ai_clients.py`) không tính ở đây —
    chúng chỉ chết khi hàm đó được gọi, nên vẫn phải khai tay trong `requires`.
    """
    import ast
    import sys

    backend = pathlib.Path(__file__).resolve().parents[1]
    stdlib = set(sys.stdlib_module_names)
    app = set(APP_MODULES) | {"packaging"}

    thay: dict[str, str] = {}
    for mod in APP_MODULES:
        for tep in (backend / mod).rglob("*.py"):
            cay = ast.parse(tep.read_text(encoding="utf-8"))
            trong_ham = {
                dong
                for ham in ast.walk(cay)
                if isinstance(ham, (ast.FunctionDef, ast.AsyncFunctionDef))
                for dong in range(ham.lineno, (ham.end_lineno or ham.lineno) + 1)
            }
            for node in ast.walk(cay):
                if not isinstance(node, (ast.Import, ast.ImportFrom)):
                    continue
                if isinstance(node, ast.ImportFrom) and node.level:
                    continue  # import tương đối = code của mình
                ten = (
                    (node.module or "").split(".")[0]
                    if isinstance(node, ast.ImportFrom)
                    else node.names[0].name.split(".")[0]
                )
                if not ten or ten in stdlib or ten in app or node.lineno in trong_ham:
                    continue
                thay.setdefault(ten, f"{mod}/{tep.name}")
    return thay


def test_moi_goi_du_thu_vien_nap_ngay_luc_import():
    """Code ứng dụng chép vào MỌI gói, nên gói nào cũng phải đủ thư viện mà code
    đó nạp ngay lúc import — kể cả `mark-failed` chỉ đổi status DynamoDB.

    Bỏ sót thì Lambda chết ở cold start với ModuleNotFoundError, và chỉ lộ ra
    khi chạy thật trên AWS.
    """
    can = {ten for ten in _import_ngay() if ten not in RUNTIME_CO_SAN}
    assert can, "AST không tìm thấy thư viện nào — hàm dò hỏng rồi"

    for goi, spec in PACKAGES.items():
        khai = {yc.split(">")[0].split("=")[0].split("[")[0] for yc in spec["requires"]}
        thieu = {ten for ten in can if ten not in khai}
        assert not thieu, (
            f"gói '{goi}' thiếu {sorted(thieu)} — code ứng dụng nạp nó ngay lúc "
            f"import (xem {[_import_ngay()[t] for t in sorted(thieu)]})"
        )


def test_khong_khai_thua_thu_vien_runtime_da_co():
    for goi, spec in PACKAGES.items():
        khai = {yc.split(">")[0].split("=")[0] for yc in spec["requires"]}
        assert not (khai & RUNTIME_CO_SAN), goi
