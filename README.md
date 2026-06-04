# Polymarket 自动套利与对冲交易系统 v1.0

> 针对 Polymarket (基于 Polygon 的预测市场) 的高频套利扫描与自动执行引擎

## 📐 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     Polymarket 套利引擎                          │
│                                                                 │
│  ┌─────────┐  Snapshot   ┌─────────┐  TradeSignal  ┌─────────┐│
│  │   MDG   │ ──────────→ │   SPE   │ ─────────────→ │   OEG   ││
│  │ 市场数据 │   Queue①    │  策略引擎 │    Queue②     │  订单执行 ││
│  └─────────┘            └─────────┘               └─────────┘│
│       ▲                                                   │     │
│       │ Gamma API + CLOB WS                              │     │
│       │                                            Result│     │
│       │                                                  ▼     │
│                                                 ┌─────────┐    │
│                                                 │   RMC   │    │
│                                                 │  风控中心 │    │
│                                                 └─────────┘    │
│                                                      │          │
│                                                 SQLite DB      │
└─────────────────────────────────────────────────────────────────┘
```

## 🔑 核心套利逻辑

在同一二元预测市场中，若:

```
Ask(YES) + Ask(NO) + Slippage < 1
```

则同时买入 YES 和 NO，无论结果如何均获赔付 $1，锁定无风险利润:

```
Profit = 1 - (P_yes + P_no) - Slippage
```

## 📁 项目结构

```
polymarket-arb/
├── .env.example          # 环境变量模板
├── .gitignore            # Git 忽略规则
├── requirements.txt      # Python 依赖
├── main.py               # 主入口 & 引擎调度
├── core/
│   ├── __init__.py       # 模块导出
│   ├── config.py         # 统一配置管理
│   ├── models.py         # 数据模型定义
│   ├── clob_client.py    # CLOB Client 单例
│   ├── mdg.py            # 市场数据网关
│   ├── spe.py            # 策略与定价引擎
│   ├── oeg.py            # 订单执行网关
│   └── rmc.py            # 风控与记录中心
├── db/
│   └── schema.sql        # SQLite Schema
├── deploy/
│   ├── polymarket-arb.service  # systemd 配置
│   └── deploy.sh          # 部署脚本
├── test_phase1.py         # Phase 1 测试: 市场发现
├── test_phase2.py         # Phase 2 测试: 影子系统
└── README.md
```

## 🚀 快速开始

### 1. 安装依赖

```bash
cd polymarket-arb
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
nano .env  # 填入真实的私钥和 API 凭证
```

### 3. Phase 1: 市场发现测试

```bash
python test_phase1.py
```

### 4. Phase 2: 影子系统运行

```bash
python test_phase2.py --duration 5  # 运行5分钟
```

### 5. 实盘模式 (⚠️ 资金风险!)

```bash
python main.py              # 实盘模式
python main.py --dry-run    # 影子系统模式
python main.py --discover    # 仅市场发现
python main.py --debug       # 调试模式
```

## ⚙️ 配置说明

| 环境变量 | 说明 | 默认值 |
|---|---|---|
| `PRIVATE_KEY` | L1 私钥 (EIP-712 签名) | - |
| `API_KEY` | L2 API Key | - |
| `API_SECRET` | L2 API Secret | - |
| `API_PASSPHRASE` | L2 API Passphrase | - |
| `RPC_URL` | Polygon RPC 节点 | 公共节点 (⚠️不推荐) |
| `MAX_TRADE_SIZE` | 单笔最大资金 (USD) | 2.0 |
| `MIN_PROFIT_THRESHOLD` | 最小利润阈值 (USD) | 0.005 |
| `MAX_SLIPPAGE_PCT` | 滑点容忍上限 (%) | 0.5 |
| `CONSECUTIVE_FAIL_LIMIT` | 连败熔断阈值 | 3 |
| `CIRCUIT_BREAKER_COOLDOWN` | 熔断冷却时间 (秒) | 900 |

## 🛡️ 风控机制

### 熔断器 (Circuit Breaker)

| 类型 | 触发条件 | 动作 |
|---|---|---|
| **单边敞口熔断** | YES 成交但 NO 失败 | 禁用该市场 + 触发平仓 |
| **连败熔断** | 连续 3 次套利失败 | 暂停 OEG 写权限 15 分钟 |
| **滑点熔断** | 实际滑点超限 | 暂停该市场交易 |
| **网络超时** | RPC 请求超时 | 暂停所有交易 |

### 安全规范

- ⚠️ **隔离原则**: 必须使用独立的专属 Web3 钱包
- ⚠️ **存储规范**: 密钥仅在 `.env` 文件, 已通过 `.gitignore` 阻断上传
- ⚠️ **RPC 节点**: 必须使用 Alchemy/QuickNode 专属高速节点

## 📊 数据流时序

```
[INIT] MDG → Gamma API → 获取 YES_Token / NO_Token
[SUB]  MDG → WebSocket  → 订阅实时订单簿
[TICK]  MDG → SPE       → 推送 Snapshot
[CALC]  SPE → OEG       → 检测价差 → 生成 TradeSignal
[EXEC]  OEG → CLOB API  → EIP-712 签名 → 并发下单
[LOG]   OEG → RMC       → 记录结果 → 熔断检测
```

## 🗺️ 演进路线图

| Phase | 目标 | 状态 |
|---|---|---|
| **Phase 1** | 跑通 Gamma API + CLOB WebSocket | ✅ 代码完成 |
| **Phase 2** | 影子系统 48h 压测 | ✅ 代码完成 |
| **Phase 3** | 金丝雀部署 ($100/$2 限制) | 📝 待验证 |
| **Phase 4** | 全自动 + Telegram 报警 | 📝 规划中 |

## ⚠️ 免责声明

本系统仅用于技术研究和学习目的。预测市场交易存在资金损失风险。使用本代码即表示您自行承担所有相关风险。作者不对任何直接或间接损失负责。