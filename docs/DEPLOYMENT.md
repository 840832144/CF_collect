# 部署指南（普通 Windows 环境，无特殊宿主依赖）

> 这套采集器**完全独立运行**：Windows + BlueStacks 5 + adb + Python + Frida 17.17.0。
> **不需要任何 AI 工具 / 特殊宿主 / "破解 ds"**。采集是玩家一边玩、脚本一边静默抓包，
> 不需要截图、点击或 agent 能力。

## 一、装什么

| 组件 | 版本/来源 | 作用 |
|---|---|---|
| Windows | 10/11 x64 | 宿主 |
| BlueStacks 5 China | 5.22.x（或任一支持 arm64 native bridge 的） | 模拟器 |
| 研究实例 | Pie（Android 9）、x86_64 + arm64 转译 | 跑 Cash Frenzy |
| Cash Frenzy | `slots.pcg.casino.games.free.android` 4.78/478 | 目标游戏 |
| Python | 3.10+ (x64) | 探针/解码 |
| PowerShell | 5.1+ | 编排 |
| Frida | 17.17.0 两个二进制 | 注入 + 采集 |

## 二、一次性部署

```powershell
# 1) 克隆本项目
git clone <你的仓库地址> CashFrenzy_collect
cd CashFrenzy_collect

# 2) 改 config.json 里的 adb_serial / instance（对应你的蓝叠实例 adb 端口）

# 3) 运行 setup
powershell -ExecutionPolicy Bypass -File setup.ps1
```

`setup.ps1` 会自动：建 venv、装依赖、定位 adb、连接实例、检测 Cash Frenzy 是否装好、
检查 root、下载/定位 Frida 二进制（也可手动把两个二进制放进 `./bin/`）。

## 三、开启研究实例 root（必须，但只影响研究实例）

在**专用研究实例**（别用日常实例）开启 root：
- BlueStacks 设置 → 该实例 → Root 打开 → 重启实例；
- 或按 `docs/ROOT_TOGGLE.md` 的备份/回滚流程操作。

验证：`adb -s <serial> shell "/system/xbin/bstk/su -c id"` 应返回 `uid=0(root)`。

> 用**独立研究实例** + **独立研究账号**，与日常实例/账号完全隔离。这就是"账号隔离"。

## 四、采集（每次）

```powershell
powershell -ExecutionPolicy Bypass -File run_collector.ps1
```

它会：预检 → 装 frida-server → 注入 gadget → 探针 READY → **提示你正常游玩** →
停止 → 自动提取 + 汇总 → 清理。你在探针 READY 后切到游戏正常转就行，建议 ≥20 次：先手动，
后 auto，遇升级/活动弹窗点掉即可。

## 五、出数据

```
data/sessions/<session_id>/
├── events.jsonl        原始结构化事件（含深度受限结构）
├── spin_records.jsonl  精简 spin 记录（base_win/total_win/coins/...）
├── summary.json        脱敏结构摘要（可入 Git / 分享）
└── session_manifest.json
```

用 `cf_summarize.py` 的 `summary.json` 做字段覆盖/一致性，用 `spin_records.jsonl` 做数值分析。

## 六、常见问题

- **设备离线**：确认蓝叠实例在跑、`adb_serial` 正确；`adb connect <serial>`。
- **root 未生效**：按 `docs/ROOT_TOGGLE.md` 开启；改完要重启实例才生效。
- **package not found**：Cash Frenzy 装到研究实例。
- **probe 一直不 READY**：检查 gadget 是否注入成功（`logcat | grep "Listening on"`），
  Frida 版本三者一致（host/server/gadget 必须都是 17.17.0）。
- **gadget 注入后被弹窗/升级打断**：正常，采集器仍记录其余事件。
