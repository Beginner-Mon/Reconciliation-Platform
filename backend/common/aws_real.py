"""Client boto3 gọi AWS THẬT — cố tình KHÔNG đọc `AWS_ENDPOINT_URL`.

Mọi client khác trong repo (`s3.py`, `dynamodb.py`, `stepfunctions.py`) đều đọc
`AWS_ENDPOINT_URL` để dev server trỏ được vào moto. Với hạ tầng thì đúng: bảng
và bucket giả lập được, tắt máy là mất, không ai thiệt gì.

Với AI thì SAI. moto có Textract giả: nó trả về Block bịa sẵn kèm
`JobStatus: SUCCEEDED`. Client viết theo nếp cũ sẽ khiến dev server chạy êm ru,
giao diện hiện đầy chữ, không tốn một xu — mà chữ đó là bịa, và không có dấu
hiệu nào để phát hiện.

Đây đúng thứ đã bị gỡ khỏi repo (`fake_ai.py`, `replay_ocr.py`, §5 CLAUDE.md):
"dữ liệu mẫu cố định nhìn không phân biệt được với hệ thống hỏng". AWS thì giả
lập, AI thì luôn thật và luôn tốn tiền.

Phải chỉ endpoint TƯỜNG MINH chứ không chỉ bỏ tham số: botocore đời mới tự đọc
`AWS_ENDPOINT_URL` từ môi trường, nên `boto3.client("textract")` trơn vẫn rơi
vào moto.

Và ENDPOINT chỉ là một nửa. Nửa còn lại là CREDENTIAL — xem `session()`.
"""

import os

import boto3
import botocore.session

DEFAULT_REGION = "ap-southeast-1"


def session() -> boto3.Session:
    """Session dùng credential THẬT, bỏ qua cặp khoá giả mà dev server đặt.

    `devserver/__main__.py DEFAULTS` đặt AWS_ACCESS_KEY_ID='dev' để moto có cái
    mà ký (moto không kiểm nên giá trị gì cũng xong). Nhưng boto3 xét biến môi
    trường TRƯỚC `~/.aws/credentials`, nên client ở file này — vốn cố ý gọi AWS
    thật — cũng vớ luôn cặp khoá giả đó. AWS trả **403 Forbidden**, tức là
    "không có quyền", khiến người ta đi sửa IAM policy trong khi khoá gửi lên
    còn chẳng tồn tại.

    Trên Lambda thì NGƯỢC LẠI: biến môi trường chính là nguồn credential thật
    (role của function bơm vào). Bỏ provider 'env' ở đó là function mất sạch
    quyền — sửa dev server mà làm chết production.
    """
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return boto3.Session()

    khong_env = botocore.session.Session()
    khong_env.get_component("credential_provider").remove("env")
    tu_cau_hinh = boto3.Session(botocore_session=khong_env)

    # Máy chỉ có credential trong env (CI, khoá STS tạm) thì đó là nguồn DUY
    # NHẤT — quay về session thường còn hơn không có gì để gọi.
    return tu_cau_hinh if tu_cau_hinh.get_credentials() else boto3.Session()


def region() -> str:
    """Textract BẮT bucket phải cùng region với job.

    Nên phải tôn trọng cả `~/.aws/config` (thứ `aws configure` ghi vào), không
    chỉ biến môi trường. Đoán bừa thì bucket nằm một nơi, job chạy một nơi, và
    lỗi báo về là InvalidS3ObjectException — nhìn như file hỏng chứ không hé lộ
    gì về region.
    """
    return (
        os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or boto3.Session().region_name
        or DEFAULT_REGION
    )


def textract_client():
    name = region()
    return session().client(
        "textract",
        region_name=name,
        endpoint_url=f"https://textract.{name}.amazonaws.com",
    )


def s3_client():
    """S3 THẬT — để đẩy file lên bucket tạm cho Textract đọc.

    Không dùng `common/s3.py` được: ở dev server client đó trỏ vào moto, mà
    Textract là AWS thật nên không nhìn thấy bucket nằm trong RAM máy mình.
    """
    name = region()
    return session().client(
        "s3",
        region_name=name,
        endpoint_url=f"https://s3.{name}.amazonaws.com",
    )
