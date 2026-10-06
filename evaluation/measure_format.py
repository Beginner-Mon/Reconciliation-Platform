import argparse
import datetime
import json
import pathlib
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import env_file

env_file.load()

HERE = pathlib.Path(__file__).parent
DOCUMENTS = HERE / "dataset" / "documents"
SNAP_DIR = HERE / "results" / "format-snapshots"
TABLES_DIR = HERE / "dataset" / "ground_truth_tables"
HO_TRO = {".pdf", ".png", ".jpg", ".jpeg", ".tiff"}


def lay_project(url):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def chup_tu_devserver(url, nhan):
    du_lieu = lay_project(url)
    tai_lieu = du_lieu.get("documents") or []
    muc = [
        {
            "file_name": d.get("file_name"),
            "ocr_engine": d.get("ocr_engine"),
            "data": d.get("extraction"),
        }
        for d in tai_lieu
    ]
    ten = nhan or du_lieu.get("project", {}).get("project_id") or "devserver"
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    duong = SNAP_DIR / f"{ten}.json"
    duong.write_text(json.dumps(muc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"da ghi {len(muc)} chung tu vao {duong}")
    return 0


def chup_tu_engine(engine, nhan):
    from flows import FLOWS

    ten_luong = f"{engine}_gemini"
    if ten_luong not in FLOWS:
        print(f"luong khong ton tai: {ten_luong}. Co: {', '.join(sorted(FLOWS))}")
        return 2
    luong = FLOWS[ten_luong]
    muc = []
    tong_tien = 0.0
    for duong_file in sorted(DOCUMENTS.iterdir()):
        if duong_file.suffix.lower() not in HO_TRO:
            continue
        noi_dung = duong_file.read_bytes()
        ket_qua = luong(noi_dung, duong_file)
        muc.append(
            {
                "file_name": duong_file.name,
                "ocr_engine": engine,
                "data": ket_qua.get("data"),
            }
        )
        tong_tien += float(ket_qua.get("cost_usd") or 0)
    ten = nhan or f"{engine}-{datetime.date.today().isoformat()}"
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    duong = SNAP_DIR / f"{ten}.json"
    duong.write_text(json.dumps(muc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"da ghi {len(muc)} chung tu vao {duong} (uoc tinh ${tong_tien:.4f})")
    return 0


def chuan_hoa_tieu_de(tieu_de):
    from scoring import strip_accents

    return strip_accents(str(tieu_de or "").strip().lower())


def cot_khop(chuan, tieu_de, quy_tac, loai_tru):
    mau = quy_tac.get(chuan) or []
    if not any(m in tieu_de for m in mau):
        return False
    cam = (loai_tru or {}).get(chuan) or []
    if any(m in tieu_de for m in cam):
        return False
    return True


def la_rong(gia_tri):
    from scoring import normalize

    if gia_tri is None:
        return True
    if isinstance(gia_tri, str) and gia_tri.strip() == "":
        return True
    return normalize(gia_tri) == 0


def o_bang_nhau(mong_doi, thuc_te):
    from scoring import normalize

    if la_rong(mong_doi) and la_rong(thuc_te):
        return True
    if la_rong(mong_doi) != la_rong(thuc_te):
        return False
    return normalize(mong_doi) == normalize(thuc_te)


def cham_bang(du_lieu, goc_file):
    goc = TABLES_DIR / f"{goc_file}.json"
    if not goc.exists():
        return None
    dap_an = json.loads(goc.read_text(encoding="utf-8"))
    quy_tac = dap_an.get("columns") or {}
    loai_tru = dap_an.get("exclude") or {}
    dong_chuan = dap_an.get("rows") or []
    truong = [c for c in quy_tac if c != "mon"]
    if not dong_chuan or not truong:
        return None
    bang_tot = None
    diem_tot = -1
    for bang in du_lieu.get("tables") or []:
        if not isinstance(bang, dict):
            continue
        tieu_des = [
            c.get("header")
            for c in bang.get("columns") or []
            if isinstance(c, dict)
        ]
        chuan_hoa = [chuan_hoa_tieu_de(h) for h in tieu_des]
        dem = sum(
            1 for c in truong if any(cot_khop(c, h, quy_tac, loai_tru) for h in chuan_hoa)
        )
        if dem > diem_tot:
            diem_tot = dem
            bang_tot = bang
    tong = len(dong_chuan) * len(truong)
    if bang_tot is None or diem_tot <= 0:
        return (0, tong)
    cot_cua = {}
    tieu_des = [
        c.get("header") for c in bang_tot.get("columns") or [] if isinstance(c, dict)
    ]
    for c in truong:
        for h in tieu_des:
            if cot_khop(c, chuan_hoa_tieu_de(h), quy_tac, loai_tru):
                cot_cua[c] = h
                break
    dong_may = bang_tot.get("rows") or []
    dung = 0
    for i, dong_gt in enumerate(dong_chuan):
        dong_thuc = dong_may[i] if i < len(dong_may) else None
        for c in truong:
            thuc = dong_thuc.get(cot_cua[c]) if isinstance(dong_thuc, dict) and c in cot_cua else None
            if o_bang_nhau(dong_gt.get(c), thuc):
                dung += 1
    return (dung, tong)


def bao_cao(snapshot, khong_cuu):
    from core.validate import validate_document

    lam_sach = None
    if not khong_cuu:
        try:
            from core.normalize import clean_extraction

            lam_sach = clean_extraction
        except ImportError:
            lam_sach = None
    muc = json.loads(pathlib.Path(snapshot).read_text(encoding="utf-8"))
    hong = 0
    print("file | trang thai | go | co | o bang")
    for item in muc:
        ten = item.get("file_name") or "?"
        du_lieu = item.get("data") or {}
        van_de = []
        if lam_sach is not None and isinstance(du_lieu, dict):
            du_lieu, van_de = lam_sach(du_lieu)
        ket_qua = validate_document(du_lieu if isinstance(du_lieu, dict) else {})
        hop_le = bool(ket_qua.get("valid"))
        if not hop_le:
            hong += 1
        dem_co = {}
        for co in ket_qua.get("flags") or []:
            ma = co.get("code") or "?"
            dem_co[ma] = dem_co.get(ma, 0) + 1
        chuoi_co = (
            ",".join(f"{ma}:{so}" for ma, so in sorted(dem_co.items())) if dem_co else "-"
        )
        goc = (ten.rsplit(".", 1)[0])
        diem = cham_bang(du_lieu if isinstance(du_lieu, dict) else {}, goc)
        chuoi_bang = f"{diem[0]}/{diem[1]}" if diem is not None else "-"
        trang_thai = "HOP LE" if hop_le else "HONG"
        print(f"{ten} | {trang_thai} | {len(van_de)} | {chuoi_co} | {chuoi_bang}")
    print(f"hong {hong}/{len(muc)}")
    return 0


def main():
    parser = argparse.ArgumentParser()
    lenh = parser.add_subparsers(dest="lenh", required=True)
    chup = lenh.add_parser("capture")
    nguon = chup.add_mutually_exclusive_group(required=True)
    nguon.add_argument("--from-devserver", dest="tu_devserver", default=None)
    nguon.add_argument("--engine", choices=["textract", "dococr"], default=None)
    chup.add_argument("--nhan", default=None)
    xem = lenh.add_parser("report")
    xem.add_argument("snapshot")
    xem.add_argument("--khong-cuu", action="store_true")
    args = parser.parse_args()
    if args.lenh == "capture":
        if args.tu_devserver:
            return chup_tu_devserver(args.tu_devserver, args.nhan)
        return chup_tu_engine(args.engine, args.nhan)
    return bao_cao(args.snapshot, args.khong_cuu)


if __name__ == "__main__":
    raise SystemExit(main())
