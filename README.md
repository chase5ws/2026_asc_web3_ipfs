# 2026_asc_web3_ipfs

AscCatSamurai NFT 的 metadata 與圖片，透過 **GitHub Pages** 提供，取代已失效的 IPFS 存放。

- 網站：https://chase5ws.github.io/2026_asc_web3_ipfs/
- 合約 baseURI：`https://chase5ws.github.io/2026_asc_web3_ipfs/metadata/`
- 合約（Polygon）：`0x39c774673a25b0f1f600bf39edf639c0f44a7488`
- 合約原始碼：[2024_web3_solidity_asc_smart_contract](https://github.com/chase5ws/2024_web3_solidity_asc_smart_contract)

## 資料夾結構

```
images/            # 圖片（0.png ~ 499.png），直接放這裡
source/metadata/   # 原始 JSON（image 還是舊的 IPFS 網址），放這裡
metadata/          # 由腳本產生，image 已改成 GitHub Pages 網址 ← 合約讀這裡
scripts/
  download_from_ipfs.sh # 從舊 IPFS 抓回 JSON 與圖片
  build_metadata.py  # source/metadata → metadata，並改寫 image 網址
  check_online.py    # 部署後抽查網址
.nojekyll          # 讓 GitHub Pages 原樣提供檔案
```

## 使用步驟

0. 第一次使用先安裝 Pillow：`pip3 install pillow`
1. 產生圖片（0~30 號用原圖縮放；31~499 號用 `~/Downloads/AscCatSamurai2.0` 圖層疊圖）：
   ```bash
   python3 scripts/generate.py --reroll   # 第一次：依新的稀有度重新抽 31~499
   python3 scripts/generate.py            # 之後中斷了就直接重跑，會自動續做
   ```
   - 可加 `--size 2048`（預設 1024）、`--workers 8`（預設 CPU 核心數 - 1）
   - 稀有度設定在 `scripts/generate.py` 的 `RARITY`
2. 產生 GitHub Pages 用的 metadata：`python3 scripts/build_metadata.py`
3. 推上 GitHub：
   ```bash
   git add . && git commit -m "Add NFT metadata and images" && git push
   ```
4. GitHub repo → **Settings → Pages** → Source 選 `Deploy from a branch`，Branch 選 `main` / `(root)` → Save。
5. 等 1～2 分鐘，抽查：`python3 scripts/check_online.py 5`
6. 到 Polygonscan 合約頁 → **Write Contract** → 連接 owner 錢包 → 呼叫：
   ```
   setBaseURI("https://chase5ws.github.io/2026_asc_web3_ipfs/metadata/")
   ```
   （結尾的 `/` 不能少）
7. **Read Contract** → `tokenURI(0)` 確認回傳 `.../metadata/0.json`。
8. 到 OpenSea 各 NFT 頁面按 **Refresh metadata**。

## 稀有度

同一類別內每個選項機率相同（Dress 的「無配件」也算一個選項），以下特殊款例外：

| 等級 | 項目 | 約略機率 |
|---|---|---|
| 超稀有 | Common99 金色閃電眼、Sword99 金柄武士刀、Armor1 黃金鎧甲 | ~1% |
| 稀有 | Scar2 紅眼刀疤、Armor2 粉色鎧甲、Original0/1 長毛耳環貓、Fox mask0 狐狸面具 | ~3% |

0~30 號為已 mint 的原版，不會被更動。

## 注意

- repo 必須是 **Public**（免費方案的 GitHub Pages 只支援公開 repo）。
- 不要改 repo 名稱或 GitHub 帳號名稱，否則網址會變，要重新 `setBaseURI`。
- GitHub Pages 單一站台建議 < 1 GB，單檔 < 100 MB。

## V2 同步輸出（scripts/sync_v2.py，GitHub Action 自動跑）
- `v2/state.json`、`v2/metadata/<id>.json`、`v2/images/<id>.png`：每顆喵武士的穿著、metadata、圖片
- `v2/parts/<配件編號>.json`、`v2/thumbs/<配件編號>.png`：配件道具（ERC-1155）的 metadata 與縮圖；traits.json 新增選項會自動產生（配件編號＝部位 × 256＋選項）
- `v2/price.json`：金庫每 1 ASC 價值的走勢（網站行情圖用；金庫地址可用 Variables `VAULT_V2_ADDRESS` 改，預設主網）
