#!/usr/bin/env python3
"""
V2 喵武士外觀同步（穿著以這裡的 JSON 為準）：讀 AscCatSamuraiV2 的鏈上事件，更新 v2/state.json，再產生每顆的圖片與 metadata。
GitHub Action 每 10 分鐘跑一次（.github/workflows/sync-v2.yml），也可以手動執行：
    NFT_V2_ADDRESS=0x... FROM_BLOCK=部署區塊 python3 scripts/sync_v2.py

合約只管「誰擁有幾號」和會動到資產的事，外觀全部在鏈下：
  鑄造（Minted＋RandomSeed）  第一次看到時依 seed 與 traits.json 的機率算出外觀，之後就寫死（改機率不影響已鑄造的）
                              第 c 類 roll = uint256(keccak256(abi.encode(seed, c))) % 該類權重總和
  空投指定外觀（PresetMinted） 複製舊系列 V1 metadata/<ref>.json 的配件
  解盲（Revealed）            之後才公開外觀，之前顯示盲盒
  換裝（Equipped）            partIds 穿上（partId＝部位 × 256 + 選項），clearSlots 脫掉（只限有「不穿」選項的部位）

管理員可以直接改外觀（例如幫某幾顆加寵物、背景）：
  1. 在 v2/overrides.json 寫 {"編號": {"部位": "選項名稱"}}，每次同步都會套用在最上層（最簡單，建議用這個）
  2. 或直接改 v2/state.json 的 tokens.<編號>.traits
  改完 push，下次同步就重畫；再用 admin 呼叫合約 refreshMetadata(0, 最大編號) 通知 OpenSea 重新讀取。

新增部位（寵物、背景、副武器…）：在 traits.json 的 categories 最後面加一類（選項第一個建議是 "file": null 的「不穿」），
order 決定圖層上下順序。traits.json 的部位與選項只能在後面新增，不能刪除或調換（配件道具的編號依這個順序）。
舊的 NFT 在新部位會是「不穿」，之後抽轉蛋或買配件再換裝穿上；新鑄造的盲盒會連新部位一起抽。

環境變數：
    NFT_V2_ADDRESS  V2 合約地址（必填）
    FROM_BLOCK      合約部署區塊（第一次同步從這裡開始；之後記在 state.json）
    RPC_URL         Polygon RPC（預設 https://polygon-bor-rpc.publicnode.com）
    SITE_URL        GitHub Pages 網址（預設 https://chase5ws.github.io/2026_asc_web3_ipfs）
    LOG_STEP        每次 eth_getLogs 的區塊數（預設 2000，公共 RPC 有上限）
輸出：v2/state.json、v2/metadata/<id>.json、v2/images/<id>.png、v2/images/box.png（盲盒）
"""
import hashlib, json, os, sys, time, urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("ASC_IPFS_ROOT", "") or Path(__file__).resolve().parent.parent)
TRAITS = json.loads((ROOT / "traits.json").read_text(encoding="utf-8"))
OUT = ROOT / "v2"
SIZE = 1024
ADDRESS = os.environ.get("NFT_V2_ADDRESS", "").strip().lower()
RPC = os.environ.get("RPC_URL", "").strip() or "https://polygon-bor-rpc.publicnode.com"
SITE = (os.environ.get("SITE_URL", "").strip() or "https://chase5ws.github.io/2026_asc_web3_ipfs").rstrip("/")
STEP = int(os.environ.get("LOG_STEP", "") or 2000)
FROM_BLOCK = int(os.environ.get("FROM_BLOCK", "") or 0)
CONFIRMATIONS = int(os.environ.get("CONFIRMATIONS", "") or 5)

# ───────────── keccak256（純 Python，免安裝套件） ─────────────
_RC = [0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000, 0x000000000000808B, 0x0000000080000001,
       0x8000000080008081, 0x8000000000008009, 0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
       0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003, 0x8000000000008002, 0x8000000000000080,
       0x000000000000800A, 0x800000008000000A, 0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008]
_ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
_M = (1 << 64) - 1


def _rol(x, n):
    return ((x << n) | (x >> (64 - n))) & _M if n else x


def _f(a):
    for rc in _RC:
        c = [a[x][0] ^ a[x][1] ^ a[x][2] ^ a[x][3] ^ a[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        a = [[a[x][y] ^ d[x] for y in range(5)] for x in range(5)]
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rol(a[x][y], _ROT[x][y])
        a = [[b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y]) for y in range(5)] for x in range(5)]
        a[0][0] ^= rc
    return a


def keccak(data: bytes) -> bytes:
    rate = 136
    msg = bytearray(data) + b"\x01"
    msg += b"\x00" * ((-len(msg)) % rate)
    msg[-1] |= 0x80
    a = [[0] * 5 for _ in range(5)]
    for off in range(0, len(msg), rate):
        blk = msg[off:off + rate]
        for i in range(rate // 8):
            x, y = i % 5, i // 5
            a[x][y] ^= int.from_bytes(blk[8 * i:8 * i + 8], "little")
        a = _f(a)
    out = b"".join(a[i % 5][i // 5].to_bytes(8, "little") for i in range(4))
    return out


def topic(sig):
    return "0x" + keccak(sig.encode()).hex()


T_MINTED = topic("Minted(uint256,address,uint8)")
T_PRESET = topic("PresetMinted(uint256,uint256)")
T_REVEALED = topic("Revealed(uint256,address)")
T_EQUIPPED = topic("Equipped(uint256,address,uint256[],uint256[])")
T_SEED = topic("RandomSeed(address,uint8,uint256,bytes32,uint256,uint256,bytes32)")

# ───────────── RPC ─────────────


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


def word(data: bytes, i: int) -> int:
    return int.from_bytes(data[32 * i:32 * i + 32], "big")


def uint_array(data: bytes, offset_word: int):
    start = word(data, offset_word) // 32
    n = word(data, start)
    return [word(data, start + 1 + k) for k in range(n)]


def logs(frm, to):
    out = []
    a = frm
    step = STEP
    while a <= to:
        b = min(a + step - 1, to)
        try:
            out += rpc("eth_getLogs", [{"address": ADDRESS, "fromBlock": hex(a), "toBlock": hex(b),
                                        "topics": [[T_MINTED, T_PRESET, T_REVEALED, T_EQUIPPED, T_SEED]]}])
            a = b + 1
        except Exception as e:
            if step <= 50:
                raise
            step //= 2
            print(f"縮小查詢範圍到 {step} 個區塊（{e}）")
    out.sort(key=lambda l: (int(l["blockNumber"], 16), int(l["logIndex"], 16)))
    return out

# ───────────── 外觀 ─────────────

CATS = TRAITS["categories"]
BY_TYPE = {c["trait_type"]: c for c in CATS}
ALIASES = TRAITS.get("aliases", {})


def empty_option(cat):
    return next((o for o in cat["options"] if not o.get("file")), None)


def weight(o):
    return int(o.get("weight", TRAITS["weights"].get(o.get("tier", "normal"), 0)))


def roll_traits(seed_hex):
    """依 seed 算外觀：第 c 類 roll = keccak256(abi.encode(seed, c)) % 權重總和"""
    seed = bytes.fromhex(seed_hex[2:])
    traits = {}
    for c, cat in enumerate(CATS):
        opts = [o for o in cat["options"] if weight(o) > 0]
        total = sum(weight(o) for o in opts)
        if total == 0:
            e = empty_option(cat)
            if e:
                traits[cat["trait_type"]] = e["name"]
            continue
        r = int.from_bytes(keccak(seed + c.to_bytes(32, "big")), "big") % total
        acc = 0
        for o in cat["options"]:
            acc += weight(o)
            if weight(o) and r < acc:
                traits[cat["trait_type"]] = o["name"]
                break
    return traits


def v1_traits(ref):
    m = json.loads((ROOT / "metadata" / f"{ref}.json").read_text(encoding="utf-8"))
    traits = {}
    for a in m.get("attributes", []):
        t, v = a.get("trait_type"), a.get("value")
        if t in BY_TYPE:
            traits[t] = ALIASES.get(t, {}).get(v, v)
    return traits


def apply_equip(tok, part_ids, clear_slots, tid):
    traits = tok.setdefault("traits", {})
    for pid in part_ids:
        c, i = pid // 256, pid % 256
        if c >= len(CATS) or i >= len(CATS[c]["options"]):
            print(f"⚠️  {tid} 號穿上的配件 {pid}（部位 {c} 選項 {i}）不在 traits.json，先記下，更新 traits.json 後會顯示")
            tok.setdefault("pending", []).append(pid)
            continue
        traits[CATS[c]["trait_type"]] = CATS[c]["options"][i]["name"]
    for c in clear_slots:
        if c < len(CATS) and empty_option(CATS[c]):
            traits[CATS[c]["trait_type"]] = empty_option(CATS[c])["name"]
        else:
            print(f"⚠️  {tid} 號要脫掉部位 {c}，但這個部位沒有「不穿」選項，略過")


def resolve_pending(tok):
    """之前 traits.json 還沒有的配件，更新後補上"""
    left = []
    for pid in tok.get("pending", []):
        c, i = pid // 256, pid % 256
        if c < len(CATS) and i < len(CATS[c]["options"]):
            tok.setdefault("traits", {})[CATS[c]["trait_type"]] = CATS[c]["options"][i]["name"]
        else:
            left.append(pid)
    if left:
        tok["pending"] = left
    else:
        tok.pop("pending", None)


def final_traits(tok, override):
    """每個部位最後的選項（新部位沒資料＝不穿），回傳 [(類別, 選項)]"""
    traits = dict(tok.get("traits") or {})
    traits.update(override or {})
    out = []
    for cat in CATS:
        name = traits.get(cat["trait_type"])
        o = next((x for x in cat["options"] if x["name"] == name), None) if name else None
        if o is None:
            if name:
                print(f"⚠️  選項 {cat['trait_type']} / {name} 不在 traits.json，當作不穿")
            o = empty_option(cat)
        if o is not None:
            out.append((cat, o))
    return out

# ───────────── 出圖與 metadata ─────────────

_cache = {}


def layer(path):
    from PIL import Image
    if path not in _cache:
        im = Image.open(ROOT / path).convert("RGBA")
        if im.size != (SIZE, SIZE):
            im = im.resize((SIZE, SIZE), Image.LANCZOS)
        _cache[path] = im
    return _cache[path]


def draw_order(picks):
    order = TRAITS.get("order") or [c["trait_type"] for c in CATS]
    rank = {t: i for i, t in enumerate(order)}
    return sorted(picks, key=lambda p: rank.get(p[0]["trait_type"], len(order) + CATS.index(p[0])))


def render(picks, out):
    from PIL import Image
    im = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    for _, o in draw_order(picks):
        if o.get("file"):
            im.alpha_composite(layer(o["file"]))
    im.save(out, "PNG", optimize=True)


def box_image(out):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (SIZE, SIZE), (11, 21, 48))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([160, 160, SIZE - 160, SIZE - 160], radius=80, outline=(212, 175, 106), width=18, fill=(19, 34, 74))
    try:
        from PIL import ImageFont
        f = ImageFont.load_default(size=420)
        d.text((SIZE / 2, SIZE / 2), "?", fill=(233, 238, 251), font=f, anchor="mm")
    except Exception:
        d.ellipse([SIZE / 2 - 60, SIZE / 2 + 140, SIZE / 2 + 60, SIZE / 2 + 260], fill=(233, 238, 251))
    im.save(out, "PNG", optimize=True)


def metadata(tid, tok, picks, version):
    if not tok.get("revealed"):
        return {
            "name": f"AscCatSamurai #{tid}",
            "description": "AscCatSamurai V2 盲盒 - 在 ASC 鏢局網站解盲後揭曉外觀。",
            "image": f"{SITE}/v2/images/box.png",
            "attributes": [{"trait_type": "Status", "value": "Unrevealed"}],
        }
    attrs, tiers = [], []
    for cat, o in picks:
        attrs.append({"trait_type": cat["trait_type"], "value": o["name"]})
        tiers.append(o.get("tier", "normal"))
    rarity = "Super Rare" if "super" in tiers else "Rare" if "rare" in tiers else "Common"
    attrs.append({"trait_type": "Rarity", "value": rarity})
    if tok.get("kind") == 3:
        attrs.append({"trait_type": "Origin", "value": f"V1 #{tok.get('ref')}"})
    return {
        "name": f"AscCatSamurai #{tid}",
        "description": "AscCatSamurai V2 - ASC 鏢局的喵武士。可以用配件換裝，配件道具記錄在 Polygon 鏈上。",
        "image": f"{SITE}/v2/images/{tid}.png?v={version}",
        "attributes": attrs,
    }


def main():
    if not ADDRESS:
        sys.exit("請設定 NFT_V2_ADDRESS")
    (OUT / "metadata").mkdir(parents=True, exist_ok=True)
    (OUT / "images").mkdir(parents=True, exist_ok=True)
    state_file = OUT / "state.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    if state.get("version") != 2 or state.get("contract") != ADDRESS:
        if state:
            print("state.json 是舊格式或別的合約，重新開始")
        state = {"version": 2, "contract": ADDRESS, "lastBlock": FROM_BLOCK - 1, "tokens": {}}
    tokens = state["tokens"]
    overrides_file = OUT / "overrides.json"
    overrides = json.loads(overrides_file.read_text(encoding="utf-8")) if overrides_file.exists() else {}

    head = int(rpc("eth_blockNumber", []), 16) - CONFIRMATIONS
    frm = state["lastBlock"] + 1
    if frm <= head:
        found = logs(frm, head)
        print(f"讀取區塊 {frm} ~ {head}：{len(found)} 筆事件")
        for l in found:
            t0 = l["topics"][0]
            data = bytes.fromhex(l["data"][2:])
            if t0 == T_SEED:
                if int(l["topics"][2], 16) != 1:  # 只看鑄造（purpose 1）；轉蛋在鏈上就決定了
                    continue
                tid = str(int(l["topics"][3], 16))
                tok = tokens.setdefault(tid, {})
                tok.setdefault("seed", "0x" + data[96:128].hex())
                continue
            tid = str(int(l["topics"][1], 16))
            tok = tokens.setdefault(tid, {})
            if t0 == T_MINTED:
                tok["kind"] = word(data, 0)
                tok.setdefault("revealed", False)
                tok["block"] = int(l["blockNumber"], 16)
            elif t0 == T_PRESET:
                tok["ref"] = word(data, 0)
            elif t0 == T_REVEALED:
                tok["revealed"] = True
            elif t0 == T_EQUIPPED:
                if not tok.get("traits"):
                    print(f"⚠️  {tid} 號還沒有外觀就換裝，略過")
                    continue
                apply_equip(tok, uint_array(data, 0), uint_array(data, 1), tid)
            # 第一次看到就把外觀寫死
            if not tok.get("traits"):
                if tok.get("ref") is not None:
                    tok["traits"] = v1_traits(tok["ref"])
                elif tok.get("seed") and tok.get("kind") in (1, 2):
                    tok["traits"] = roll_traits(tok["seed"])
        state["lastBlock"] = head

    box = OUT / "images" / "box.png"
    if not box.exists():
        box_image(box)

    changed = 0
    for tid in sorted(tokens, key=int):
        tok = tokens[tid]
        if not tok.get("traits") and tok.get("seed") and tok.get("kind") in (1, 2):
            tok["traits"] = roll_traits(tok["seed"])
        resolve_pending(tok)
        picks = final_traits(tok, overrides.get(tid))
        sig = hashlib.sha1(json.dumps([tok.get("revealed"), [(c["trait_type"], o["name"]) for c, o in picks]], ensure_ascii=False).encode()).hexdigest()[:12]
        img = OUT / "images" / f"{tid}.png"
        meta = OUT / "metadata" / f"{tid}.json"
        if tok.get("rendered") == sig and meta.exists() and (img.exists() or not tok.get("revealed")):
            continue
        if tok.get("revealed"):
            render(picks, img)
        meta.write_text(json.dumps(metadata(tid, tok, picks, sig), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tok["rendered"] = sig
        changed += 1
        print(f"✅ #{tid} {'（盲盒）' if not tok.get('revealed') else ' / '.join(o['name'] for _, o in picks)}")
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"完成：{len(tokens)} 顆，本次更新 {changed} 顆，同步到區塊 {state['lastBlock']}")


if __name__ == "__main__":
    main()
