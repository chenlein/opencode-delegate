Mac rc.8 三路线验收：实现与调用记录补包

本补包只整理已有自有脚本、冻结合成输入和本次自有调用记录。没有重新运行模型、子代理、Codex/OpenCode 服务、固定验收检查或原始报告构造器。基准台账仍为 20/20；这次整理使用另授的一个协调会话额度。工程源码和 GitHub 未修改。

文件用途
- prepare.py：原有合成仓库/冻结检查器/台账准备逻辑，只把根目录改为环境参数。保留随机 marker 逻辑，因此未来新运行会产生新 marker/源提交；本次实际固定字节在 frozen-source 和 recorded-inputs/frozen-manifest.json。
- harness.py：原有三路线调用器，包含完整九条协调提示词、冻结契约构造、真实 bounded adapter、app-server JSONL 连接、模型 turn、计时/超时、独立检查、verify/review、用量通知与进程收尾逻辑。只把路径解析改成环境参数，业务函数与门槛未修补或改写。
- publish.py：第一次证据包的原始单批报告构造器（仅路径参数化）。它有针对本批已观测值的固定总结段；只用于审查第一次如何报告，不能拿它给未来实验生成成功结果。本整理轮次未执行它、未改这些结果。
- captured-source：上述三文件的最终本地源捕获副本，仅替换绝对路径。原始字节哈希、脱敏副本哈希和参数化副本哈希见 SOURCE_AND_PROMPT_PROVENANCE.json，逐行差异在 parameterization-diffs。
- prompts：九条真实保存的协调 turn 输入，措辞/标点/空白原样保留，仅替换路径。另有三个 OpenCode prompt，按固定提交中的 PRELUDE + 已保存 packet + 原 JSON 序列化模板重建，packet 摘要与执行记录一致；它们明确标为重建，不冒充原样 prompt 捕获。
- records：三路线真实 argv/权限回读、Skill 动态工具入参、宿主 Runner 调用、实际 policy/packet、增量反馈、固定验证和评审记录、原生 token 通知及最终 Session 累计用量的脱敏投影。无原始私人会话日志。
- helpers/collect_metadata_usage.materialized.py：从上轮已经执行过的 inline 代码整理成文件；这次没有执行。只查询两个本次自有 Session，保留 tokens/cost/model 白名单和响应哈希，不落盘原始 metadata。
- PUBLIC_PRODUCT_DEPENDENCIES.json：Runner 和 execute/terminate_group 等导入来自公开 opencode-delegate 精确提交，文件哈希与直链均固定。按“只打包本次自有源码”的要求没有将公共产品代码重新 vendoring；复核者使用现有精确 checkout 即可。未改该依赖。

路径参数（均由调用者在自己的授权环境提供，不包含任何凭据）
MAC_ACCEPTANCE_ROOT：新的、自有验收输出根目录；默认脚本目录。
MAC_ACCEPTANCE_PRODUCT_CHECKOUT：22595dcfcc0a1880102fcc3a0055caa2558cef2b 的公开 checkout。
MAC_ACCEPTANCE_CODEX_BINARY：既有版本匹配的 Codex 可执行文件。
MAC_ACCEPTANCE_OPENCODE_BINARY：既有版本匹配的 OpenCode 可执行文件。
MAC_ACCEPTANCE_CODEX_RUNTIME_HOME：预先由授权者准备好的独立运行目录；默认输出根目录下 runtime/codex-home。认证准备是外部前置条件，本包不创建/复制认证、不提供认证引用或目标映射，不包含 auth 文件、符号链接、运行数据库或用户配置。
所有其余状态/工作树/临时文件路径由这些参数派生。实际调用环境中的网络传输变量未保存或公开，成功路线沿用当时既有进程传输；没有新转发或系统网络修改。
静态审查可解析脚本，不需要执行。未来重现模型执行必须另有调用授权和额度；这次授权明确不执行。

三个初始化失败与修复（以保存记录为准）
1. 第一次服务在 initialize 等待约 30.013 秒，没有握手响应，尚未发送模型 turn；该次 stderr 为空，完整根因 UNKNOWN。构造失败导致外层未拿到 Server 对象，因此单独核对并停止这个自有进程组，随后确认静止。
2. 后续启动保留约 30.214 秒失败；stderr 明确显示 SQLite state backfill 正在运行，等待后仍为 running。曾调整为已安装的真实 Mach-O CLI、初始化通知顺序，并加构造失败自动收尾；这些调整没有自行证明是根因修复。
3. 改为独立运行 home 后仍复用了先前的自有 SQLite 目录，约 30.151 秒再次等回填失败。随后把 sqlite_home 指到新 home 下的全新 state 目录，并移除继承的宿主连接/线程标识变量；握手终于成功。成功环境禁用 memories、项目环境文档、插件/应用和宿主 skill 发现。不声称已经检查内部回填代码是否曾打开其他文件。
握手成功后另有一次独立传输失败：先前 clean_env 清掉既有代理变量，直连模型端点超时，约 80.139 秒收尾。零凭证的连通性检查证明既有进程传输可达而直连不可达；后续 clean_env 保留原有传输变量并成功。不修改全局配置、不搭建转发。该失败的远端请求结果/用量/计费 UNKNOWN，不当成零成本。
成功路线的实际 argv、原生 sandbox 回读与原始记录哈希均在 records 中。历史失败完整源代码快照未保存，没有伪造历史源哈希。当前 final harness 的 child-subscription 分支在 direct 完成后才加入，但三条成功路线均未触发该分支（实际 native 通知是 subAgentActivity 与 wait），已单独标注。

bounded adapter 与沙箱边界
三路线 Codex 回读均为 workspaceWrite、networkAccess=false、approvalPolicy=never，runtimeWorkspaceRoots 只含本路线合成 fixture；不是 danger-full-access。模型文件工具在此沙箱内工作。
Skill 协调者调用动态工具 delegate_action；真正执行的是宿主 harness 的 DelegateTool.__call__，不是在 Codex shell 沙箱内执行 OpenCode。宿主按固定 case/action 白名单调用未修改 Runner，冻结契约/检查器、固定 task/session，反馈/评审只落在自有目录。宿主调用本身有独立进程组和 95 秒 execute 上限；OpenCode 任务自身有 45 秒/累计预算和原生工具权限。
因此 Codex 的 network=false 不能约束这个显式宿主适配器的网络或文件访问；其边界是已授权的宿主进程、适配器白名单、可信 Runner/固定检查，以及 OpenCode 的原生工具权限。worktree 与工具权限不是 OS 沙箱。没有关闭 Codex 沙箱，也不能把宿主适配器说成受同一沙箱限制的内置工具。

计时与用量
每条路线用同一 monotonic 边界：app-server 启动前至最后独立检查/审查/本地进程收尾。共享 fixture 准备、外层协调和失败尝试另列；Skill 包含读文档、两个托管任务初始化与适配器回复开销。不得据此泛化速度或成本优劣。
turn() 的 75 秒期限在消息循环检查；同步 host adapter 调用可能在其中阻塞，且另有 interrupt/cleanup，所以这不是不可超过的全流程 75 秒硬上限。失败网络尝试实测 80.139 秒已保留。
Codex thread/tokenUsage/updated 的每线程最新累计 total 覆盖旧值，最后按协调者/child 分别计一次，不把 last 或每条累计通知累加。原生 child 用量通知确实存在。OpenCode worker-result 事件用量标为 partial；后来按已建立的 GET /api/session/<本次自有 ID> 路由取两个 Session 最终累计，各只计一次，fix 续跑不重复计整个 Session。代码和原通知均已提供。
provider 请求数、失败传输用量、外层 Mac/dot 协调用量、真实账单、OpenCode default 实际 reasoning effort 与后台模型快照仍 UNKNOWN；native cost 字段不是账单，不算字符 token 或节省比例。

观测限制与未修补事项
原生子代理的实际转发 prompt 参数和 fork-context 标志没有在此 app-server 通知流中暴露；九条根提示词和子代理 model/effort/三轮活动可复核，缺失项明确 UNKNOWN，未从期望要求倒推出实际参数。也未读取受限旧会话目录去补日志。
Skill harness 的 readonly_verified 快速谓词检查 inspect 输出，里面也包含源文本，单凭它不足以证明 worker 的 claim。上轮最终独立复核另外核对了 worker-result.result 内的准确 marker/引用；本包保留原实现和该已有复核，没有在整理中修补谓词或制造新测试结果。
八类旧协调行为评测未重跑，新的真实超时恢复实验也未追加。旧证据保持原身份。无新模型或子代理，无新验收状态。原先 21 个自有进程组已停止、临时登录引用已移除、全局配置未变的记录原样附入；本轮没有重新开服务检查。

本补包不裁定 Issue 关闭，也不接管最终工程审查；由 dot 用上述可复核范围独立决定。
