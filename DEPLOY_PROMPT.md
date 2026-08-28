# 一键部署话术

把下面内容与仓库地址交给本机部署助手即可。游戏内操作、Root 授权与继续/停止决定仍由 User 完成。

```text
你是部署工程师。请把 CF_collect 被动数据采集器部署到本机，并验证 Collector 1.0 的一键入口与本地 Session 结构。

Git 仓库：https://github.com/840832144/CF_collect

环境：Windows + Python 3.10+ + PowerShell 5.1+ + BlueStacks 5 专用 Android 9 研究实例；【游戏】已安装。

按顺序执行，每步报告实际结果：

1) git clone https://github.com/840832144/CF_collect.git CF_collect
2) 读取 README.md、config.json、docs/，用现场值核对 adb_serial、instance、package、app_version
3) 运行 powershell -ExecutionPolicy Bypass -File setup.ps1
4) 若专用研究实例 Root 未开启，停止并让我按 docs/ROOT_TOGGLE.md 完成备份、开启、重启与 uid=0 验证
5) 核对 package `slots.pcg.casino.games.free.android` 确实安装在该实例
6) 运行 powershell -ExecutionPolicy Bypass -File run_collector.ps1
7) Probe READY 后停下来，由我按本次授权手动执行普通 Spin；禁止自动点击、Auto Spin、购买、充值或挂机
8) 我完成后创建提示路径中的 STOP 文件，等待脚本 re-extract、summary 与 cleanup
9) 回读 session_manifest.json、summary.json 和 summary.md，只报告：最终状态、source/event/spin 聚合计数、Adapter warning/截断、六字段覆盖
10) 确认 Session 固定包含 session_manifest.json、source_events.jsonl、events.jsonl、spin_records.jsonl、summary.json、summary.md
11) 确认 events.jsonl 每行顶层严格为 event + adapter + source + payload；batch_spin 只含 base_win、bonus_base_win、total_win、coins、win_lines、win_pos_list
12) 清理 gadget、frida-server、forward 和进程；提醒我关闭 Root、重启实例并验证失效

约束：
- 只做被动、只读采集，不修改、伪造或重放请求/返回/内存/余额/奖励/服务器状态
- 不修改 Android 9 inbound Hook/serializer 路线，不进入 signer/encryptor/XXTEA/Stalker 或全局 Lua 日志
- 不恢复新字段，不扩大 batch_spin schema，不做 20-Spin/F4
- Raw、JSONL、完整响应、账号、token、绝对余额和逐笔值只留本机，不上传或提交 Git
- 任一 identity、Root、READY、cleanup 或 schema Gate 失败时报告精确 blocker，不以“应该可以”代替证据
```
