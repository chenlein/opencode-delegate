# 权限、认证与恢复

## 威胁模型

本工具用于受信任开发者本机，防止协作错误、范围越界、会话串线和证据误报；不是 OS 沙箱，不抵御同账号恶意进程、插件或测试。worktree 共享部分 Git 数据，不隔离账户、凭证、网络或全部进程。

CLI、配置/插件、Git filter/hooks 和验证代码必须可信。严格环境使用独立受限账户、容器/虚拟机、最小凭证和网络限制。不要把项目源码、原始任务日志或凭证提交到公开维护仓库。

## 默认权限

专用 Agent 默认拒绝工具，仅开放 read/glob 和授权 edit。Shell、子代理、外部目录、网络、技能执行及 grep 内容搜索拒绝。敏感命名文件或 symlink 在运行前阻断，但这不是全内容秘密扫描。

不安装 OpenCode、不复制认证、不改全局配置。OpenCode 使用自己的凭证。配置探测可能初始化插件，须在可信环境执行；事后指纹检查不能撤销外部副作用。

配置指纹忽略无意义空白，但保留权限规则顺序。已声明规则按内容冻结；未知/远端指令源拒绝。无法识别有效权限时停止，不宽松降级。

## 版本认证

当前没有已认证 CLI 版本。doctor 仅打印精确版本、二进制/help 哈希及能力。真实受监督试用需要 --experimental-cli-version 精确匹配；这不代表认证。

V1/V2 适配器均为候选，V2 要求 standalone 能力。debug config 结构不匹配就停止。实际配置合并、隐式规则、权限效果和会话事件需要绑定具体 CLI 构建联调。二进制包装脚本哈希不证明所有间接依赖。

rc.5 的 V2 预检识别 v2.2.3 来源列表，核对原生最终 Agent 的规范化模型/指令/权限；两类查询使用相同 cwd、env 和 standalone 语义，并前后检查来源及相关配置/Agent 文件。不是同一持久服务实例，仍须另行做真实权限验证。冻结权限块以通配 deny 开始，覆盖之前的默认/全局规则；完整块必须保序相等，其后只容许 deny。来源里的 formatter=true 或未知 references 保守拒绝，不猜测覆盖优先级。JSONC 只接受无歧义的注释/尾逗号。V2 新指纹不自动替换旧任务基线。

## 测试信任

argv 不等于安全沙箱。授权前审核入口、断言、fixtures、构建配置和副作用。verification_sources 是显式可信清单，不自动证明动态导入和系统工具。禁止伪装成本地测试执行生产操作、SSH 部署或模型调用。

## 不确定状态恢复

进程组超时会尝试终止，残留后代或中断进入 OUTCOME_UNKNOWN。脱离进程组的 daemon、远端已受理任务和 PID 重用需要人工核对。

先 status 检查 execution.json 和必要日志；核对 CLI/服务会话、进程及实际工作区修改，不盲杀 PID、不直接重发。确认停止后编写恢复说明，再运行：

```bash
python3 "$RUNNER" recover --task "$TASK" --confirmed-stopped --note /absolute/recovery.md
```

恢复不会还原源码或宣告通过。run 阶段恢复需要新会话、审核后的检查点和剩余预算；无污染的 verify 阶段恢复为 VERIFY_RETRY_READY，直接重跑冻结检查再 review，不新建模型尝试。越界、HEAD/index 变化或测试修改源码必须保留现场，不自动 reset 或改证据。

EVIDENCE_ERROR 可在排除 Git/IO 故障后重新 verify；缺补丁不等于无差异。损坏或未知状态不自动放行。

## 清理

export 不合并、提交、推送。cleanup 默认预览；只有明确 --confirm、已审查终态、导出完整未变、快照一致、进程停止时，才移除本工具创建的 worktree，保留状态和证据。运行中/不确定任务不得清理，主仓和未知目录不在清理范围。


## rc.2 阶段恢复补充

PREPARING 表示已预留尝试且可能尚未启动；RUNNING/VERIFYING/OUTCOME_UNKNOWN 必须依据 operation.phase 和 start_sha256 检查。即使没有 verification.json，也不能放宽测试不得改源码的规则；已经记录的违规不可因文件恢复原样而抹除。未启动尝试同样需要显式确认现场，不自动删除/重用 attempts 目录。

CLEANING 的已验证导出必须仍完好。工作区已删除且 Git 注册已消失时，cleanup --confirm 只补交 ARCHIVED；原路径重新出现时不自动清理。Git 部分删除留下注册时停止，保留证据并人工核对，不自动全局 prune。

旧 rc.1 中断任务没有可信 phase，不使用猜测恢复。保留旧代码/日志做人工核对，尤其不能把 rc.1 的 recover 结果当作测试未改源码的证明。

受限 edit 策略保守保留所有大小写 AGENTS.* 与 CLAUDE.* 名称；真实 CLI 的前置拒绝仍需精确版本认证。实际自定义 fallback/配置指令须显式声明；此清单不等于自动解析全部 Codex/OpenCode 配置。

## rc.4 预算和日志边界

先持久化预算预留，再启动执行器。故障后仅用同 operation ID 的完整执行证据结算；未知消耗不得计零，可能保守耗尽该任务余量。total_execution_seconds 是额度扣记，operation.budget.observed_seconds 才是可确认的观测值，均非 token/账单。旧版未预留的活动 run 不享有自动退款。

直接父进程正常退出后的同组残留也要执行完整收尾。无法确认停止时，不宣称日志已固定，不发布最终哈希；failure --include-details 会注明暂不共享。确认停止并 recover 后重新 verify 生成新证据，不能手工补哈希来接受旧日志。
