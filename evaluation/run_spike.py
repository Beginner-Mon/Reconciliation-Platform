"""Spike test: chạy các luồng OCR/extract trên dataset và chấm điểm.

Xem README.md cùng thư mục.

    python run_spike.py                      # chạy mọi luồng có đủ credential
    python run_spike.py --flows gemini_direct
    python run_spike.py --limit 3 --dry-run  # xem sẽ chạy gì, không gọi AI
"""

import argparse
import json
import os
import pathlib
import sys
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import env_file  # noqa: E402

env_file.load()

from flows import FLOWS, PROCESSOR_ENV  # noqa: E402
from scoring import aggregate, score_document  # noqa: E402

HERE = pathlib.Path(__file__).parent
DOCUMENTS = HERE / "dataset" / "documents"
GROUND_TRUTH = HERE / "dataset" / "ground_truth"
RESULTS = HERE / "results"
SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg", ".tiff"}


def load_dataset(limit: int | None) -> list[tuple[pathlib.Path, dict]]:
    if not DOCUMENTS.is_dir():
        return []
    pairs = []
    for path in sorted(DOCUMENTS.iterdir()):
        if path.suffix.lower() not in SUPPORTED:
            continue
        truth_path = GROUND_TRUTH / f"{path.stem}.json"
        if not truth_path.exists():
            print(f"  bỏ qua {path.name}: thiếu ground_truth/{path.stem}.json")
            continue
        pairs.append((path, json.loads(truth_path.read_text(encoding="utf-8"))))
    return pairs[:limit] if limit else pairs


def available_flows(requested: list[str] | None) -> list[str]:
    names = requested or list(FLOWS)
    unknown = [n for n in names if n not in FLOWS]
    if unknown:
        sys.exit(f"Luồng không tồn tại: {', '.join(unknown)}. Có: {', '.join(FLOWS)}")

    usable = []
    for name in names:
        if not os.environ.get("GEMINI_API_KEY"):
            print(f"  bỏ {name}: thiếu GEMINI_API_KEY")
            continue
        needed = PROCESSOR_ENV.get(name)
        if needed and not (os.environ.get("DOCAI_PROJECT") and os.environ.get(needed)):
            print(f"  bỏ {name}: thiếu DOCAI_PROJECT / {needed}")
            continue
        usable.append(name)
    return usable


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--flows", nargs="*", help="mặc định: tất cả luồng đủ credential")
    parser.add_argument("--limit", type=int, help="chỉ chạy N tài liệu đầu")
    parser.add_argument("--dry-run", action="store_true", help="không gọi AI, chỉ liệt kê")
    args = parser.parse_args()

    dataset = load_dataset(args.limit)
    if not dataset:
        print(f"Chưa có dữ liệu. Bỏ file vào {DOCUMENTS} và ground truth vào {GROUND_TRUTH}.")
        return 2

    flows = available_flows(args.flows)
    print(f"\n{len(dataset)} tài liệu, {len(flows)} luồng: {', '.join(flows) or '(không có)'}\n")
    if args.dry_run:
        for path, truth in dataset:
            print(f"  {path.name:32s} -> {truth.get('document_type')}")
        return 0
    if not flows:
        return 2

    RESULTS.mkdir(exist_ok=True)
    summary = {}

    for flow_name in flows:
        flow = FLOWS[flow_name]
        scores, cost, latency, errors, detail = [], 0.0, 0.0, [], []

        print(f"=== {flow_name}")
        for path, truth in dataset:
            try:
                outcome = flow(path.read_bytes(), path)
            except Exception as exc:
                errors.append({"file": path.name, "error": f"{type(exc).__name__}: {exc}"})
                print(f"  {path.name:32s} LỖI {type(exc).__name__}: {exc}")
                traceback.print_exc(limit=1)
                continue

            score = score_document(truth, outcome["data"])
            scores.append(score)
            cost += outcome["cost_usd"]
            latency += outcome["latency_s"]
            detail.append(
                {"file": path.name, "score": score, "extracted": outcome["data"],
                 "cost_usd": outcome["cost_usd"], "latency_s": outcome["latency_s"]}
            )
            print(
                f"  {path.name:32s} {score['accuracy']*100:5.1f}%  "
                f"${outcome['cost_usd']:.5f}  {outcome['latency_s']:.1f}s"
            )

        if scores:
            agg = aggregate(scores)
            agg.update(
                {"cost_usd": round(cost, 5), "cost_usd_per_doc": round(cost / len(scores), 5),
                 "latency_s_per_doc": round(latency / len(scores), 2), "errors": errors}
            )
            summary[flow_name] = agg
        else:
            summary[flow_name] = {"errors": errors, "so_document": 0}
        print()

        (RESULTS / f"{flow_name}.json").write_text(
            json.dumps({"summary": summary[flow_name], "documents": detail},
                       ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    print("=" * 78)
    print(f"{'luồng':<22}{'chính xác':>11}{'bỏ dấu':>9}{'classify':>10}{'$/doc':>10}{'giây/doc':>10}")
    print("-" * 78)
    for name, agg in summary.items():
        if not agg.get("so_document"):
            print(f"{name:<22}{'không chạy được':>52}")
            continue
        print(
            f"{name:<22}{agg['accuracy']*100:>10.1f}%{agg['accuracy_bo_dau']*100:>8.1f}%"
            f"{agg['classify_accuracy']*100:>9.1f}%{agg['cost_usd_per_doc']:>10.5f}"
            f"{agg['latency_s_per_doc']:>10.1f}"
        )
    print("=" * 78)

    for name, agg in summary.items():
        if agg.get("field_hay_sai"):
            print(f"\n{name} — field hay sai nhất:")
            for field, count in agg["field_hay_sai"]:
                print(f"    {field:<28} sai {count} lần")

    (RESULTS / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"\nChi tiết: {RESULTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
