#!/bin/bash
# 從 OpenSea 的圖片快取下載已 mint 的 1~30 號（2048x2048 PNG）
#   bash scripts/download_from_opensea.sh
cd "$(dirname "$0")/.." || exit 1
mkdir -p images
fail=0
while IFS=$'\t' read -r id url; do
  out="images/$id.png"
  if [ -s "$out" ]; then echo "略過 $id（已存在）"; continue; fi
  if curl -fsSL --max-time 90 -H "Accept: image/png" -o "$out.part" "$url?w=2048&format=png" \
     && file "$out.part" | grep -q "PNG image"; then
    mv "$out.part" "$out"; echo "✅ $id"
  else
    rm -f "$out.part"; echo "❌ $id"; fail=$((fail+1))
  fi
  sleep 1
done < scripts/opensea_images.tsv
echo "完成，失敗 $fail 張。images/ 共 $(ls images/*.png 2>/dev/null | wc -l | tr -d ' ') 張"
