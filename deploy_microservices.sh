#!/bin/bash
# 部署微服务架构到远程服务器
# 用法: bash deploy_microservices.sh [--rollback]

set -e

REMOTE_HOST="192.168.3.117"
REMOTE_USER="roy"
REMOTE_PASS="kaiyic"
REMOTE_DIR="/home/roy/polymarket-arb"

echo "=== Polymarket 微服务部署 ==="
echo "目标: ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}"

# 使用 sshpass 进行远程部署
SSH_CMD="sshpass -p ${REMOTE_PASS} ssh -o StrictHostKeyChecking=no ${REMOTE_USER}@${REMOTE_HOST}"
SCP_CMD="sshpass -p ${REMOTE_PASS} scp -o StrictHostKeyChecking=no"

if [[ "$1" == "--rollback" ]]; then
    echo "=== 回滚到单体架构 ==="
    $SSH_CMD "echo ${REMOTE_PASS} | sudo -S systemctl stop polymarket-mdg polymarket-spe polymarket-oeg polymarket-rmc 2>/dev/null || true"
    $SSH_CMD "echo ${REMOTE_PASS} | sudo -S systemctl disable polymarket-mdg polymarket-spe polymarket-oeg polymarket-rmc 2>/dev/null || true"
    $SSH_CMD "echo ${REMOTE_PASS} | sudo -S systemctl start polymarket-arb 2>/dev/null || true"
    echo "回滚完成 - 已恢复单体架构"
    exit 0
fi

# 1. 停止单体服务
echo "[1/6] 停止单体服务..."
$SSH_CMD "echo ${REMOTE_PASS} | sudo -S systemctl stop polymarket-arb 2>/dev/null || true"
$SSH_CMD "pkill -9 -f 'python.*main.py' 2>/dev/null || true"
sleep 2

# 2. 创建 services 目录
echo "[2/6] 上传微服务代码..."
$SSH_CMD "mkdir -p ${REMOTE_DIR}/services"

# 3. 上传微服务文件
$SCP_CMD -r ${REMOTE_DIR}/../polymarket-arb/services/*.py ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/services/ 2>/dev/null || \
$SCP_CMD services/*.py ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/services/

$SCP_CMD -r ${REMOTE_DIR}/../polymarket-arb/core/message_bus.py ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/core/message_bus.py 2>/dev/null || \
$SCP_CMD core/message_bus.py ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/core/

$SCP_CMD -r ${REMOTE_DIR}/../polymarket-arb/db/queue_schema.sql ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/db/queue_schema.sql 2>/dev/null || \
$SCP_CMD db/queue_schema.sql ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/db/

# 4. 上传 systemd 服务文件
echo "[3/6] 部署 systemd 服务文件..."
$SSH_CMD "sudo mkdir -p /etc/systemd/system/polymarket-services/"
for svc in mdg spe oeg rmc; do
    $SCP_CMD deploy/polymarket-${svc}.service ${REMOTE_USER}@${REMOTE_HOST}:/tmp/polymarket-${svc}.service
    $SSH_CMD "echo ${REMOTE_PASS} | sudo -S cp /tmp/polymarket-${svc}.service /etc/systemd/system/"
done
$SCP_CMD deploy/polymarket-arb.target ${REMOTE_USER}@${REMOTE_HOST}:/tmp/polymarket-arb.target
$SSH_CMD "echo ${REMOTE_PASS} | sudo -S cp /tmp/polymarket-arb.target /etc/systemd/system/"
$SCP_CMD deploy/polymarket-bus.target ${REMOTE_USER}@${REMOTE_HOST}:/tmp/polymarket-bus.target
$SSH_CMD "echo ${REMOTE_PASS} | sudo -S cp /tmp/polymarket-bus.target /etc/systemd/system/"

# 5. 初始化消息队列表
echo "[4/6] 初始化消息队列表..."
$SSH_CMD "cd ${REMOTE_DIR} && source venv/bin/activate && python3 -c \"
from core.message_bus import MessageBus
bus = MessageBus()
print('消息队列初始化完成')
print('队列深度:', bus.queue_depth())
\""

# 6. 启用并启动微服务
echo "[5/6] 启用微服务..."
$SSH_CMD "echo ${REMOTE_PASS} | sudo -S systemctl daemon-reload"
$SSH_CMD "echo ${REMOTE_PASS} | sudo -S systemctl disable polymarket-arb 2>/dev/null || true"

for svc in mdg spe oeg rmc; do
    $SSH_CMD "echo ${REMOTE_PASS} | sudo -S systemctl enable polymarket-${svc}"
done
$SSH_CMD "echo ${REMOTE_PASS} | sudo -S systemctl enable polymarket-arb.target"

echo "[6/6] 启动微服务..."
# 按顺序启动: MDG → SPE → OEG → RMC
$SSH_CMD "echo ${REMOTE_PASS} | sudo -S systemctl start polymarket-mdg"
sleep 5
$SSH_CMD "echo ${REMOTE_PASS} | sudo -S systemctl start polymarket-spe"
sleep 3
$SSH_CMD "echo ${REMOTE_PASS} | sudo -S systemctl start polymarket-oeg"
sleep 3
$SSH_CMD "echo ${REMOTE_PASS} | sudo -S systemctl start polymarket-rmc"

# 验证
echo ""
echo "=== 微服务状态 ==="
for svc in mdg spe oeg rmc; do
    STATUS=$($SSH_CMD "systemctl is-active polymarket-${svc}")
    echo "  polymarket-${svc}: ${STATUS}"
done

echo ""
echo "=== 微服务架构部署完成 ==="
echo ""
echo "常用命令:"
echo "  启动全部:  sudo systemctl start polymarket-arb.target"
echo "  停止全部:  sudo systemctl stop polymarket-arb.target"
echo "  重启 OEG:  sudo systemctl restart polymarket-oeg"
echo "  重启 SPE:  sudo systemctl restart polymarket-spe"
echo "  查看日志:  journalctl -u polymarket-oeg -f"
echo ""
echo "  回滚到单体: ./deploy_microservices.sh --rollback"