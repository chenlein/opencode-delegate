# 真实认证与效果评测

2026-10-31：rc.6 已有本机 v2.2.3/Sol 的受控任务、规则压缩、超时恢复、三路线小修复和实仓 scoped 测量；rc.7 补上原生 session 迁移绑定，补齐三路线只读与受控验收失败后的续跑。详见 [前批证据](ISSUE1_RC6_EVIDENCE.md) 和 [后续验证](ISSUE1_RC7_EVIDENCE.md)。完整发布认证仍未完成。以下为验收要求，不能将计划当作结果；mock 版本号和合成用量不是支持声明。

## 精确版本认证

记录 OS/架构、Python/Git、OpenCode 完整版本/二进制 SHA-256/来源、请求和可确认的实际模型。使用无秘密的小仓库、最小凭证，在获授权环境执行；run 可能产生费用。

需要实际证明：只读任务不改源码；允许文件可编辑；Shell/子代理/外部目录/网络/敏感路径真正拒绝；同 session 续跑正确且错配阻断；规则在 worktree、换会话及压缩后保持必要约束；故意失败后仅凭增量证据修复；超时断连不盲重试；导出与裁决绑定同一快照。

采集正常、重复、分块、错误、缺尾等脱敏真实事件夹具，并标记版本与来源。配置探测和执行必须对应同一环境/实例语义。不要提交 auth.json、原始 debug config 或完整会话日志。

## 行为对照

用 assets/behavior-evals.json 的八类任务，增加真实小修复和失败续跑。每次独立新会话、同一源码基线和验收标准，比较 codex-direct、codex-native-child、opencode-delegate。记录通过率、漏检、返工、人工介入、总耗时、主会话与执行器实际用量。

JSONL 格式示例（不是测得结果）：

```json
{"run_id":"unique","case_id":"bounded-fix","route":"opencode-delegate","passed":true,"elapsed_seconds":123,"coordinator_tokens":null,"worker_tokens":null}
```

用 tools/summarize_evals.py 汇总，缺失值保持未知。不能用字符数冒充 token，不能把同一会话先做一次产生的记忆优势算成 Skill 效果。

## 大仓与费用

先跑 tools/benchmark_snapshot.py，再经授权测实际小/中/大源码仓、依赖和产物目录、多验证检查、峰值资源。记录扫描量与阶段时间，不通过忽略未跟踪改动来提速。合成扫描结果不能换算端到端提升比例或费用。

只有实际结果、可复核证据与独立评审完成，才关闭对应 F05/F10/F12/F13/F14/F15。
