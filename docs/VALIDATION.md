# 2.0.1-rc.7 本机验证

2026-10-31：232 项 Runner + 15 项安装 = 247 项离线测试通过，另有 13/13 事件回放。新增 12 项 session 绑定回归；真实零模型迁移错配被拒绝，安装后新 Sol 任务及绑定校验、独立验收通过。三路线只读与受控验收故障后的同会话恢复也已实际执行。旧 CLI 的配置文件哈希变化保留 UNKNOWN 归因，未回滚或忽略；后续改用应用入口。详见 [rc.7 后续证据](ISSUE1_RC7_EVIDENCE.md)。以下记录保持各自版本身份。

---

# 2.0.1-rc.6 本机真实验证

2026-10-31：220 项 Runner + 15 项安装 = 235 项离线测试通过；另有 13 项原生捕获/明确派生事件回放通过。已安装 31 文件校验一致。实际 Sol 读写、同 session 续跑、原生压缩、超时确认停止与 fresh-session 验收已运行；三路线小修复及八类协调行为有真实记录，也保留初始化阻断和 60.825 秒超限，不把它们记作全部通过。实仓完整扫描被 2 GiB 保护阻断，组件副本的 6 次托管快照和两项只读一致性检查另行限定范围。

完整环境、命令、原始收据哈希、独立用量与剩余门槛见 [rc.6 实际证据](ISSUE1_RC6_EVIDENCE.md) 及其 JSON 摘要。当前 Issue #1 仍开放；以下各节为其标注版本的历史记录，不覆盖本节结果。本轮忽略 GitHub Actions，未将历史 CI 当作本次实测。

---

# 2.0.1-rc.5 本机配置适配验证

日期：2026-10-31。基线 `728c08b0db4cdc1662addd0d022df115598cf36b` 上的本地未提交修订，无推送。Python 3.9.6 / macOS arm64；OpenCode `v2.2.3`，二进制 SHA-256 `0262eaa54be5d18110ff0bfaf0413debb61cb0ec23716f09e97b3ae69f3e1fac`。

- 27 项新增配置适配回归、3 项既有 V2 定向回归通过；完整 Runner 212/212、安装 15/15，共 227 项离线测试通过。定向重跑不重复计入总数。语法编译、发布清单校验及安装文件校验通过。
- 真实 `debug config --standalone` 返回配置来源数组，`debug agents --standalone` 返回最终 Agent。观察到模型规范化、全局/Agent 权限叠加和原生额外拒绝；没有通过简单展开来源数组来声称有效配置已验证。
- 重新安装后的只读策略、限定编辑路径策略、JSONC 来源三项配置预检通过；模型不匹配、formatter 冲突两项正确返回保护性错误码 3。只构造权限配置，未创建 delegate 任务、未执行实际编辑或模型调用；夹具文件哈希不变。
- 使用临时 HOME/XDG 和无凭证的临时工作目录，不修改用户认证/模型配置。两类探测各自使用私有服务、相同环境/目录语义，并前后核对来源和相关文件；不是同一个持久服务实例。原始配置不落盘，只有结构、指纹与通过/拒绝结论进入交付证据。
- 新版 V2 指纹不自动迁移旧任务；来源 formatter 冲突、未知 references、模型 #variant 和未识别结构继续保守阻断。V1 行为及状态 schema 未改。

接口与规则语义依据：[官方 CLI](https://opencode.ai/v2/docs/cli/commands/)、[官方 Agent 合并规则](https://opencode.ai/v2/docs/agents/)、[官方有序权限规则](https://opencode.ai/v2/docs/permissions/)，并以以上本机二进制实际输出核对。本轮只证明无模型配置读取和保护边界；真实 Shell/子代理/网络拒绝、会话事件、恢复、费用和效果认证仍未运行，认证矩阵保持空。

---

# 2.0.1-rc.3 验证与复审记录

日期：2026-10-30。最终本地 154 项 Runner + 15 项安装测试通过，共 **169/169**。新增 8 条修复后边界测试，其中两条复现同一“启动失败证据缺字段”根因；修复后全部通过。AST（17 个 Python 文件）、Shell 语法、Git diff 与 23 个安装输入的 manifest 校验通过。

已核实 rc.2 提交 d6b9c3a 的 CI 两个 macOS 安装任务失败；修正路径别名测试后的 2270ef1 在五个 CI 矩阵全部成功（161 项）。rc.3 的最终跨平台结果必须检查其自身提交，不能沿用前者。详见 [修复后复审](POST_FIX_REVIEW.md)，包括源码身份、故障注入、通过/未通过范围和全部剩余门槛。

仍未进行真实 OpenCode/GPT、用户 Mac、真实大仓性能或模型用量认证。以下保留历史原始记录，不代表新版本/真实模型认证。

---

# 2.0.1-rc.2 验证记录

日期：2026-10-30。基于远端 d4ac2af 的原始文件树 `211c967bcd9f806435fcaaff9ee1a56e9500bef7`，先核对源码再修复。

本地 Linux/Python 3.13.5/Git 2.47.3：146 项 Runner 测试与 14 项安装测试通过，共 160。包含真实临时 Git 仓库、模拟 OpenCode、受控本地测试进程以及文件/状态写入故障注入。发布 manifest 与语法检查另行校验，不算进用例数。真实 OpenCode/GPT 与用户 Mac 没有运行。

CI 使用既有 Ubuntu/macOS 矩阵。结果必须以本次提交的 GitHub Actions 为准；不能把 rc.1 的 CI 通过继承为 rc.2 结果。后续复审见 [修复清单](ROUND2_FIXES.md) 与对应提交记录。

## 历史 rc.1 记录（不代表 rc.2 已完成真实认证）

# 实际验证记录 — 2.0.1-rc.1

日期 2026-10-30；Linux x86_64、Python 3.13.5、Git 2.47.3。

| 项目 | 实际结果 | 方法 |
|---|---|---|
| 原有 Runner 回归 | 70/70 通过 | 真实临时 Git 仓库、模拟 OpenCode，fixture 适配严格协议 |
| 审查驱动反例 | 40/40 通过 | 状态写入故障、范围/证据/交接/升级/导出清理 |
| 安装升级 | 8/8 通过 | 临时 HOME，不修改用户机器；包括旧活动任务保护 |
| Python 静态解析 | 14 个文件通过 | AST 解析，不代表其他 Python 版本运行认证 |
| Shell 语法 | 通过 | bash -n |
| 发布完整性 | 通过 | SHA-256 manifest 检查 |

共 118 个离线测试。模拟执行器故意产生错误，不代表真实 OpenCode 会如此行为，也不构成真实版本认证。最后重新运行的 40 项反例 11.107 秒、8 项安装测试 9.526 秒；时长仅用于定位本次记录，不是性能承诺。

复现无需 OpenCode、网络或凭证：

```bash
export PYTHONDONTWRITEBYTECODE=1
python3 opencode-delegate/scripts/test_delegate.py --jobs 4
python3 opencode-delegate/scripts/test_review_fixes.py
python3 tools/test_install.py
python3 tools/build_release.py --check
```

GitHub Actions 配置 Linux/macOS、Python 3.9/3.11/3.13 离线矩阵。这里记录的是本地容器结果；远端 CI 结果以相应提交的 Actions 状态为准。

## 合成快照测量

1000 个普通文件，每个 4096 字节，共 4096000 字节；连续三次扫描为 0.052365、0.040323、0.038874 秒。运行命令：`python3 tools/benchmark_snapshot.py --files 1000 --bytes 4096`。

这是本容器文件系统的合成快照耗时，不是 Lakehouse 真实大仓、macOS、模型延迟、总成本或提效比例。没有为提速跳过忽略文件和未跟踪文件；仅 3 次样本，不做显著性结论。

## 明确未完成

未安装或调用真实 OpenCode/GPT，未访问用户 Mac，未验证真实 V1/V2 配置输出/权限/事件，未执行实际 Codex 行为对照，未采集双方完整用量费用及用户大仓性能。

精确 CLI 认证矩阵仍为空。剩余 F05/F10/F12/F13/F14/F15 见 [整改状态](REVIEW_STATUS.md) 与 [真实验证方案](LIVE_VALIDATION.md)。

## rc.4：C01–C03（2026-10-30）

新增 19 项验收：验证恢复完整闭环、保守预算与崩溃幂等结算、真实 POSIX 同组子进程收尾、停止未确认的日志策略、正常路径快照计数。该次记录为 173 Runner + 15 安装 = 188 项离线测试。Python AST、Shell 语法、manifest、临时目录安装校验同时检查。见 [RECOVERY_BUDGET_FIXES.md](RECOVERY_BUDGET_FIXES.md)。远端 CI 必须核对本版本提交，不能继承旧提交结果。

跨方案只读源码核对见 [COMPARISON_RECHECK.md](COMPARISON_RECHECK.md)，不属于第三方运行时测试或真实目标版本认证。

## rc.4 交付整合（2026-10-31）

在已发布 `4797128`（188 项）上整合交付中的额外边界保护，不整体覆盖远端代码或删除远端测试。新增 `test_delivery_guards.py` 的 8 项，完整重跑结果为 181/181 Runner + 15/15 安装 = 196/196；发布清单、Python AST、Shell 语法和差异检查通过。此为本轮隔离 Linux 结果；本提交的 Linux/macOS CI 以对应 Actions 运行结果为准，不继承 `4797128` 的 CI 成功。

测试使用 mock CLI、临时 Git 和真实本地验证程序，无真实 OpenCode/GPT 或用户 Mac 访问。精确远端基线、整合取舍、兼容性边界见 [RC4_DELIVERY_INTEGRATION.md](RC4_DELIVERY_INTEGRATION.md)。
