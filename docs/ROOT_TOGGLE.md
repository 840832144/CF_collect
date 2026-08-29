# 研究实例 Root 开关（备份 / 开启 / 回滚）

> 仅在**专用研究实例**上操作，不影响日常实例与账号。机器级变更，开启前先备份并保留回滚证据。
>
> Root 始终由 User 手动控制。`setup.ps1` 与 `run_collector.ps1` 只检测当前状态，不会编辑 BlueStacks 配置、自动开启、自动关闭或自动回滚 Root。

## 1. 备份（开启前必做）

- 备份 `bluestacks.conf`（位置通常在 `C:\Program Files\BlueStacks_nxt_cn\` 或用户数据目录 `D:\BlueStacks_nxt_cn\bluestacks.conf`）
- 备份实例描述文件（如 `Pie64_3.bstk` / `Pie64_3.bstk-prev`）
- 记录实例 VHDX 的 SHA-256（用于会话后对照）
- 记录 root 键原值：`bst.instance.<实例名>.enable_root_access`

## 2. 开启

- 方法 A（推荐）：BlueStacks 多开管理器 → 该实例 → 设置 → 开启 Root → **重启实例**
- 方法 B：编辑 `bluestacks.conf` 将 `bst.instance.<实例名>.enable_root_access` 改为 `"1"`，然后重启实例
- 验证：`adb -s <serial> shell "/system/xbin/bstk/su -c id"` → `uid=0(root)`

## 3. 会话完成后由 User 手动回滚（每次必做）

- 关闭 root（conf 改回 `"0"` 或 GUI 关闭），**重启实例**（确认 root 已失效：`su -c id` 不再返回 root）
- 核对 VHDX SHA-256 与备份一致（除游戏自身数据外）
- 确认设备无残留：`/data/local/tmp` 无 `cf_*`、`ps -A | grep cf_rt` 为空

Collector 的自动 cleanup 只处理 Gadget、frida-server、ADB forward、Probe 进程和临时文件。看到 cleanup 完成不代表 Root 已关闭；必须完成本节的关闭、重启和失效验证。

> 注意：root 开关在**实例启动时**读取，改完 conf 必须**重启实例**才生效。
> 若 `adb emu kill` + 重启后 uptime 没变小（guest 未真正重启），改用蓝叠管理器关闭实例再启动。
