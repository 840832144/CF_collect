# 部署指南（普通 Windows 环境）

Collector 1.0 独立运行于 Windows + BlueStacks 5 + adb + Python + Frida 17.17.0，不依赖特定 AI 宿主。采集只发生在【游戏】专用 Android 9 研究实例中，真实 Session 与逐笔值只留本机。

## 1. 环境

| 组件 | 要求 | 作用 |
| --- | --- | --- |
| Windows | 10/11 x64 | 宿主 |
| BlueStacks 5 | 支持 arm64 native bridge | 模拟器 |
| 研究实例 | Pie / Android 9，独立于日常实例 | 运行【游戏】 |
| 【游戏】 | package `slots.pcg.casino.games.free.android` | 目标应用 |
| Python | 3.10+ x64 | Adapter / Session 工具 |
| PowerShell | 5.1+ | 一键编排 |
| Frida | 17.17.0 host/server/gadget 一致 | 已验证的 scoped probe 路线 |

## 2. 一次性部署

```powershell
git clone https://github.com/840832144/CF_collect.git CF_collect
cd CF_collect

# 先用当前研究实例的现场值更新 config.json
powershell -ExecutionPolicy Bypass -File setup.ps1
```

`setup.ps1` 会创建 `.venv`、安装依赖、定位 adb、连接实例、检查 package/Root，并下载或定位 Frida 二进制。若实例 identity、package 或 Root 不符合预期，先修复环境，不修改采集逻辑绕过。

## 3. Root Gate

只在专用研究实例按 [ROOT_TOGGLE.md](ROOT_TOGGLE.md) 开启 Root：

```text
adb -s <serial> shell "/system/xbin/bstk/su -c id"
```

必须返回 `uid=0(root)`。开启前备份配置，Session 后关闭 Root、重启实例并验证失效。

## 4. 一键运行

```powershell
powershell -ExecutionPolicy Bypass -File run_collector.ps1
```

固定顺序为：

```text
preflight → renamed frida-server → gadget staging → adb forward
→ Android 9 bootstrap → scoped probe READY → User 手动操作
→ stop → deterministic re-extract → summary → cleanup
```

READY 后只由 User 按本次授权手动执行普通 Spin。脚本不会自动点击、Auto Spin、购买、充值或长时间挂机。

## 5. 输出

```text
data/sessions/<session_id>/
├── session_manifest.json
├── source_events.jsonl
├── events.jsonl
├── spin_records.jsonl
├── summary.json
└── summary.md
```

- `source_events.jsonl`：Android 9 scoped source records；
- `events.jsonl`：顶层严格为 `event + adapter + source + payload`；
- `spin_records.jsonl`：状态为 `ok` 的 `batch_spin` Event 子集；
- `summary.*`：只含 Adapter 命中、warning、截断和六字段覆盖计数，不含逐笔值。

所有 JSONL 和真实 Session 都被 Git 忽略。只分享确有需要的脱敏聚合，不提交完整响应、账号、token 或绝对余额。

## 6. 离线重建

```powershell
python collector/cf_rextract.py data/sessions/<session_id>
python collector/cf_summarize.py data/sessions/<session_id>/events.jsonl `
  --output data/sessions/<session_id>/summary.json `
  --markdown data/sessions/<session_id>/summary.md
```

新 Session 从 `source_events.jsonl` 确定性重建。旧 Session 若只有 raw `events.jsonl`，原文件保持只读，normalized 输出写入 `normalized_events.jsonl`。

## 7. 常见问题

- `device offline`：核对实例已启动及 `adb_serial`；
- `package not found`：确认【游戏】安装在当前研究实例；
- `root NOT active`：按 Root 文档开启并重启实例；
- Probe 未 READY：核对 Frida 三端版本、Gadget staging、forward 和前台 package；
- Adapter 0 命中：保留本地 source/manifest，检查 exact command/shape；不要通过扩大字段或全局 Lua 日志补救；
- 运行路线需要改变：停止并进入新的 Task/Review，不在 Collector 1.0 内继续协议研究。
