# rc.4 交付整合记录

日期：2026-10-31。提交基线：`4797128fea64830956480aac4b38408876e5a820`，tree `ee37c7104b0b5d355d7f2698c8597354c69e89da`。

## 为什么不是直接应用旧补丁

提交前发现 main 已经包含 C01–C03 的另一版 rc.4 修复（188 项测试）。先前交付包以 c1b1664 为基线（191 项），两者状态字段、账本实现和测试覆盖并不完全相同。因此保留远端已提交代码、文档和所有既有测试，在其上补入交付包中尚缺的证据保护，不重写历史，不盲目覆盖整仓。

## 保留与补入

- 保留 `VERIFY_RETRY_READY`、operation.budget 的启动前预留/幂等结算、process_group_quiescent/log_evidence 的进程和日志接口。
- 补入 `worker_completion` 固定成功结果路径、哈希、attempt、契约、规则清单和源码快照；verify 和验证恢复检查同一完成身份。下一次 worker 尝试清除旧绑定。
- 验证恢复复查规则来源。规则/结果漂移不会获得重验许可；源码污染仍由原违规状态阻断。
- 预算恢复对已确认停止的记录检查两份最终日志哈希；日志漂移不退款。损坏记录保持原样并保守耗尽剩余任务额度，重复恢复不重复计账。原 operation/contract 错配拒绝逻辑不放宽。
- 不替换进程控制模块，不改模型权限，不加入 profiles/MCP，不将 CLI 退出 0 当作 ACCEPTED。

## 验证

新增 8 项交付整合回归，保留既有全部测试：181 Runner + 15 安装，共 196 项。覆盖首次验证前结果漂移、验证恢复结果漂移、新规则、缺失旧绑定、两次验证中断后最后一次 worker 仍可验收、最终日志变化、损坏执行记录、记录写入失败。正常记录仍可结算，不稳定日志与未知消耗不当成零。

运行命令：

```bash
export PYTHONDONTWRITEBYTECODE=1
python3 -m unittest discover -s opencode-delegate/scripts -p 'test_*.py' -v
python3 tools/test_install.py
python3 tools/build_release.py --check
```

在本次隔离 Linux 中完整重跑通过，并执行发布清单、AST、Shell、差异检查。无真实模型调用、无用户 Mac 访问。新版远端 CI 必须查询本次确切提交；旧 CI 不能替代。真实 OpenCode/权限/事件/大仓/行为和成本门槛仍由 Issue #1 跟踪。

## 兼容边界

版本仍为受监督候选版 2.0.1-rc.4，不宣称稳定认证。旧活动任务即使状态 schema 同为 2，也不能凭空补建 worker_completion；保持原 Runner 与证据，完成或恢复后再按本修订建立新任务。时间预算不是 token/费用统计；信号收尾不是 OS 沙箱。

先前下载包与本次整合源码不是逐字相同版本，今后以本提交及其发布清单为准。比较资料沿用仓库 COMPARISON_RECHECK.md，避免新增重复的平行报告。
