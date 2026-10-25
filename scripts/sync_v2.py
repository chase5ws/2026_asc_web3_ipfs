#!/usr/bin/env python3
"""
V2 自動出圖：讀鏈上 AscCatSamuraiV2 每一顆的配件，有新鑄造或換裝就重畫圖片、更新 metadata。
GitHub Action 每 10 分鐘跑一次（.github/workflows/sync-v2.yml），也可以手動執行：
    NFT_V2_ADDRESS=0x... python3 scripts/sync_v2.py
環境變數：
    NFT_V2_ADDRESS  V2 合約地址（必填）
    RPC_URL         Polygon RPC（預設 https://polygon-bor-rpc.publicnode.com）
    SITE_URL        GitHub Pages 網址（預設 https://chase5ws.github.io/2026_asc_web3_ipfs）
輸出：v2/metadata/<id>.json、v2/images/<id>.png、v2/state.json（記錄每顆目前畫的是哪個組合）
"""
import json, os, sys, time, urllib.request
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
TRAITS = json.loads((ROOT / "traits.json").read_text(encoding="utf-8"))
LEGACY = json.loads((ROOT / "contract" / "legacy-traits.json").read_text())
OUT = ROOT / "v2"
SIZE = 1024
ADDRESS = os.environ.get("NFT_V2_ADDRESS", "").strip()
RPC = os.environ.get("RPC_URL", "").strip() or "https://polygon-bor-rpc.publicnode.com"
SITE = (os.environ.get("SITE_URL", "").strip() or "https://chase5ws.github.io/2026_asc_web3_ipfs").rstrip("/")

SEL_NEXT_ID = "0x61b8ce8c"        # nextId()
SEL_TRAITS_RANGE = "0xb0afa776"   # traitsRange(uint256,uint256)
BATCH = 200


def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for attempt in range(5):
        try:
            req = urllib.request.Request(RPC, body, {"Content-Type": "application/json", "User-Agent": "asc-sync"})
            res = json.loads(urllib.request.urlopen(req, timeout=30).read())
            if "error" in res:
                raise RuntimeError(res["error"])
            return res["result"]
        except Exception as e:
            if attempt == 4:
                raise
            print(f"RPC 重試（{e}）")
            time.sleep(3 * (attempt + 1))


def call(data):
    return bytes.fromhex(rpc("eth_call", [{"to": ADDRESS, "data": data}, "latest"])[2:])


def word(b, i):
    return int.from_bytes(b[32 * i: 32 * i + 32], "big")


def traits_range(a, b):
    data = SEL_TRAITS_RANGE + a.to_bytes(32, "big").hex() + b.to_bytes(32, "big").hex()
    r = call(data)
    o1, o2 = word(r, 0) // 32, word(r, 1) // 32
    n = word(r, o1)
    exists = [word(r, o1 + 1 + i) != 0 for i in range(n)]
    packed = [word(r, o2 + 1 + i) for i in range(word(r, o2))]
    return exists, packed


def unpack(p):
    return [(p >> (8 * c)) & 0xFF for c in range(5)]


_cache = {}
def layer(path):
    if path not in _cache:
        im = Image.open(ROOT / path).convert("RGBA")
        if im.size != (SIZE, SIZE):
            im = im.resize((SIZE, SIZE), Image.LANCZOS)
        _cache[path] = im
    return _cache[path]


def render(tid, t, out):
    # 舊 0~30 號沒換過裝 → 用原圖
    if tid < len(LEGACY) and t == LEGACY[tid] and (ROOT / "images" / f"{tid}.png").exists():
        im = Image.open(ROOT / "images" / f"{tid}.png").convert("RGBA")
        if im.size != (SIZE, SIZE):
            im = im.resize((SIZE, SIZE), Image.LANCZOS)
    else:
        im = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        for c, cat in enumerate(TRAITS["categories"]):
            f = cat["options"][t[c]]["file"]
            if f:
                im.alpha_composite(layer(f))
    im.save(out, "PNG", optimize=True)


def metadata(tid, t, version):
    attrs, tiers = [], []
    for c, cat in enumerate(TRAITS["categories"]):
        o = cat["options"][t[c]]
        attrs.append({"trait_type": cat["trait_type"], "value": o["name"]})
        tiers.append(o["tier"])
    rarity = "Super Rare" if "super" in tiers else "Rare" if "rare" in tiers else "Common"
    attrs.append({"trait_type": "Rarity", "value": rarity})
    if tid < len(LEGACY):
        attrs.append({"trait_type": "Edition", "value": "Genesis"})
    return {
        "name": f"AscCatSamurai #{tid}",
        "description": "AscCatSamurai V2 - ASC鏢局的喵武士。配件記錄在 Polygon 鏈上，可以換裝。",
        "image": f"{SITE}/v2/images/{tid}.png?v={version}",
        "attributes": attrs,
    }


def main():
    if not ADDRESS:
        sys.exit("請設定 NFT_V2_ADDRESS")
    (OUT / "metadata").mkdir(parents=True, exist_ok=True)
    (OUT / "images").mkdir(parents=True, exist_ok=True)
    state_file = OUT / "state.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}

    next_id = word(call(SEL_NEXT_ID), 0)
    changed = 0
    for a in range(0, next_id, BATCH):
        exists, packed = traits_range(a, min(a + BATCH, next_id))
        for i, (ok, p) in enumerate(zip(exists, packed)):
            tid = a + i
            if not ok:
                continue
            key = str(tid)
            img = OUT / "images" / f"{tid}.png"
            if state.get(key) == p and img.exists():
                continue
            t = unpack(p)
            if any(t[c] >= len(TRAITS["categories"][c]["options"]) for c in range(5)):
                print(f"⚠️  {tid} 號配件 {t} 超出 traits.json，請先更新 traits.json 與 layers/")
                continue
            render(tid, t, img)
            (OUT / "metadata" / f"{tid}.json").write_text(
                json.dumps(metadata(tid, t, p), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            state[key] = p
            changed += 1
            print(f"✅ {tid} {[TRAITS['categories'][c]['options'][t[c]]['name'] for c in range(5)]}")
    state_file.write_text(json.dumps(state, indent=0, sort_keys=True))
    print(f"完成：鏈上 nextId={next_id}，本次更新 {changed} 顆")


if __name__ == "__main__":
    main()
