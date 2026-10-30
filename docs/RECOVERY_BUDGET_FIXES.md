# C01–C03 修复与复审（2.0.1-rc.4）

基线：`c1b166459d217dd6e6f1bac41d8adb886b74c73c`，Git tree `7326478e99782248c700cff20bd3566d5b756b80`。2026-10-30。

本轮修复已确认的三个 P2；不调用真实 OpenCode/GPT、不创建 Codex 会话、不访问用户 Mac。测试使用临时仓库、模拟 CLI、真实本地验证程序和 POSIX 进程信号。三项原反例及两个补充集成/计数用例共 19 项新增测试；不是 19 项真实模型认证。

## C01：验证恢复后可以继续验收

`recover` 按原阶段选择后继状态。验证阶段无源码污染且原入口合法时进入 `VERIFY_RETRY_READY`，保留 worker session/attempt，清空旧验证记录；仅允许重新执行冻结的 verify 计划。新检查通过后仍须逐项 review，不会直接 ACCEPTED。

原 run 阶段恢复仍进入 RECOVERED，需要明确新会话与剩余预算，不能跳过 worker 直接 verify。测试污染、HEAD/index 变化、已登记违规保持拒绝。

主要验收：max_attempts=1，worker 成功，第一次固定测试暂态超时，人工确认停止后 recover → verify → review；最终 ACCEPTED、worker 次数仍为 1，原 worker-result 未改。还覆盖重验继续失败后回到 NEEDS_FIX，以及源码污染负对照。

## C02：崩溃后的预算不是免费额度

运行前将本次允许执行秒数预留并与 PREPARING 操作意图一起持久化。`execution.json` 带 operation_id、contract_sha256；结算固定到该操作的 before_seconds，不能重复加减。

| 证据情况 | 处理 |
|---|---|
| 完整记录、绑定正确且进程组停止已确认 | 按观测耗时结算，释放未使用预留；收尾导致的超时开销也计入 |
| PREPARING/preparing，证明尚未启动 | 确认现场后释放预留，仍不减少尝试次数、不覆盖目录 |
| 已可能启动但记录缺失／停止未确认 | 保守耗尽剩余任务额度，observed_seconds 保持未知 |
| 记录操作 ID 错误、数值非法 | 拒绝恢复，不根据错误证据退款 |
| rc.3 活动运行没有预算预留 | 标明 legacy_unknown，不假定零消耗；保留现场及旧版本 |

`total_execution_seconds` 是预算扣记值，不是精确费用或纯实测耗时；operation.budget 分列 observed_seconds、charged_seconds、settlement status。CLI 进程的启动、信号收尾并不能绝对保证精确到秒的 OS 运行上限；无法确认的已受理任务仍需人工核查。

验收包含：execution.json 写成而最终状态提交失败、恢复提交再次失败、重复结算、没有执行记录、启动前准备失败、旧任务无预留、错误操作记录、NaN/负值，以及实际杀死监督进程后恢复。未知运行不能用原剩余预算再次调用模型。

## C03：同组残留后代完整收尾

统一已知进程组的退出路径：TERM → 最多 2 秒等待 → KILL → 最多 1 秒再次检查。轮询回收直接子进程，不使用无界 wait。正常组长退出后发现同组后代仍记录 descendants_still_running，保持不确定状态，即使最终已终止，也不自动接受产物。

组是否存在仍用保守探测；未回收僵尸可能使停止无法被确认。这时 log_evidence=unstable、stdout/stderr hash=null，详细失败交接不共享这些未固定日志。人工确认停止后恢复并重新验证生成新证据。不同账号、脱离进程组 daemon、远端服务及同账号恶意进程不属于 OS containment 保证。

验收真实 fork：父进程退出 0，子进程保留同组、忽略 TERM、持续写日志。检查发送了 TERM/KILL，返回后不再持续写日志；正常退出对照保留最终哈希。另测超时同一收尾路径、终止未确认，以及不稳定日志暂不共享后重新验证。

## 测试与复审

新增 `test_recovery_budget.py` 19 项；现有两项验证恢复断言改为 VERIFY_RETRY_READY。原 PID 提交失败用例不再期待免费重跑，改为验证未知预算被阻断；其余准备阶段仍可安全续跑，原违规断言没有删除。

最终本地：173 Runner + 15 安装 = 188 项通过；发布 manifest、Python AST、Shell 语法及差异检查通过。最新远端矩阵必须以该提交的 Actions 结果为准，不能沿用 rc.3 的绿色状态。

复审重点：恢复前后阶段不变、worker 次数/结果不变；预算预留与状态一次提交、按 operation ID 恢复重复结算不重复扣记；已知进程组未静止不发布最终哈希。新增快照计数测试确认正常两检查任务到 ACCEPTED 为 N+6 次，到导出/清理为 N+9 次；只验证次数，不证明大仓耗时或 token 收益。

在本轮已执行范围内没有保留新的未修复程序反例；不等于全系统无缺陷。F05/F10/F12/F13/F14/F15 继续开放。参考 [比较核对](COMPARISON_RECHECK.md) 与 [真实认证计划](LIVE_VALIDATION.md)。

```bash
export PYTHONDONTWRITEBYTECODE=1
python3 -m unittest discover -s opencode-delegate/scripts -p 'test_*.py' -v
python3 tools/test_install.py
python3 tools/build_release.py --check
```
