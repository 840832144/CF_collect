# CF 1→10 级 spin 计数 + 升 bet 强制性核实 —— 交接文档（给 Codex）

> **2026-10-22 后续接手核对：请先读 [本轮诊断](result/接手诊断_20261022.md)。** 两台当前均为 Play 来源的 4.87 / arm64；实际启动已出现 `login_success`，随后 `store_v2 / need_download / need_reason_new=8`，仍未进入大厅。下文“Play 必定下发 x86_64”“网络已全部排除”“CPU 证明请求重试”“5585 仍有 1.22 GB”均不能直接当作已验证现状。原交接保留作为历史记录。

> 目标读者：接手的 AI。**先读完第 1、5、6 节再动手**，第 5 节是我已经排除掉的坑（别重复烧时间）。
> 生成时间：2026-10-22。目标游戏：Cash Frenzy（`slots.pcg.casino.games.free.android`，国服名"爆有錢 ONLINE"，Product Madness，Cocos2d-x + Lua）。

---

## 1. 任务（两个问题，都要证据）

1. **新号从 1 级到 10 级，每一级各需要多少次 spin？**
   要求：连续逐级记录，给出 `等级 → 该级消耗 spin 数` 的表，并说明口径（是"升到下一级所需 spin"还是"在该级停留期间的 spin"）。
2. **游戏提示"可以提升 bet"时，这个提升是强制还是非强制？**
   判定方法：提示出现时**先不点**，截图记下当前 bet 档；关掉提示后打开 BET 面板，看**旧的低档位是否还在、是否仍可选中**。
   - 旧档可选 → 非强制（只是解锁更高档）
   - 只剩新档 / 必须确认才继续 → 强制
   两个分支都要截图存证。

---

## 2. 环境现状（都在本机，已就绪）

| 项 | 值 |
|---|---|
| 实例（跑 CF 用） | `Pie64_5` / 显示名 `topTycoon` / adb `127.0.0.1:5605` |
| 实例（另一台，同样装了 CF） | `Pie64_3` / `AppResearch2` / adb `127.0.0.1:5585` |
| 分辨率 | 1600×900，DPI 240 |
| root | 已开（`su -c id` → uid=0），conf 里 `enable_root_access="1"` |
| CF 包 | `slots.pcg.casino.games.free.android` |
| CF 安装包（本机） | `D:\CashFrenzyResearch\local-only\apk\4.80-vc480\`（base + arm64_v8a，2 件）<br>`D:\CashFrenzyResearch\local-only\apk\4.78-vc478\`（base + arm64_v8a + hdpi + zh，**4 件完整**） |
| CF 的 ABI | **只有 arm64**（`lib/` 下仅 `arm64/` + `containsArmLibs.txt`），在 x86_64 蓝叠上走 Houdini 翻译 |
| frida-server | `D:\PopSlotsProbe\bin\fs16`（16.7.19，114 MB）。5605 已 push 到 `/data/local/tmp/fs16`；宿主 frida-python 也是 16.7.19 |
| 宿主代理 | `127.0.0.1:29290`（用户自备，**能通 Google**；但对 CloudFront 返回 403） |
| 宿主 IP / 默认路由 | 仅 WLAN，**没有 TUN 网卡**（用户说"改完了"但实测无 TUN，Google 仍不通） |

---

## 3. 当前阻塞症状（一句话）

CF 启动后卡在 **95%**，界面文字 `檢查遊戲資源中...`，**永不前进**；两台实例表现完全一致（截图 `evidence/01_..png` 与 `02_..png` 是逐字节相同的帧）。

---

## 4. 已经做过的网络侧改造（可直接复用，不必重写）

因为缺失的只有 Google 链路，我搭了一套"透明回落"，让**模拟器里不认识系统代理的原生栈**（Cocos/libcurl、GMS）也能借宿主的 HTTP 代理出去：

1. `tools/google_sni_relay.py` —— 宿主上监听 `127.0.0.1:443`，读取 TLS ClientHello 的 **SNI**，再通过 `127.0.0.1:29290` 代理 `CONNECT <SNI>:443` 双向透传。
   ```powershell
   python D:\CF_LevelSpins_Handoff\tools\google_sni_relay.py
   ```
2. `tools/cf_ipv6.sh` —— 在模拟器里 root 执行：
   - `iptables -t nat` 把 Google 的 IPv4 段（172.217/16、216.239.32/20、142.250/15、142.251/16、74.125/16、173.194/16:443）**DNAT 到 10.0.2.2:443**（= 上面的中继）
   - `ip6tables` 对 Google 的 IPv6 段 `REJECT`，逼客户端回落 IPv4
   ```powershell
   adb -s 127.0.0.1:5605 push tools\cf_ipv6.sh /data/local/tmp/cf_ipv6.sh
   adb -s 127.0.0.1:5605 shell 'su -c "sh /data/local/tmp/cf_ipv6.sh"'
   ```
3. `tools/cf_reach.sh` —— 一键可达性体检（storage.googleapis / firebaseinstallations / cloudfront / www.google）。
   ```powershell
   adb -s 127.0.0.1:5605 push tools\cf_reach.sh /data/local/tmp/cf_reach.sh
   adb -s 127.0.0.1:5605 shell 'su -c "sh /data/local/tmp/cf_reach.sh"'
   ```

**改造后实测**（中继日志）：CF 确实成功到达
`firebaseinstallations.googleapis.com`、`firestore.googleapis.com`、`play.googleapis.com`、`www.googleapis.com`、`games.googleapis.com`、`gameswhitelisted.googleapis.com`、`android.apis.google.com`、`firebaselogging.googleapis.com`。
→ **Google 链路已经不是瓶颈**，但 CF 仍然卡 95%。

> 回滚：`adb shell su -c "iptables -t nat -F OUTPUT; ip6tables -F OUTPUT"`，宿主把中继进程停掉即可。
> 注意：这些 iptables 规则**重启实例即丢**，需要重加。

---

## 5. 已排除的假设（别重复验证）

| 假设 | 验证方式 | 结论 |
|---|---|---|
| 资源 CDN 不通 | 设备内 `nc -z d2rargdj3vlbg6.cloudfront.net 443`（CF 的真实 CDN，从 app 文件里 grep 出来的） | ✅ **通**，不是它 |
| GCS 不通 | `nc -z storage.googleapis.com 443` | ✅ 通 |
| Firebase / Play Games 不通 | 见第 4 节，中继后确认可达 | ✅ 已解决，但仍卡 → **不是根因** |
| 系统代理能救 | `settings put global http_proxy 10.0.2.2:29290` | ❌ 无效：Cocos 的 libcurl 不读系统代理；且该代理对 CloudFront 返 403（反而可能弄坏资源下载）。**当前已清空** |
| 安装包缺 split | 4.80（2 件）→ 4.78（**完整 4 件**）重装两次 | ❌ 都卡 95% |
| 实例本身坏了 | 同一 CF 在 **5605 与 5585** 各跑一遍（5585 的 CF 数据有 1.22 GB、以前能进） | ❌ 两台一样卡 → 不是实例问题 |
| Vulkan 渲染问题 | `bluestacks.conf` 把 `Pie64_5.graphics_renderer` 从 `vlcn` 改成 `gl`，重启实例再试 | ❌ 仍卡 95%（**配置已还原成 vlcn**，备份 `bluestacks.conf.bak_20261022_163250`） |
| 缺存储权限 | `pm grant WRITE_EXTERNAL_STORAGE` | CF 根本没申请该权限（走 app 私有目录），不成立 |
| 在下载大资源 | 连续 `du -sk /data/data/<pkg>` 与 `/sdcard/Android/data/<pkg>` | 完全不动（≈28 MB / 12 KB 静止）→ **没在下载，是真空转** |

---

## 6. 剩余最强假设（建议按顺序试）

### 6.0 17:10 追加的两条新证据（很重要，接手先看这段）

在 `AppResearch2`(5585) 上又试了一轮，过程中发现并修掉两个新问题，但**仍然卡 95%**：

1. **5585 上还残留着系统代理** `settings get global http_proxy` = `10.0.2.2:29290`（是我早前给 POP 绑 FB 时设的）。已清空。
   清空后 CF 的 socket 从"5 条通往 29290"变成直连 `34.208.12.121:443`(AWS 后端) + `35.71.176.15:443`，**说明代理不是唯一变量**。
2. **CF 初始化会连 Facebook**：清掉代理后，`netstat` 里 CF 出现多条 `SYN_SENT → 69.171.235.2:443`（Meta/Facebook），即被墙导致卡住。
   我把 DNAT 从「只有 Google 段」扩展到**Google + Meta 全段**（脚本 `tools/cf_netfix.sh`），中继日志随即出现 `graph.facebook.com` 隧道成功的记录 → **Facebook 链路也通了**。
3. 这两条都修好之后，CF **依旧停在 95% `檢查遊戲資源中...`**。

补充的量化观测（可直接引用）：

| 观测 | 数值 / 结论 |
|---|---|
| CF 进程 CPU | 20 秒内 utime 增长 ~90 ticks（≈45% 单核），之后稳定在 ~6 ticks/s → **在跑循环，不是死锁 sleep** |
| `/data/data/<pkg>` 与 `/sdcard/Android/data/<pkg>` 体积 | 60 秒内**完全不变**（28 MB / 12 KB）→ **没有在下载、也没在解包** |
| 进程状态 | `S`（可中断睡眠）+ 周期性 CPU → 典型的**请求-重试循环** |
| 三台/多次截图 sha256 | 完全相同 `a216b4fd…` → 画面确实一动没动 |

> 也就是说：**外网能到的都到了（Google、Meta、CDN、GCS、自家 AWS 后端），客户端仍然不认**。
> 剩下最可能的就是 **arm64-only 包在 Houdini 翻译层上的初始化缺陷**，见下面第 1 条。

### 6.1 建议按序尝试

1. **★ 换成 Play 商店安装的原生 x86_64 包**（最可能）。
   现在的包只有 arm64，靠 Houdini 翻译；Cocos 在"最后资源校验"阶段对翻译层不稳很常见。
   做法：在实例里装 Google Play（该实例已登录 `w6450265@gmail.com`，且 Google 链路现已通），从 Play 装 CF → 会下发 x86_64 split。
   ```powershell
   adb -s 127.0.0.1:5605 shell 'am start -a android.intent.action.VIEW -d "market://details?id=slots.pcg.casino.games.free.android"'
   ```
   > 如果这个包在国区 Play 不可见，改用"外区 Google 账号"或直接找一份**带 `split_config.x86_64.apk` 的安装包**给我/给 Codex。

2. **要一份真正能进大厅的 CF 实例快照**。
   注意：`AppResearch2`(5585) 的 CF 曾正常运行过（`/data/data/<pkg>` 有 1.22 GB 资源缓存），但**今天也卡 95%**，说明不是"缺资源"。若能拿到那台机器几个月前的可用快照，测量可以直接在上面做。

3. **比对一次"能进 vs 不进"的网络差异**。
   在能进的机器上抓 CF 启动阶段的完整请求列表（`tools/cf_urlwatch.py` 的思路：hook `libcocos2dlua.so` 的 `curl_easy_setopt` 打印 URL），与卡住的机器对比，找出那条"回了但客户端不认"的请求。
   ⚠️ 前提：frida-server 必须是 **root** 起来。5605 上我用 `su -c "nohup fs16 ... &"` 起出来的进程 uid 是 `shell`（导致 `enumerate_processes` 报 `unable to find process with name 'system_server'`）。可用做法：`su -c "/data/local/tmp/fs16 -l 0.0.0.0:27042 --daemonize"` 或先 `su` 进去再手动起，起完用 `ps -o USER,PID,NAME -p <pid>` 确认是 root。

4. **最后兜底**：换一个 Android 9 以下 / 或非 Houdini 的实例配置再试；或在真机上跑。

---

## 7. CF 一旦能进大厅，测量怎么做（方案已定，照着实现即可）

### 7.1 计数与分级（推荐 Frida 方案，精度最高）

- **拿每次 spin**：`frida -U -f <pkg>` 注入，hook `libcocos2dlua.so` 里的 `curl_easy_perform`（读 `CURLOPT_URL` 就能拿到 spin 接口）或直接 hook `SSL_read/SSL_write`（若 libcurl 静态链接进该 .so）。参考 `D:\PopSlotsProbe\fvl_spin_logger.py`（POP 版，结构可复用：滚动缓冲 + 花括号配平 + `json.loads` + 按 id 去重 + 落 jsonl + 余额看门狗）。
- **拿等级**：优先在响应里找 `level` / `xp` / `playerLevel` 字段（CF 的 spin 响应通常带 XP 增量）；若没有，退化为"模板匹配 LEVEL UP 弹层"：
  1. 第一次升级时截图存成模板 `ref_levelup.png`
  2. 之后每完成一次 spin 后比对一次（PAD 平均绝对差 < 阈值即判定升级）
  3. 记录 `spin_index_at_levelup`，相邻差即为"该级消耗 spin 数"
- **下注档**：日志里同时记录每次 spin 的 `bet`，升 bet 那一级能直接从数据里看出档位变化。

### 7.2 若 Frida 不可用（退化方案）

- 用 `adb exec-out screencap` 以固定节奏点 SPIN，每张截图裁 HUD 区域与上一次比较：
  - 变化率 < 阈值 → 视为"这一转已结算"（+1）
  - 命中 LEVEL UP 模板 → 记录级数
- 缺点：精度依赖节奏，级别数少时可接受（1→10 级总共几十到一两百转）。

### 7.3 交付物

```
D:\CF_LevelSpins_Handoff\result\
     spins_per_level.md          # 1→10 级逐级 spin 数 + 口径说明 + 置信说明
     spins_per_level.json        # 机读版
     bet_unlock_check.md         # 强制/非强制结论 + 两张截图路径
     spins.jsonl                 # 每次 spin 原始记录（bet / win / balance / level / ts）
     evidence/*.png              # 升级瞬间、bet 提示瞬间、BET 面板前后对比
```

---

## 8. 纪律（红线）

- **不购买任何东西**。见到 `BUY / 首充 / 礼包 / 限时特惠` 一律关掉。
- **不动 POP 那台的任务**：`AppResearch2`(5585) 上正在做 POP! Slots「FIRE VS LIGHTNING RTP」测量，已按用户要求暂停；`fvl_spin_logger.py`、`ps_state.py` 等状态都在，别清它的数据、别改 `bluestacks.conf` 里 `Pie64_3` 的任何项。
- 改 `bluestacks.conf` 前**先备份**（已有 `bluestacks.conf.bak_20261022_163250`）。
- root 只在专用研究实例上开；`docs/ROOT_TOGGLE.md` 有开关与回滚流程。
- CF 是新号测量，注意**别把 5585 上那个有 1.22 GB 数据的老账号 `pm clear` 掉**（那是唯一一个"曾经能跑"的证据样本）。

---

## 9. 文件索引

| 路径 | 用途 |
|---|---|
| `tools/google_sni_relay.py` | 宿主 SNI 中继（443 → 29290 代理），解决「原生栈不认系统代理」 |
| `tools/cf_ipv6.sh` | 模拟器内 DNAT(Google IPv4→中继) + REJECT(Google IPv6) |
| `tools/cf_dnat.sh` | 只做 DNAT 的最小版 |
| `tools/cf_reach.sh` | 可达性体检 |
| `tools/cf_urlwatch.py` | hook `curl_easy_setopt` 打印 URL（frida 需 root） |
| `tools/fvl_symprobe.py` | 枚举模块导出符号的模板（找 hook 点时用） |
| `evidence/01..04*.png` | 卡 95% 的两台实例截图、4 件套重装后的截图、5585 老账号截图 |
| `evidence/cf_logcat_tail.txt` | CF 进程 logcat 尾部（Cocos 初始化完成后静默、`PluginPlayGames` 缺失等） |
| `D:\PopSlotsProbe\fvl_spin_logger.py` | POP 版 spin 采集器（滚动缓冲/去重/看门狗，CF 版照它改） |
| `D:\PopSlotsProbe\ps_state.py` | POP 13 态状态机（不用于 CF，但"先判定再点"的写法照它来） |
| `D:\CashFrenzy_collect\` | 以前的 CF 采集工程（config.json 里 `package`/`gadget_port`/`root_launcher` 可直接抄） |
| `D:\CashFrenzy_collect\docs\ROOT_TOGGLE.md` | root 开关/回滚规范 |

---

## 10. 一句话交接

> CF 现在**进不去**（95% 资源校验空转），网络侧能修的都修了（Google 链路已打通、CDN 本就通、包/实例/渲染器/权限都排除）。
> 最可能是 **arm64-only 包在 Houdini 上初始化卡死**，请优先尝试 **Play 商店装原生 x86_64 包**。
> 一旦能进大厅，按第 7 节方案做测量即可，产物写进 `result\`。

---

## 11. ★ 历史档案：L6→L50 已经测过，只缺 L1–L5

这轮排查时翻出了以前（2026-09-21/22）的 CF 采集成果，**大半工作其实已经做完了**，接手前必须先读，避免重复测量。

### 11.1 服务器下发的等级主表（实机抓的 `get_level_road_info`）

位置：`D:\CashFrenzyResearch\local-only\analysis\level_road.json`、`cf_road_*.csv`

| 字段 | 内容 |
|---|---|
| `bet_change_list` | **升 bet 发生的等级：3, 4, 5, 10, 15, 20, 25, 30, 35, 40, 50, 75, 100**（13 档） |
| `base_bonus_list` | 升级奖励：L2=5,000 / L3=10,000 / L4=15,000 / L5=20,000 / L6=25,000 / L7=30,000 / L8=40,000 / L9=50,000 / L10=60,000（之后每级 +10,000，L50 特殊 11,500,000） |
| `level_multi_list` | 金币权益/等级倍率：L2–9 ×1、L10–19 ×2、L20–29 ×4、L30–39 ×6、L40–49 ×8、L50–74 ×10、L75–99 ×12、L100–124 ×14 |
| `guide` | **老号上返回空对象 `{}`** ← 新号可能带新手引导配置，这是验证"升 bet 是否强制"的第一手入口 |
| 等级阶段 | 0–100 / 101–500 / 501–1000 … 一直排到 200,000 |

### 11.2 实测（1020 手 / 45 次升级，L6 → L50）

位置：`cf_spins.csv`（逐手 34 列）、`cf_levels_measured.csv`、`CF_LEVEL_EXPERIENCE.md`、`CF_LEVEL_ECONOMY.md`

| 等级 | ΔXP | 本级手数 | 当时的 bet |
|---|---|---|---|
| L6 | — | 1 | 300,000 |
| L7 | 300,000 | 3 | 300,000 |
| L8 | 500,000 | 5 | 300,000 |
| L9 | 800,000 | 8 | 300,000 |
| L10 | 1,200,000 | 12 | 300,000（升 L10 后上限 450,000） |
| L11 | 1,550,000 | 17 | 450,000 |
| L12 | 2,100,000 | 14 | 450,000 |

**核心公式（已实测验证）：每手 XP = bet / 3**（等级倍率 ×1 时，300,000 注 = 100,000 XP/手）
→ **本级手数 = 3 × ΔXP ÷ 当级注码**
（`FINAL_REPORT.md` 也写明：跨表比较前必须先统一注码，否则"手数"没可比性）

### 11.3 参考表（配置推导，覆盖 L1–L5000）

位置：`reference_task0036_cf_levels.csv`（5000 行），源头工作簿
`C:\Users\admin\AppData\Local\AI-Workspace\cr-numerics-20260922\outputs\task0036-bet-dev-20260921\CR_CF_等级体验_简表.xlsx`（sheet `SRC`）

| 等级 | 升级模式 | dev门槛 | 最大解锁Bet | 候选EXP | CF原始Spin | 等级倍率 |
|---|---|---|---|---|---|---|
| 1 | 1 | 3 | 30,000 | 3 | 1 | 1 |
| 2 | 1 | 6 | 30,000 | 3 | 2 | 1 |
| 3 | 1 | 10 | 90,000 | 9 | 3 | 1 |
| 4 | 1 | 10 | 150,000 | 90 | 2 | 1 |
| 5 | 0 | 270 | 150,000 | 90 | 3 | 1 |
| 6 | 0 | 270 | 300,000 | 180 | 1.5 | 1 |
| 7 | 0 | 360 | 300,000 | 180 | 2 | 1 |
| 8 | 0 | 540 | 300,000 | 180 | 3 | 1 |
| 9 | 0 | 1800 | 750,000 | 452 | 4 | 1 |
| 10 | 0 | 2260 | 750,000 | 452 | 5 | 2 |

两个**必须注意的口径陷阱**：
1. `升级模式=1` 覆盖 L1–L4，含义是"**这四级门槛直接沿用 CR 的 dev 门槛**"（工作簿原注：
   "1–4级沿用User的dev门槛"），**不是**"强制升 bet"。别误读。
2. 该表的 bet 台阶（L9 起 750,000）与 live 实测（L10 起 450,000）**不一致** → 参考表是旧版/别的 theme，**实机以 live 为准**。

### 11.4 缺口只有 L1–L5（外加 1 个结论待补）

- ❌ **L1–L5 的实测手数**：唯一一次实测从 L6 开始，前五级没有实机数据
- ❌ **升 bet 提示是否强制**：档案里无直接结论。间接线索两条：①L3/L4/L5 是**连续三次**解锁（典型新手期节奏）；②`level_road.guide` 在老号为空 `{}`，新号很可能非空 → 新号一登录就抓一次 `get_level_road_info`，看 `guide` 里有没有强制引导字段
- ✅ L6–L50 手数、ΔXP、每手 XP 公式、升级奖励、倍率台阶、bet 解锁等级：**都已有实测**
- ✅ 参考表 L11–L5000 的期望手数：已有（配置推导，可作对照）

### 11.5 给接手的建议（新号只需补三件事）

1. **L1→L5 每级几手**（补最后一块空档），顺便记录 L1–L5 的 bet 与升级奖励
2. **L3/L4/L5/L10 升 bet 提示的交互**（强制 or 非强制，双截图）
3. 抓一次新号视角的 `get_level_road_info`，看 `guide` 字段

### 11.6 ★ "当时实际用的 bet / 手数"（不是配置上限，别搞混）

`cf_levels_measured.csv` 里的 `dominant_bet` / `spins_spent` / `total_wagered` 才是实测值：

| 等级 | 实际在用的 bet | 本级手数 | 本级总投注 | 升到下一级需要 ΔXP | 升级奖励 |
|---|---|---|---|---|---|
| L6 | 300,000 | **1** | 300,000 | 300,000 | 25,000 |
| L7 | 300,000 | **3** | 900,000 | 500,000 | 30,000 |
| L8 | 300,000 | **5** | 1,500,000 | 800,000 | 40,000 |
| L9 | 300,000 | **8** | 2,400,000 | 1,200,000 | 50,000 |
| L10 | 300,000 | **12** | 3,600,000 | 1,550,000 | 60,000 |
| L11 | 450,000 | 17 | 7,350,000 | 2,100,000 | 70,000 |

- **L6→L11 共 29 手、总投注 8,700,000，全程 300,000 单注**；450,000 是升到 L11 之后才用的
  （L10 那一级仍只下 300,000，`max_bet_multiplier` 变 450,000 只是解锁上限）
- 每手 XP = bet / 3 → 300,000 注 = 100,000 XP/手；`本级手数 = 3 × ΔXP ÷ 注码`

### 11.7 L1–L5 确实没有任何实机记录（已全量扫描确认）

扫过 `D:\CashFrenzyResearch`、`D:\CashFrenzy-DS-Lab`、`D:\CashFrenzy_collect`、
`D:\cr_design\Collector\collectors\cash_frenzy` 下 **1357 个候选采集文件 + 14 个 probe session**：

| 文件 | 覆盖等级 | 有无逐手数据 |
|---|---|---|
| `cf_spins.csv` / `cf_levels_measured.csv`（session 20260922_103131） | **L6–L50** | ✅ 1020 手 |
| `probe/_sessions/20260922_101458`、`20260922_102404` | 早期 | ❌ 0 手（只有大厅/菜单流量） |
| `probe/_sessions/20260922_112259` | 已经是 L30 上下（XP≈3.7 亿） | ✅ 但不在低等级 |
| `reference_task0036_cf_levels.csv` | L1–L5000 | ❌ 配置推导，不是实测 |

**采集器开始记录时账号已经是 L6** → L1–L5 的真实注码/手数在档案里不存在，只能开新号补测。
（顺带排掉一个坑：别用 `multiplier_current_level` 之类的字段当"玩家等级"，我最初扫描时就是它
误报出"L1/L2"的假命中。玩家等级要么用 `experience` 累计 XP 反推，要么看 `levelup` 事件。）

### 11.8 ★ 用户口述的 L1–L4 实测值（2026-10-22 由用户提供，优先级高于任何配置推导）

> **L1=3 手、L2=6 手、L3=10 手、L4=10 手**；用户回忆"**5 级好像会提示升 bet**"。

这三个数与参考表里的 `dev_threshold`（3 / 6 / 10 / 10）完全一致 —— 说明那张表的"dev门槛"其实就是
**实际升级所需 spin 数**（工作簿原注也写着"1–4级沿用User的dev门槛"），而不是什么抽象经验值。
所以**不要再把 `dev_threshold` 当经验用**，它就是 spins。

推断出的前 10 级（含 live 实测）：

| 等级 | 升级需要 spin | 该级 bet 上限（解锁点来自 `bet_change_list`） | 实测实际下注 |
|---|---|---|---|
| L1 | **3**（用户） | 30,000 | 未知 |
| L2 | **6**（用户） | 30,000 | 未知 |
| L3 | **10**（用户） | 90,000 ⬆ 解锁 | 未知 |
| L4 | **10**（用户） | 150,000 ⬆ 解锁 | 未知 |
| L5 | 待确认（参考表 3） | 300,000 ⬆ 解锁（用户印象里有提示） | 未知 |
| L6 | **1**（实测） | 300,000 | **300,000** |
| L7 | **3**（实测） | 300,000 | **300,000** |
| L8 | **5**（实测） | 300,000 | **300,000** |
| L9 | **8**（实测） | 300,000 | **300,000** |
| L10 | **12**（实测） | 450,000 ⬆ 解锁 | **300,000** |

### 11.9 "升 bet 是不是强制" —— 档案证据：**不是强制，是解锁可选**

`analyze_bet_switch.py` 对主 session 的 582 手逐手 bet 序列分析：

1. **全部 5755 次 `batch_spin` 里没有任何 bet/wager/stake 相关命令** → 改注是客户端本地选择，
   只体现在下一次 spin 请求带的 `bet` 字段上，没有"服务端要求改注"的请求。
2. **解锁更高档之后，玩家仍大量回落到低档**：解锁 3,000,000 后回落到 1,050,000（自第 242 手起）、
   甚至 **900,000**（第 295–304 手），之后又自己升回 1,050,000 / 3,000,000。
   **共 275 手是"低于已解锁最高档"的注码** → 若是强制，就不可能往回降。
3. bet 本身是一份**阶梯列表**（例：`10,000 30,000 60,000 90,000 100,000 120,000 150,000 180,000 300,000`），
   等级只是把阶梯**上端逐级解锁**（`bet_change_list` = 3,4,5,10,15,20,25,30,35,40,50,75,100），
   解锁后整段可选。

⚠️ 唯一没有直接证据的是**新手期 L1–L5 的弹窗交互本身**（那几级没录到逐手数据）。
机制层面已经证明"解锁≠强制"，若 L1–L5 存在强制引导，那是教学流程里的特例，需要新号实机确认：
提示出现时**先不点**→ 关掉 → 打开 BET 面板看**旧档是否还在且可选**。



