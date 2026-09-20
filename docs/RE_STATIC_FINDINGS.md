# Cash Frenzy / 爆有钱Online — 静态逆向结论（RTP 与"调控"假设的判定）

- 目标：`slots.pcg.casino.games.free.android`（繁中名 **爆有钱Online**）
- 现网版本：**4.80 / versionCode 480**（本次静态基于设备上现网包，本地核对哈希；早前样本为 4.78 vc478）
- 方法：**纯静态**（APK 资产 + 明文 Lua + 字段目录）。未注入、未改包、未碰账号
- 工具：`huuuge-research/tools/analysis/` 的 `apk_recon.py`、`lua_field_catalog.py`、`symbol_cluster.py`
- 结论按**证据分级**：高＝符号/字符串/字段名/代码；中＝实测数据；低＝推测（本文不含低置信结论）

---

## 一、三个假设的判定

### 1）新手调控（新手给中奖）—— **客户端侧不成立**

**不存在**任何"按新手身份改变结果"的客户端逻辑。新用户相关的全部落点如下（4.80，含行号）：

| 位置 | 用途 |
|---|---|
| `User.luac:406` `if data.new_user then self.isNewUser = true` | **服务端下发"是否新用户"**；客户端仅用于 Adjust 归因埋点（`stsyap`/`pmbt95`）与 UX |
| `User.luac:420` `data.new_welcomeback_flag == 1 → isRecalled` | 召回玩家标记（营销） |
| `ADSControl.luac:3214` `isNewUser = (data.experience == "0")` | 经验 0 视为新用户 |
| `ADSControl.luac:1322` `level >= 6 and last_purchase == 0 and not isNewUser` | **广告资格**判定 |
| `JackpotControl.luac:3316` `isNewUser() → 不弹 jackpot 通知` | 避免新用户困惑 |
| `User:isBeginnerCouponABTest()` / `setBeginnerCouponABTest` | **新手优惠券 A/B 实验组**（`abtest_new_user_coupon`）|
| `DownloadConfig.luac` `["newbie_paid_task"]` | 新手付费任务配置项（含 version）|
| `novice_fund`（`Lobby_Chinese_Language.luac:141`「X%s升級經驗值！」、`RewardsCenterMainPage` 「獎勵大禮包／解鎖豪華禮包」）| **新手礼包 + 经验加成** |
| `User.luac:298` `-- checkIsNewUserGroup()`（已注释）| 曾有过"新用户分组"概念 |
| `User.luac:431` `-- abtest_new_user_flag / setNewUserActivityABTest`（已注释）| 曾有"新用户活动 A/B" |

**判读**：新手相关的机制全是**内容/优惠/UX**（礼包、券、引导、广告资格、通知抑制），
**没有任何一条读取结果、注额或中奖**。也**不存在**新手专用的胜负/权重/倍率参数。

### 2）破产调控（输光后调控）—— **存在，但是"卖币"而不是"放水"**

`assets/res/recoup_reward/src/ActivityDialogs.luac`（`RecoupRewardDialog`）：

```lua
self.recoupData = self.ctl:getRecoupRewardData() or {}      -- 向服务端取"挽回报价"
self.is_high_type = self.recoupData.high_info
self.uiName = self.is_high_type and "recoup_reward_high" or "recoup_reward_base"
...
base_info: { credits = <服务端下发>, price = 49.49, origin_price = 49.99 }
high_info: { credits = <服务端下发>, price = 99.99, recoup_extra_coins = ... }
```

**判读**：这是**金币耗尽时触发的打折购币弹窗**（原价 49.99 → 49.49；另有 99.99 高档位，
含 `recoup_extra_coins`）。配套还有 `out_of_coins` 分支处理（58 处引用）。
**它是变现机制，不是胜率机制** —— 没有改动注额、中奖或倍率的代码路径。

### 3）付费调控（按付费情况调控）—— **有实验框架，但实验维度不含结果**

客户端持有付费历史：`total_purchase` / `last_purchase` / `max_purchase` / `vip_level` / `vip_points`，
并用它做**资格与推荐**判定（如 `last_purchase == 0 and level >= 6` → 广告）。

**服务端有一套完整的 A/B 实验框架**（这是本次最重要的结构性发现）：

```lua
-- 下发：登录响应里的 new_abtest 子对象
if data.new_abtest then
  if data.new_abtest.abtest_theme_payout_btn then self:setThemePayoutTest(...) end
  if data.new_abtest.abtest_piggy_double   then self:setPiggyDoubleABTest(...) end
  if data.new_abtest.new_red_point_rule    then self:setRedPointABTest(...) end
  if data.new_abtest.abtest_new_user_coupon then self:setBeginnerCouponABTest(...) end
  if data.new_abtest.abtest_10216          then self:setC10216ABTest(...) end
  if data.new_abtest.abtest_60011          then self:setC60011ABTest(...) end
end
-- 上报：客户端把实验反馈发回服务端
function User:sendABTestV2Feedback(name, type, params) ... bole.potp:send("abtest_v2_feedback", send_data) end
-- Network.luac:428  ["abtest_v2_feedback"] = true      ← 已注册的协议命令
```

已知实验维度（**全部是营销/UX/活动**）：新手券、piggy 保险箱双档位、红点规则、booster 展示、
领取奖励动画加速、`abtest_theme_payout_btn`（注释写明"这个对照组是0 实验组是2"，实际作用于
**payout 动画风格**：`theme_payout_anim`；`canShowPayOutBtn` 已是 `do return false end` 死代码）、
活动 10216/60011 入口开关。另有按 user_id 手动圈人（`id % N % 2`、注释里的
`id >= 34725925 and id <= 35630718`、`user_id == 28931935`）与策划手改记录
（`isStampsPickBonusABTest`：`--7.26策划要求ab反转--8月4号去掉abtest展示b版本`）。

**判读**：**实验基建确实存在且由服务端驱动**，但**没有**"按付费情况改变中奖"的字段或逻辑。

---

## 二、被证伪的"调控"候选（附证据）

| 候选 | 真相 | 证据 |
|---|---|---|
| `adjustWinRetData(ret)`（`ThemeLuckyPuzzle*.luac`）| **多屏坐标重映射**：`v[1] + (i-1)*5`、`v.col_ck = (i-1)*5`，只改 `win_pos_list`/`win_lines` 的展示对齐，**金额不参与运算** | `ThemeLuckyPuzzle.luac:984-1004` |
| `control_add_delay` | **客户端本地置 0** 的字段，注释 `-- control_add_delay必须存在` | `ThemeControl.luac:1825` |
| `theme_vip_ratio` / `theme_add_ratio` | **整段注释掉的死代码** | `User.luac:475-480` |

## 三、结果生成位置：**服务端**（静态无法判定 RTP 调控）

- 客户端**没有任何权重/概率表**（516 个 JSON + 全部明文 Lua 均无 `weight`/`probability`/`hit_rate` 表；
  唯一 "probability" 命中是本地化文案，如 `chest_probability = "寶箱機率"` / `"PROBABILITY OF ALL CHESTS"` —— **合规披露文案**）。
- 服务端响应字段目录共 **319 个唯一名字**（4.80 与 4.78 **完全一致**，无新增）。
  逐一检查**不含** `winRate` / `rtp` / `bankrupt` / `newUserWin` / `pity`（作为字段）等语义。
  与结果相关的只有：`win_lines` / `win_pos_list` / `win_ways` / `total_win` / `win_type` / `big_win_type` /
  `jackpot_win` / `bonus_game` / `free_spins` / `hasSpecialWin` / `before_win_show`。
- 风控标志：`result["Cheating"]`（与 `cs_error`、`out_of_coins` 同构处理，三处：`ThemeControl` /
  `ThemeBaseViewControl` / `ThemePubComp_Network`）→ 证明**服务端会在 spin 响应里下发判定**。

**因此**：若存在 RTP 调控，它发生在服务端的结果生成内部，**不体现在协议字段上** —— **静态分析无法证实也无法证伪**。

## 四、已有的运行时证据（193 把，历史采集）

来自 `local-only/collector-demo/20260827_192117/spin_samples.jsonl`（上行 `lua_bolesocket_BLSocket_sendTable`
读到的 `bet`/`client_coins` 等字段）：

- 总下注 **70,350,000**；余额净变化 **+19,148,093**；推算总中奖 89,498,093 → **实测 RTP 粗估 127.2%**
- 正向跳变 **23** 次 / 负向 **163** 次；最大正向 **+13,905,000（= 31× 注额）**，负向跳变**恰好等于 −注额**
- **判读**：+19.1M **不是一次性登录奖励**，而是**多次真实大倍率中奖**累积（与"我一直在赢"的体感一致）

**⚠️ 但样本量远远不够**：逐把净收益 均值 +477,698 / **标准差 1,744,032**（波动是均值的 3.6 倍）。
判定 RTP 是否偏离 100% 所需样本：**±10% 精度 ≈ 8,258 把；±5% ≈ 33,031 把；±2% ≈ 206,444 把**。
→ **192 把连"100% 还是 120%"都分不开**；"一直赢钱"在真实 RTP 96% 的高波动 slot 上同样常见。

## 五、后续可做的（按性价比）

1. **变化点分析**（比"证明 RTP>1"容易）：若存在新手加成，典型形态是**衰减**（前 N 把 / 前 X 天 /
   某等级后回落）。需要较长时间连续采集，看 RTP 是否在某点下降。
2. **扩大统计样本**：需先解决注入（现网 4.80 为干净包、无 Gadget；且带 `libsigner.so` 完整性校验，
   这很可能就是历史上 ARM64 Gadget 注入即崩 `gum-js-loop`/`GLThread SIGSEGV` 的根因）。
3. **对齐版本**：本结论基于现网 4.80；早前的采集与 4.78 样本可作为版本差异对照。

## 五之二、"暗改"证据与 A/B 实验清单（中文关键词扫描所得，**本轮最重要的发现**）

对 4.80 做**中文关键词全量扫描**（`新手/保底/调控/概率/暗改/放水/送分/干预/平衡/中奖率/返奖`）后，
在 `assets/src/Systems/BlazingChallenge/BlazingChallengeController.luac` **第 6216 行**命中一条
**代码内的自白**：

```lua
function BlazingChallengeController:getComebackUserBoosterMul()
    -- 暗改，显示的少，实际后端给的多
    local ab_test = LobbyThemeControl:getInstance():getABTestByKey("abtest_comeback_theme_prize")
    if ab_test then
        -- return ab_test == 2 and 1 or 1.3 (只有实验组1和3，会多给)
        return 1
    end
    return 1
end
```

**三层判读（务必分开引用）**：

1. **机制类别真实存在**：**召回/回归玩家（comeback）的奖励加成**，由服务端下发的 A/B key
   `abtest_comeback_theme_prize` 驱动；配套 `comeback_user_bc_config_ts`（服务端下发配置时间戳）、
   `isActivedComebackUserBooster()`、`getComebackBoosterLeftTime()`（BC 任务奖励中的 MP 星星额外加成）。
2. **设计意图有白纸黑字**：注释明说"**显示的少，实际后端给的多**"，注释掉的实现是
   `ab_test == 2 and 1 or 1.3`，并注明"只有实验组1和3，会多给" → 即**对照组显示 1×、
   实验组后端实际给 1.3×**。
3. **但现网 4.80 已停用**：两个分支都是 `return 1`，真实逻辑被注释 → **客户端不再隐藏**，
   加成（若仍在生效）完全在服务端，**静态看不到**。

> ⚠️ 这只是**召回玩家**的机制，**不是新手机制**；且它是"显示与实发不一致"，
> 不是"按身份改中奖率"。引用时不要外推。

### 客户端认识的 A/B key 全清单（`getABTestByKey` 字面量，25 个）

与钱/奖励沾边的全部是 **UI/促销/活动展示**，且多处**已硬编码停用**：

| A/B key | 实际作用 | 状态 |
|---|---|---|
| `abtest_bet_coins` | `checkShowCoinNode()`：大厅 loading 是否展示金币节点 | UI |
| `abtest_bet_choice` | 注额选择 UI 变体（含 `id == 65662` 手动圈人） | UI |
| `abtest_novice_task` | 注释 `【新手】【优化】新手任务逻辑&展示测试`、`11.14全开` | **新手任务逻辑与展示**，已全量放开（函数硬编码 `return true`）|
| `abtest_ooc_show` | `isOOCTestUser()`：金币耗尽时展示哪个促销 | 变现展示 |
| `abtest_bc_hunt_modify` | A/B 已注释，硬编码 `return true` | 停用 |
| `abtest_welcome_back_login_bonus` / `abtest_welcome_bundle` / `abtest_welcome_unlock` | 回归/新手礼包与登录奖励展示 | 营销 |
| `abtest_money_bank_day`(5x) / `abtest_fq_next_bc`(9x) / `abtest_lobby_footer_ad`(5x) / `abtest_speedy` / `abtest_bingo_game` / `abtest_drop_blast` / `abtest_theme_order` / `abtest_new_guide` / `abtest_limit_stamp` / `abtest_store_default_item` / `abtest_place_dark` / `abtest_policy_version` / `abtest_a_props_obtain` / `abtest_60075` / `abtest_theme_feature_activity_42019` / `abtest_independence_slots` | 功能入口/展示/活动开关 | 营销/UX |

**中文关键词扫描的其余结果**：`保底` 4 处（**全部与队列/加载兜底有关**，与抽奖保底无关）、
`概率` 12 处（多为文案；`ADSControl` 有一张 `{ratio=0.75,name="HugeWin",PR=0.6}` 的
**弹窗展示概率**表 —— 决定何时弹 BigWin/HugeWin 动画，不是中奖概率）、
`放水`/`送分`/`干预`/`中奖率`/`返奖`/`新手保护`/`扶持` **全部 0 命中**。

## 六、边界

- 全流程**只读**：未修改游戏数值、未伪造/重放请求、未改服务器状态；未注入、未改包。
- 资产与样本**只留本地**（`D:\CashFrenzyResearch\local-only\`），本文件只含结论与行号引用。
- 无对照账号 → 任何"分段调控"结论都只能在拿到对照后成立。
- 引用本文时请保留证据等级与第五节限制。
