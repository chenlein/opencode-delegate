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
