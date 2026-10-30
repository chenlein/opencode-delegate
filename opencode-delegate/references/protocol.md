# 任务、状态与证据协议

## 契约

契约 schema_version=2，创建后冻结。必须明确 project_id/task_id/environment、实际 Git 根目录、模型 provider/model、目标/非目标、修改范围、验收项与检查。不同环境不复用会话。

| 字段 | 规则 |
|---|---|
| allowed_paths | 精确文件或以 / 结尾的目录，不支持通配符；analyze 必须为空 |
| protected_paths | 叠加内建规则与敏感路径保护 |
| context | path/purpose/kind；reference 可变化，rule 冻结保护 |
| instruction_sources | 已审核的外部规则绝对路径与 scope；单份最多 8 KiB |
| verification_sources | 可信既有测试、断言、配置、夹具；必须存在并保护 |
| checks | 固定 argv/cwd/timeout_seconds/criterion_ids/output_contains |
| trusted_inline | 默认 false；true 仅允许已审核、自包含的 `['{python}','-c',code]` |
| verification_artifacts | 明确目录前缀，仅验证阶段可产生；与源码/规则/可信测试不可相等或嵌套 |
| max_attempts / timeout_seconds | 默认 3 次 / 600 秒 |
| max_execution_seconds | 默认累计 CLI 运行 1800 秒；不是 token 或费用硬上限 |

外部检查必须登记可信验收源；新增业务测试可以属于修改范围，但不能替代原门槛。声明清单不自动证明所有动态依赖可信，协调者须审核依赖闭包和副作用。不要用 trusted_inline 包装未登记的可变测试实现。

`{python}`、`{worktree}`、`{evidence_dir}` 由 Runner 替换。不调用 Shell 不等于所执行程序没有危险副作用。

## 三种版本

产品版本为 2.0.1-rc.2；新状态 state_schema_version=2，与产品补丁号解耦；执行器业务结果 schema_version=1。CLI NDJSON 是独立的传输层，不能代替业务校验。

执行器必须返回唯一 BEGIN_DELEGATE_RESULT/END_DELEGATE_RESULT 块，包含 schema_version、task_id、status、summary、claims、tests_run、risks。tests_run 必须为空。最终业务结果只属于最后一条消息；混合/冲突身份、重放、未知事件、缺终态、错误会话、重复条目、非法关联或结果落盘失败，不能进入待验证成功状态。

## 持久化与升级

baseline.json 固定初始源码；checkpoints/<sha256>.json 不可变。先写快照，再原子替换 state.json 指针，保留 state.previous.json。文件及父目录 fsync；未引用的孤立快照不影响旧完整代。写操作仍用独占锁；status 不取写锁，只读单次原子 state 和它引用的不可变快照，标注 generation 与“最后已提交状态”。可选扫描单独尝试锁，竞争时跳过，不移除锁文件。

新操作在副作用之前持久化 operation.id/phase/stage/start_sha256/errors。run 先提交 PREPARING 与尝试号，再创建尝试目录；失败不复用旧目录、不减次数。verify 先记录原阶段与起始快照；recover 按原阶段判断且不丢弃已发现违规。CLEANING 先绑定导出与快照；删除完成后提交失败可以重跑 cleanup --confirm 收尾。

rc.1 静止状态可读取；旧中断状态缺少 operation.phase 时不自动恢复，不猜测、不静默补写；人工核对旧 Runner 记录和实际副作用后再规划。旧 2.0.0 状态仅支持只读 status。写操作须使用安装器备份的旧 Runner 完成或恢复，再创建新任务；未知状态 schema 拒绝，不静默迁移。安装器检测指定 state-root 中的旧活动任务，显式 --preserve-legacy-runner 才允许保留旧 Runner 后升级。自定义状态目录必须传 --state-root。

磁盘损坏不自动回退并假装任务没执行。上一完整代只提供恢复证据；实际进程和工作区仍须核对。

## 验证与裁决

固定检查由 Runner 记录退出码、超时、输出要求、日志哈希、关联验收项。验证修改源码进入 VERIFICATION_MUTATED_SOURCE；差异生成失败进入 EVIDENCE_ERROR，不生成虚假的空差异证明。

最终 review、memory、export 继续复查规则内容与新出现的环境规则，输出记录 instruction_manifest_sha256。Codex 裁决绑定 contract_sha256、snapshot_sha256、verification_sha256，覆盖所有验收项且不重复。证据为 file:relative/path、test:check_id 或 diff。失败测试可以支持 fail/blocked，pass 必须关联已通过测试；diff 必须生成完整。

ACCEPTED 只接受隔离工作区。export 包含新增文件完整内容、修改内容、删除清单、基线及哈希，不自动应用。tracked.patch 本身仍不含未跟踪文件，不能单独当完整交付。

## 交接与观测

任务包含验证计划、规则索引、必要反馈和检查点，不默认传整段日志/聊天。失败包默认仅元数据；详细摘录须先通过 failure --include-details 审阅，再显式共享。脱敏不是 DLP。

status 默认不扫描源码，--check-worktree 才扫描。run/verify 安全边界仍扫描全部普通文件，包括忽略和未跟踪文件。scan_totals、total_execution_seconds、total_verification_seconds 是独立观测，不参与内容哈希。

usage 缺失为 unknown、片段为 partial；不推算账单。工具无法得知主会话全部成本，端到端评测需另行采集双方用量。

事件适配仍未获得真实版本认证。无 messageID 的合成/兼容事件单独标为 legacy-unidentified，不混用有身份事件；后续活动会丢弃旧候选结果，不能借用之前的 stop。
