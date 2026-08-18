"""Xem OCR trả về cái gì — KHÔNG chấm điểm, KHÔNG validate, KHÔNG cross-check.

Dùng để nhìn tận mắt output thô của từng processor trước khi quyết định gì.
Không cần ground truth.

    python inspect_ocr.py tai_lieu.pdf
    python inspect_ocr.py tai_lieu.pdf --ocr-only        # dừng trước khi gọi Gemini
    python inspect_ocr.py --all                          # mọi file trong dataset/documents
    python inspect_ocr.py tai_lieu.pdf --ocr dococr layout
"""

import argparse
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import env_file  # noqa: E402
import ocr_cache  # noqa: E402

_LOADED_ENV = env_file.load()

from flows import OCR_ONLY, OCR_ONLY_ENV, OCR_ONLY_USD_PER_PAGE  # noqa: E402

HERE = pathlib.Path(__file__).parent
DOCUMENTS = HERE / "dataset" / "documents"
OUT = HERE / "results" / "inspect"
SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg", ".tiff"}
RULE = "=" * 78


def preview(text: str, lines: int = 25, width: int = 76) -> str:
    rendered = []
    for line in (text or "").splitlines()[:lines]:
        rendered.append(line[:width] + ("…" if len(line) > width else ""))
    remaining = len((text or "").splitlines()) - lines
    if remaining > 0:
        rendered.append(f"... còn {remaining} dòng nữa")
    return "\n".join(rendered) or "(rỗng)"


GEMINI_ENGINE = "gemini_direct"
ALL_ENGINES = list(OCR_ONLY) + [GEMINI_ENGINE]

ENGINE_LABEL = {
    "formparser": "Document AI Form Parser        $30/1.000 trang",
    "layout": "Document AI Layout Parser     $10/1.000 trang",
    "dococr": "Enterprise Document OCR       $1,50/1.000 trang",
    GEMINI_ENGINE: "KHÔNG PHẢI OCR — Gemini nhìn thẳng ảnh, chỉ để làm mốc so sánh",
}


def usable_ocr(requested: list[str] | None) -> list[str]:
    names = requested or ALL_ENGINES
    unknown = [n for n in names if n not in ALL_ENGINES]
    if unknown:
        sys.exit(f"Không có: {', '.join(unknown)}. Chọn trong: {', '.join(ALL_ENGINES)}")

    usable = []
    for name in names:
        if name == GEMINI_ENGINE:
            if not os.environ.get("GEMINI_API_KEY"):
                print(f"  bỏ {name}: thiếu GEMINI_API_KEY")
                continue
            usable.append(name)
            continue
        env = OCR_ONLY_ENV[name]
        if not (os.environ.get("DOCAI_PROJECT") and os.environ.get(env)):
            print(f"  bỏ {name}: thiếu DOCAI_PROJECT / {env}")
            continue
        usable.append(name)
    return usable


def run_gemini_direct(content: bytes, path, out_dir: pathlib.Path) -> None:
    """Gemini nhìn thẳng vào ảnh. Không cần Document AI, chỉ cần API key."""
    from flows import gemini_direct

    started = time.time()
    try:
        outcome = gemini_direct(content, path)
    except Exception as exc:
        print(f"  LỖI {type(exc).__name__}: {exc}")
        return

    print(f"  {time.time() - started:.1f}s   ~${outcome['cost_usd']:.5f}   token: {outcome['usage']}")
    print("\n  --- Gemini trả về (KHÔNG qua OCR) ---")
    print("  " + json.dumps(outcome["data"], ensure_ascii=False, indent=2).replace("\n", "\n  "))
    if outcome.get("confidence"):
        print("\n  --- confidence Gemini tự khai ---")
        print("  " + json.dumps(outcome["confidence"], ensure_ascii=False, indent=2).replace("\n", "\n  "))
    (out_dir / f"{path.stem}.gemini_direct.json").write_text(
        json.dumps(outcome, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def describe_ocr(name: str, ocr_json: dict) -> None:
    pages = ocr_json.get("pages") or []
    kv_count = sum(len(p.get("key_value_pairs") or []) for p in pages)
    table_count = sum(len(p.get("tables") or []) for p in pages)
    chunk_count = len(ocr_json.get("chunks") or [])
    text = ocr_json.get("text") or ""

    print(f"  trang         : {len(pages)}")
    print(f"  ký tự text    : {len(text):,}")
    print(f"  key-value     : {kv_count}" + ("   <- Document OCR không có" if not kv_count else ""))
    print(f"  bảng          : {table_count}" + ("   <- không tách được bảng" if not table_count else ""))
    if chunk_count:
        print(f"  chunk layout  : {chunk_count}")

    print("\n  --- text thô (25 dòng đầu) ---")
    print("  " + preview(text).replace("\n", "\n  "))

    for page in pages[:1]:
        kvs = page.get("key_value_pairs") or []
        if kvs:
            print(f"\n  --- key-value trang {page.get('page_number', '?')} (10 cặp đầu) ---")
            for kv in kvs[:10]:
                print(f"    {str(kv.get('key'))[:34]:36s} = {str(kv.get('value'))[:34]}")
        for index, table in enumerate(page.get("tables") or [], start=1):
            rows = table.get("rows") or []
            print(f"\n  --- bảng {index}: {len(rows)} dòng ---")
            for row in rows[:6]:
                print("    | " + " | ".join(str(c)[:18] for c in row.get("cells", [])) + " |")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", nargs="?", help="đường dẫn file cần xem")
    parser.add_argument("--all", action="store_true", help="mọi file trong dataset/documents")
    parser.add_argument("--ocr", nargs="*", help=f"chọn trong: {', '.join(ALL_ENGINES)}")
    parser.add_argument("--ocr-only", action="store_true", help="không gọi Gemini")
    parser.add_argument("--refresh", action="store_true", help="bỏ cache, gọi lại API (TỐN TIỀN)")
    parser.add_argument("--clear-cache", action="store_true", help="xoá cache OCR rồi thoát")
    args = parser.parse_args()

    if args.clear_cache:
        print(f"Đã xoá {ocr_cache.clear()} file cache OCR.")
        return 0

    if args.all:
        targets = [p for p in sorted(DOCUMENTS.iterdir()) if p.suffix.lower() in SUPPORTED] \
            if DOCUMENTS.is_dir() else []
    elif args.file:
        targets = [pathlib.Path(args.file)]
    else:
        parser.error("cần <file> hoặc --all")

    if not targets:
        print(f"Không có file nào. Bỏ tài liệu vào {DOCUMENTS}")
        return 2

    if _LOADED_ENV:
        print(f"Đã nạp từ .env: {', '.join(_LOADED_ENV)}\n")

    engines = usable_ocr(args.ocr)
    if not engines:
        print("\nChưa đặt credential nào. Điền vào file .env:")
        print("\n  OCR THẬT (không dùng Gemini) — cần DOCAI_PROJECT + đăng nhập GCP:")
        for name, env in OCR_ONLY_ENV.items():
            print(f"    {env:30s} -> {name}")
        print("\n  Không phải OCR, chỉ làm mốc so sánh:")
        print(f"    {'GEMINI_API_KEY':30s} -> {GEMINI_ENGINE}")
        if not env_file.ENV_PATH.exists():
            print("\nChưa có file .env. Tạo bằng:  Copy-Item .env.example .env")
        return 2

    if all(name == GEMINI_ENGINE for name in engines):
        print(
            "\nCẢNH BÁO: chỉ chạy được gemini_direct, mà đó KHÔNG phải OCR.\n"
            "Muốn xem OCR thật trả về gì thì phải có processor Document AI.\n"
        )

    OUT.mkdir(parents=True, exist_ok=True)

    for path in targets:
        if not path.exists():
            print(f"Không thấy file: {path}")
            continue
        content = path.read_bytes()
        print(f"\n{RULE}\n{path.name}  ({len(content):,} bytes)\n{RULE}")

        for name in engines:
            print(f"\n[{name}]  {ENGINE_LABEL[name]}")
            if name == GEMINI_ENGINE:
                run_gemini_direct(content, path, OUT)
                continue

            started = time.time()
            try:
                ocr_json, from_cache = ocr_cache.run(
                    name, content, lambda: OCR_ONLY[name](content, path), refresh=args.refresh
                )
            except Exception as exc:
                print(f"  LỖI {type(exc).__name__}: {exc}")
                continue

            elapsed = time.time() - started
            pages = len(ocr_json.get("pages") or [])
            if from_cache:
                print(f"  {elapsed:.1f}s   $0 (dùng lại cache, không gọi API)")
            else:
                print(f"  {elapsed:.1f}s   ~${pages * OCR_ONLY_USD_PER_PAGE[name]:.5f}")
            describe_ocr(name, ocr_json)

            raw_path = OUT / f"{path.stem}.{name}.ocr.json"
            raw_path.write_text(
                json.dumps(ocr_json, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )

            from common.ai_clients import _build_ocr_text

            prompt_text = _build_ocr_text(ocr_json)
            (OUT / f"{path.stem}.{name}.prompt.txt").write_text(prompt_text, encoding="utf-8")
            print(f"\n  --- phần Gemini thực sự nhận được ({len(prompt_text):,} ký tự) ---")
            print("  " + preview(prompt_text, lines=15).replace("\n", "\n  "))

            if args.ocr_only:
                continue
            if not os.environ.get("GEMINI_API_KEY"):
                print("\n  (bỏ bước Gemini: thiếu GEMINI_API_KEY)")
                continue

            from common.ai_clients import extract_with_gemini

            try:
                extracted = extract_with_gemini(ocr_json)
            except Exception as exc:
                print(f"\n  Gemini LỖI {type(exc).__name__}: {exc}")
                continue
            usage = extracted.pop("_usage", {})
            print(f"\n  --- Gemini trả về (token: {usage}) ---")
            print("  " + json.dumps(extracted, ensure_ascii=False, indent=2).replace("\n", "\n  "))
            (OUT / f"{path.stem}.{name}.extracted.json").write_text(
                json.dumps(extracted, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    hits = ocr_cache.stats()
    if hits["hit"] or hits["miss"]:
        print(f"\nOCR: {hits['miss']} lần gọi API, {hits['hit']} lần dùng cache (miễn phí)")
    print(f"File chi tiết: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
