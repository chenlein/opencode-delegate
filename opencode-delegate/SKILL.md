---
name: opencode-delegate
description: Delegate one bounded repository task from Codex to local OpenCode with isolated worktrees, explicit session continuity, and independent verification. Use only when the user invokes $opencode-delegate or explicitly requests OpenCode; not for ordinary coding, deployment, or recursive orchestration.
---

# OpenCode Delegate

Codex 负责目标、授权和验收，OpenCode 执行一个有界任务。版本 2.0.1-rc.8；Python 3.9+、Git、macOS/Linux。候选版：没有完成真实联调认证的 OpenCode 版本。

## 选择与边界

简单任务优先直接完成；只有独立上下文、环境或工具确有收益才委派。明确请求 OpenCode 时遵照执行，但不扩大成无限编排。默认一个执行器、一层委派。

worktree 与工具权限不是 OS 沙箱；相同 GPT 模型不共享记忆，不承诺省 token。实现必须获明确授权；不自动合并、提交、推送或部署。

## 准备

1. 执行 `python3 <SKILL_DIR>/scripts/delegate.py doctor`。它只探测 CLI，不调用模型、不证明兼容。阅读 [权限与恢复](references/security-recovery.md)。真实试用须明确认可未认证状态。
2. 阅读 [任务协议](references/protocol.md)，复制 `assets/task.template.json` 到仓库外，填写实际项目/任务/环境、目标/非目标、模型、允许文件、验收项和固定检查。
3. 审阅项目规则。`context.kind=rule`、AGENTS.md/AGENTS.override.md/CLAUDE.md 与 `verification_sources` 冻结保护；外部规则通过 `instruction_sources` 声明来源与作用域。不发送完整聊天或秘密；区分事实与假设。
4. 审核验证命令及其测试、配置、依赖断言和副作用。外部检查必须声明可信测试源；`trusted_inline` 仅用于已审核且自包含的 Python -c，不用于隐藏可变测试入口。
5. 源仓库必须干净；不自动 stash、commit、reset 或复制未知修改。init 创建独立 detached worktree。含敏感命名文件或符号链接的工作区会被拒绝。

```bash
RUNNER="<SKILL_DIR>/scripts/delegate.py"
python3 "$RUNNER" init --contract /absolute/task.json
# implement 需追加 --authorize-implementation。记录输出的真实 task_dir 为 TASK。
python3 "$RUNNER" run --task "$TASK" --acknowledge-local-execution \
  --experimental-cli-version "$EXACT_DOCTOR_VERSION"
# implement 运行同样需 --authorize-implementation。
```

授权标志只能表达已经获得的授权。精确版本试用标志不代表认证；无法确认有效权限时停止，不改成宽松模式消除错误。

V2 配置预检读取配置来源与原生最终 Agent，不把来源数组当有效配置。两种探测都使用与执行相同的 `--standalone` 语义和环境，前后核对来源/文件指纹；它们不是同一个常驻服务实例，也不构成实际工具权限认证。来源中的 formatter 冲突、未知引用或模型 variant 仍阻断，原始配置不落盘。配置指纹变化的旧任务保留旧 Runner，不自动重建基线。

执行环境的 PWD 与子进程 cwd 都绑定隔离 worktree；上下文的 worktree_path 是读写定位。source_repository 和规则 source 字段仅供来源核对，不得当作文件访问目标。外部目录拒绝规则保持不变。

V2 指定 session 会优先使用原生会话保存的位置。续跑在尝试/预算预留前读取原生 metadata，结束后接受结果前再次核对 session ID、worktree、模型和 Agent；未知结构、查询失败或位置漂移均阻断，不自动移动任务。查询不调用模型，原始 metadata 不落盘；结果只保存经核对的绑定。V1 不新增未经认证的 API 依赖。

## 上下文与续跑

先读 state、changes 和 worker-result，有疑点才展开日志。run 返回 0 仅表示 AWAITING_VERIFY，不是验收通过。

同任务用已登记 session 和 `--feedback /absolute/feedback.md` 发送增量；合法已登记改动可以续跑，未知外部修改必须停止。禁止 --continue、--auto 和“最近会话”。次数或累计时间耗尽则重新分析，不换任务 ID 绕过。预算先预留、后结算；未知消耗保守扣记，不等于实测用量或账单。

失败包默认共享验证计划、检查 ID、退出码和哈希。先用 `failure --task "$TASK" --include-details` 预览脱敏摘录，审核后才在 run 加 `--share-failure-details`。正则脱敏不是秘密检测保证。

换会话时按 `assets/handoff.template.md` 写检查点，区分已验证事实、假设、未完成项和证据，再用 `--fresh-session --checkpoint /absolute/handoff.md`。旧任务是否停止不确定时先恢复，不能启动第二份写任务。

## 验收与交付

```bash
python3 "$RUNNER" verify --task "$TASK" --authorize-tests
python3 "$RUNNER" status --task "$TASK"
python3 "$RUNNER" review --task "$TASK" --review /absolute/review.json
```

只运行已审核获授权的测试。status 可在写操作持锁期间读取最后已提交状态，默认不扫描；--check-worktree 遇运行中任务会明确跳过。REVIEW_REQUIRED 仍不是通过。

Codex 根据原目标、代码、反例及可信测试独立判断，用 `assets/review.template.json` 绑定当前契约/源码/验证哈希。失败测试可支持 fail，不能支持 pass；测试必须关联该验收项。不能修改原测试门槛来使实现通过。

review、memory、export 均复查冻结规则来源。只有固定检查和语义条目全部通过、证据未变，才 ACCEPTED。执行器声明不是测试证明。分析任务没有自动测试时仍需要有代码/差异证据的语义审查。

ACCEPTED 不自动合并。`export --task "$TASK" --output /absolute/delivery.zip` 导出新增/修改/删除及哈希。`cleanup --task "$TASK"` 仅预览；用户授权后才 --confirm，只移除完整导出且快照匹配的终态 worktree，保留证据。

## 异常、记忆与汇报

越界、HEAD/index 改动或验证修改源码时保留现场，不 reset 或篡改证据。EVIDENCE_ERROR 表示差异/证据生成失败，排障后可重新 verify，不等于合法空差异。

超时、残留进程与中断按 [恢复流程](references/security-recovery.md) 确认停止及实际副作用，再 recover；不能盲重试。PREPARING 也是持久化尝试，恢复后保留原目录并使用新尝试号；recover 按原 phase 检查，测试改源码绝不登记为合法实现。无污染的验证恢复为 VERIFY_RETRY_READY，直接重跑固定 verify 再 review，不追加模型调用；run 阶段恢复仍需新会话与剩余预算。进程组停止未确认时日志为 unstable，不能当最终证据。CLEANING 用原 cleanup --confirm 收尾，不调用 run。没有 phase 的旧中断任务禁止推断原阶段，须人工核对现场及旧版本；2.0.0 状态只读兼容，用备份旧 Runner 完成/恢复，不让新版静默改写。

通过验收后 memory 只产生含来源、环境、证据和失效条件的知识候选，不自动改 AGENTS.md，不建立平行项目记忆。

汇报准确状态、修改、独立验证证据、风险和交付位置；区分执行器声明与已验证事实，用量缺失标未知。mock 通过不代表真实 OpenCode/GPT/macOS 已认证。

rc.4 交付整合：verify 与验证恢复会核对 worker_completion 和规则；缺少完成结果绑定的旧任务须保留原 Runner，不自动采信或迁移。预算恢复不以损坏记录或变化日志退款。状态名称仍为 VERIFY_RETRY_READY，详情按需读 references/protocol.md。
