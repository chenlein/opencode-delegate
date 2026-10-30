# 横向结论核对与取舍（2026-10-30）

核对用户粘贴的横向比较结论；没有声称读取/修改 Pages 全文。对三份上游源码做只读核对，不运行第三方代码、不创建 Codex 会话；没有将第三方源码复制到本仓库。上游后续变化不自动纳入以下结论。

## 固定比较身份

| 方案 | 核对提交 |
|---|---|
| [amElnagdy/delegate-skills](https://github.com/amElnagdy/delegate-skills/tree/3aa72d681a79e2a9d09bd9a316353003ae1cb4a7) | 3aa72d681a79e2a9d09bd9a316353003ae1cb4a7 |
| [mryesiller/opencode-delegate-mcp](https://github.com/mryesiller/opencode-delegate-mcp/tree/52440fd2277858bf1c066daa4bdee02ea596f92e) | 52440fd2277858bf1c066daa4bdee02ea596f92e |
| [alejandro-technology/opencode-mcp](https://github.com/alejandro-technology/opencode-mcp/tree/e142d786589e163ed679b038f981a612699c0afc) | e142d786589e163ed679b038f981a612699c0afc |
| 本项目 | 比较基线 c1b1664 / rc.3；本轮仅修复 C01–C03，rc.4 |

## 1. delegate-skills：调用适配可取，完成状态不等于验收

其 [OpenCode relay](https://github.com/amElnagdy/delegate-skills/blob/3aa72d681a79e2a9d09bd9a316353003ae1cb4a7/skills/opencode-delegate/scripts/relay.mjs#L318-L410) 包含有界版本探测、1.x/2.x variant 参数区分、stdin 传任务、POSIX/Windows 分支；调度时同时设置 cwd 与 PWD。值得建立本项目的版本适配与回归夹具，不直接照搬未经认证的参数猜测。

[完成分支](https://github.com/amElnagdy/delegate-skills/blob/3aa72d681a79e2a9d09bd9a316353003ae1cb4a7/skills/opencode-delegate/scripts/relay.mjs#L638-L662) 的 completed 对应 code=0 且 watchdog 未触发，不证明验收条件已满足。它要求协调者检查差异、重跑项目检查，不应被描述为完全不关心验收；区别在程序是否强制执行本项目的冻结测试、污染检测和逐项 ACCEPTED。

[read-only-tripwire](https://github.com/amElnagdy/delegate-skills/blob/3aa72d681a79e2a9d09bd9a316353003ae1cb4a7/test/relay/read-only-tripwire.mjs#L178-L184) 的 tripwireSkills 是 claude、grok 和非 Windows 的 commandcode，不含 opencode。用户对此的限定正确；这不意味着 OpenCode 完全没有参数、流或生命周期测试，也不把 plan 视作 OS 只读沙箱。

本轮只借鉴设计取舍，不复制代码。未知协议应保守拒绝，不能把容错流解析的“跳过坏片段”搬进最终业务验收门禁。

## 2. mryesiller：入口、profile 与摘要可取，默认授权不能照搬

[tools.ts](https://github.com/mryesiller/opencode-delegate-mcp/blob/52440fd2277858bf1c066daa4bdee02ea596f92e/src/tools.ts#L131-L230) 支持显式参数 → profile → 默认配置的解析，以及模型发现和结构化摘要。它直接在目标目录运行，文档/工具描述明确默认自动批准。

[delegate_tests](https://github.com/mryesiller/opencode-delegate-mcp/blob/52440fd2277858bf1c066daa4bdee02ea596f92e/src/tools.ts#L295-L322) 构造测试写作提示后仍调用 backend.run，并非独立 verifier。因此应借鉴生成契约的用户体验，而非把测试代理的自述替代本项目 verify。

补充风险：[backend.ts](https://github.com/mryesiller/opencode-delegate-mcp/blob/52440fd2277858bf1c066daa4bdee02ea596f92e/src/backend.ts#L146-L220) 的 emptyUsage 将缺失用量初始化为 0。直观摘要值得借鉴，但本项目必须保留 unknown/partial/complete，不能由无事件推导零成本。

## 3. alejandro：能力不能低估，但 passed 不是 ACCEPTED

[README](https://github.com/alejandro-technology/opencode-mcp/blob/e142d786589e163ed679b038f981a612699c0afc/README.md#L25-L74) 确认异步任务、run_id 历史、进度、长轮询、取消、可选 worktree、实际变化及调用方 checks。它不是简单 CLI 包装器，并且已有缺失用量保持未知的设计。

[task-registry.ts](https://github.com/alejandro-technology/opencode-mcp/blob/e142d786589e163ed679b038f981a612699c0afc/src/modules/shared/task-registry.ts#L76-L98) 使用 Map/Set 管理任务；README 明确重启丢失任务历史与工作区所有权记录。不能据此推断 OpenCode 服务自身的会话也全部丢失。

[captureReport](https://github.com/alejandro-technology/opencode-mcp/blob/e142d786589e163ed679b038f981a612699c0afc/src/modules/shared/execution-report.ts#L470-L526) 计算预期变化的 missing 子集，并执行调用方检查；源码变化快照在检查前生成，不能等同本项目检查后的源码污染检测。未见等价的冻结可信测试源与逐项协调者语义裁决。

README 明确使用 v1 SDK/API、验证过 OpenCode 1.18.34、不支持 2.x。对于用户记录的 2.2.1，不能直接替换。本项目同样尚未完成 2.2.1 实机认证；更严格的拒绝不等于更好的兼容性。

## 4. 本项目的定位与实际代价

“入口 Skill + 有状态 Runner”是准确定位；应分开评价入口简洁与执行系统责任，而不是因为脚本较长就推倒重做。

一次 init → run → verify(N 个实际执行的检查) → review 成功路径：init 1、run 3、verify N+1、review 1，总计 N+6 次完整快照；再 export 2、cleanup 1，为 N+9。额外 status --check-worktree、重试、恢复另计；提前失败则路径不同。本轮新增两检查临时仓库计数测试确认这一正常路径，但它不是大仓性能或 token 成本实测。

同 GPT 不共享上下文，也不天然带来异构审查收益。直做、原生子会话、跨工具三路线应使用相同基线、相同验收、独立会话，比较端到端时间、双方真实用量、首次验收率、漏检、返工和人工介入。模型回答更短、worker 更快返回都不能单独证明提效。

## 5. 本项目采纳顺序（建议，不是本轮已实现功能）

| 顺序 | 可取能力 | 接入边界与验收标准 |
|---|---|---|
| 立即 | 修复 C01–C03，认证实际 CLI | 本轮代码已修复；真实 2.2.1/模型/权限仍需 Issue #1。关注 variant 表达、cwd/PWD、配置探测与执行同实例 |
| 下一步 | models + init profile + 契约生成 | 只提供经过审核的默认值；任务 init 后冻结；profile 变化不能修改活动任务；不自动挑便宜模型或扩大权限 |
| 下一步 | 一屏结果摘要与下一条安全命令 | 区分 worker完成/检查通过/最终接受；显示 task/session/commit、预算扣记、证据与 unknown 用量；完整日志按需展开 |
| 有真实长任务需求后 | 薄 MCP、wait/cancel、历史轮次 | 只调用同一 Runner/状态账本；wait 不轮询模型；cancel 需确认实际停机；不引入独立内存权威状态 |
| 有大仓证据后 | 减少重复扫描 | 测量每阶段扫描量后优化，不靠跳过 ignored/untracked、降低验收或允许共享写目录提速 |

保留显式授权、独立工作区、冻结契约、明确 session 和最终裁决；不照搬默认 auto、最近会话、共享写目录或 exit 0=验收。OpenCode V2 的 auto 文档指批准未显式拒绝的权限，不应误说成必定忽略 deny；本项目仍选择不用它。[官方说明](https://opencode.ai/v2/docs/cli/commands/)

本轮没有新增 models/profile/MCP 等功能，没有完成真实对照和成本测量；先把恢复闭环修好，再用真实任务证明收益。
