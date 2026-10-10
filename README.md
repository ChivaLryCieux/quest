# Quest - 个人量化交易CTA系统

Quest 是一个面向个人使用的 Python 量化交易CTA系统。它不是发布到 PyPI 的包或通用库，而是把实盘/模拟盘执行、终端交互、Web GUI、Redis 状态通道、邮件报告、交易所接入、仓位风控、回测研究和运行日志组织在同一个仓库里，方便日常迭代和复盘。

框架当前围绕 Binance 永续合约工作，但核心结构并不绑定某一个具体策略。策略可以替换，执行引擎、TUI、Web GUI、交易所接入、风控、报告和回测日志体系可以继续复用。

**v0.3.0 核心升级**: 极速标的/周期动态切换、多路并行拉取预热、轻量级 K 线图表整合、国内免代理直连看盘模式、基于“双锁”机制的多线程安全同步、100vh 视口自适应 UI。

**v0.2.0 核心升级**: 多信号共识策略引擎、8项高级技术指标、HMM市场状态检测、Kelly Criterion动态仓位管理、蒙特卡洛策略模拟、完整绩效分析系统。

---

## 技术栈

### 后端 (Python)

| 类别 | 库 | 用途 |
| --- | --- | --- |
| 交易所接入 | `ccxt` | 统一交易所 REST API（市场、余额、下单） |
| 实时数据 | `websocket-client` | Binance WebSocket 行情流（K线、盘口、资金费率） |
| Web 服务器 | `fastapi` | REST API + WebSocket 实时推送 |
| ASGI 服务器 | `uvicorn` | 运行 FastAPI 应用 |
| 数据验证 | `pydantic` | API 请求/响应模型定义与验证 |
| 数据处理 | `pandas`, `numpy` | K线数据处理、技术指标计算 |
| 可视化 | `matplotlib`, `seaborn` | 报告图表、权益曲线 |
| 统计建模 | `statsmodels`, `hmmlearn`, `scikit-learn` | HMM 状态识别、聚类分析 |
| 消息队列 | `redis` | 交易记录与心跳的异步通道 |
| 邮件发送 | `resend` | 交易报告和告警邮件 |
| 定时任务 | `schedule` | 邮件报告定时发送 |
| 配置管理 | `python-dotenv` | `.env` 环境变量加载 |
| 终端 UI | `rich`, `colorama` | TUI 彩色输出、面板、表格 |
| HTTP 客户端 | `requests`, `aiohttp` | API 调用、数据抓取 |

### 前端 (Web GUI)

| 类别 | 库 | 用途 |
| --- | --- | --- |
| 构建工具 | `Vite` | 快速开发服务器与生产构建 |
| UI 框架 | `React 18` | 组件化用户界面 |
| 类型系统 | `TypeScript` | 静态类型检查 |
| 状态管理 | `Zustand` | 轻量级全局状态管理 |
| 样式方案 | `Tailwind CSS` | 原子化 CSS 框架 |
| K线图表 | `TradingView Lightweight Charts` | 专业金融图表与实时 Tick 增量绘图 |
| WebSocket | 原生 `WebSocket API` | 实时数据接收 |

---

## 框架要点

### 1. 量化策略执行核心

交易执行核心位于 `core/engine/`，负责协调行情驱动、策略信号计算、风控审查与订单路由。框架遵循面向对象与分层设计原则，解耦数据流与执行流：

- `core/engine/bot.py`：主循环协调器（`QuantBot`），维护毫秒级 Tick 事件循环、驱动多周期 K 线归集与全局状态同步。
- `core/engine/switcher.py`：标的与模式热切换控制器（`ModeSwitcher` / `SymbolSwitcher` / `WarmupCoordinator`），基于**两阶段并发锁协议**，在锁外异步预热并在锁内原子置换，彻底杜绝数十秒网络 I/O 阻塞 50ms 主交易循环。
- `core/engine/trader.py`：订单执行器，管理开仓、平仓、保本止损、追踪止盈与滑点仿真。
- `core/engine/state_store.py`：基于系统级 `os.replace` 的原子落盘存储，保障运行态崩溃一致性与自愈恢复。
- `core/models/position.py`：基于 `@dataclass` 的强类型 `Position` 领域实体，统领持仓方向、名义价值与风控收益计算。
- `core/strategy/`：策略抽象层，基于 `BaseStrategy` 规范生命周期契约，支持多策略插拔与盘口微观结构（`OrderBookAnalyzer`）分析。
- `core/analysis/`：指标与特征层，全面引入 `collections.deque(maxlen=N)` 双端定长缓冲，消除 K 线流追加时的 $O(N)$ 连续内存拷贝。

### 2. TUI 终端界面

终端界面位于 `core/ui/`，使用 `Rich` 库实现现代化的终端显示效果。Rich 提供了丰富的文本格式化能力，包括彩色输出、面板、表格、样式等，同时保持良好的跨平台兼容性。

- `core/ui/display.py`：基于 Rich 的显示管理器，提供：
  - 启动面板：圆角边框、符号 Logo、模式和策略信息
  - 日志消息：带时间戳和级别标识的格式化输出（`✔` 成功、`●` 信息、`⚠` 警告、`✖` 错误）
  - 开仓日志：带颜色标识的入场信息面板（绿色=做多，红色=做空）
  - 平仓日志：盈亏高亮的出场信息面板
  - 状态栏：实时刷新的持仓状态、市场状态、MACD/ADX/Reversal 指标
- `core/ui/input.py`：处理键盘输入，结合 `msvcrt`、`termios`、`tty` 等标准库能力支持运行中暂停、继续和退出。

TUI 是这个框架的一个实用入口：不需要额外部署服务，也能看到交易系统是否正常工作。

### 2.5 Web GUI 界面

Web GUI 位于 `core/web/`（后端）和 `web/`（前端），提供基于浏览器的可视化界面。它与 TUI 并行工作，启动后自动打开浏览器，无需手动部署。

**后端架构** (`core/web/`)：

- `state.py`：线程安全的共享状态管理器，使用 `threading.Lock` 保护数据，在主循环和 Web 服务器之间传递行情、策略、持仓、交易和告警数据。支持订阅者模式，WebSocket 连接自动接收数据更新。
- `server.py`：基于 FastAPI 的 Web 服务器，提供：
  - REST API：`/api/status`（完整快照）、`/api/market`（行情）、`/api/strategy`（策略）、`/api/position`（持仓）、`/api/trades`（交易历史）、`/api/alerts`（告警历史）
  - WebSocket：`/ws` 端点，实时推送数据变更，支持心跳检测 and 自动重连
  - 静态文件服务：自动提供前端构建产物
  - Swagger 文档：`/api/docs` 自动生成 API 文档
- `runner.py`：Web 线程管理器，在独立守护线程中启动 uvicorn 服务器，使用 `webbrowser` 库自动打开浏览器，并且保存 FastAPI 线程事件循环，确保跨线程协程推送不引发死锁崩溃。
- `models.py`：Pydantic 数据模型，定义 API 请求/响应结构，提供类型安全和自动验证。

**前端架构** (`web/`)：

- 技术栈：Vite + React 18 + TypeScript + Tailwind CSS
- 状态管理：Zustand，轻量级且支持 TypeScript 类型推断
- 组件结构：
  - `PriceHeader`：价格、余额、盈亏、资金费率概览（纸盘/实盘可见，纯看盘模式隐藏）
  - `KLineChart`：集成了 TradingView Lightweight Charts 图表，顶部配有币种和周期切换控制栏，并支持 Tick 级秒级蜡烛内数据动态归集，切换时自动重设以防时序竞争。
  - `StrategyStatus`：市场状态（强涨/震荡/强跌）、ADX/MACD/Reversal 指标、SuperTrend 多周期对比
  - `PositionPanel`：持仓方向、入场价、止损止盈、浮动盈亏
  - `OrderBookPanel`：盘口深度可视化，买卖五档挂单对比
  - `TradeHistory`：开仓/平仓记录表格
  - `AlertPanel`：BOCPD/KDJ/ADX/MACD 告警历史
- WebSocket Hook：自动连接、心跳保活、断线重连

**数据流**：

```text
Bot 主循环 ──[bot_lock / api_lock]──> WebState ──> FastAPI WebSocket ──> 浏览器
     │                                                               │
     └──> TUI (stdout)                                          React 组件更新
```

**Web GUI 功能**：
- **极速多标的切换**：支持在 `BTC`、`ETH`、`SOL` 之间切换，后端自动清除内存特征缓存，通过 `ThreadPoolExecutor` 并行加载 4 周期历史数据，实现 1 ~ 2 秒级热启动重载。
- **动态 K 线周期**：提供 `5m`、`15m`、`1h`、`1d` 的秒级无感切换，前端秒级价格 Tick 依所选周期自动归集蜡烛时间戳。
- **100vh 视口自适应**：整体界面严格限制在 `100vh` 高度内，去除浏览器全局滚动条。看盘模式（Dashboard）下隐藏头部和日志组件，让 K 线图撑满整个右侧大屏。
- **国内直连看盘**：支持新浪财经 API 直连拉取 A 股（如贵州茅台 `sh600519`，日线对应 `scale=240` 分钟）或加密货币行情，免代理，仅作行情看板与指标分析。
- 暗色主题，适合长时间监控

启动后会自动打开浏览器访问 `http://127.0.0.1:8000`，同时 TUI 终端界面继续工作。两者共享同一份数据，互不干扰。

### 3. 基于 Redis 的异步削峰解耦与分布式探活

系统采用 Redis 作为轻量级高性能异步消息总线，实现高可用解耦：

- **跨进程生产者-消费者削峰解耦**：核心交易主循环在平仓后，仅以纳秒级开销将交易流水推入 Redis List（`trade_journal_pending`）；独立的报告进程（`scripts/run_report.py`）异步消费并执行耗时的 Matplotlib 权益绘图与 Resend 邮件投递，**实现交易主循环与报表渲染的彻底物理隔离**，避免网络与绘图抖动阻塞交易执行。
- **基于 TTL 租约的死信探活（Lease-based Liveness Probe）**：交易主进程定期向 Redis 写入心跳（`bot_status_heartbeat`）并配置 `ex=10` 秒租约过期；外部监控进程若侦测到 Key 缺失即可零侵入判定核心进程假死，触发容灾告警。

### 4. 独立网关适配层 (Gateway Layer)

独立网关层位于 `core/gateway/`，基于**门面模式（Facade）**与**适配器模式（Adapter）**统一封装交易所连接：

- **数据流与执行解耦**：
  - `binance_stream.py`（`MarketDataStreamer`）：基于 `websocket-client` 实现 Binance 永续合约实时组合流订阅，包含断线毫秒级自动重连与心跳保活。
  - `domestic_feed.py`（`DomesticDataStreamer`）：国内 A 股免代理直连行情源，支持盘口五档与秒级合成 K 线。
  - `service.py`（`ExchangeService`）：统一网关门面，封装 CCXT 接口并向下屏蔽纸盘仿真记账与实盘委托差异。
- **分层异常体系与异常链**：全面采用基于 `QuestError` 的分层异常（`OrderError` / `DataError`），并遵循 **PEP 3134 异常链（`raise ... from e`）** 保留交易所底层真实调用栈，杜绝伪成交假阳性。

### 5. 仓位管理与风控体系

仓位管理与风控体系分布在 `core/engine/trader.py`、`core/risk/manager.py` 和 `core/risk/position_sizer.py`：

- **强类型领域实体**：统一采用不可变/自计算领域模型 `Position`（`core/models/position.py`），封装入场价、杠杆倍数、动态止损止盈、名义价值与方向敏感浮盈，杜绝裸字典键缺失与隐式类型转换。
- **动态风控拦截**：`RiskManager` 负责资金费率逆向套利防御、固定止损止盈、持仓时间防御与动态分级熔断。
- **Kelly Criterion 动态资金管理**：`PositionSizer` 依据历史胜率、盈亏比与当前 ATR 波动率自适应计算半 Kelly 最优开仓比例与自适应杠杆，并在高回撤期线性缩减仓位。

### 6. 回测与日志系统

回测与日志系统用于离线验证和线上排查。回测代码放在 `backtest/`，日志配置放在 `core/utils/logging_config.py`。

- 回测引擎：`backtest/backtester.py` 复用 `core/` 中的策略、指标和风控模块，避免回测和实盘逻辑完全分叉。
- 数据处理：回测和分析脚本大量使用 `pandas`、`numpy`、`matplotlib`、`seaborn` 和 `statsmodels`。
- 模型实验：`hmmlearn`、`scikit-learn`、`joblib` 等库用于 HMM、聚类和模型持久化实验。
- 日志系统：使用 Python 标准库 `logging` 和 `logging.handlers.RotatingFileHandler`，同时支持终端彩色日志和滚动文件日志。
- 诊断脚本：`backtest/replay_5m_diagnostics.py` 可按历史窗口重放信号，并输出 CSV 和图表辅助复盘。

这部分让框架不只是能跑，还能在亏损、异常、网络问题或策略变更后定位原因。

### 7. 其他

其他辅助能力让这个仓库更接近完整的个人量化工作台。

- 配置加载：`core/config/settings.py` 使用 `python-dotenv` 读取 `.env`，并做基础运行前校验。
- 爆仓预警：`scripts/liquidation_alert.py` 使用 `requests` 轮询 Binance 强平订单 API，并通过邮件系统发送告警。
- 异步和网络实验：依赖中保留 `aiohttp`，适合后续扩展异步数据抓取或外部服务调用。
- 技术指标库：`core/analysis/indicators/` 分类维护（trend, momentum, volatility, volume, utils）常用指标实现，便于实盘和回测共享。
- 基础测试：`tests/` 使用 Python 标准库 `unittest` 覆盖风控、盘口分析、纸盘开平仓等核心行为。
- 研究资产：`backtest/` 中保留 PNG、CSV 和实验脚本，方便把策略研究和实盘框架放在同一个工作目录中。

### 8. v0.2.0 量化分析升级

v0.2.0 在策略信号、仓位管理和分析能力上做了全面升级，目标是提高盈利能力和策略鲁棒性。

**8.1 多信号共识引擎** (`core/strategy/analyzers.py`)

信号生成从"单一条件触发"升级为"多指标加权投票"系统:

- 11个独立信号源投票: ADX+VWAP方向、快/标准MACD、SuperTrend(5m/15m)、Ichimoku云、StochasticRSI、OBV背离、CCI、CMF资金流、Parabolic SAR、VWMA偏差
- 加权求和后与自适应阈值比较: 趋势行情阈值=3.0(积极)，震荡行情阈值=5.0(保守)
- 强趋势(ADX>30)自动降低阈值20%
- 强共识信号自动获得杠杆加成(+10%~15%)
- 日志显示每个投票指标和最终得分，方便复盘

**8.2 高级技术指标** (`core/analysis/indicators/`)

新增8个指标(总计20+):

| 指标 | 类型 | 信号含义 |
| --- | --- | --- |
| Ichimoku Cloud | 趋势 | 云上/云下/TK交叉 |
| Stochastic RSI | 超买超卖 | K/D交叉 |
| OBV | 量价 | 量价背离、趋势斜率 |
| CCI | 周期 | 超买(>100)/超卖(<-100) |
| Williams %R | 超买超卖 | >-20超买/<-80超卖 |
| Parabolic SAR | 趋势 | 多/空方向 |
| VWMA | 量价 | VWMA与SMA偏差 |
| CMF | 资金流 | 买方/卖方主导 |

**8.3 Kelly Criterion动态仓位** (`core/risk/position_sizer.py`)

仓位大小不再是固定比例，而是根据历史表现动态调整:

- Kelly公式: `f* = W - (1-W)/R`，使用半Kelly降低波动
- 波动率自适应杠杆: `leverage = base * (target_vol / current_vol)`，ATR高时降杠杆
- 回撤缩仓: 5%回撤开始线性缩减，20%回撤时缩至20%仓位
- 信号强度加权: 强共识信号使用更大仓位

**8.4 HMM市场状态检测** (`core/analysis/regime.py`)

使用Hidden Markov Model自动识别4种市场状态:

- 状态0: 低波动震荡 → 均值回归策略，收紧止盈止损
- 状态1: 上升趋势 → 趋势跟随，放宽止盈，降低ADX门槛
- 状态2: 下降趋势 → 趋势跟随(做空)，同上
- 状态3: 高波动 → 防御模式，大幅减仓，收紧止盈

每50根K线自动重训练，输入特征: 对数收益率+波动率+成交量变化+趋势强度。

**8.5 绩效分析系统** (`core/analysis/performance.py`)

回测报告现在包含完整的机构级绩效指标:

- 风险调整: Sharpe Ratio, Sortino Ratio, Calmar Ratio
- 盈利质量: Profit Factor, Payoff Ratio, Expectancy
- 回撤分析: 最大回撤(绝对值+百分比), Recovery Factor
- 连续统计: 最大连胜/连亏, 破产风险估计
- 方向分析: 多/空分别的胜率和盈亏

**8.6 蒙特卡洛模拟** (`core/analysis/monte_carlo.py`)

回测后自动运行1000次蒙特卡洛模拟:

- Bootstrap重采样: 打乱交易顺序模拟不同市场路径
- 破产概率: 基于历史交易分布估算
- 置信区间: 5%-95%分位的收益和回撤范围
- 仓位优化: 测试5%-40%仓位的风险收益特征
- Sharpe分布: 策略夏普比率的置信区间

---

## 快速开始

### 0. 项目结构

```text
Quest/
├── run.py                         # 主入口，默认 DASHBOARD 看盘模式，WebUI 控制切换
├── pyproject.toml                 # 项目元信息与依赖声明 (v0.3.0)，支持 pip install -e .
├── requirements.txt               # Python 依赖（与 pyproject.toml 保持一致）
├── .gitignore                     # 忽略 __pycache__/.env/logs/data/output 等
├── README.md
│
├── core/                          # 核心业务逻辑
│   ├── gateway/                   # 【交易所网关层】门面模式统一接入
│   │   ├── service.py             # ExchangeService 核心门面与订单路由
│   │   ├── binance_stream.py      # Binance 组合流 WebSocket 订阅与自动保活
│   │   └── domestic_feed.py       # 国内 A 股新浪直连数据源
│   │
│   ├── config/                    # 系统配置层
│   │   ├── settings.py            # 默认配置、.env 加载、运行前校验
│   │   ├── mode.py                # 交易模式状态机定义与切换校验
│   │   └── exchange.py            # 向后兼容网关垫片 (Shim)
│   │
│   ├── models/                    # 领域实体层 (纯数据对象)
│   │   └── position.py            # Position 强类型持仓模型
│   │
│   ├── engine/                    # 交易调度层
│   │   ├── bot.py                 # QuantBot 主循环协调器
│   │   ├── switcher.py            # ModeSwitcher / SymbolSwitcher 两阶段热切换控制器
│   │   ├── trader.py              # TradeExecutor 订单执行与滑点仿真
│   │   ├── alert_manager.py       # 运行中的告警辅助
│   │   └── state_store.py         # 基于 os.replace 的崩溃一致性状态落盘
│   │
│   ├── strategy/                  # 策略框架层
│   │   ├── base.py                # BaseStrategy 策略标准抽象契约
│   │   ├── microstructure.py      # OrderBookAnalyzer 盘口失衡与深度点差
│   │   ├── brain.py               # StrategyBrain 多周期数据流与策略驱动
│   │   └── analyzers.py           # SignalEngine 11 信号加权投票引擎
│   │
│   ├── analysis/                  # 特征与分析层
│   │   ├── indicators/            # 模块化技术指标包 (trend/momentum/volatility/volume/utils)
│   │   ├── feature_engineering.py # 特征工程
│   │   ├── bocpd.py               # BOCPD变点检测
│   │   ├── regime.py              # HMM市场状态检测 (4状态)
│   │   ├── performance.py         # 绩效分析 (Sharpe/Sortino/Calmar)
│   │   └── monte_carlo.py         # 蒙特卡洛策略模拟
│   │
│   ├── risk/                      # 风控与资金管理层
│   │   ├── manager.py             # 风控管理 (硬止盈止损、时间防御、分级熔断)
│   │   └── position_sizer.py      # Kelly Criterion 动态仓位与自适应杠杆
│   │
│   ├── ui/                        # 终端交互层
│   │   ├── display.py             # Rich TUI 输出 (QUEST_CTA 启动面板与状态栏)
│   │   └── input.py               # 键盘输入
│   │
│   ├── web/                       # Web GUI 后端
│   │   ├── __init__.py
│   │   ├── state.py               # 线程安全的共享状态管理 (deque 缓冲)
│   │   ├── server.py              # FastAPI 服务器 (REST + WebSocket)
│   │   ├── runner.py              # Web 线程管理器
│   │   ├── models.py              # Pydantic 数据模型
│   │   └── static/                # 前端构建产物 (自动生成)
│   │
│   └── utils/
│       ├── logging_config.py      # 日志配置
│       ├── mailer.py              # 邮件发送封装
│       └── reporting.py           # 报告生成、CSV 导出、日线快照
│
├── web/                           # Web GUI 前端 (Vite + React 18 + TS + Tailwind)
│   ├── src/
│   │   ├── components/            # React 组件 (KLineChart, StrategyStatus 等)
│   │   ├── hooks/                 # 自定义 Hooks
│   │   ├── stores/                # Zustand 状态管理
│   │   └── types/                 # TypeScript 类型定义
│   ├── package.json
│   └── vite.config.ts
│
├── scripts/                       # 离线辅助与运维脚本
│   ├── fetch_candles.py           # 简易 K 线数据下载与保存工具
│   ├── plot_candles.py            # 简易 K 线纯黑美化绘图工具
│   ├── run_report.py              # Redis 交易报告消费者和定时邮件任务
│   ├── liquidation_alert.py       # 爆仓量预警脚本
│   └── pretrain.py                # 数据预热/模型辅助脚本
│
├── data/                          # 本地数据管理目录
│   ├── historical/                # 历史行情 CSV 数据
│   └── models/                    # 模型权重与聚类中心数据
│
├── output/                        # 分析产物与图表输出目录 (如 kline_chart.png)
├── logs/                          # 交易运行日志
└── tests/                         # 本地单元测试 (test_framework_core, test_new_modules)
```

> `__pycache__/`、日志、研究资产 PNG/CSV/PKL 都在 `.gitignore` 中被忽略，不会进入版本控制。

### 1. 安装依赖

推荐方式（一次性把 `core` 安装为可导入包，`scripts/` 脱离根目录也能 `from core.xxx import ...`）：

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .                   # 会读取 pyproject.toml 并安装所有依赖
```

传统方式仍保留：

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 配置 `.env`

在项目根目录创建 `.env` 文件。模拟盘可以不配置 API key。实盘必须配置：

```env
BINANCE_API_KEY=your_api_key
BINANCE_SECRET=your_secret_key
```

**完整环境变量参考**（写在 `.env` 中即生效，不写则使用 `core/config/settings.py` 里的默认值）：

| 分组 | 变量 | 默认值 | 说明 |
| --- | --- | --- | --- |
| 代理 | `PROXY_ENABLED` | `True` | 是否启用代理访问交易所 |
| 代理 | `PROXY_HOST` | `127.0.0.1` | 代理主机 |
| 代理 | `PROXY_PORT` | `7890` | 代理端口 |
| 交易所 | `BINANCE_API_KEY` | — | 实盘必需 |
| 交易所 | `BINANCE_SECRET` | — | 实盘必需 |
| 交易标的 | `SYMBOL` | `SOL/USDT` | 交易对 |
| 交易标的 | `TIMEFRAME_SIGNAL` | `5m` | 主信号周期（kline） |
| 交易标的 | `TIMEFRAME_TREND` | `15m` | 趋势过滤周期 |
| 交易标的 | `TIMEFRAME_MACRO` | `1h` | 宏观趋势周期 |
| 资金管理 | `PAPER_BALANCE` | `100.0` | 模拟盘初始余额（USDT） |
| 资金管理 | `MIN_LEVERAGE` | `5.0` | 允许的最小杠杆 |
| 资金管理 | `MAX_LEVERAGE` | `10.0` | 允许的最大杠杆 |
| 资金管理 | `DEFAULT_LEVERAGE` | `10.0` | 默认杠杆 |
| 资金管理 | `POSITION_ALLOC_RATIO` | `0.20` | 单笔仓位占账户比例 |
| 资金管理 | `TAKER_FEE_RATE` | `0.0005` | taker 手续费率估算 |
| 策略 | `BAILOUT_ON_NTH_FLIP` | `99` | 盈利翻转多少次触发离场（默认禁用） |
| 策略 | `MIN_ATR_PCT` | `0.0020` | ATR 下限（用于保护入场） |
| 策略 | `MIN_TP_DISTANCE` | `0.012` | 最小止盈距离（相对价格） |
| 策略 | `MAX_SL_DISTANCE` | `0.004` | 最大止损距离（相对价格） |
| 微结构 | `OBI_THRESHOLD_TREND` | `-0.2` | 盘口失衡阈值（趋势侧） |
| 微结构 | `OBI_THRESHOLD_BREAKOUT` | `0.1` | 盘口失衡阈值（突破侧） |
| 微结构 | `MAX_SPREAD_PCT` | `0.001` | 最大允许买卖价差（相对） |
| 邮件报告 | `ENABLE_MAIL_REPORT` | `False` | 启用邮件报告（需 Redis 运行） |
| 邮件报告 | `MAIL_FROM` | — | 发件人，例如 `CTA q-bot <report@your-domain.com>` |
| 邮件报告 | `MAIL_TO` | — | 收件人，多个以英文逗号分隔 |
| 邮件报告 | `RESEND_API_KEY` | — | Resend API Key |
| 邮件报告 | `REDIS_HOST` | `localhost` | Redis 主机 |
| 邮件报告 | `REDIS_PORT` | `6379` | Redis 端口 |
| 邮件报告 | `REDIS_DB` | `0` | Redis DB 编号 |
| 邮件报告 | `REPORT_ARCHIVE_DIR` | `~/quant_archive` | 报告归档目录 |
| 爆仓预警 | `ENABLE_LIQUIDATION_ALERT` | `False` | 启用爆仓预警 |
| 爆仓预警 | `LIQUIDATION_ALERT_SYMBOL` | `SOLUSDT` | 监听的交易对 |
| 爆仓预警 | `LIQUIDATION_ALERT_WINDOW_SEC` | `300` | 汇总窗口（秒） |
| 爆仓预警 | `LIQUIDATION_ALERT_THRESHOLD_USD` | `1000000` | 触发阈值（USD） |
| 爆仓预警 | `LIQUIDATION_ALERT_POLL_INTERVAL_SEC` | `30` | 轮询间隔（秒） |
| 爆仓预警 | `LIQUIDATION_ALERT_COOLDOWN_SEC` | `900` | 触发后的冷却期（秒） |
| 日志 | `LOG_LEVEL` | `INFO` | 日志等级 |
| 日志 | `LOG_DIR` | `logs` | 日志目录 |
| 日志 | `LOG_FILE` | `quant_bot.log` | 日志文件名 |
| 日志 | `LOG_TO_CONSOLE` | `True` | 是否同时输出到控制台 |
| Web GUI | `WEB_ENABLED` | `True` | 启用 Web GUI 界面 |
| Web GUI | `WEB_HOST` | `127.0.0.1` | Web 服务器监听地址 |
| Web GUI | `WEB_PORT` | `8000` | Web 服务器端口 |
| Web GUI | `WEB_AUTO_OPEN` | `True` | 启动时自动打开浏览器 |

### 3. 启动交易框架

```bash
python run.py      # 交互式选择模式
python run.py 1    # 模拟盘（Paper）
python run.py 2    # 实盘（Live）
```

模式说明：

- `0`：退出
- `1`：模拟盘，适合调试执行链路
- `2`：实盘，会使用 Binance API 下单

启动后会同时运行 TUI 终端界面和 Web GUI（如果已构建前端并启用）。Web GUI 默认地址：`http://127.0.0.1:8000`

如果执行了 `pip install -e .`，也可以直接调用入口脚本：

```bash
quest-bot        # 等效于 python run.py
```

### 4. 构建 Web GUI 前端（可选）

如果需要使用 Web GUI 界面，需要先构建前端：

```bash
cd web
npm install
npm run build
cd ..
```

构建产物会自动输出到 `core/web/static/`，FastAPI 服务器会自动提供静态文件服务。

开发模式（前端热重载）：

```bash
cd web
npm run dev
```

然后在另一个终端启动交易框架，前端开发服务器会自动代理 API 请求到后端。

### 5. 启动邮件报告服务

先确保 Redis 正在运行，并且 `.env` 中设置了 `ENABLE_MAIL_REPORT=true`。

```bash
python scripts/run_report.py
```

默认每天 11:00 和 23:00 发送报告。报告数据来自 Redis，而不是直接从交易主循环发送。

### 6. 启动爆仓预警

```env
ENABLE_LIQUIDATION_ALERT=true
ENABLE_MAIL_REPORT=true
RESEND_API_KEY=your_resend_api_key
MAIL_TO=foo@example.com

LIQUIDATION_ALERT_SYMBOL=SOLUSDT
LIQUIDATION_ALERT_WINDOW_SEC=300
LIQUIDATION_ALERT_THRESHOLD_USD=1000000
LIQUIDATION_ALERT_POLL_INTERVAL_SEC=30
LIQUIDATION_ALERT_COOLDOWN_SEC=900
```

```bash
python scripts/liquidation_alert.py
```

---

## 运行流程

```text
Binance WebSocket/REST
        |
        v
ExchangeService
        |
        v
StrategyBrain + Feature Engineering
        |
        v
SignalEngine
        |
        v
RiskManager
        |
        v
TradeExecutor
        |
        +--> TUI 状态输出 (终端)
        +--> WebState --> FastAPI WebSocket --> Web GUI (浏览器)
        +--> Binance 实盘订单 / Paper 纸盘订单
        +--> Redis 心跳与交易记录
                         |
                         v
                 ReportService + Resend
```

**线程模型与多线程同步机制**：

系统在运行时采用多线程并发模式，通过专门的“双锁”机制确保了线程安全和无死锁阻塞：

* **核心串行锁 (`bot_lock`)**：用于同步主交易循环（`_tick()`）与 Web 控制请求（`handle_control()`）。在标的切换重载期间（包括内存清除、历史拉取和策略重新预热），FastAPI 线程将独占 `bot_lock`，主循环线程挂起等待，彻底消除对 `self.brain` 历史 DataFrame 并发读写引发的内存竞态崩溃。
* **接口独占锁 (`api_lock`)**：在 `ExchangeService` 内用于同步底层的 CCXT API 调用。在后台 REST 循环频繁读取与主循环下单/预热请求之间进行串行保护，防止共享 HTTP 链接池死锁。同时，多周期历史数据拉取解耦至独立临时客户端（`temp_client`），完全避免占用 `api_lock` 以释放轮询开销。

```text
主线程 (Bot.run, main_loop) [受 bot_lock 保护]
    ├── 交易所连接 & 数据预热
    └── 主循环 (tick) [与 handle_control 互斥]
        ├── 行情数据更新
        ├── 策略分析
        ├── 交易执行
        ├── TUI 更新 (stdout)
        └── WebState 更新 (threading.Lock)

WebSocket 线程 (MarketDataStreamer)
    └── Binance WebSocket 行情流

REST 轮询线程 (ExchangeService._poll_rest_data) [受 api_lock 保护]
    └── 定时拉取最新价与五档盘口

Web 服务器线程 (WebRunner, daemon)
    └── uvicorn (FastAPI) [受 bot_lock 保护]
        ├── REST API /api/control (模式/标的切换)
        └── WebSocket 协程推送 (asyncio.run_coroutine_threadsafe)
```

---

## 测试

运行本地单元测试：

```bash
python -m unittest discover -s tests
```

当前测试重点覆盖：

- 资金费率风控
- 熔断冷却
- 订单簿失衡与价差分析
- 模拟盘开仓、平仓、余额变化和订单记录

---

## 常见问题 FAQ

**Q1：启动时报 `WS Connection Timeout (30s)`，是什么原因？**

大概率是本地代理未启动或端口不对。检查以下三点：

- `PROXY_ENABLED=true` 时，代理必须在 `PROXY_HOST:PROXY_PORT`（默认 `127.0.0.1:7890`）可用。
- 测试：`curl -x http://127.0.0.1:7890 https://api.binance.com/api/v3/ping` 应返回 `{}`。
- 如果不使用代理，在 `.env` 中设置 `PROXY_ENABLED=false`。

**Q2：为什么邮件报告不发送？**

- 必须同时设置 `ENABLE_MAIL_REPORT=true`、`RESEND_API_KEY=...`、`MAIL_TO=...`。
- Redis 必须在运行，并且 `REDIS_HOST` / `REDIS_PORT` 正确。
- `scripts/run_report.py` 是独立进程，需要与 `run.py` 同时运行（它从 Redis 的 `trade_journal_pending` 列表消费）。

**Q3：Paper 模式与 Live 模式有什么区别？**

- Paper：不会调用真实下单接口，用模拟的 `paper_orders` 记录，便于本地调试验证执行链路。
- Live：会通过 `ccxt.binance` 调用 REST API 下单，请确认 API Key 有交易权限并绑定白名单 IP。

**Q4：为什么要 `pip install -e .` 而不是 `pip install -r requirements.txt`？**

- 两者都能安装依赖。但 `pip install -e .` 会额外把 `core/` 注册为包，使得 `python scripts/run_report.py` 无论在哪个工作目录下都能正确执行 `from core.xxx import ...`，避免 `ModuleNotFoundError`。

**Q5：研究资产（PNG / CSV / PKL）会提交到版本库吗？**

不会。`.gitignore` 已忽略 `*.png`、`*.csv`、`*.pkl` 以及 `__pycache__/`、`.env`、`logs/` 等。

**Q6：Web GUI 无法访问怎么办？**

检查以下几点：

- 确认已构建前端：`cd web && npm install && npm run build`
- 确认 `.env` 中 `WEB_ENABLED=true`（默认已启用）
- 确认端口未被占用：默认使用 `8000` 端口，可通过 `WEB_PORT` 修改
- 查看启动日志是否有 `Web GUI: http://127.0.0.1:8000` 输出
- 如果前端未构建，访问根路径会显示提示页面

**Q7：Web GUI 数据不更新怎么办？**

- 检查浏览器控制台是否有 WebSocket 连接错误
- WebSocket 连接会自动重连（3秒间隔），网络恢复后会自动同步
- 确认交易主循环正常运行（TUI 有数据输出）

**Q8：如何在开发模式下使用 Web GUI？**

```bash
# 终端 1：启动前端开发服务器（支持热重载）
cd web && npm run dev

# 终端 2：启动交易框架
python run.py 1
```

前端开发服务器会自动代理 `/api` 和 `/ws` 请求到后端 `http://127.0.0.1:8000`。

---

## 使用定位

这个项目适合继续作为个人量化交易工作台演进：

- 策略研究放在 `backtest/` 和 `core/strategy/`
- 实盘执行放在 `core/engine/`
- 运行观察放在 `core/ui/`（TUI）和 `core/web/` + `web/`（Web GUI）
- 报告和通知放在 `core/utils/` 与 `scripts/`
- 参数管理放在 `core/config/settings.py`，敏感信息通过 `.env` 注入

后续扩展可以优先考虑：多交易对支持、持仓状态持久化、统一事件总线、回测和实盘共享订单模型、K线图表集成、以及更完整的测试覆盖。
