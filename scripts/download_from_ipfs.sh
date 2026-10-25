#!/bin/bash
# 從 IPFS 慢慢把原本的 metadata 和圖片抓回來（請在 Mac「終端機」執行）
#   bash scripts/download_from_ipfs.sh          # 先抓已 mint 的 0~30
#   bash scripts/download_from_ipfs.sh 500      # 再抓全部 0~499
# 遇到 429（請求太頻繁）會自動暫停再試；中斷後重跑會跳過已下載的檔案。

META_CID="QmUwNukp3RLYioJZFkz5UTkkoAvNnV9rBfSVkMRg5pA4x9"
IMG_CID="QmY8upzoVGvrdhCSi2NZmprUWcgRQWzkcYjuHHkA17vQZX"
MAX=${1:-31}
DELAY=${DELAY:-3}          # 每個請求之間等幾秒
GATEWAYS="https://gateway.pinata.cloud/ipfs https://ipfs.io/ipfs https://dweb.link/ipfs https://w3s.link/ipfs https://4everland.io/ipfs"

cd "$(dirname "$0")/.." || exit 1
mkdir -p source/metadata images

fetch() {  # fetch <cid/path> <output>
  [ -s "$2" ] && return 0
  for try in 1 2 3 4 5; do
    for gw in $GATEWAYS; do
      code=$(curl -sSL --max-time 90 -o "$2.part" -w "%{http_code}" "$gw/$1" 2>/dev/null)
      if [ "$code" = "200" ] && [ -s "$2.part" ]; then
        mv "$2.part" "$2"; sleep "$DELAY"; return 0
      fi
      sleep "$DELAY"
    done
    wait=$((try * 30))
    echo "  ⏳ $1 暫時抓不到（最後狀態 $code），等 ${wait} 秒再試…"
    sleep $wait
  done
  rm -f "$2.part"; echo "❌ 失敗：$1"; return 1
}

fail=0
for ((i=0; i<MAX; i++)); do
  fetch "$META_CID/$i.json" "source/metadata/$i.json" || fail=$((fail+1))
  fetch "$IMG_CID/$i.png"   "images/$i.png"            || fail=$((fail+1))
  echo "✅ $i / $((MAX-1))"
done

echo "完成。失敗 $fail 個（重跑即可補抓）。"
echo "metadata：$(ls source/metadata/*.json 2>/dev/null | wc -l | tr -d ' ') 個，圖片：$(ls images/*.png 2>/dev/null | wc -l | tr -d ' ') 張"
