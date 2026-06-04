#!/bin/bash
# ============================================================
# Polymarket 套利引擎 - 部署脚本
# 适用于 Ubuntu / Debian / Fedora / Arch Linux
# ============================================================

set -euo pipefail

APP_DIR="/opt/polymarket-arb"
SERVICE_USER="polymarket"
PYTHON_CMD="python3"

echo "╔══════════════════════════════════════════╗"
echo "║  Polymarket 套利引擎 - 部署脚本 v1.0    ║"
echo "╚══════════════════════════════════════════╝"

# ---- 1. 创建系统用户 ----
echo "[1/6] 创建系统用户: ${SERVICE_USER}..."
if ! id -u ${SERVICE_USER} > /dev/null 2>&1; then
    sudo useradd -r -s /bin/false -d ${APP_DIR} ${SERVICE_USER}
    echo "  ✓ 用户 ${SERVICE_USER} 已创建"
else
    echo "  ✓ 用户 ${SERVICE_USER} 已存在"
fi

# ---- 2. 安装依赖 ----
echo "[2/6] 安装系统依赖..."
if command -v apt-get &> /dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y python3 python3-pip python3-venv
elif command -v dnf &> /dev/null; then
    sudo dnf install -y python3 python3-pip
elif command -v pacman &> /dev/null; then
    sudo pacman -S --noconfirm python python-pip
fi

# ---- 3. 拷贝项目文件 ----
echo "[3/6] 拷贝项目文件到 ${APP_DIR}..."
sudo mkdir -p ${APP_DIR}/db
sudo cp -r . ${APP_DIR}/
sudo cp .env.example ${APP_DIR}/.env.example

# ---- 4. 创建 Python 虚拟环境 ----
echo "[4/6] 创建 Python 虚拟环境..."
sudo ${PYTHON_CMD} -m venv ${APP_DIR}/venv
sudo ${APP_DIR}/venv/bin/pip install --upgrade pip
sudo ${APP_DIR}/venv/bin/pip install -r ${APP_DIR}/requirements.txt

# ---- 5. 创建数据库目录 ----
echo "[5/6] 初始化数据库目录..."
sudo mkdir -p ${APP_DIR}/db
sudo chown -R ${SERVICE_USER}:${SERVICE_USER} ${APP_DIR}

# ---- 6. 安装 systemd 服务 ----
echo "[6/6] 安装 systemd 服务..."
sudo cp deploy/polymarket-arb.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable polymarket-arb

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║           部署完成!                       ║"
echo "╠══════════════════════════════════════════╣"
echo "║                                          ║"
echo "║  ⚠️  请编辑配置文件:                      ║"
echo "║      sudo nano ${APP_DIR}/.env           ║"
echo "║                                          ║"
echo "║  启动服务:                                ║"
echo "║      sudo systemctl start polymarket-arb ║"
echo "║                                          ║"
echo "║  查看日志:                                ║"
echo "║      journalctl -u polymarket-arb -f     ║"
echo "║                                          ║"
echo "║  影子系统测试 (不执行下单):                 ║"
echo "║      cd ${APP_DIR}                       ║"
echo "║      ./venv/bin/python main.py --dry-run ║"
echo "║                                          ║"
echo "╚══════════════════════════════════════════╝"