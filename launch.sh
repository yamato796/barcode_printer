#!/bin/bash
# 切換到腳本所在目錄（確保相對路徑如 IMG_0114.PNG 可以找到）
cd "$(dirname "$0")"

# 載入 pyenv（若有安裝）
export PATH="$HOME/.pyenv/shims:$HOME/.pyenv/bin:$PATH"
eval "$(pyenv init - 2>/dev/null)" || true

# 等待桌面環境就緒
sleep 3

exec python3 barcode_with_midi.py
