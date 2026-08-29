# Changelog

## 1.0.2 - 2026-08-29

### Fixed

- Frida server helper 现在返回 `pid / remote_path / started_by_run`；cleanup 只停止本轮拥有且 PID、路径精确匹配的后台 server，再删除本轮文件。
- cleanup engine 使用可注入 action、严格 LIFO、幂等 stop/verify 与错误聚合；运行错误、停止失败、验证失败和残留不再相互覆盖或静默丢失。
- finally 后逐项验证 Probe、server、forward、Gadget/config 与 `/data/local/tmp/cf_*` 无残留。

### Tests

- 新增 7/7 可注入 cleanup tests：各步骤故障、严格 LIFO、幂等、停止失败、残留、错误聚合和 ownership gate。

### Boundaries

- READY、Root 文档口径、Android 9 Hook/serializer 与 `batch_spin` 六字段保持不变；未启动模拟器、Frida、Collector 或执行 Spin。

## 1.0.1 - 2026-08-29

### Fixed

- 把一键入口的运行时 cleanup 收敛到 `finally`，READY 失败或中途异常时也按 LIFO 清理 Probe、ADB forward、Gadget、server 与临时文件，并显式报告 cleanup 失败。
- READY 只接受已验证的 `hook-status`：`onUIThreadReceiveMessage` 与 `lua_pcall` 必须均已安装；脚本加载或任意 Frida 消息不再误报 READY。
- 统一 Root 文档口径：Collector 只检测、不改变 Root；会话后由 User 手动关闭 Root、重启研究实例并验证失效。

### Boundaries

- 本修订没有启动模拟器、执行 Spin、改变 Android 9 Hook/serializer 路线或扩大 `batch_spin` 六字段 schema。

## 1.0.0 - 2026-08-28

### Added

- 建立 `adapters/`：exact-target `batch_spin`、`keepalive` 与集中 Registry。
- 固定统一 Event 顶层 `event + adapter + source + payload`。
- 固定新 Session 的 manifest、source events、normalized events、Spin Records、JSON/Markdown summary artifacts。
- 增加完全合成的 Adapter、Session、legacy re-extract、summary 与一键部署回归测试。

### Changed

- 正式仓库改名为 `CF_collect`，面向用户的介绍统一使用“【游戏】”。
- Raw scoped records 从 `events.jsonl` 分离到 `source_events.jsonl`；`events.jsonl` 只保存 normalized Adapter Event。
- 修复一键脚本的项目根默认值、Frida server `.xz` 下载路径，以及 server helper 未使用项目 venv 的问题。

### Boundaries

- `batch_spin` schema 固定为 `base_win / bonus_base_win / total_win / coins / win_lines / win_pos_list`，不发现或输出额外字段。
- Android 9 inbound Hook/serializer、Gadget bootstrap 和人工操作路线不变。
- 未迁移 DS Sidecar 历史、`.local/`、真实 Session、fixtures/artifacts、schema expansion 或实验文件。
