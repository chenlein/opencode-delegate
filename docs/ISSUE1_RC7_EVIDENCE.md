# Issue #1 后续：rc.7 与成组路线验证

2026-10-31。仍是本地未提交候选版，基线为 `728c08b0db4cdc1662addd0d022df115598cf36b`；Issue 保持开放，尚无稳定认证声明。本记录补充 [rc.6 原始范围](ISSUE1_RC6_EVIDENCE.md)，不覆盖其失败和历史边界。

## 原生 session 迁移适配

v2.2.3 的 [session-target.ts](https://github.com/anomalyco/opencode/blob/v2.2.3/packages/cli/src/session-target.ts) 优先使用已指定 session 的 location。单独修正 cwd/PWD 只覆盖新会话；已移动的 session 仍可能运行在别处。

rc.7 在 V2 续跑的尝试/预算预留前，以及接受完成结果前，调用同环境 standalone 的只读 metadata API，核对 session ID、真实目录、模型/default variant 和 Agent。失败、超时、未知结构或漂移均停止；不自动迁移、换 session 或重建契约。已核对绑定纳入 worker-result 原有文件哈希；不保存原始 metadata。探测初始化写源码同样阻断。V1 命令面和状态 schema 不变。

新增 12 项针对性回归，完整 232 Runner + 15 安装 = **247 项**通过；事件回放仍为 **13/13**。安装后 32 个 Skill 文件与 manifest 一致，旧 rc.6 按安装器机制备份，原任务状态未改写。

实际零模型迁移探测中，首次 native move API 仅排队，独立读回仍在原位置，未当作成功。确认只有一个待执行 move、token/cost 均为零后，保留并移动自有临时 Git worktree，按原生 [源位置不可用恢复分支](https://github.com/anomalyco/opencode/blob/v2.2.3/packages/core/src/session/move.ts) 完成该会话迁移。新鲜 metadata 查询确认位置已变，rc.7 正确返回保护性错误；源码快照保持相同，队列收尾为零，未迁移任何已有 delegate 任务。

第 35 次真实试验使用已安装 rc.7 创建新 Session：11.928 秒返回、原生绑定进入 worker-result，重复只读 metadata 校验一致，固定检查和独立 review 后 ACCEPTED。认证/配置文件哈希未变化。这只证明该组合的新任务和绑定门禁，不把 rc.6 全部模型场景自动重标为 rc.7。

## 同基线对照补齐

| 用例 | 相同基线 | 三路线结果 |
|---|---|---|
| 只读随机 marker | `d8eb80ae814539970adc9e22186868924ac4b320` | 应用直做、原生子会话、Skill 均独立核对 marker/引用及源码不变 |
| 受控验收失败与增量恢复 | `e1f6c643a97fb3b4f330fce5140f9715a8561b17` | 各路线两次、沿用各自原会话；首次检查人为返回 5，第二次独立检查通过，首次修改字节保留 |

三路线都是新会话，使用相同源码、规则和四条冻结业务断言。首次业务断言其实都通过；失败来自故意注入的瞬态验收故障，**不是 worker 写错代码**。直做/子会话在协调层注入，Skill 用固定 verifier 的自有证据标记实现一次失败；不将该实验说成三路线修复业务缺陷的成功率。没有改写测试来使代码通过，没有额外源码返工。

实际模型活动耗时：应用两轮 14.735/9.064 秒，原生子会话 19.833/6.542 秒，Skill run 15.430/14.876 秒。这些不是统一的端到端时钟，含义分别为应用 turn 和 Runner run；总流程还包含协调者等待、检查及审查。保留未知，不据此宣称提效或节省比例。

## 保护性事件与边界

第 25 次 bundled CLI 的只读业务结果通过，但前后 Codex 配置文件哈希变化，认证文件修改时间未变。已知 model/reasoning 设置与此前观察一致；没有旧配置全文，**具体差异及写入者仍 UNKNOWN**，时序相关不能证明因果。没有执行手工认证/模型配置写命令，也未回滚未知改动。该 CLI 入口已停用；后续改用应用现有聊天与原生子会话，逐次核对文件无再次变化。该事件不记为边界合规通过。

先前限定编辑协调者 60.825 秒的超限保留；后续缩短内部期限并提前中断未完成会话，不声称历史上所有尝试都符合 60 秒。临时应用评测聊天完成后归档，原始记录保留。

当前事件语料中的分块/重复/缺尾仍含明确标记的派生故障。v2.2.3 [原生 CLI 源码](https://github.com/anomalyco/opencode/blob/v2.2.3/packages/cli/src/run/noninteractive.ts) 在 text-ended 时输出文本，并在 reconcile 时补齐缺失后缀；未观察到的原生行为不能靠派生语料冒充。权限引擎探测不能替代每条工具执行链的证据。实仓根目录的 2 GiB 阻断与组件副本测量也不能替代完整原仓库任务生命周期。

最后一项授权模型额度用于独立核对 rc.7 源码、实际收据和上述剩余门槛；结论另行记录。仍不发布 GitHub 修改或关闭 Issue。
