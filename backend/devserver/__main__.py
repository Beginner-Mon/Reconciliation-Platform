"""Dev server — chạy toàn bộ backend ở máy, không cần AWS, không tốn tiền.

    cd backend
    .venv\\Scripts\\python.exe -m devserver

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

ROUTES_NOTE = """
  POST   /projects                                  tạo project
  GET    /projects                                  danh sách project
  GET    /projects/{id}                             chi tiết + tiến độ  (poll 2s)
  POST   /projects/{id}/documents                   xin presigned PUT URL
  GET    /projects/{id}/documents                   danh sách document
  POST   /projects/{id}/process                     chạy xử lý (skip doc đã xong)
  POST   /projects/{id}/reconcile                   đối chiếu lại
  PATCH  /projects/{id}/documents/{doc_id}          sửa tay + đối chiếu lại
  GET    /reconciliations/{id}                      kết quả đối chiếu đầy đủ
  POST   /reconciliations/{id}/approve              duyệt
  POST   /reconciliations/{id}/reject               từ chối
"""


def load_real_ai_env() -> bool:
    env_path = pathlib.Path(__file__).resolve().parents[2] / "evaluation" / ".env"
    if not env_path.exists():
        return False
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if value and not value.startswith("<") and key.strip() not in os.environ:
            os.environ[key.strip()] = value
    return True


def main() -> int:
    parser = argparse.ArgumentParser(prog="devserver")
    parser.add_argument("--port", type=int, default=8000, help="cổng API (mặc định 8000)")
    parser.add_argument("--aws-port", type=int, default=5000, help="cổng moto (mặc định 5000)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--slow", type=float, default=0.0,
                        help="giả lập độ trễ AI (giây) để nhìn rõ trạng thái running khi poll")
    parser.add_argument("--real-ai", action="store_true",
                        help="dùng Document AI/Gemini thật (TỐN TIỀN), đọc evaluation/.env")
    parser.add_argument("--no-seed", action="store_true", help="không tạo project demo")
    parser.add_argument("--quiet", action="store_true", help="không in từng request")
    args = parser.parse_args()

    for key, value in DEFAULTS.items():
        os.environ.setdefault(key, value)
    os.environ["AWS_ENDPOINT_URL"] = f"http://{args.host}:{args.aws_port}"

    # moto chạy trên werkzeug và log mọi request nội bộ — ồn và không giúp gì,
    # request thật đã được http_server.py in ra rồi.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    import boto3
    from moto.server import ThreadedMotoServer

    from devserver import bootstrap, fake_ai, http_server, pipeline

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

        if args.real_ai:
            found = load_real_ai_env()
            print(f"\nAI           : THẬT (tốn tiền){'' if found else ' — CẢNH BÁO: không thấy evaluation/.env'}")
        else:
            fake_ai.install(latency=args.slow)
            suffix = f", độ trễ giả lập {args.slow}s/bước AI" if args.slow else ""
            print(f"\nAI           : giả (miễn phí){suffix}. Dùng --real-ai nếu muốn gọi thật.")

        # Frontend đọc qua GET /__dev__ để biết có nên hiện băng cảnh báo không.
        http_server.DEV_META = {"fake_ai": not args.real_ai, "latency": args.slow}

        plan = pipeline.install(slow=0.0)
        print("Điều phối    : đọc từ statemachine.asl.json")
        print(f"  mỗi doc    : {' -> '.join(plan['per_document'])}")
        print(f"  sau Map    : {' -> '.join(plan['after_map'])}")

        if not args.no_seed:
            from devserver.seed import create_demo_project

            project_id = create_demo_project()
            print(f"\nProject demo : {project_id} (3 chứng từ đã upload, chưa xử lý)")
            print(f"  chạy thử   : curl -X POST http://{args.host}:{args.port}/projects/{project_id}/process")

        server = http_server.serve(args.host, args.port, quiet=args.quiet)
        print(f"\nAPI          : http://{args.host}:{args.port}")
        print(ROUTES_NOTE)
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
