# CashFrenzy_collect

对 **Cash Frenzy™ — Casino Slots**（Android）做**被动、只读**游戏数据采集与结构化解码的工具。
目标是拿到老虎机的结构化玩法数据：**每笔下注 → 停轮(wins) → base/bonus/total 赢分 → 余额(coins) → 彩金(respin/免费游戏)**，
用于游戏体验/策划分析。**只观察、复制、解析，绝不修改请求、返回值、余额或服务器状态。**

> 底层只依赖 Windows 上常见的 **BlueStacks 5 + adb + Python + Frida**，**不依赖任何特定 AI 工具 / 特殊宿主**。
> 任何人按本文档在一台普通 Windows 机器上即可部署运行。

## 它采集什么（一次会话输出）

| 数据 | 来源 | 说明 |
|---|---|---|
| `batch_spin` 结果 | 入站 Lua `lua_pcall` 参数 | `base_win / bonus_base_win / total_win / coins / win_lines / win_pos_list`（含 sub-list 明细） |
| 直接余额 | `keepalive.coins` + `batch_spin.coins` | 服务器下发的真实余额（非推导） |
| 下注信息 | `bet_per_line / max_bet_multiplier / avg_bet / lounge_min_bet` | 下注档位与上下限 |
| 彩金奖池 | `jp_data` + `new_broadcast_jackpot.bet` | minor/mini/grand/major |
| 特殊玩法 | `free_game.base_win` | respin / 免费游戏触发 |

产出目录：
```
data/sessions/<session_id>/
├── events.jsonl        原始序列化事件（深度受限，含结构摘要）
├── spin_records.jsonl  精简的 spin 记录（数值）
├── summary.json        脱敏结构摘要（不含绝对数值，可入 Git）
└── session_manifest.json  会话信息
```

## 前置条件

1. **Windows** + **BlueStacks 5 China**（或任一支持 arm64 native bridge 的 Pie/Android 9 实例）
2. **Cash Frenzy**（`slots.pcg.casino.games.free.android`）安装在**研究实例**上，能正常游玩
3. **Python 3.10+** 和 **PowerShell 5.1+**
4. 研究实例的**临时 root**（用于把 Frida gadget 注入游戏进程；见 `docs/ROOT_TOGGLE.md`，含备份/回滚，不影响日常实例）
5. **Frida 17.17.0** 两个二进制（`setup.ps1` 可自动下载到 `./bin/`）：
   - `frida-server-17.17.0-android-x86_64`（x86_64 宿主力）
   - `frida-gadget-17.17.0-android-arm64.so`（arm64 游戏侧）

> **为什么需要 root？** BlueStacks 本体是 x86_64 而游戏核心是 arm64（经 Houdini 转译）。
> 只有在研究实例开启 root，才能把 arm64 Gadget 加载进游戏自己的 native-bridge 命名空间，
> 从而在**明文层**观察到已解码的 Lua 数据结构——**不需要碰 `libsigner`/`libEncryptorP`/XXTEA 加密链**。

## 快速开始

```powershell
# 1) 部署（检测 adb/蓝叠、建 venv、下载/定位 Frida 二进制、校验设备）
powershell -ExecutionPolicy Bypass -File setup.ps1

# 2) 采集（一键：部署 gadget → 探针 READY → 玩家正常游玩 → 自动停止 + 提取）
powershell -ExecutionPolicy Bypass -File run_collector.ps1
```

`run_collector.ps1` 会：
1. 预检（设备在线、包已装、root 已开）
2. 推送并启动改名 frida-server（会话后删除）
3. 把 gadget + config 部署到游戏 `lib/arm64` 命名空间
4. 冷启动游戏、注入 Gadget、探针 READY
5. **提醒你正常游玩**（建议 ≥20 次拟人节奏 Spin，含 auto/respin 更好）
6. 停止 → `cf_rextract.py` + `cf_summarize.py` 出数据与脱敏摘要
7. 强制清理（gadget/server/forward/进程），不残留

### 手动分步（排障用）

```powershell
# 用已装好的 Frida 自己一步步来，日志更清楚
powershell -File collector/cf_start_frida_server.ps1 -ServerPath <frida-server> -Serial 127.0.0.1:5585
adb -s 127.0.0.1:5585 forward tcp:27043 tcp:27043
python collector/cf_bootstrap_gadget.py --device-id 127.0.0.1:5585 --gadget-path <app lib/arm64/libcash-gadget.so>
python collector/cf_probe.py --session-dir data/sessions/<id> --endpoint 127.0.0.1:27043 --duration 2400 --max-depth 7
```

## 配置

所有参数在 `config.json`：
- `adb_serial` / `instance` / `package` / `app_version`：环境标识
- `gadget_port`：默认 `27043`（listen）
- `frida_version`：必须 `17.17.0`（host/server/gadget 三者一致）
- `max_depth`：默认 `7`（深度 7 才能完整还原嵌套结果；低于此会被截断）
- `bin.frida_server` / `bin.frida_gadget`：留空则 `setup.ps1` 自动下载到 `./bin/`

## 数据边界 & 安全（务必阅读）

- 这是**客户端可见**的数据，不等同于完整游戏数学（部分逻辑可能依赖 Lua/native/资源配置）。
- **逐笔绝对值（coins/win/bet）只存本机**；Git 只提交 `summary.json` 等脱敏摘要。
- 不 hook `libsigner`/`libEncryptorP`/XXTEA；不从 APK 重打包（保持 v3 签名完整）。
- 会话过程：临时工具用后即删、root 会话后回滚、账号/实例/IP 隔离。详见 `docs/STEALTH.md`。

## 已知限制

- 偶发**升级/活动弹窗会打断下注**（游戏自身行为，正常）；采集器照常记录其余事件。
- 超大的彩金/奖池 payload 可能触发单消息 64KiB 预算被截断（不影响 spin 主字段，`summary.json` 会标注 `message-budget`）。
- 1 个实例同时只跑 1 个采集会话；如需多开按实例隔离。

## 参考

- 逆向基线：TASK-0022 可行性审计 / TASK-0024 入站结构化采集 Spike（本仓库 docs 摘要）
- 协议：`BLSocket`（UDP）+ Cocos2d-x + LuaJIT，明文在 Lua dispatch 层
