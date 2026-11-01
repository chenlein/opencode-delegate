# opencode-delegate

**让 Codex 将有界任务交给 OpenCode 执行，并独立验证结果。**

opencode-delegate 是一个 Codex Skill，配套本地 Python Runner。它将任务范围、工作区、会话、预算与验收证据绑定在一起，适合需要明确交付边界的代码分析和小范围修改。

当前版本：**2.0.1-rc.8，受监督预发布版**。已验证范围与限制见 [兼容性与验收依据](docs/ISSUE1_ACCEPTANCE_DECISION.md)，不代表任意 CLI、模型或平台均已认证。

## 什么时候使用

- 需要让 OpenCode 独立探索一个明确范围的模块。
- 将一个可独立验证的小修复交给执行器，保留人工或主代理裁决。
- 需要同会话增量反馈、受控重试，以及可追溯的测试与交付证据。

简单任务、主会话已掌握充分上下文的任务，通常直接由 Codex 完成更合适。本项目不承诺减少 token、费用或耗时，也不做递归多代理编排。

## 核心能力

| 能力 | 使用者得到什么 |
|---|---|
| 冻结任务契约 | 执行前明确源码范围、项目规则、预算和验收条件 |
| 隔离 Git worktree | 在独立工作区执行，检查越界修改和源码污染 |
| 显式会话绑定 | 绑定任务、环境和 session，支持同任务增量反馈 |
| 有界执行与恢复 | 限制尝试次数和累计执行预算，保留不确定结果 |
| 独立验证与裁决 | 固定检查与语义审核分离，不以 CLI 退出码代替验收 |
| 可核对交付 | 导出新增、修改、删除清单及哈希，不自动应用到主仓 |

## 安装

需要 **Python 3.9+、Git、macOS 或 Linux**，以及可使用 Skill 的 Codex 环境。OpenCode CLI 和模型接入需另行配置；安装器不申请或复制凭证，不修改 OpenCode 全局设置。

从首个预发布版本安装，避免默认分支与说明版本不一致：

```bash
git clone --branch v2.0.1-rc.8 --single-branch https://github.com/chenlein/opencode-delegate.git
cd opencode-delegate
export PYTHONDONTWRITEBYTECODE=1
python3 tools/build_release.py --check
python3 install.py --dry-run
python3 install.py --replace
```

默认安装到 `~/.agents/skills/opencode-delegate`；识别已有的 `~/.codex/skills/opencode-delegate`。两处都存在时需显式指定 `--target`。覆盖安装会保留旧版备份。

**有活动任务时先阅读 [升级与恢复指南](docs/USAGE.md)。** 不直接迁移旧状态或用新 Runner 强行恢复旧任务；需要保留旧 Runner 和现场。

## 快速开始

在 Codex 中调用：

```text
$opencode-delegate
请只读分析当前仓库的指定模块，不修改文件。
先明确范围、项目规则和验收条件，再由 Codex 独立验证结论。
```

建议从只读任务开始。需要修改代码时，明确允许修改的文件和验收条件，再授权实现。

工作流程：**确定范围 → 冻结契约 → OpenCode 执行 → 独立检查 → 审核裁决 → 导出交付**。

- `run` 成功只表示等待验证，`verify` 成功只表示等待审核；通过最终裁决才是 `ACCEPTED`。
- 超时或证据不完整时停止并核查，不盲目重试。模型调用可能产生费用。
- 默认单执行器、一层委派；不会自动提交、推送、合并或部署。

手动操作命令、任务模板、失败反馈、恢复与清理见 [使用指南](docs/USAGE.md)。

## 兼容性与安全边界

- 已有 Linux x86_64 / OpenCode 2.2.5 与 macOS ARM64 / OpenCode 2.2.3 的限定场景实测。完整范围、模型及运行方式以 [验收裁定](docs/ISSUE1_ACCEPTANCE_DECISION.md) 为准，不能外推其他组合。
- `doctor` 仅做能力探测；当前仍须显式确认精确 CLI 版本的实验运行，不自动放宽权限。
- **这不是 OS 沙箱或 DLP。** 默认约束执行器 Shell、子代理、外部目录等工具权限，依赖受信任的 CLI、插件、Git hooks/filter 和验证代码。需要严格隔离时另配账号、容器及网络边界。
- 文件名检查与日志脱敏不能保证发现所有秘密；不要提交凭证、私有源码或原始会话日志。任务内容会交给所配置的模型服务，运行前应审核范围。
- 本地进程停止不证明远端模型请求已取消或不会计费。未知用量保留为未知，不推算成本优势。

详见 [权限与恢复边界](opencode-delegate/references/security-recovery.md)。

## 文档导航

| 文档 | 内容 |
|---|---|
| [使用指南](docs/USAGE.md) | 安装升级、CLI 流程、反馈、恢复与导出 |
| [Skill 入口](opencode-delegate/SKILL.md) | 主代理调用规则 |
| [协议说明](opencode-delegate/references/protocol.md) | 任务契约、状态与兼容性 |
| [验收裁定](docs/ISSUE1_ACCEPTANCE_DECISION.md) | 当前限定版本的真实验证范围 |
| [整体审查](docs/FINAL_REVIEW_RC8.md) | 代码审查结论与保留限制 |
| [开发指南](docs/DEVELOPMENT.md) | 离线测试、构建与贡献要求 |
| [CHANGELOG](CHANGELOG.md) | 版本变化及历史兼容性记录 |

## 许可证

尚未指定开源许可证。公开可见不等于已授予某种开源许可。
