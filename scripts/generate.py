#!/usr/bin/env python3
"""
AscCatSamurai 圖片產生器（多核心平行處理）

做兩件事，已存在且尺寸正確的檔案會自動跳過（中斷後重跑即可續做）：
  1. 已 mint 的 0~30 號：把原圖縮放到指定尺寸
  2. 31~499 號：用 AscCatSamurai2.0 圖層疊圖生成
     - 圖層順序與原版相同：Wepon → Body → Clothes → Face → Dress
     - source/metadata/<id>.json 已存在 → 照它的 attributes 疊圖
     - 不存在 → 隨機抽一組不重複的組合（固定 seed），並寫出 JSON

用法（在 2026_asc_web3_ipfs 資料夾執行）：
  python3 scripts/generate.py
  python3 scripts/generate.py --size 2048 --workers 8
  python3 scripts/generate.py --layers ~/Downloads/AscCatSamurai2.0 --originals .tmp/images_2048
完成後再執行：python3 scripts/build_metadata.py
"""
import argparse, json, os, random, sys, time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ORDER = ["Wepon", "Body", "Clothes", "Face", "Dress"]
MINTED = 31
TOTAL = 500
SEED = 20261025
IMG_CID = "QmY8upzoVGvrdhCSi2NZmprUWcgRQWzkcYjuHHkA17vQZX"

# 圖層檔名 → 原版 trait 名稱（由 0~30 號原圖比對得出；沒列到的 = 檔名，結尾非數字則補 0）
NAME_MAP = {
    "Wepon": {"Sword2": "Sword99"},
    "Body": {"3": "Original1", "Orange": "Original0", "Tabby": "Tabby0", "1": "Tabby1", "2": "Tabby2",
             "Tuxedo": "Tuxedo0", "Black": "Pure0", "4": "Pure1", "5": "Pure2",
             "Broken": "Broken0", "6": "Broken1", "7": "Broken2", "8": "Broken3"},
    "Dress": {"11": "Cigar0", "Cigar": "Cigar1", "Fox mask": "Fox mask0", "Rice": "Rice0", "8": "Rice1",
              "7": "Rice2", "Bamboo hat": "Bamboo hat0", "4": "Bamboo hat1", "5": "Bamboo hat2",
              "Veil": "Veil0", "1": "Veil1"},
}
NONE_NAMES = {"None0", "None1", "None2"}   # Dress 不疊任何圖層

# 稀有度：沒列在這裡的一律權重 1.0（同一類別內出現機率相同）
#   Dress 的 None（不戴配件）也當成一個普通選項
SUPER_RARE, RARE = 0.12, 0.35
RARITY = {
    "Face":    {"Common99": SUPER_RARE,      # 金色閃電眼
                "Scar2": RARE},              # 紅眼刀疤
    "Wepon":   {"Sword99": SUPER_RARE},      # 金柄武士刀
    "Clothes": {"Armor1": SUPER_RARE,        # 黃金鎧甲
                "Armor2": RARE},             # 粉色鎧甲
    "Body":    {"Original1": RARE,           # 白色長毛＋耳環
                "Original0": RARE},          # 橘色長毛＋耳環
    "Dress":   {"Fox mask0": RARE},          # 狐狸面具
}


def trait_name(cat, stem):
    if stem in NAME_MAP.get(cat, {}):
        return NAME_MAP[cat][stem]
    return stem if stem[-1].isdigit() else stem + "0"


def load_options(layers):
    opts = {}
    for cat in ORDER:
        files = sorted((layers / cat).glob("*.png"))
        if not files:
            sys.exit(f"找不到圖層：{layers / cat}")
        rar = RARITY.get(cat, {})
        items = [(trait_name(cat, f.stem), str(f), rar.get(trait_name(cat, f.stem), 1.0)) for f in files]
        if cat == "Dress":
            items.append(("None0", None, rar.get("None0", 1.0)))
        opts[cat] = items
    return opts


# ---------- 子行程：疊圖 / 縮圖 ----------
_cache = {}

def _layer(path, size):
    key = (path, size)
    if key not in _cache:
        im = Image.open(path).convert("RGBA")
        if im.size != (size, size):
            im = im.resize((size, size), Image.LANCZOS)
        _cache[key] = im
    return _cache[key]


def _save(im, out):
    tmp = out + ".part"
    im.save(tmp, "PNG", optimize=True)
    os.replace(tmp, out)


def job_compose(tid, paths, size, out):
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    for p in paths:
        if p:
            canvas.alpha_composite(_layer(p, size))
    _save(canvas, out)
    return tid


def job_resize(tid, src, size, out):
    im = Image.open(src).convert("RGBA")
    if im.size != (size, size):
        im = im.resize((size, size), Image.LANCZOS)
    _save(im, out)
    return tid


# ---------- 主程式 ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--layers", default="~/Downloads/AscCatSamurai2.0", help="圖層資料夾")
    ap.add_argument("--originals", default=".tmp/images_2048", help="0~30 號原圖所在資料夾（找不到就用 images/ 裡現有的）")
    ap.add_argument("--size", type=int, default=1024, help="輸出尺寸（預設 1024）")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    ap.add_argument("--out", default="images")
    ap.add_argument("--reroll", action="store_true", help="重新抽 31~499 號的組合（覆寫 JSON 並重畫圖片）")
    a = ap.parse_args()

    layers = Path(os.path.expanduser(a.layers))
    originals = (ROOT / os.path.expanduser(a.originals)).resolve()
    out_dir = ROOT / a.out
    meta_dir = ROOT / "source" / "metadata"
    out_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    opts = load_options(layers)
    by_name = {c: {n: p for n, p, _ in opts[c]} for c in ORDER}
    for c in ORDER:
        by_name[c].update({n: None for n in NONE_NAMES} if c == "Dress" else {})

    def done(tid):
        if a.reroll and tid >= MINTED:
            return False
        f = out_dir / f"{tid}.png"
        if not f.exists():
            return False
        try:
            return Image.open(f).size == (a.size, a.size)
        except Exception:
            return False

    # 讀既有 metadata；缺的就抽新組合
    attrs = {}
    for tid in range(TOTAL):
        f = meta_dir / f"{tid}.json"
        if a.reroll and tid >= MINTED:
            continue
        if f.exists():
            attrs[tid] = [x["value"] for x in json.loads(f.read_text())["attributes"]]
    missing_minted = [t for t in range(MINTED) if t not in attrs]
    if missing_minted:
        sys.exit(f"缺少已 mint 的 metadata：{missing_minted}，請先補齊 source/metadata/")

    rng = random.Random(SEED)
    seen = {tuple(v) for v in attrs.values()}
    new_meta = 0
    for tid in range(MINTED, TOTAL):
        if tid in attrs:
            continue
        while True:
            pick = [rng.choices(opts[c], weights=[w for *_, w in opts[c]])[0][0] for c in ORDER]
            if tuple(pick) not in seen:
                seen.add(tuple(pick)); attrs[tid] = pick; break
        (meta_dir / f"{tid}.json").write_text(json.dumps({
            "name": f"AscCatSamurai #{tid}",
            "description": "This is a collection about AscCatSamurai",
            "image": f"ipfs://{IMG_CID}/{tid}.png",
            "edition": tid,
            "date": int(time.time() * 1000),
            "attributes": [{"trait_type": c, "value": v} for c, v in zip(ORDER, pick)],
            "compiler": "HashLips Art Engine",
        }, indent=2, ensure_ascii=False))
        new_meta += 1
    if new_meta:
        print(f"新增 metadata：{new_meta} 個")
    # 機率報表
    print("\n各類別出現機率（31~499 抽卡設定）：")
    for c in ORDER:
        tot = sum(w for *_, w in opts[c])
        print(f"  {c}: " + "、".join(f"{n} {w / tot:.1%}" for n, _, w in sorted(opts[c], key=lambda x: -x[2])))
    print()

    # 建立工作清單
    jobs = []
    for tid in range(TOTAL):
        if done(tid):
            continue
        out = str(out_dir / f"{tid}.png")
        if tid < MINTED:
            src = originals / f"{tid}.png"
            if not src.exists():
                src = out_dir / f"{tid}.png"
            if not src.exists():
                print(f"⚠️  找不到 {tid} 號原圖，略過"); continue
            jobs.append((job_resize, (tid, str(src), a.size, out)))
        else:
            try:
                paths = [by_name[c][v] for c, v in zip(ORDER, attrs[tid])]
            except KeyError as e:
                print(f"⚠️  {tid} 號的 trait {e} 沒有對應圖層，略過"); continue
            jobs.append((job_compose, (tid, paths, a.size, out)))

    if not jobs:
        print(f"全部 {TOTAL} 張都已是 {a.size}x{a.size}，不需處理。"); return
    print(f"要處理 {len(jobs)} 張，尺寸 {a.size}，使用 {a.workers} 個核心…")
    t0 = time.time(); n = 0
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(fn, *args) for fn, args in jobs]
        for f in as_completed(futs):
            f.result(); n += 1
            if n % 20 == 0 or n == len(jobs):
                el = time.time() - t0
                print(f"  {n}/{len(jobs)}  已用 {el:.0f}s，預估剩 {el / n * (len(jobs) - n):.0f}s", flush=True)
    print("完成！下一步：python3 scripts/build_metadata.py")


if __name__ == "__main__":
    main()
