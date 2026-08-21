"""Loại chứng từ không khớp bất kỳ loại nào đã định nghĩa.

Có loại này để một chứng từ lạ vẫn **đi hết được pipeline** thay vì chết ở bước
validate. Thực tế gặp: chứng từ vận tải biển (booking confirmation, arrival
notice, bill of lading) — không phải PO, không phải hóa đơn, không phải biên bản
nghiệm thu, nhưng vẫn cần đọc và lưu.

Mọi trường đều TÙY CHỌN, cố ý. Đây là nơi chứa thứ chưa hiểu rõ, nên không ràng
buộc gì ngoài định dạng. Đổi lại, nó gần như **không kiểm tra được gì** — không
có rule nghiệp vụ trong `core/validate.py`, và các rule đối chiếu ở `core/rules.py`
tự bỏ qua loại này vì chúng khai rõ cần loại nào.

Chứng từ nào chạy nhiều và quan trọng thì nên tách thành schema riêng (§6
CLAUDE.md), đừng để nằm mãi ở đây.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from .purchase_order import DOC_NUMBER_PATTERN


class Unknown(BaseModel):
    document_type: Literal["unknown"]
    doc_number: str | None = Field(default=None, pattern=DOC_NUMBER_PATTERN)
    doc_date: date | None = None
    issuer: str | None = Field(default=None, max_length=200, description="bên phát hành")
    recipient: str | None = Field(default=None, max_length=200, description="bên nhận")
    # Số hiệu chứng từ khác được nhắc tới (số booking, số container, số vận đơn…).
    # Chưa đủ hiểu để gán tên riêng cho từng loại nên gom vào một danh sách.
    reference_numbers: list[str] = Field(default_factory=list, max_length=50)
    currency: str | None = None
    total_amount: int | None = Field(default=None, gt=0)
    summary: str | None = Field(default=None, max_length=1000, description="tóm tắt nội dung")
