"""Dev server — chạy toàn bộ backend ở máy, không cần AWS.

    cd backend
    .venv\\Scripts\\python.exe -m devserver

AWS được giả lập bằng moto. AI thì KHÔNG: mọi lần chạy đều gọi Document AI và
Gemini thật, và đều tốn tiền thật. Không còn chế độ AI giả — dữ liệu mẫu trông
y hệt lỗi hệ thống, đã làm mất thời gian một lần rồi.

Xem devserver/README.md.
"""

import argparse
import logging
import os
import pathlib
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULTS = {
    "AWS_DEFAULT_REGION": "ap-southeast-1",
    "AWS_ACCESS_KEY_ID": "dev",
    "AWS_SECRET_ACCESS_KEY": "dev",
    "PROJECTS_TABLE": "dev-projects",
    "DOCUMENTS_TABLE": "dev-documents",
    "RUNS_TABLE": "dev-processing-runs",
    "RECONCILIATIONS_TABLE": "dev-reconciliations",
    "AUDIT_LOG_TABLE": "dev-audit-log",
    "DOCUMENTS_BUCKET": "dev-documents",
    "STATE_MACHINE_ARN": "arn:aws:states:local:000000000000:stateMachine:devserver",
}

# Processor id và ĐƠN GIÁ phải đi cùng một chỗ. Tách ra là sai: bản v1 từng ước
# tính chi phí lệch 20 lần vì lấy đơn giá Form Parser cho Enterprise Document OCR.
PROCESSORS = {
    "dococr": {
        "env": "DOCAI_OCR_PROCESSOR_ID",
        "usd_per_page": "0.0015",
        "label": "documentai-enterprise-document-ocr",
        "note": "Enterprise Document OCR",
    },
    "formparser": {
        "env": "DOCAI_PROCESSOR_ID",
        "usd_per_page": "0.030",
        "label": "documentai-form-parser",
        "note": "Form Parser",
    },
    "layout": {
        "env": "DOCAI_LAYOUT_PROCESSOR_ID",
        "usd_per_page": "0.010",
        "label": "documentai-layout-parser",
        "note": "Layout Parser",
    },
}

ENV_PATH = pathlib.Path(__file__).resolve().parents[2] / "evaluation" / ".env"

SUPPORTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tiff"}

ROUTES_NOTE = """
  POST   /projects                                  tạo project
  GET    /projects                                  danh sách project
  GET    /projects/{id}                             chi tiết + tiến độ  (poll 2s)
  POST   /projects/{id}/documents                   xin presigned POST URL
  GET    /projects/{id}/documents                   danh sách document
  GET    /projects/{id}/documents/{doc_id}/ocr      text OCR thô
  POST   /projects/{id}/process                     chạy xử lý (skip doc đã xong)
  POST   /projects/{id}/reconcile                   đối chiếu lại
  PATCH  /projects/{id}/documents/{doc_id}          sửa tay + đối chiếu lại
  GET    /reconciliations/{id}                      kết quả đối chiếu đầy đủ
  POST   /reconciliations/{id}/approve              duyệt
  POST   /reconciliations/{id}/reject               từ chối
"""


def load_env_file() -> None:
    """Nạp evaluation/.env vào os.environ. Biến đã có sẵn thì không ghi đè."""
    if not ENV_PATH.exists():
        return
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if value and not value.startswith("<") and key.strip() not in os.environ:
            os.environ[key.strip()] = value


def setup_ai(processor: str) -> dict:
    """Chọn processor, kiểm credential. THIẾU LÀ THOÁT — không có đường lui.

    Trước đây thiếu credential thì rơi về AI giả, và giao diện hiện dữ liệu mẫu
    trông y hệt hệ thống hỏng. Thà chết lúc khởi động còn hơn chạy sai âm thầm.
    """
    spec = PROCESSORS[processor]
    processor_id = os.environ.get(spec["env"], "")

    missing = []
    if not os.environ.get("DOCAI_PROJECT"):
        missing.append("DOCAI_PROJECT")
    if not processor_id:
        missing.append(f"{spec['env']}  (processor {processor})")
    if not os.environ.get("GEMINI_API_KEY"):
        missing.append("GEMINI_API_KEY")

    if missing:
        print("\nTHIẾU CREDENTIAL, không khởi động được:\n")
        for name in missing:
            print(f"  - {name}")
        print(f"\nĐiền vào {ENV_PATH}")
        print("Dev server chỉ chạy với AI thật; không còn chế độ dữ liệu mẫu.")
        sys.exit(2)

    # ai_clients đọc các biến này lúc import, nên phải đặt TRƯỚC khi import worker.
    os.environ["DOCAI_PROCESSOR_ID"] = processor_id
    os.environ["DOCAI_USD_PER_PAGE"] = spec["usd_per_page"]
    os.environ["DOCAI_PROCESSOR_LABEL"] = spec["label"]
    return spec


def upload_folder(folder: pathlib.Path, host: str, port: int) -> str | None:
    """Tạo project rồi upload sẵn file thật trong thư mục — KHÔNG chạy /process.

    Upload không tốn tiền, chỉ /process mới tốn. Có cái này vì moto giữ dữ liệu
    trong RAM: khởi động lại là mất sạch, không lẽ mỗi lần lại kéo tay từng file.
    """
    import json

    from api.handler import lambda_handler
    from devserver.upload import upload

    def call(method: str, path: str, body: dict | None = None) -> dict:
        event = {
            "requestContext": {"http": {"method": method}},
            "rawPath": path,
            "body": json.dumps(body) if body is not None else None,
        }
        result = lambda_handler(event, None)
        parsed = json.loads(result["body"])
        if result["statusCode"] >= 400:
            raise RuntimeError(f"{method} {path} -> {result['statusCode']}: {parsed}")
        return parsed

    if not folder.is_dir():
        print(f"\nKhông thấy thư mục: {folder}")
        return None

    files = {
        path.name: path.read_bytes()
        for path in sorted(folder.iterdir())
        if path.suffix.lower() in SUPPORTED_SUFFIXES
    }
    if not files:
        print(f"\nThư mục không có file nào đọc được: {folder}")
        return None

    project = call("POST", "/projects", {"name": folder.name, "description": str(folder)})
    project_id = project["project_id"]
    created = call(
        "POST",
        f"/projects/{project_id}/documents",
        {"files": [{"file_name": name} for name in files]},
    )
    for entry in created["documents"]:
        status = upload(entry, files[entry["file_name"]])
        if status not in (200, 204):
            raise RuntimeError(f"Upload {entry['file_name']} -> {status}")

    print(f"\nProject      : {project_id} — đã upload {len(files)} chứng từ, CHƯA xử lý")
    for name in files:
        print(f"  {name}")
    print(f"  giao diện  : http://localhost:5173/projects/{project_id}")
    print(f"  hoặc curl  : curl -X POST http://{host}:{port}/projects/{project_id}/process")
    return project_id


def main() -> int:
    parser = argparse.ArgumentParser(prog="devserver")
    parser.add_argument("--port", type=int, default=8000, help="cổng API (mặc định 8000)")
    parser.add_argument("--aws-port", type=int, default=5000, help="cổng moto (mặc định 5000)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--processor", choices=list(PROCESSORS), default="dococr",
                        help="processor Document AI (mặc định dococr — rẻ nhất)")
    parser.add_argument("--upload", metavar="THƯ_MỤC",
                        help="tạo project và upload sẵn file thật trong thư mục (không xử lý)")
    parser.add_argument("--quiet", action="store_true", help="không in từng request")
    args = parser.parse_args()

    for key, value in DEFAULTS.items():
        os.environ.setdefault(key, value)
    os.environ["AWS_ENDPOINT_URL"] = f"http://{args.host}:{args.aws_port}"

    load_env_file()
    spec = setup_ai(args.processor)

    # moto chạy trên werkzeug và log mọi request nội bộ — ồn và không giúp gì,
    # request thật đã được http_server.py in ra rồi.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    import boto3
    from moto.server import ThreadedMotoServer

    from devserver import bootstrap, http_server, pipeline

    region = os.environ["AWS_DEFAULT_REGION"]
    endpoint = os.environ["AWS_ENDPOINT_URL"]

    print(f"\nAWS giả lập  : {endpoint}")
    moto = ThreadedMotoServer(ip_address=args.host, port=args.aws_port, verbose=False)
    moto.start()

    try:
        bucket = bootstrap.create_bucket(
            boto3.client("s3", region_name=region, endpoint_url=endpoint), region
        )
        tables = bootstrap.create_tables(
            boto3.resource("dynamodb", region_name=region, endpoint_url=endpoint)
        )
        print(f"  bucket     : {bucket}")
        print(f"  bảng       : {', '.join(tables)}")

        print("\nAI           : THẬT — mỗi lần xử lý đều TỐN TIỀN")
        print(f"  OCR        : {spec['note']}  (${spec['usd_per_page']}/trang)")
        print(f"  trích xuất : {os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')}")
        print(f"  dự án GCP  : {os.environ['DOCAI_PROJECT']} / {os.environ.get('DOCAI_LOCATION', 'us')}")

        plan = pipeline.install()
        print("\nĐiều phối    : đọc từ statemachine.asl.json")
        print(f"  mỗi doc    : {' -> '.join(plan['per_document'])}")
        print(f"  sau Map    : {' -> '.join(plan['after_map'])}")

        if args.upload:
            upload_folder(pathlib.Path(args.upload).resolve(), args.host, args.port)

        server = http_server.serve(args.host, args.port, quiet=args.quiet)
        print(f"\nAPI          : http://{args.host}:{args.port}")
        print(ROUTES_NOTE)
        print("Dữ liệu nằm trong RAM của moto — tắt là mất, xử lý lại sẽ tốn tiền lại.")
        print("Ctrl+C để dừng.\n")
        server.serve_forever()

    except KeyboardInterrupt:
        print("\nĐang dừng...")
        return 0
    finally:
        moto.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
