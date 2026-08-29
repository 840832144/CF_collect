# CF_collect

这是面向 Android 9 研究实例的【游戏】被动、只读数据采集器。Collector 1.0 把已验证的 inbound-scoped Lua source records 转换为固定 Adapter Event 和 Session artifacts，用于本地复现与策划分析。

工具只观察应用已经解码的数据，不修改请求、返回值、余额、奖励、内存或服务器状态。Android package、Lua command 和 native module 等运行所需技术标识保持真实名称；公开介绍统一使用“【游戏】”。

## Collector 1.0 边界

- Android 9 `onUIThreadReceiveMessage` scope + `lua_pcall` 采集路线保持不变；
- 只注册 `batch_spin` 与 `keepalive` 两个 Adapter，未知命令 fail closed；
- `batch_spin` 固定六字段：`base_win / bonus_base_win / total_win / coins / win_lines / win_pos_list`；
- 不发现同对象额外字段，不扩 schema，不做 20-Spin/F4；
- Raw、逐笔值、完整响应、账号和绝对余额只保存在本地 Session，Git 不接收真实 Session。

## 架构

```text
Android 9 scoped probe
        │
        ▼
source_events.jsonl
        │
        ▼
adapters/registry.py
   ├─ batch_spin.py
   └─ keepalive.py
        │
        ├─ events.jsonl
        └─ spin_records.jsonl
```

所有 normalized Event 顶层严格固定为：

```json
{
  "event": {},
  "adapter": {},
  "source": {},
  "payload": {}
}
```

`payload.fields` 只包含对应 Adapter 的 allowlist；类型变化、缺字段和截断通过 `warnings` 显式记录。

## Session 输出

```text
data/sessions/<session_id>/
├── session_manifest.json  schema、runtime identity、artifact map、计数与最终状态
├── source_events.jsonl    scoped source records（本机）
├── events.jsonl           统一 Adapter Event（本机）
├── spin_records.jsonl     有效 batch_spin Event 子集（本机）
├── summary.json           不含逐笔值的聚合摘要
└── summary.md             同一摘要的可读版
```

旧 Session 只有 raw `events.jsonl` 时，`cf_rextract.py` 会只读该文件，并把 normalized Event 写到 `normalized_events.jsonl`，不会覆盖旧 Raw。

## 前置条件

1. Windows 10/11、PowerShell 5.1+、Python 3.10+；
2. BlueStacks 5 的专用 Pie / Android 9 研究实例；
3. 【游戏】已安装，技术 package 为 `slots.pcg.casino.games.free.android`；
4. 研究实例临时 Root，按 [Root 开关说明](docs/ROOT_TOGGLE.md) 备份和回滚；
5. Frida 17.17.0 host/server/gadget 版本一致。

不要修改或复用日常 BlueStacks 实例做 Root/Frida 实验。

## 快速开始

```powershell
# 一次性部署
powershell -ExecutionPolicy Bypass -File setup.ps1

# 一键运行：preflight → server → gadget → bootstrap → verified probe READY
#          → User 手动操作 → stop → re-extract → summary → cleanup
powershell -ExecutionPolicy Bypass -File run_collector.ps1
```

Probe 只有在收到并验证 `hook-status`，且 `onUIThreadReceiveMessage` 与 `lua_pcall` 两个 scoped hooks 均已安装后才进入 READY。进程启动、脚本加载或任意 Frida 消息都不等于 READY。READY 后只按本次明确授权由 User 手动执行普通 Spin。采集器不会自动点击、Auto Spin、购买、充值或挂机。完成后在提示的 Session 目录创建 `STOP` 文件，或等待配置的时限结束。

手动排障入口保持可用：

```powershell
powershell -File collector/cf_start_frida_server.ps1 -ServerPath <frida-server> -Serial <adb-serial>
python collector/cf_bootstrap_gadget.py --device-id <adb-serial> --gadget-path <app-lib-path>
python collector/cf_probe.py --session-dir data/sessions/<id> --endpoint 127.0.0.1:27043 --duration 600 --mode lua
python collector/cf_rextract.py data/sessions/<id>
python collector/cf_summarize.py data/sessions/<id>/events.jsonl --output data/sessions/<id>/summary.json --markdown data/sessions/<id>/summary.md
```

## 配置

`config.json` 保存 `adb_serial / instance / package / app_version / gadget_port / frida_version / max_depth / session_duration_seconds` 以及可选二进制路径。实例和版本必须以当前研究环境现场值为准。

## 离线回归

```powershell
py -m compileall -q adapters collector tests
py -m unittest discover -s tests -v
powershell -NoProfile -ExecutionPolicy Bypass -File tests/Test-Cleanup.ps1
```

测试全部使用代码内合成 records，不依赖 `.local/`、真实 Session、fixture 或模拟器。

## 安全与停止边界

- Hook 只在 inbound dispatch thread/scope 内激活；无全局 Lua API 日志、Stalker 或 signer/encryptor/XXTEA 路线；
- 不重打包 APK，不修改请求/返回/余额/奖励，不伪造或重放业务消息；
- Gadget、server、forward、进程和临时文件由 `finally` 路径按严格 LIFO 清理；Frida helper 返回 `pid / remote_path / started_by_run`，只停止本轮拥有且路径、PID 均精确匹配的 server 进程；
- cleanup 后逐项验证 Probe、server、forward、Gadget/config 与 `/data/local/tmp/cf_*` 均无残留；停止、验证和残留错误会聚合报告，不静默吞掉；Collector 只检测、不改变 BlueStacks Root；
- Session 后由 User 按 [Root 开关说明](docs/ROOT_TOGGLE.md) 手动关闭 Root、重启研究实例并验证 `su -c id` 不再返回 `uid=0`；
- 若需要恢复新字段、扩大 schema、进入新协议层或修改 Android 9 路线，停止并另走 Review/Task；
- `.local/`、`data/`、JSONL、APK、SO、日志和真实 Session 均不进入 Git。

更多说明见 [部署指南](docs/DEPLOYMENT.md)、[Root 开关](docs/ROOT_TOGGLE.md) 与 [安全清单](docs/STEALTH.md)。
