# 一键部署话术（给 DSH Desktop 用户直接粘贴）

> 前提：用户已有 DSH Desktop 且已连接 AIP，新建一个项目/对话，把下面整段话 + git 地址发进去即可。
> AI 会按步骤自动部署、检测环境、引导采集，并汇总结果。

## 粘贴这段话术

```
你是部署工程师。请把 CashFrenzy_collect 被动数据采集器完整部署到本机并完成一次验证采集。完全照做以下步骤。

Git 仓库：https://github.com/840832144/CashFrenzy_collect

我的环境（已具备）：Windows + DSH Desktop（已连 AIP）+ Python 3.10+ + BlueStacks 5（一个 Android 9 实例，已装 Cash Frenzy）。

请按顺序执行，每步报告结果，不要跳过或简化：

1) 把仓库克隆到当前工作区：git clone https://github.com/840832144/CashFrenzy_collect CashFrenzy_collect
2) 读取 README.md、config.json、docs/，用本机实际值更新 config.json（adb_serial、instance、package、app_version）
3) 运行部署：powershell -ExecutionPolicy Bypass -File setup.ps1
   - 它会自动：建 venv、装依赖（frida==17.17.0 等）、检测 adb（蓝叠 HD-Adb）、连接模拟器、
     检测 Cash Frenzy 是否安装、检查 root、下载/定位 Frida 17.17.0 两个二进制（或让我把二进制放进 ./bin/）
4) 若 root 未开启：按 docs/ROOT_TOGGLE.md 的备份/回滚流程，在【专用研究实例】开启 root；
   先备份 bluestacks.conf + 记录 VHDX 哈希；验证 adb -s <serial> shell "/system/xbin/bstk/su -c id" 返回 uid=0
5) 确保 Cash Frenzy（slots.pcg.casino.games.free.android）已装到该研究实例；未装则提示我安装
6) 运行采集：powershell -ExecutionPolicy Bypass -File run_collector.ps1
   - 它会自动：推送并启动改名 frida-server、注入 arm64 gadget、探针 READY
   - READY 后弹提示让我在模拟器里正常游玩 ≥20 次老虎机（先手动、可 auto、遇 respin 更好；
     遇升级/活动弹窗点掉 × 继续）
   - 采集完成后自动停止、提取，生成 data/sessions/<id>/summary.json（脱敏）+ spin_records.jsonl
7) 汇总：读取 summary.json，报告捕获的 spin 数、字段覆盖（base_win/bonus_base_win/total_win/coins/
   win_lines/win_pos_list）、是否 ≥20 次、是否有 error；确认与预期 schema 一致
8) 收尾：清理设备上临时工具（gadget/frida-server/forward）、按 docs/ROOT_TOGGLE.md 回滚 root、
   确认无残留（/data/local/tmp 无 cf_*、ps -A 无 cf_rt）。

约束（必须遵守）：
- 只做被动采集，不修改请求/返回值/余额/内存/服务器状态；不重打包 APK（保持 v3 签名完整）
- 不 hook libsigner / libEncryptorP / XXTEA 加密链
- 逐笔数值（coins/win/bet）只存本机；报告只使用脱敏的 summary.json
- 任一命令失败先看输出归因（改配置/环境/提示我处理），不要用“应该可以”代替证据
- 全程只使用 1 个专用研究实例 + 专用研究账号，与日常实例/账号隔离
```

## 说明

- 若用户没有 root 或 Cash Frenzy 未装，AI 会停留在对应步骤并提示，不硬来。
- 该话术让 AI 复用仓库里的 `setup.ps1`（自动检测/下载）与 `run_collector.ps1`（一键采集/清理），
  需要大改时直接改 `config.json`，不要改采集逻辑。
- 部署完成后，用户把 `data/sessions/*/summary.json`（脱敏）交给分析即可，数值类 `spin_records.jsonl` 留本机。
