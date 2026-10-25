#!/usr/bin/env python3
"""
把 source/metadata/ 裡的原始 JSON 轉成 GitHub Pages 用的版本，輸出到 metadata/。

- 輸出檔名一律是 <tokenId>.json（合約 tokenURI() 會接上 ".json"）
- 每個 JSON 的 "image" 會改成 GitHub Pages 上 images/ 的網址
- 會檢查 0 ~ MAX_SUPPLY-1 的 JSON 和圖片是否齊全

用法：
    python3 scripts/build_metadata.py            # 實際產生
    python3 scripts/build_metadata.py --dry-run  # 只檢查，不寫檔
"""
import json
import re
import sys
from pathlib import Path

BASE_URL = "https://chase5ws.github.io/2026_asc_web3_ipfs"
MAX_SUPPLY = 500
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".mp4")

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "metadata"
OUT = ROOT / "metadata"
IMAGES = ROOT / "images"


def find_source(token_id: int):
    for name in (f"{token_id}.json", f"{token_id}"):
        p = SRC / name
        if p.is_file():
            return p
    return None


def find_image(token_id: int, original_url: str):
    # 1) 先用原本 image 網址裡的檔名（例如 ipfs://Qm.../12.png -> 12.png）
    if original_url:
        name = re.split(r"[/\\]", original_url.split("?")[0])[-1]
        if name and (IMAGES / name).is_file():
            return name
    # 2) 再用 tokenId + 常見副檔名
    for ext in IMAGE_EXTS:
        if (IMAGES / f"{token_id}{ext}").is_file():
            return f"{token_id}{ext}"
    return None


def main():
    dry = "--dry-run" in sys.argv
    missing_json, missing_img, done = [], [], 0
    for tid in range(MAX_SUPPLY):
        src = find_source(tid)
        if not src:
            missing_json.append(tid)
            continue
        data = json.loads(src.read_text(encoding="utf-8"))
        img = find_image(tid, data.get("image", ""))
        if not img:
            missing_img.append(tid)
            continue
        data["image"] = f"{BASE_URL}/images/{img}"
        if not dry:
            (OUT / f"{tid}.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        done += 1

    print(f"{'檢查' if dry else '產生'}完成：{done}/{MAX_SUPPLY}")
    if missing_json:
        print(f"缺少 JSON（{len(missing_json)}）：{missing_json[:20]}{' ...' if len(missing_json) > 20 else ''}")
    if missing_img:
        print(f"找不到圖片（{len(missing_img)}）：{missing_img[:20]}{' ...' if len(missing_img) > 20 else ''}")
    print(f"\n部署後在合約呼叫：setBaseURI(\"{BASE_URL}/metadata/\")")
    return 1 if (missing_json or missing_img) else 0


if __name__ == "__main__":
    sys.exit(main())
