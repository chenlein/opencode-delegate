# opencode-delegate

**Codex 负责规划与验收，OpenCode 执行一个有界任务。** 使用隔离 Git worktree、冻结任务契约、明确会话 ID 和独立测试证据，不把两个 GPT 会话当成共享记忆，也不把 CLI 退出 0 当成验收通过。

当前版本 **2.0.1-rc.2：受监督候选版，尚非稳定认证版**。源代码、README、回归测试和审查整改在本仓库维护。

**160 项离线测试通过，不等于真实 OpenCode/GPT/macOS 已认证。** 当前精确 CLI 认证矩阵为空。详见 [实际验证](docs/VALIDATION.md)、[18 项整改状态](docs/REVIEW_STATUS.md) 、[本轮 A01–A10 修复](docs/ROUND2_FIXES.md) 和 [真实认证方案](docs/LIVE_VALIDATION.md)。

## 本轮可靠性修复

A01–A10 的程序级反例已转成验收回归：操作阶段与起始快照持久化、PREPARING 尝试预留、CLEANING 清理意图、AGENTS.override.md 保护、最终规则漂移复查、配置语义比较、最终消息绑定、安装路径规范化和测试环境隔离。具体证据与适用边界见 [修复清单](docs/ROUND2_FIXES.md)。

`status` 可在运行中读取最后已提交的状态代号，不会启动第二份执行。运行时的 `--check-worktree` 明确跳过扫描，而不是声称拿到了实时一致的源码快照。

## 安装与升级

需要 Python 3.9+、Git、macOS/Linux；OpenCode 必须另行安装并配置。安装器不申请或复制凭证，不修改 OpenCode 全局设置。

```bash
git clone https://github.com/chenlein/opencode-delegate.git
cd opencode-delegate
export PYTHONDONTWRITEBYTECODE=1
python3 tools/build_release.py --check
python3 install.py --dry-run
python3 install.py --replace
```

新安装默认 `~/.agents/skills/opencode-delegate`；识别已有 `~/.codex/skills/opencode-delegate`。两处都存在时必须显式选择 --target，不自动删除。旧版备份在 `~/.local/share/opencode-delegate/skill-backups/`，不进入技能扫描目录。

**有 2.0.0 活动任务时不要直接迁移。** 新 Runner 只读查看旧状态；用备份旧 Runner 完成/恢复，再建立新任务。安装器发现旧活动任务会阻止覆盖，明确保留原 Runner 后才使用 --preserve-legacy-runner。自定义状态目录通过 --state-root 指定。[协议与升级](opencode-delegate/references/protocol.md)

**rc.1 的已中断任务不要猜测原阶段。** rc.2 的新操作会记录 phase/operation ID/start snapshot；缺少这些字段的旧 RUNNING/VERIFYING/OUTCOME_UNKNOWN 任务不会自动恢复。先保留原版本及现场，人工核对原操作、进程和测试副作用；不能将旧版恢复成功当作验证源码未污染的证据。静止任务可查看，再按新版本建立受控操作。

## 在 Codex 中调用

```text
$opencode-delegate
请只读分析当前仓库的指定模块，不修改文件。
先明确范围、项目规则和验收条件，由 Codex 独立验证结论。
```

简单、已有充分上下文的任务优先由 Codex 直接完成；确实需要独立探索或 OpenCode 环境时再委派。默认单执行器、一层委派，不递归编排。实现任务需明确授权；不会自动合并、提交、推送或部署。

## 命令行流程

从 `opencode-delegate/assets/task.template.json` 复制任务到仓库外，填写实际模型、仓库、范围、可信测试和验收标准。以下路径是示例，不可直接照抄为实际任务路径。

```bash
RUNNER="$HOME/.agents/skills/opencode-delegate/scripts/delegate.py"
python3 "$RUNNER" doctor
python3 "$RUNNER" init --contract /absolute/task.json
# implement 模式需加 --authorize-implementation；记录 init 返回的真实 task_dir。
TASK="/absolute/task_dir"
CLI_VERSION="REPLACE_WITH_EXACT_DOCTOR_VERSION"
python3 "$RUNNER" run --task "$TASK" \
  --acknowledge-local-execution --experimental-cli-version "$CLI_VERSION"
# implement 模式同样需加 --authorize-implementation。
python3 "$RUNNER" verify --task "$TASK" --authorize-tests
python3 "$RUNNER" status --task "$TASK"
python3 "$RUNNER" review --task "$TASK" --review /absolute/review.json
```

doctor 仅探测能力，不调用模型、不认证权限。--experimental-cli-version 表示明确选择未认证版本的受监督试用，不会放宽权限检查。实际 run 可能产生模型费用。

`run` 返回 0 只是 AWAITING_VERIFY；`verify` 返回 0 只是 REVIEW_REQUIRED。只有 Codex 逐项语义审核、固定检查通过且证据匹配，才 ACCEPTED。超时为 OUTCOME_UNKNOWN，差异证据生成失败为 EVIDENCE_ERROR，不能当成功或盲重试。

## 上下文、记忆和失败续跑

绑定 project_id/task_id/environment/session_id、源码快照及规则内容哈希。同任务发送增量，不重复完整聊天。不同环境不能共用会话，不能使用 --continue、--auto 或“最近会话”。

```bash
python3 "$RUNNER" failure --task "$TASK" --include-details
# 先审阅脱敏摘录，再允许共享；implement 仍需实现授权标志。
python3 "$RUNNER" run --task "$TASK" --feedback /absolute/feedback.md \
  --acknowledge-local-execution --experimental-cli-version "$CLI_VERSION" \
  --share-failure-details
```

默认失败包只有验证计划、检查 ID、退出码和哈希；详细日志摘录须审核后显式共享。正则脱敏不是 DLP。换会话需 --fresh-session --checkpoint，检查点明确事实、假设、已排除路线和剩余事项。次数或累计执行时间耗尽停止，不能换 task_id 绕过。

只在验收后生成含来源、环境和失效条件的知识候选，不自动写 AGENTS.md，不建立第二套平行记忆。未知模型用量保持 unknown/partial，不推算节省比例。

## 可信验收和交付

外部检查须声明 verification_sources，固定已有测试、断言、配置和夹具。自包含的 `['{python}','-c',code]` 可以经审核后显式 trusted_inline；不得用它隐藏可变验收代码。可信源清单不自动证明全部依赖安全。

源码与验证产物目录不可相等或嵌套。失败测试可证明失败，不能证明通过。允许新增业务测试，但不能用修改原预期降低验收标准。

```bash
python3 "$RUNNER" export --task "$TASK" --output /absolute/delivery.zip
python3 "$RUNNER" cleanup --task "$TASK"           # 仅预览
python3 "$RUNNER" cleanup --task "$TASK" --confirm # 必须明确授权
```

导出包含新增/修改文件内容、删除清单及哈希，不自动应用。清理先持久化 CLEANING 意图与完整导出绑定，再移除托管 worktree，最后提交 ARCHIVED。删除完成但状态提交中断后，可重跑同一条 `cleanup --confirm` 收尾。导出损坏、路径重新出现、Git 注册残留或没有清理意图的目录丢失仍会阻断；不扩大删除范围、不清理主仓或未知状态。

## 安全限制

这不是 OS 沙箱。默认禁止执行器 Shell、子代理、网络、外部目录及 grep 内容搜索；用 glob/read 和受限 edit 完成任务，测试由 Runner 独立执行。敏感命名文件与符号链接会阻断，但不是全内容秘密扫描。

受信任的 CLI、插件、Git hooks/filter、验证代码是前提；同账号恶意进程不在保护范围。严格场景需账号/容器/网络隔离。[权限与恢复说明](opencode-delegate/references/security-recovery.md)

## 开发与验证

```bash
export PYTHONDONTWRITEBYTECODE=1
python3 -m unittest discover -s opencode-delegate/scripts -p 'test_*.py' -v
python3 tools/test_install.py
python3 tools/build_release.py --check
python3 tools/benchmark_snapshot.py --files 1000 --bytes 4096
# 修改安装包文件后生成新 manifest，再重新检查。
python3 tools/build_release.py
```

当前 146 项 Runner 测试（70 既有场景、40 首轮反例、36 本轮回归）和 14 项安装测试（8 既有、6 本轮）通过。mock 通过不证明真实 CLI 支持。CI 只做离线测试，不读取 API 密钥、不调用模型；远端是否通过以对应提交 Actions 结果为准。

| 目录 | 作用 |
|---|---|
| opencode-delegate/SKILL.md | 精简技能入口 |
| opencode-delegate/scripts/ | Runner、独立模块、离线回归 |
| opencode-delegate/assets/ | 契约、裁决、检查点、知识与行为评测模板 |
| docs/REVIEW_STATUS.md | F01–F18 状态及剩余准入项 |
| docs/VALIDATION.md | 实际已执行验证，不把计划当结果 |
| docs/LIVE_VALIDATION.md | 精确版本认证与真实对照方案 |
| docs/SOURCES.md | 官方规范和设计依据 |
| CHANGELOG.md | 变更与兼容性说明 |

不要提交用户源码、真实凭证或原始会话日志。尚未指定开源许可证；公开可见不等于已授予某种开源许可。
