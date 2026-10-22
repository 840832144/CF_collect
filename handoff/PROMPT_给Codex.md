# 给 Codex 的话术（整段复制）

> **后续更正：先读 `result/接手诊断_20261022.md`。** 当前两台已是 Play 来源的 4.87 / arm64；现场证据定位到登录成功后的 `store_v2` 资源等待。下文关于必有 x86_64 包及 Houdini 根因的说法尚未证实，不宜继续原样转述为结论。两个测量目标仍未完成。

> 使用方式：把下面整段丢给 Codex（或其它能操作本机终端/ADB 的 Agent）。
> 前提：它能在本机 Windows 上跑 PowerShell + adb。

---

接手一个卡住的任务。**先读完 `D:\CF_LevelSpins_Handoff\README_HANDOFF.md`（含 tools/ 与 evidence/）再动手**，第 5、6 节是我已经排除掉的坑，别重复验证。

**任务目标（两个问题，都要证据）：**
1. Cash Frenzy（`slots.pcg.casino.games.free.android`，国服"爆有錢 ONLINE"，Cocos2d-x + Lua）**新号从 1 级到 10 级，每一级各需要多少次 spin**。给表格 + 口径说明（"升到下一级所需 spin"）。
2. 游戏提示"可以提升 bet"时，**这个提升是强制还是非强制**。判定：提示出现时先不点、截图记当前档位 → 关掉提示 → 打开 BET 面板看**旧低档位是否还在且可选**（可选=非强制；只剩新档=强制）。两个分支都要截图。

**当前状态（我卡住的地方）：**
- CF 装上后**永久卡在 95%**，界面 `檢查遊戲資源中...`。两台实例（`127.0.0.1:5605 / Pie64_5 topTycoon`、`127.0.0.1:5585 / Pie64_3 AppResearch2`）表现一致。
- 网络侧我已经修到"该通的都通了"：CF 的 CDN(`d2rargdj3vlbg6.cloudfront.net`)、GCS、自家 AWS 后端直连可达；Google 与 Meta(Facebook) 通过我写的宿主 SNI 中继 + 模拟器内 iptables DNAT 也能通了（中继日志可见 `firebaseinstallations / play.googleapis / games.googleapis / graph.facebook.com` 全部隧道成功）。
- 实测：CF 进程**在跑循环**（~6% CPU 持续），但 `/data/data/<pkg>` 与 `/sdcard/Android/data/<pkg>` 体积**完全不变** → 不是在下载、不是在解包；进程状态 `S` + 周期 CPU = 请求重试循环。
- 已排除：资源 CDN 不通、GCS 不通、系统代理(`settings put global http_proxy`)、安装包缺 split（4.80 两件套 与 4.78 完整四件套都试过）、实例本身（两台一样）、Vulkan 渲染器（切成 OpenGL 也卡，配置已还原）、存储权限（app 根本没申请）。

**最可能的根因与首选尝试：** 现在装的是 **arm64-only 包**（`lib/` 下只有 `arm64/`），在 x86_64 蓝叠上走 Houdini 翻译，Cocos 在"最后资源校验"阶段对翻译层不稳很常见。
→ **优先在实例里用 Google Play 装原生 x86_64 包**（该实例已登录 `w6450265@gmail.com`，Google 链路现已通）：
```
adb -s 127.0.0.1:5605 shell 'am start -a android.intent.action.VIEW -d "market://details?id=slots.pcg.casino.games.free.android"'
```
若国区 Play 不提供该包，找一份带 `split_config.x86_64.apk` 的安装包 `install-multiple` 上去。

**网络工具（可直接复用，别重写）：**
```
python D:\CF_LevelSpins_Handoff\tools\google_sni_relay.py          # 宿主 443 SNI 中继 -> 代理 127.0.0.1:29290（需要先跑着）
adb -s 127.0.0.1:5605 push D:\CF_LevelSpins_Handoff\tools\cf_netfix.sh /data/local/tmp/cf_netfix.sh
adb -s 127.0.0.1:5605 shell 'su -c "sh /data/local/tmp/cf_netfix.sh"'   # Google+Meta 段 DNAT 到 10.0.2.2:443 + IPv6 REJECT
adb -s 127.0.0.1:5605 shell 'su -c "sh /data/local/tmp/cf_reach.sh"'     # 可达性体检
```
注意：iptables 规则**重启实例即丢**；`su -c "nohup fs16 ... &"` 起出来的 frida-server uid 是 `shell`（不够权限，`enumerate_processes` 会报 `unable to find process with name 'system_server'`），要用 `su -c "/data/local/tmp/fs16 -l 0.0.0.0:27042 --daemonize"` 之类的方式确认拿到 root。

**CF 一旦进得去大厅，测量这么做（方案已定）：**
- Frida hook `libcocos2dlua.so` 的 `curl_easy_perform`（读 `CURLOPT_URL`）或 SSL 层，拿每次 spin 的 `bet / win / xp / level`；参考 `D:\PopSlotsProbe\fvl_spin_logger.py`（滚动缓冲 + 花括号配平 + json 解析 + 按 id 去重 + 落 jsonl + 余额看门狗，结构可直接改）。
- 等级优先从响应字段取；没有则用"LEVEL UP 弹层模板匹配"：第一次升级截图当模板，之后每转比一次。
- 产物写到 `D:\CF_LevelSpins_Handoff\result\`：`spins_per_level.md/json`、`bet_unlock_check.md`、`spins.jsonl`、`evidence/*.png`。

**红线：**
- 不买任何东西（见到 `BUY / 首充 / 礼包` 一律关）。
- **别动 5585(Pie64_3) 上 POP! Slots 的东西**：那台正在做 FIRE VS LIGHTNING 的 RTP 测量（已暂停，随时恢复），别 `pm clear`、别改 `bluestacks.conf` 里 `Pie64_3.*`。
- 改 `bluestacks.conf` 前先备份（已有 `bluestacks.conf.bak_20261022_163250`）。
- 别把 5585 上那个 1.22 GB 的 CF 老账号数据 `pm clear` 掉——它是唯一"曾经能跑"的证据样本。

**开工前先回我三条：** ①你打算先试哪条路、为什么；②`cf_reach.sh` 体检结果；③如果 Play 装不了，你需要我提供什么（x86_64 安装包 / 能跑的实例快照 / 其它）。
