# rc.4 合并复核与提交收尾

日期：2026-10-31。此次以提交 `9b3e090a65f47103c42b4efccf80f5f14f33d6d0` 为基线，保留其运行时代码，不重放基于 `c1b1664` 的旧补丁。

## 输入身份

| 输入 | 身份 | 用途 |
|---|---|---|
| 远端 main | `9b3e090a65f47103c42b4efccf80f5f14f33d6d0` | 最终合并基线，196 项离线用例 |
| 远端 tree | `123a05d4dcd49065903aa86beef72e4d5e4f112f` | 从 GitHub Actions 源码归档重建后完全匹配 |
| 远端源码归档 SHA-256 | `d385a1472da647fc20a69a7235b69888d773e7ea8d816ab6c06ba1d8ccd6fd16` | CI #7 的精确源码归档，不含凭证或任务现场 |
| 旧 rc.4 交付完整包 SHA-256 | `c50346c575e5582333ac9866f6ae43c595fc4df3c63ce225ae228006d927ea4d` | 191 项用例的另一实现，仅作比较输入 |

不能仅比较版本号或用例数量决定覆盖。`4797128` 已发布 C01–C03 的一种实现；`9b3e090` 又合入成功结果绑定与恢复证据检查。此次再次逐文件比较两份源树，确认核心保护已存在；保留全部 11 个运行时 Python 模块及原有测试文件的原始字节。只新增测试、更新 README、发布清单及本记录。

## 合并取舍

| 维度 | 保留的远端实现 | 不采用的旧包覆盖方式 |
|---|---|---|
| 验证恢复 | `VERIFY_RETRY_READY`；保留完成结果和会话，重跑冻结检查后再裁决 | 不退回旧包的通用 `AWAITING_VERIFY` 恢复状态 |
| 时间预算 | `operation.budget` 预留和幂等结算；操作/契约绑定；未知消耗保守耗尽剩余额度 | 不替换成另一套 `execution_reservations` 账本 |
| 可信完成身份 | `completion_binding.py`；verify/recover 检查原 worker 结果与规则清单 | 不把同名版本视为任意旧任务均可自动迁移 |
| 恢复证据 | 已停止记录必须匹配最终日志；损坏记录按未知处理；身份错配拒绝 | 不用较宽松的退款或证据接受规则覆盖原门禁 |
| 进程收尾 | 有界 TERM/wait/KILL/wait；`process_group_quiescent` 和 `log_evidence` | 不换字段、不在未确认停止时发布最终日志哈希 |

因此，这个收尾提交没有新的运行时行为修改；新增测试用于锁定合并后仍应保持的边界，不声称再次修复一个已在 main 修复的问题。

## 新增四项回归

文件：`opencode-delegate/scripts/test_delivery_reconciliation.py`。使用现有上游接口，不依赖旧包的内部字段。

1. 未确认停止的进程组只能把测得时间视为下界，保守扣完剩余任务额度；重复结算不重复扣记。含已确认停止可按实测结算的正对照。
2. 实测耗时超过单次预留乃至任务额度时，保留实际已观测的超额，不能截断成较小数值。含重复结算检查。
3. 执行操作已持久化但未结算时，不能再次启动 worker；恢复没有完成记录的已启动任务后耗尽预算，即使显式提供新会话检查点也不能绕过。确认执行次数和原状态不被失败重入改写。
4. 对进程组发送信号遭遇 PermissionError 时，组长退出不代表整个组停止；必须保留未确认状态与错误。信号完全模拟，虚拟 PID 不会到达操作系统。

这四项在提交前均通过，没有降低权限、删除断言或跳过平台。对于未知时长，预算只是后续准入控制，不能追溯性地强制已经失去监督的 worker 停止；也不等于 token 或账单统计。

## 本地验证

本轮使用隔离 Linux x86_64、Python 3.13.5、Git 2.47.3。测试为临时 Git、模拟 OpenCode 和受控本地验证/进程，不调用真实模型，不访问用户 Mac。

| 验证 | 结果 |
|---|---|
| 未修改基线完整重跑 | 181/181 Runner、15/15 安装，196/196 |
| 合并收尾完整重跑 | 185/185 Runner、15/15 安装，200/200 |
| 新增定向回归 | 4/4（包含在上面的 185 项中，不重复计数） |
| 发布输入清单 | 29 项输入 SHA-256 校验通过 |
| Python AST、Shell 语法、Git diff --check | 通过 |

```bash
export PYTHONDONTWRITEBYTECODE=1
python3 -m unittest discover -s opencode-delegate/scripts -p 'test_*.py' -v
python3 tools/test_install.py
python3 tools/build_release.py --check
```

基线 [CI #7](https://github.com/chenlein/opencode-delegate/actions/runs/41146861368) 的五个矩阵已核对通过，但不替代本收尾提交的 CI。PR 的精确提交和跨平台结果以其 Checks 为准。

## 交付范围

仍为 `2.0.1-rc.4` 受监督候选版；此次不改变任务状态 schema，不引入 profiles、MCP 或自动权限。新旧同版本归档并非同一源码身份，使用提交 SHA 和 MANIFEST.json 核对安装内容，不盲目迁移活动任务。

真实 CLI/规则/事件、大仓性能、三路线行为对照及双方总成本仍由 Issue #1 跟踪。本次不关闭这些准入项，也不声称真实 OpenCode 兼容或已经节省 token。
