"""Tài khoản chỉ XEM dashboard: quyền phải đúng bằng những gì dashboard cần.

Người xem (người hướng dẫn, giảng viên) đăng nhập AWS Console bằng mật khẩu. Thêm
một action "cho tiện" là người ngoài dự án có thêm quyền trên tài khoản AWS thật,
nên danh sách action được khoá cứng ở đây. User và mật khẩu tạo bằng script để
mật khẩu không vào tfstate, và không bao giờ có access key.
"""

import pathlib
import re

INFRA = pathlib.Path(__file__).resolve().parents[2] / "infra"
MAIN_TF = INFRA / "modules" / "aws" / "main.tf"
SCRIPT = INFRA / "scripts" / "create_viewer.ps1"

QUYEN_DUOC_CAP = {
    "cloudwatch:GetDashboard",
    "cloudwatch:ListDashboards",
    "cloudwatch:GetMetricData",
    "cloudwatch:ListMetrics",
    "logs:StartQuery",
    "logs:GetQueryResults",
    "logs:StopQuery",
}


def _resource(loai: str, ten: str) -> str:
    """Cắt thân `resource "<loai>" "<ten>" { ... }`, bỏ qua ngoặc nằm trong chuỗi."""
    nguon = MAIN_TF.read_text(encoding="utf-8")
    moc = f'resource "{loai}" "{ten}" {{'
    assert moc in nguon, f"Không thấy {moc} trong main.tf"
    dau = nguon.index(moc) + len(moc)
    sau = 1
    trong_chuoi = False
    for i in range(dau, len(nguon)):
        c = nguon[i]
        if c == '"':
            trong_chuoi = not trong_chuoi
        elif not trong_chuoi:
            if c == "{":
                sau += 1
            elif c == "}":
                sau -= 1
                if sau == 0:
                    return nguon[dau:i]
    raise AssertionError(f"Block {moc} không đóng")


def _statement(policy: str, action: str) -> str:
    """Phần policy (cắt theo `Sid`) chứa action đã cho."""
    khop = [phan for phan in policy.split("Sid") if f'"{action}"' in phan]
    assert len(khop) == 1, f"{action} nằm ở {len(khop)} statement"
    return khop[0]


def test_nguoi_xem_chi_co_dung_bay_quyen_doc():
    policy = _resource("aws_iam_policy", "dashboard_viewer")
    co = set(re.findall(r'"([a-z0-9-]+:[A-Za-z*]+)"', policy))
    assert co == QUYEN_DUOC_CAP, f"Thừa: {co - QUYEN_DUOC_CAP}\nThiếu: {QUYEN_DUOC_CAP - co}"


def test_khong_co_action_dang_wildcard():
    policy = _resource("aws_iam_policy", "dashboard_viewer")
    assert not re.search(r'"[a-z0-9-]+:[A-Za-z]*\*"', policy)
    assert not re.search(r'Action\s*=\s*\[?\s*"\*"', policy)


def test_dashboard_va_log_chi_cap_tren_tai_nguyen_cua_he_thong():
    policy = _resource("aws_iam_policy", "dashboard_viewer")
    xem = _statement(policy, "cloudwatch:GetDashboard")
    assert "aws_cloudwatch_dashboard.poc.dashboard_arn" in xem
    assert '"*"' not in xem
    log = _statement(policy, "logs:StartQuery")
    assert "aws_cloudwatch_log_group.lambda" in log
    assert '"*"' not in log


def test_nhom_nguoi_xem_co_policy_va_chi_doi_duoc_mat_khau_cua_chinh_minh():
    gan = _resource("aws_iam_group_policy_attachment", "dashboard_viewer")
    assert "aws_iam_group.dashboard_viewer.name" in gan
    assert "aws_iam_policy.dashboard_viewer.arn" in gan
    doi = _resource("aws_iam_group_policy_attachment", "dashboard_viewer_doi_mat_khau")
    assert '"arn:aws:iam::aws:policy/IAMUserChangePassword"' in doi


def test_mat_khau_va_khoa_khong_vao_tfstate():
    """User và mật khẩu tạo bằng script; Terraform chỉ giữ quyền."""
    nguon = MAIN_TF.read_text(encoding="utf-8")
    for loai in ("aws_iam_user", "aws_iam_access_key", "aws_iam_user_login_profile", "aws_iam_user_group_membership"):
        assert f'resource "{loai}"' not in nguon, loai


def test_script_tao_nguoi_xem_dang_nhap_bang_mat_khau_khong_co_access_key():
    script = SCRIPT.read_text(encoding="utf-8-sig")
    assert "create-access-key" not in script
    assert "create-login-profile" in script
    assert "--password-reset-required" in script
    assert "output -raw dashboard_viewer_group" in script
    for outputs in (INFRA / "outputs.tf", INFRA / "modules" / "aws" / "outputs.tf"):
        assert 'output "dashboard_viewer_group"' in outputs.read_text(encoding="utf-8"), outputs
