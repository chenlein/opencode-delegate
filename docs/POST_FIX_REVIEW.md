# A01–A10 修复后复审 — 2.0.1-rc.3

日期：2026-10-30。结论：本轮明确反例已修复且回归通过；保持受监督候选版，不是稳定/真实模型认证版。

## 1. 恢复现场与源码身份

上次会话提示失败，不代表 GitHub 写入失败。重新读取 `main` 确认已存在 rc.2 修复提交 `d6b9c3a3286d74376ffc38f88a98aaf26a51275a`，因此没有重放或覆盖这份提交。聊天中断本身缺少系统日志，不能断言它与 CI 失败有因果关系。

rc.2 的 [CI #2](https://github.com/chenlein/opencode-delegate/actions/runs/41051700186) 中，146 项 Runner 在全部矩阵通过；三个 Linux 任务成功，两个 macOS 任务在安装器测试失败。日志定位为 `test_a08_legal_external_backup_is_supported` 比较了 `/var/...` 与已规范化的 `/private/var/...` 路径。产品安装器本身已规范化路径，修复的是测试断言，不是放宽产品安全边界。

提交 `2270ef1008f635d965a242d6231ba00e48b8985b` 修正断言、增加父目录别名正向用例、保存 CI 的精确 tracked-source 归档；[CI #3](https://github.com/chenlein/opencode-delegate/actions/runs/41056726866) 五个任务均成功（146 Runner + 15 安装）。下载源码归档后校验 SHA-256，并重建 Git tree，结果精确等于 `0158605685352b9bbd338e20fcc90080e8b5976f`。

rc.3 在这个受核对基线上新增以下复审及 B01 修复。发布内容身份：

- `scripts/delegate.py` SHA-256：`93737405a74bd399498cac696566b7f8e5c733f36fcd41c03b2b799944bcc244`。
- `MANIFEST.json` SHA-256：`dd78e8b58cfe24fadf61607468902e34a77e99da69a3855c70f3bf4018b9bd12`；覆盖 23 个安装输入，包括本轮新增测试。
- 本地受测操作系统为 Linux，Python 3.13.5；Git 2.47.3。没有真实 OpenCode/GPT 调用，没有读取或修改用户 Mac。

## 2. A01–A10 复查结论

| ID | 修复后检查 | 判断 |
|---|---|---|
| A01 | 恢复绑定原 run/verify 阶段及起始快照；测试污染不能洗成合法实现；合法产物可恢复 | 原回归通过；补充报告写失败、检查后状态写失败两个场景通过 |
| A02 | PREPARING 先于目录创建，保存尝试身份；中断后不覆盖原尝试，也不盲目重复执行 | mkdir/marker/packet/policy/RUNNING/PID 反例通过 |
| A03 | 覆盖 AGENTS.override.md、全局与自定义规则；权限生成拒绝大小写变体 | 程序级/规则模拟通过，真实 CLI 生效仍属 F05/F10 |
| A04 | review/memory/export 再查规则清单；新来源及已知来源漂移均阻断 | 原回归通过；验证后新增全局 override 的补充用例通过 |
| A05 | V1 保留匹配映射顺序；V2 保留数组顺序但忽略单条规则键排列 | 原正反对照通过；不取消有意义的权限优先级检查 |
| A06 | 结果归属最终消息；冲突、重放和缺终态拒绝 | 原回归及“最终空消息不得借用前一结果”通过；真实事件夹具仍缺 |
| A07 | CLEANING 意图先提交；已导出结果和清理目标绑定；失败可安全收尾 | 原回归通过；部分删除留下 Git 注册时停止，不自动扩大清理 |
| A08 | 规范化安装/备份目录与别名，保护发现根与发行树 | 15 项安装测试通过；macOS 别名断言已修复 |
| A09 | 无锁读取最后原子提交代，可选扫描遇写锁明确跳过 | 原回归及 VERIFYING 持锁状态查询通过，不宣称实时心跳 |
| A10 | 测试隔离 HOME/XDG/CODEX_HOME；真实规则检查保留 | 原回归通过，未以禁用规则让测试变绿 |

## 3. 复审新发现与处理

### B01 / P2 — 进程启动失败缺少完整执行证据（已修复）

在受测 rc.2 代码中，`execute()` 捕获 `Popen` 的 `OSError` 后提前返回，只包含 `exit_code=127`、`reason=spawn_error` 和错误字符串，没有 `stdout_sha256`、`stderr_sha256`、`elapsed_seconds`。

用故障注入模拟验证程序不存在：独立验证正确进入 NEEDS_FIX，但 `failure --include-details` 因 `KeyError: stdout_sha256` 退出 2；后续 run 生成失败交接包时也受影响。执行器启动失败同样缺少耗时和日志哈希。两条失败测试属于同一个根因，不计为两个独立缺陷。

修复：写入启动错误日志并 flush，所有启动失败结果补齐耗时、退出码、原因和两份日志哈希。它仍是失败，不变成成功；可预览、核实、增量交接。不自动安装缺失命令，不重试执行，不修改冻结验收标准。

覆盖：`test_missing_verifier_preserves_failure_handoff`、`test_missing_worker_records_complete_execution_metadata`。修复前分别 FAIL/ERROR，修复后均通过。

### CI01 / P2 — macOS 路径别名测试误判（已修复）

以规范化后的 HOME 和路径比较实际目录身份；增加 `test_a08_legal_backup_parent_alias_preserves_files`。同时验证旧文件备份内容、新安装内容及别名本身保留。安装越界拒绝条件未减少。

## 4. 新增复审用例与最终测试

`opencode-delegate/scripts/test_postfix_review.py` 新增 8 条边界检查，复用已有临时 Git/模拟执行器夹具，但另写故障路径和断言；这不是第二个真实模型的独立审计。

| 场景 | 修复前 | rc.3 |
|---|---|---|
| 验证程序启动失败仍可预览和发送失败包 | FAIL，缺 stdout_sha256 | 通过 |
| 执行器启动失败保留完整计时/日志身份 | ERROR，缺 elapsed_seconds | 通过 |
| 验证后出现新的全局覆盖规则 | 正确阻断 | 通过 |
| 合法验证产物生成后，报告写入中断 | 保持可恢复 | 通过 |
| 测试改源码后，检查点状态写入中断 | 正确保留违规 | 通过 |
| 清理部分完成而 Git 注册仍在 | 停止，不清理主仓 | 通过 |
| 最终消息为空，不能借用早先结果；合法最终消息正对照 | 正确拒绝/接受 | 通过 |
| 验证持锁时查询提交状态，不谎称已扫描源码 | 正确报告 | 通过 |

本地最终：154/154 Runner、15/15 安装，共 **169/169 通过**；17 个 Python 文件 AST 检查、Shell 语法、Git diff 空白检查和发布 manifest 校验通过。一次串行容器测试被调用时限打断，未计作完成；之后完整按进程隔离重跑并保存全部 154 条结果，安装测试另行完整运行。

复现命令：

```bash
export PYTHONDONTWRITEBYTECODE=1
python3 -m unittest discover -s opencode-delegate/scripts -p 'test_*.py' -v
python3 tools/test_install.py
python3 tools/build_release.py --check
```

最新提交的跨平台结果以 [Actions](https://github.com/chenlein/opencode-delegate/actions) 为准，不从旧提交继承；CI 不调用模型。发布归档不包含本地任务运行日志。

## 5. 未关闭事项与范围

F05/F10/F12/F13/F14/F15 继续由 [Issue #1](https://github.com/chenlein/opencode-delegate/issues/1) 跟踪：真实精确 CLI/模型/权限、规则继承/压缩、真实事件夹具、大仓性能、真实代理对照和双方端到端成本。

本轮确认的新增程序问题 B01 和 CI01 已修复，在已执行的范围内没有新增未修复 P1/P2 程序反例。该陈述不等于没有未知问题；剩余 F05 本身仍是 P1 真实准入缺口。同账号恶意进程、任意不可信测试/插件、OS 级隔离不在此 Runner 的保证内。

复审依据保持与 [官方资料](SOURCES.md) 一致：Skill 按需加载、职责单一，Codex override 规则受保护；OpenCode 的权限顺序依版本区别处理。认证失败不得以扩大权限解决，测试通过不得代替真实模型验证。

## 6. 最终 CI 的测试可移植性复查

提交 `331a3e1` 的 [CI #4](https://github.com/chenlein/opencode-delegate/actions/runs/41059407939) 又发现新增故障注入测试的一处路径别名假设：`test_missing_worker_records_complete_execution_metadata` 用原始字符串匹配可执行文件，而生产适配器使用规范路径；macOS 上 `/var` 与 `/private/var` 不相等，导致注入没有发生、模拟执行器正常执行，测试却期望退出 4。它不证明生产代码把启动失败当成成功。

已将测试匹配改成两边 Path.resolve() 后比较，并在所有平台主动经父目录符号链接调用，确保 Linux 也覆盖这个条件。没有修改生产运行逻辑或减少断言。该修正归入 CI01 测试路径可移植性问题；重新生成 manifest 后，本地完整 154+15 项再次通过。上文 manifest 哈希对应这份最终测试包；Runner 内容哈希不变。最新远端结果必须读取这个后续提交本身，不能引用失败的 CI #4 作为通过证明。
