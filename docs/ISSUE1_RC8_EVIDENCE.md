> 后续更新：Mac 三路线读/改/增量恢复及用量证据已补齐，父协调者独立复核完成。以下为云端批次的原始阶段状态，不再代表最新阻塞。最新逐项裁定及兼容性边界见 [验收裁定](ISSUE1_ACCEPTANCE_DECISION.md)。

# Issue #1：rc.8 云端真实验收与剩余阻塞

2026-10-31。**Issue 保持开放，不发布稳定认证声明。** 本轮运行时代码固定为 `2318d8ac92df8322537d520c1a9a133cf5a68432`，其 Linux/macOS 离线 CI 两轮均成功。此后新增的是证据、回放工具与语料完整性检查，没有把旧版本实测重标成新版本。

机器可读结果、执行日志原始哈希和用量观察见 [ISSUE1_RC8_EVIDENCE.json](ISSUE1_RC8_EVIDENCE.json)。不发布原始会话、私有绝对路径、代理地址或任何凭证。

## 验证组合

- Linux x86_64，Python/Git 精确版本见 JSON。
- OpenCode `v2.2.5`，官方 `@opencode/cli@2.2.5`，二进制 SHA-256：`8d060e1d2fbb9bb44cf09ae6ed1f3f6a7cff070b5227e2f90970132b23a92050`。
- 请求模型和原生 Session 绑定为 `openai/gpt-6.1-sol`、default variant。provider 的实际模型快照未独立披露，保留 UNKNOWN，不把请求字段或 Session 字段当作后台模型身份的独立证明。
- 使用隔离 HOME/XDG、无秘密合成仓库及公开 TypeScript 源码。既有用户配置、认证文件和已有会话不作为测试修改对象。

## 真实功能与恢复

| 场景 | 结果 | 独立证据与边界 |
|---|---|---|
| 只读分析 | ACCEPTED | 正确识别 `a - b`；源码字节不变，固定检查及语义审查通过 |
| 限定单文件修复 | ACCEPTED | 只有算术表达式改为 `a + b`；四条冻结断言通过，保护文件不变 |
| 同 Session 失败恢复 | ACCEPTED | 首次业务断言已通过，冻结 verifier 人为注入一次瞬态失败；增量续跑沿用原 Session、保持原修改字节，第二次 verifier 通过。不是修复 worker 写错的代码 |
| 实际外部读取拒绝 | BLOCKED，保护符合预期 | 原生 read 工具真实返回 `Permission denied: external_directory`；不绕过、不改文件 |
| 实际保护文件编辑拒绝 | BLOCKED，保护符合预期 | 原生 patch 工具真实返回 `Permission denied: edit`；保护文件字节不变 |
| Session 权限覆盖 | 续跑前阻断 | 向自有测试 Session 注入 shell allow，新门禁返回 3；状态/预算不变、无新 attempt、零模型调用。随后恢复空权限并读回核对 |
| 真实超时及恢复 | 保留失败后 ACCEPTED | 连接错误导致原生运行超时；确认本地进程组停止、保存证据和预算后，显式 fresh-session/checkpoint 继续，不盲重试、不采信晚到结果 |

首次选择的 `gpt-5.1-codex-mini` 虽在 OpenAI API 模型列表中，却不在该 OpenCode 版本路由目录中，返回 `provider.no-route`；保留为失败，不宣称调用成功。后续另建冻结模型契约使用目录中可用的 Sol。

首个 Sol 运行的测试环境遗漏了既有代理变量，出现 ECONNRESET。恢复了进程级传输环境，没有改权限策略。该次配置超时为 45 秒，实测执行及收尾 45.136 秒；不能宣称所有尝试都严格小于等于 45 秒。后续诊断采用更短执行期限预留收尾时间。本地进程组停止不代表远端请求已被撤销或未计费。

## 原生权限与规则

[15 项权限矩阵](NATIVE_PERMISSION_MATRIX_V225.json) 在一个临时、仅绑定 loopback、带临时认证的原生服务实例内执行。先确认自定义 Agent 及完整规则已就绪，再检查 read/glob/限定 edit 允许对照，以及保护路径、敏感命名、Shell、子代理、外部目录、网络、skill、question、execute 拒绝。全部符合预期，模型 token/cost 为零，测试服务已确认停止。

此前逐次启动私有 API 客户端的冷启动探测曾把允许读取判成 deny。它没有通过正向对照，**不能把“全拒绝”当权限认证成功**。最终结果以就绪后同实例矩阵为准。权限判定 API 不等于每一种工具主体的实际调用；实际 read/patch 拒绝另外记录在事件语料中。

三个独立规则标记分别来自仓库、祖先目录和全局规则。原生 compaction 记录为 completed；压缩摘要及同 Session 后续结果都含三个标记，源码和冻结检查保持不变。祖先及全局规则同时由契约显式冻结传递，不把这两项全部归因为隐式加载。规则内容改变及新增未注册祖先规则，均在 attempt 预留前拒绝，状态不变；自有测试规则随后恢复原字节。

另在 v2.2.5 的自有零模型 Session 中实际调用 move，并显式恢复待处理控制项；独立读回确认同一 Session 已迁到新目录，旧 worktree 仍存在。迁移前绑定通过，迁移后生产门禁拒绝，token/cost 均为零。没有迁移任何既有用户任务。rc.7 的 v2.2.3 迁移证据仍保留原身份。

## 真实大仓完整流程

公开来源：[Microsoft TypeScript 固定提交](https://github.com/microsoft/TypeScript/tree/6161772c1370bdd4a82f808e6823bd755eb1870d)，提交日期 2026-10-30。

- 完整 checkout：68,201 个源码/测试文件，219,367,414 字节。没有删文件、稀疏排除、改扫描上限或跳过安全检查。
- 完成 init → 原生只读任务 → 两个固定检查 → 重复 verify → 独立 review，最终 ACCEPTED。
- 任务只分析 `tsc/internal/core/core.go` 的 FindIndex：正向遍历、首次匹配立即返回索引，无匹配返回 -1。固定源码哈希和空 tracked diff 独立验证。
- verifier 在声明的忽略目录里生成两个**明确合成**的缓存/输出文件，供后续完整扫描核对；不是实际 TypeScript 构建产物。没有运行该项目的安装、构建或业务测试。
- 全流程累计 14 次快照、68.538058 秒扫描时间。累计扫描文件数/字节数是重复工作量，不能当仓库体积。
- 在上述合成忽略产物存在时，一次独立重复 verify 耗时 16.014 秒，三个快照累计 14.201693 秒，子进程峰值 RSS 253,300 KiB。不是整机峰值、跨平台 SLO 或普遍性能承诺。

另保留 DuckDB v2.0.0 完整源码扫描：16,801 文件、约 260.6 MB，发现 4 个符号链接/敏感命名测试条目。因此不将其计作可执行准入仓库，也没有删除这些文件强行通过；后续选择原样符合安全条件的 TypeScript 仓库。

## 原生事件及回放

保留 v2.2.3 语料，新增 v2.2.5 的 8 个脱敏原生捕获：正常只读、限定编辑、同会话恢复、外部读取拒绝、保护编辑拒绝、压缩后续跑、大仓只读、真实连接超时。新增 5 个明确派生的重复/累计分块/缺尾/冲突会话/截断反例。

合计 **26 个回放用例通过：13 原生、13 派生**。派生故障没有冒充原样观测到的原生行为。新增 6 项语料完整性回归，拒绝目录符号链接、篡改内容、额外未审文件及逃逸清单的测试路径。CI 和发布打包同时纳入两个版本语料。

```sh
export PYTHONDONTWRITEBYTECODE=1
python -m unittest discover -s opencode-delegate/scripts -p 'test_*.py' -v
python tools/test_install.py
python tools/test_real_event_corpus.py
python tools/check_real_events.py
python tools/build_release.py --check
# 以下为显式选择的零模型原生探测，不在离线 CI 中自动运行：
python tools/probe_session_permissions.py --opencode /absolute/native/opencode
python tools/probe_native_permissions.py --opencode /absolute/native/opencode --check-move
```

## Codex 对照、用量及未关闭项

官方 Codex CLI 0.166.0 在受控命令环境中，文件工具受到嵌套 sandbox 初始化问题阻断。[上游同类问题](https://github.com/openai/codex/issues/53799) 仅作背景，当前判断以本轮错误和实际探测为准。

可见宿主终端的只读 `/bin/true` 沙箱检查通过，但该宿主没有可用外网；受控命令环境的进程级代理端点不能搬到宿主使用。本轮没有修改系统网络、移除沙箱或搭建转发来规避限制。

显式 OpenAI HTTPS provider、零项目文档的空夹具诊断可取得真实 Codex `OK` 及 token 记录。但在同一受控环境尝试 apply_patch 时仍被文件沙箱阻断，源码无变更。**无工具 API 成功不是代码工具链或三路线对照通过。** 所有已启动尝试、超时和清理介入均保留，不以成功退出码掩盖业务 BLOCKED。

F14 尚缺当前可执行环境的完整、同条件三路线对照；F15 尚缺相应完整协调者/执行器与统一端到端时钟。原生 token 和目录估价不当作账单，dot 协调者用量不可见时记 UNKNOWN，不用字符数估算或宣称省钱。

当前只完成本轮可独立完成的证据补齐。**未满足全部原关闭要求，因此不关闭 Issue、不自动合并 PR、不发布稳定认证。** 待获授权的可联网非嵌套环境完成剩余对照后，逐项裁定关闭，再进行最后一轮整体审查。

本地最终回归：236 Runner、16 安装、6 语料完整性测试及 26 回放通过。检查过程中检查脚本曾产生两个未跟踪 Python 缓存，安装器因此拒绝不干净的源码包；只清理自有生成缓存后重跑通过，没有放宽安装器完整性校验。

新增诊断入口曾在未设置 PYTHONDONTWRITEBYTECODE 时，仅执行 --help 就向 Skill 目录生成字节码。已在诊断与回放入口导入运行时前禁写字节码，并新增隔离发布副本的安装回归。没有忽略或放宽未知文件检查。
