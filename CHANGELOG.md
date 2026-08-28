# Changelog

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
