#!/usr/bin/env python3
"""
Poke Test — 压力注入测试验证 SPE→OEG 管道畅通

目的: 排除"可能2: 配置参数过于严苛"导致 0 信号

流程:
  1. 备份当前 .env
  2. 修改: DRY_RUN=true, MIN_PROFIT_THRESHOLD=-0.05
  3. 重启服务
  4. 监控 3 分钟, 统计 DRY_RUN_SIGNAL 数量
  5. 恢复原始 .env
  6. 再次重启服务

如果 3 分钟内有 DRY_RUN_SIGNAL → 管道畅通, 0信号是市场有效
如果 3 分钟内 0 DRY_RUN_SIGNAL → 管道堵塞或 MDG 数据异常

用法:
  python poke_spe.py
  python poke_spe.py --duration 120   # 监控 120 秒
  python poke_spe.py --threshold -0.1 # 更激进的阈值
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import paramiko

HOST = os.getenv("REMOTE_HOST", "192.168.3.117")
USER = os.getenv("REMOTE_USER", "roy")
PASSWORD = os.getenv("REMOTE_PASSWORD", "changeme")
REMOTE = "/home/roy/polymarket-arb"

DEFAULT_DURATION = 180  # 3 minutes
DEFAULT_THRESHOLD = -0.05


def run_ssh(ssh: paramiko.SSHClient, cmd: str, timeout: int = 30) -> str:
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    return (stdout.read() + stderr.read()).decode("utf-8", errors="replace")


def backup_env(ssh: paramiko.SSHClient) -> str:
    """备份远程 .env"""
    ts = int(time.time())
    backup = f"{REMOTE}/.env.poke_backup_{ts}"
    run_ssh(ssh, f"cp {REMOTE}/.env {backup}")
    return backup


def modify_env(ssh: paramiko.SSHClient, threshold: float) -> None:
    """修改 .env: 启用 DRY_RUN, 降低 MIN_PROFIT_THRESHOLD"""
    # Remove existing DRY_RUN and MIN_PROFIT_THRESHOLD lines, add new ones
    run_ssh(ssh, f"cd {REMOTE} && sed -i '/^DRY_RUN=/d' .env")
    run_ssh(ssh, f"cd {REMOTE} && sed -i '/^MIN_PROFIT_THRESHOLD=/d' .env")
    run_ssh(ssh, f"cd {REMOTE} && echo 'DRY_RUN=true' >> .env")
    run_ssh(ssh, f"cd {REMOTE} && echo 'MIN_PROFIT_THRESHOLD={threshold}' >> .env")


def restore_env(ssh: paramiko.SSHClient, backup_path: str) -> None:
    """恢复 .env"""
    run_ssh(ssh, f"cp {backup_path} {REMOTE}/.env")
    run_ssh(ssh, f"rm -f {backup_path}")


def restart_service(ssh: paramiko.SSHClient) -> None:
    """重启服务"""
    run_ssh(ssh, f"echo {PASSWORD} | sudo -S systemctl restart polymarket-arb.service 2>/dev/null")
    time.sleep(5)
    status = run_ssh(ssh, "systemctl is-active polymarket-arb.service").strip()
    print(f"  服务状态: {status}")


def monitor_logs(ssh: paramiko.SSHClient, duration: int) -> dict:
    """监控指定时长，统计 DRY_RUN_SIGNAL 和 spe_below_threshold"""
    print(f"\n  监控中 ({duration}秒)...")
    start = time.time()
    counts = {
        "dry_run_signals": 0,
        "below_threshold": 0,
        "arbitrage_calc": 0,
        "errors": 0,
    }

    # Collect all journal logs for the monitoring period
    while time.time() - start < duration:
        elapsed = int(time.time() - start)
        remaining = duration - elapsed

        # Get recent logs since start
        since_str = f"{elapsed - 5} seconds ago" if elapsed > 5 else "5 seconds ago"
        cmd = (
            f'journalctl -u polymarket-arb.service --since "{since_str}" '
            '--no-pager 2>/dev/null | grep -cE "DRY_RUN_SIGNAL|below_threshold|arbitrage_calc|error" || true'
        )
        # For more precise counting, we use a cumulative approach
        time.sleep(min(30, remaining))

        # After monitoring period, do final analysis
        if time.time() - start >= duration:
            break

    # Final comprehensive log analysis
    minutes = duration // 60 + 1
    cmd = (
        f'journalctl -u polymarket-arb.service --since "{minutes} minutes ago" --no-pager 2>/dev/null'
    )
    _, stdout, _ = ssh.exec_command(cmd, timeout=30)
    logs = stdout.read().decode("utf-8", errors="replace")

    for line in logs.splitlines():
        if "DRY_RUN_SIGNAL" in line:
            counts["dry_run_signals"] += 1
        if "spe_below_threshold" in line or "below_threshold" in line:
            counts["below_threshold"] += 1
        if "spe_arbitrage_calc" in line:
            counts["arbitrage_calc"] += 1
        if "error" in line.lower() and "traceback" in line.lower():
            counts["errors"] += 1

    # Also count by grep for accuracy
    for key, pattern in [
        ("dry_run_signals", "DRY_RUN_SIGNAL"),
        ("below_threshold", "spe_below_threshold"),
        ("arbitrage_calc", "spe_arbitrage_calc"),
    ]:
        _, stdout, _ = ssh.exec_command(
            f'journalctl -u polymarket-arb.service --since "{minutes} minutes ago" --no-pager 2>/dev/null '
            f'| grep -c "{pattern}" || true',
            timeout=15,
        )
        try:
            counts[key] = int(stdout.read().decode().strip() or "0")
        except ValueError:
            pass

    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Poke Test - 验证 SPE→OEG 管道")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION, help="监控秒数")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="临时负阈值")
    args = parser.parse_args()

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASSWORD, timeout=15)

    print("=" * 60)
    print("  Poke Test — SPE→OEG 管道压力注入")
    print("=" * 60)
    print(f"  目标: {HOST}")
    print(f"  临时阈值: {args.threshold}")
    print(f"  监控时长: {args.duration}s")
    print(f"  DRY_RUN: true (不下单)")

    # Step 1: 备份
    print("\n[1/6] 备份 .env ...")
    backup = backup_env(ssh)
    print(f"  备份: {backup}")

    # Step 2: 读当前配置
    print("\n[2/6] 当前配置:")
    current_env = run_ssh(ssh, f"grep -E 'MIN_PROFIT|DRY_RUN|MAX_TRADE' {REMOTE}/.env")
    for line in current_env.strip().splitlines():
        print(f"  {line}")

    try:
        # Step 3: 修改配置
        print(f"\n[3/6] 修改: DRY_RUN=true, MIN_PROFIT_THRESHOLD={args.threshold}")
        modify_env(ssh, args.threshold)

        modified_env = run_ssh(ssh, f"grep -E 'MIN_PROFIT|DRY_RUN|MAX_TRADE' {REMOTE}/.env")
        for line in modified_env.strip().splitlines():
            print(f"  {line}")

        # Step 4: 重启
        print("\n[4/6] 重启服务 ...")
        restart_service(ssh)

        # Step 5: 监控
        print(f"\n[5/6] 监控 {args.duration}s ...")
        counts = monitor_logs(ssh, args.duration)

        print("\n  结果:")
        print(f"    DRY_RUN_SIGNAL 数量:  {counts['dry_run_signals']}")
        print(f"    below_threshold 数量: {counts['below_threshold']}")
        print(f"    arbitrage_calc 数量:   {counts['arbitrage_calc']}")
        print(f"    错误数:                {counts['errors']}")

        # Diagnosis
        print("\n" + "=" * 60)
        print("  诊断结论")
        print("=" * 60)

        if counts["dry_run_signals"] > 0:
            print(f"  ✅ 管道畅通! {counts['dry_run_signals']} 个信号通过 SPE→OEG")
            print("     → 0 信号是「可能1: 市场极度有效」")
            print("     → 套利窗口只在消息面爆发时短暂存在")
            if counts["below_threshold"] > 0:
                print(f"     → 另有 {counts['below_threshold']} 次被 MIN_PROFIT_THRESHOLD 过滤")
                print("     → 放宽阈值可捕获更多信号,但利润可能为负")
        elif counts["below_threshold"] > 0:
            print(f"  ⚠️  SPE 检测到潜在套利但 VWAP 后被阈值过滤")
            print(f"     → {counts['below_threshold']} 次被过滤")
            print("     → 验证: 管道基本畅通, 但当前阈值确实卡住了信号")
            print("     → 建议: 降低 MIN_PROFIT_THRESHOLD 或缩小 MAX_TRADE_SIZE")
        elif counts["arbitrage_calc"] > 0:
            print(f"  ⚠️  SPE 计算了 {counts['arbitrage_calc']} 次套利,但全部未产生信号")
            print("     → 可能是 VWAP 滑点完全吞噬了薄利")
            print("     → 建议: 先运行 spread_scanner.py 看真实价差分布")
        else:
            print("  ❌ 管道可能堵塞!")
            print("     → 0 arbitrage_calc 意味着 SPE 没收到订单簿数据")
            print("     → 检查: MDG WebSocket 连接 / Market Channel 订阅")
            print("     → 建议: journalctl -u polymarket-arb.service | grep mdg_")

    finally:
        # Step 6: 恢复
        print(f"\n[6/6] 恢复原始 .env ...")
        restore_env(ssh, backup)
        restart_service(ssh)
        print("  已恢复并重启")

    ssh.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())