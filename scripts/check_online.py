#!/usr/bin/env python3
"""部署到 GitHub Pages 後，抽查網址是否打得開。用法：python3 scripts/check_online.py [數量，預設 5]"""
import json
import sys
import urllib.request

BASE_URL = "https://chase5ws.github.io/2026_asc_web3_ipfs"
n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
ok = True
for tid in range(n):
    url = f"{BASE_URL}/metadata/{tid}.json"
    try:
        data = json.load(urllib.request.urlopen(url, timeout=15))
        img = data.get("image", "")
        code = urllib.request.urlopen(urllib.request.Request(img, method="HEAD"), timeout=15).status
        print(f"✅ {tid}.json  image {code}  {img}")
    except Exception as e:
        ok = False
        print(f"❌ {tid}  {url}  -> {e}")
sys.exit(0 if ok else 1)
