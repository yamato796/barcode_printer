#!/bin/bash
# 自動偵測專案路徑並安裝桌面捷徑與開機自動啟動
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LAUNCH_SCRIPT="$PROJECT_DIR/launch.sh"
DESKTOP_FILE="$PROJECT_DIR/barcode_printer.desktop"

echo "專案路徑: $PROJECT_DIR"

# 確保 launch.sh 可執行
chmod +x "$LAUNCH_SCRIPT"

# 用實際路徑產生 .desktop 檔
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Barcode Printer
Exec=$LAUNCH_SCRIPT
Path=$PROJECT_DIR
Icon=utilities-terminal
Terminal=false
Categories=Utility;
X-GNOME-Autostart-enabled=true
EOF

echo "產生 .desktop: $DESKTOP_FILE"

# 安裝到應用程式選單
mkdir -p ~/.local/share/applications
cp "$DESKTOP_FILE" ~/.local/share/applications/
echo "已安裝到應用程式選單"

# 安裝到開機自動啟動
mkdir -p ~/.config/autostart
cp "$DESKTOP_FILE" ~/.config/autostart/
echo "已安裝開機自動啟動"

echo "完成！重新開機後將自動執行。"
