# 隐身 / 防封清单（注入隐身 + 行为像人 + 账号隔离）

> Cash Frenzy 防护特征：APK v3 签名、`libsigner.so`/`libEncryptorP.so`/XXTEA 加密链、
> 遥测（libapminsight/volc_log/applovin 崩溃上报）。
> **我们的采集点在明文 Lua 层，不需要碰任何加密/签名链。**

## A. 注入隐身
- [ ] 不重打包 APK（保持 v3 签名完整），用 Houdini runtime 注入 Gadget
- [ ] frida-server 改名（`cf_rt_mon`）+ 会话后删除；不常驻
- [ ] Gadget 文件名中性化；config 只 listen `127.0.0.1`（不回连外部）
- [ ] 仅会话期开 root，会话后回滚（见 ROOT_TOGGLE.md）
- [ ] 所有 hook 只读、仅 inbound dispatch 线程 scope 激活；回调 try/catch，绝不 crash 客户端
- [ ] 不 hook `libsigner`/`libEncryptorP`/XXTEA/SSL；无 Stalker、无全局 Lua 日志
- [ ] 每次会话前 120s 无操作稳定性 Gate（Gadget 加载稳定性，TASK-0024 标准）

## B. 行为像人
- [ ] Spin 玩家手动（可 auto，但别 24h 连跑）；拟人节奏、随机停顿
- [ ] 单会话 ≤ 15–30 分钟；会话间自然间隔；下注档位随游玩变化
- [ ] 遇升级/活动弹窗正常点掉，不异常速刷

## C. 账号与网络
- [ ] 专用研究账号 + 专用研究实例；单账号↔单实例↔单 IP
- [ ] 实例指纹稳定（分辨率/CPU/RAM 会话间不变，Pie64_3 参数固化）
- [ ] 账号进度自然增长；Android ID / GAID 不重置

## D. 数据
- [ ] 逐笔绝对值（coins/win/bet）只存本机 `data/`；`summary.json` 脱敏后才可外发/入 Git
- [ ] 账号 ID/token/签名/完整 payload 仅本机

## E. 会话规程
1. 会话前核对 A/B/C/D；确认无残留；root 已按流程开启
2. 会话中玩家正常游玩，探针只读
3. 会话后自动清理（gadget/server/forward/进程）+ root 回滚

## F. 异常预案
- 崩溃/警告/异常掉线：立即停采，先归因（hook vs 风控），再决定是否继续
- 不确定宁可停采，不冒险
