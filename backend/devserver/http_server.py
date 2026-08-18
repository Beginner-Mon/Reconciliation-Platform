"""Dịch HTTP <-> event Lambda. Không có logic nghiệp vụ nào ở đây.

Router, path params, xử lý lỗi đều đã nằm trong api/handler.py — file này chỉ
dựng đúng hình dạng event mà API Gateway HTTP API v2 gửi tới Lambda, rồi trả
kết quả về dạng HTTP.

CORS preflight do file này lo, vì ở môi trường thật API Gateway lo phần đó
(xem cors_configuration trong infra/modules/aws/main.tf).
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from api.handler import lambda_handler

PREFLIGHT_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PATCH, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "content-type",
    "Access-Control-Max-Age": "600",
}

# Route CHỈ CÓ ở dev server, cố ý không nằm trong api/handler.py.
# Frontend gọi thử; nhận 404 nghĩa là đang chạy production thật.
DEV_META_PATH = "/__dev__"

# __main__.py đặt lại giá trị này lúc khởi động.
DEV_META = {"fake_ai": True, "latency": 0.0}


class DevHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    quiet = False

    def log_message(self, fmt, *args):
        if not self.quiet:
            print(f"  {self.command:6s} {self.path}  -> {args[1] if len(args) > 1 else ''}")

    def _read_body(self) -> str | None:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return None
        return self.rfile.read(length).decode("utf-8")

    def _send(self, status: int, headers: dict, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _dispatch(self) -> None:
        path = self.path.split("?", 1)[0]

        if path == DEV_META_PATH:
            self._send(
                200,
                {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
                json.dumps(DEV_META, ensure_ascii=False),
            )
            return

        event = {
            "requestContext": {"http": {"method": self.command}},
            "rawPath": path,
            "body": self._read_body(),
        }
        try:
            result = lambda_handler(event, None)
        except Exception as exc:  # dev server không được chết vì 1 request hỏng
            self._send(
                500,
                {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
                json.dumps({"error": f"Dev server lỗi: {exc}"}, ensure_ascii=False),
            )
            return

        self._send(
            result.get("statusCode", 200),
            result.get("headers", {"Content-Type": "application/json"}),
            result.get("body", ""),
        )

    def do_OPTIONS(self):
        self._send(204, PREFLIGHT_HEADERS, "")

    do_GET = do_POST = do_PATCH = do_DELETE = _dispatch


def serve(host: str, port: int, quiet: bool = False) -> ThreadingHTTPServer:
    DevHandler.quiet = quiet
    return ThreadingHTTPServer((host, port), DevHandler)
