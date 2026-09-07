"""Gói `common` CỐ TÌNH RỖNG — import thẳng submodule.

Trước đây file này re-export mọi thứ từ 7 submodule, nên `from common import X`
ở bất kỳ đâu cũng kéo theo TOÀN BỘ `common/` + `schemas/` + pydantic. Đó là lý
do Lambda `mark-failed` — chỉ đổi một dòng status trong DynamoDB — vẫn phải mang
pydantic trong gói.

Giờ mỗi Lambda chỉ chứa module nó thật sự dùng. Đừng thêm re-export lại vào đây;
đã có test chặn (`tests/test_packaging.py`).
"""
