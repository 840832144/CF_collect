# AI_START_HERE —— Cash Frenzy 前 10 级测量交接（另一台电脑接手）

> 面向接手的 AI：**先把本文件读完（约 5 分钟），再看 `README_HANDOFF.md` 的第 5/6/11 节**。
> 已经做过的事不要再做一遍，第 3 节列的就是"别再重复验证"的清单。

---

## 1. 任务（两个交付）

1. **CF 新号 1→10 级，每级各需要多少次 spin**，并写清"当时实际下的注是多少"
   （注意：要的是**真实下注**，不是配置里的"最大解锁 bet"，这两者是不同的东西）
2. **升 bet 提示是强制还是非强制**：
   提示出现时**先不点** → 截图记当前档位 → 关掉提示 → 打开 BET 面板看**旧低档是否还在且可选**
   - 旧档可选 = 非强制（只是解锁更高档）
   - 只剩新档 / 必须确认才能继续 = 强制
   两个分支都要留截图。

---

## 2. 已经确定的结论（可直接引用，不用重测）

### 2.1 前 10 级：升级所需 spin

| 等级 | 升级需要 spin | 数据来源 |
|---|---|---|
| L1 | **3** | 用户口述（与参考表 `dev_threshold` 3/6/10/10 完全一致） |
| L2 | **6** | 同上 |
| L3 | **10** | 同上 |
| L4 | **10** | 同上 |
| L5 | **待补**（参考表给 3；用户印象里这级会弹"可以升 bet"） | ← 新号要补的 |
| L6 | **1** | 实机实测 1020 手 |
| L7 | **3** | 实测 |
| L8 | **5** | 实测 |
| L9 | **8** | 实测 |
| L10 | **12** | 实测 |

- **L6→L11 实测：29 手 / 总投注 8,700,000，全程单注 300,000**
- 换算公式（实测验证）：**每手 XP = bet ÷ 3** → `本级手数 = 3 × ΔXP ÷ 注码`
- 参考表里 `dev_threshold` 那列 3/6/10/10 **就是手数**，不是经验值（工作簿原注："1–4级沿用User的dev门槛"）

### 2.2 升 bet 是不是强制 → **不是强制，是"解锁可选"**

证据（`config/analyze_bet_switch.py` 对 582 手逐手 bet 序列分析）：

1. 全库 5755 次 `batch_spin` 里**没有任何 bet/wager/stake 相关命令** → 改注是客户端本地选择
2. **解锁更高档后玩家大量回落**：解锁 3,000,000 后回到 1,050,000（第 242 手起）、甚至 900,000（第 295–304 手），
   之后又回到 1,050,000 / 3,000,000 —— **共 275 手低于"已解锁最高档"**。强制就不可能往回降
3. bet 是一份**阶梯** `10,000 … 300,000`，`bet_change_list = 3,4,5,10,15,20,25,30,35,40,50,75,100`
   只是逐级**打开阶梯上端**，打开后整段可选

> ⚠️ 唯一没有直接证据的是**新手期 L1–L5 弹窗本身的交互**（那几级没录到逐手数据）。机制已证明"解锁≠强制"，
> 但如果 L1–L5 有教学强制引导，那是特例 —— 这正是新号要验的第 2 件事。

### 2.3 服务器配置（`config/` 里都有原始表）

- `bet_change_list`（升 bet 的等级）：**3, 4, 5, 10, 15, 20, 25, 30, 35, 40, 50, 75, 100**
- 升级奖励：L2=5,000 · L3=10,000 · L4=15,000 · L5=20,000 · L6=25,000 · L7=30,000 · L8=40,000 · L9=50,000 · L10=60,000
- 等级倍率：L2–9 ×1、L10–19 ×2、L20–29 ×4、L30–39 ×6、L40–49 ×8、L50–74 ×10、L75–99 ×12、L100–124 ×14

---

## 3. 这台机器踩到的卡点（另一台可能不会遇到，但先看）

CF 装好后**永久卡在 95% `檢查遊戲資源中...`**，以下全部已排除：

| 假设 | 结论 |
|---|---|
| 资源 CDN 不通 | ❌ 排除：`d2rargdj3vlbg6.cloudfront.net`、`storage.googleapis.com` 直连可达 |
| Google / Firebase / Play Games 不通 | ❌ 排除：我写了 SNI 中继 + iptables DNAT，中继日志确认这些域名全部隧道成功 |
| Facebook 不通 | ❌ 排除：把 Meta 全段也加进 DNAT 后 `graph.facebook.com` 打通 |
| 系统代理 | ❌ 排除：设了/清了都一样（Cocos 的 libcurl 不读系统代理；且该代理对 CloudFront 返 403） |
| 安装包缺 split | ❌ 排除：4.80 两件套 与 4.78 **完整四件套** 都试过 |
| 实例本身 | ❌ 排除：5605 与 5585 两台表现完全一致 |
| Vulkan 渲染 | ❌ 排除：切 OpenGL 也一样（配置已还原） |
| 没在下载/在哈希 | ❌ 观测：数据目录体积 60 秒不变，进程 ~6% CPU 空转（请求重试循环） |

**剩余最强假设：sideload 的包是 arm64-only（`lib/` 下只有 `arm64/`），在 x86_64 蓝叠上走 Houdini 翻译，
Cocos 在最后一步资源校验时卡死。**
→ 另一台电脑优先：**用 Google Play 在实例里装 CF**（会下发原生 x86_64 split）。

---

## 4. 另一台电脑上的执行顺序

1. 克隆本仓库，读本文件 + `README_HANDOFF.md`
2. 装 BlueStacks 研究实例（Android 9 / Pie64）+ root（`docs/ROOT_TOGGLE.md`）+ adb
3. **优先用 Google Play 装 CF**（不要先试 sideload 的 arm64 包）
   - 若 Play 不可用，再试 sideload，并按 `tools/cf_reach.sh` → `tools/google_sni_relay.py` + `tools/cf_netfix.sh` 的顺序修网络
4. CF 一旦进得大厅：**开新号**（`pm clear` 或换游客身份），按第 5 节测量
5. 产物放 `handoff/result/`（结构见 README_HANDOFF.md 第 7.3 节）

---

## 5. 测量方法（新号要采的东西）

**优先 Frida**（精度最高）：hook `libcocos2dlua.so` 的 `curl_easy_perform` 读 `CURLOPT_URL`，或 hook SSL 层；
从 `batch_spin` 响应里取 `experience`（累计 XP）、`coins`、`total_win`、`levelup`、`multiplier_current_level_idx`。

- **玩家等级**：用 `experience` 累计 XP 反推，或看 `levelup` 事件
  ⚠️ **别用 `multiplier_current_level` 当等级**（它会让扫描误报出 L1/L2 的假命中，已踩过）
- **每手注码**：`batch_spin` 请求体里的 `bet`
- **升级判定**：`levelup` 事件 / LEVEL UP 弹层模板匹配（第一次升级截图当模板）
- 退化方案：固定节奏点 SPIN + 截图比对 HUD（无需 Frida，但精度依赖节奏）

**新号必须记录的字段**（每手一行）：`ts, bet, experience, coins, total_win, levelup, level, theme_max_bet`

---

## 6. 纪律红线

- **不买任何东西**（`BUY / 首充 / 礼包 / 限时特惠` 一律关掉）
- root 只开专用研究实例，用完按 `docs/ROOT_TOGGLE.md` 回滚
- **本仓库不提交真实 Session / 逐笔数据 / 绝对余额**（`.gitignore` 已挡 `data/`、`*.jsonl`、`sessions/`）；
  派生汇总表可以提交
- 截图里若出现他人昵称/头像，交付时只留自己的部分
- 别把已知结论再测一遍：L6–L50 的手数/ΔXP/公式、升级奖励、倍率台阶、bet 解锁等级都已经在 `README_HANDOFF.md` 第 11 节

---

## 7. 文件索引

| 路径 | 内容 |
|---|---|
| `handoff/AI_START_HERE.md` | 本文件（先读） |
| `handoff/README_HANDOFF.md` | 主交接文档：环境、已排除项、假设排序、测量方案、历史档案（L6–L50） |
| `handoff/PROMPT_给Codex.md` | 给 Agent 的启动话术 |
| `handoff/config/` | 服务器等级配置表（`bet_change_list`/奖励/倍率）、参考表 `reference_task0036_cf_levels.csv`（L1–L5000）、分析脚本 |
| `handoff/tools/` | SNI 中继、DNAT 脚本、可达性体检、CPU 判活、URL 监听、符号枚举 |
| `handoff/evidence/` | 卡 95% 的截图（两台实例）、4 件套重装后、Google+Meta 打通后、CF logcat 尾部 |
| `docs/ROOT_TOGGLE.md` | 实例 root 开关与回滚 |
| `docs/DEPLOYMENT.md` / `STEALTH.md` | 采集器部署与隐蔽性说明 |
