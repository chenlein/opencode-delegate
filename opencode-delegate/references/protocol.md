# 任务、状态与证据协议

rc.7：V2 原生 session 的位置优先于 CLI 调用目录。续跑预留额度前和完成结果绑定前，用 standalone metadata 查询核对 ID、worktree、模型及 Agent，失败或漂移停止，不迁移/重建任务。只把已核对字段纳入 worker-result 的哈希，不保存原始 metadata。检查初始化产生的源码副作用仍进入原有快照门禁。状态 schema 不变，历史结果的运行时版本和文件哈希不能冒充新版认证。

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
| max_execution_seconds | 默认累计 CLI 预算 1800 秒；启动前预留、结束/恢复幂等结算；不是 token 或费用硬上限 |

外部检查必须登记可信验收源；新增业务测试可以属于修改范围，但不能替代原门槛。声明清单不自动证明所有动态依赖可信，协调者须审核依赖闭包和副作用。不要用 trusted_inline 包装未登记的可变测试实现。

`{python}`、`{worktree}`、`{evidence_dir}` 由 Runner 替换。不调用 Shell 不等于所执行程序没有危险副作用。

## 三种版本

产品版本为 2.0.1-rc.6；新状态 state_schema_version=2，与产品补丁号解耦；执行器业务结果 schema_version=1。CLI NDJSON 是独立的传输层，不能代替业务校验。

任务包增加 anchors.managed_worktree/source_repository，以及 context_index.worktree_path；均为附加字段，契约 schema 不变。实际运行同时设置 cwd 与 PWD，避免 v2.2.3 优先采用继承的旧 PWD。源仓库路径只作 provenance；文件访问必须定位到隔离 worktree。旧任务不自动迁移指纹或续跑，保留原 Runner 与证据。

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

status 默认不扫描源码，--check-worktree 才扫描。run/verify 安全边界仍扫描全部普通文件，包括忽略和未跟踪文件。scan_totals 与 total_verification_seconds 是观测；total_execution_seconds 是预算扣记值（包括故障时保守预留），不等于实际费用。operation.budget 区分 reserved/settled_observed/settled_not_started/settled_unknown，并分列 observed_seconds 与 charged_seconds。这些字段不参与源码内容哈希。

usage 缺失为 unknown、片段为 partial；不推算账单。工具无法得知主会话全部成本，端到端评测需另行采集双方用量。

事件适配仍未获得真实版本认证。无 messageID 的合成/兼容事件单独标为 legacy-unidentified，不混用有身份事件；后续活动会丢弃旧候选结果，不能借用之前的 stop。

## rc.4 恢复与预算

验证恢复无违规且原入口合法时进入 VERIFY_RETRY_READY，保留 worker session/attempt；verification 清空，须完整重跑固定检查再逐项 review。此状态拒绝 run，避免不必要的模型调用；重验失败进入 NEEDS_FIX 后，仍有额度时才能按失败证据委派修复。run 阶段恢复仍是 RECOVERED，不得直接 verify。

预算在 PREPARING 状态提交时预留与本次 timeout 相同的额度；execution.json 绑定 operation_id 与 contract_sha256。完整且确认进程组停止的结果按 observed_seconds 结算（含收尾耗时，可能略超时）；保存中断后恢复用同一记录幂等结算，不重复扣记。确认停留 PREPARING/preparing 才能证明尚未 spawn 并释放预留；RUNNING/starting 不能这样推断。缺少记录或停止未确认的运行保守耗尽剩余额度；旧活动 run 没有预留协议时也不假定零消耗。未知预算不靠换 task_id 绕过。

同组残留后代与超时共用 TERM（最多 2 秒）→ KILL（最多 1 秒）收尾。组仍存在（含可能未回收的僵尸）时保守标为不确定；日志 hash=null、log_evidence=unstable，详细失败包暂不共享这些日志。监督程序退出不证明脱组 daemon/远端会话已停止；恢复仍需人工确认。

### rc.4 完成结果绑定与交付整合

保留 `VERIFY_RETRY_READY`，不消耗 worker 尝试来重验。成功执行记录 `worker_completion`（结果路径/哈希、attempt、contract、instruction manifest、源码快照）；首次 verify 和无污染的验证恢复均复核结果身份，验证 operation 固定同一绑定。恢复时新增或变化的规则也会阻断。缺少绑定的旧任务由其原 Runner 完成，不自动迁移。

预算恢复只对 operation/contract 相符、停止已确认且最终日志哈希有效的执行记录按观测时间结算。记录缺失/损坏保守耗尽剩余预算，不计零；身份冲突、最终日志缺失或变化则停止恢复、不退款。保留远端已有 operation.budget 和 log_evidence 字段，不引入平行账本。
