# rc.8：原生 Session 权限覆盖修复

2026-10-31。基于 PR #3 的 `b572330799355c98aa1f0d0b3391465f973ab0f5`。
状态：权限绑定缺口已修复并验证；Issue #1 全部发布准入尚未完成。

## 原因与修复边界

OpenCode V2 会把 session.permissions 追加到 Agent 规则之后，最后匹配项生效。因此即便配置探测确认 Agent 的 shell deny，旧 Session 的 shell allow 仍能使权限判定为 allow。rc.7 只核对 Session 的 ID、目录、模型及 Agent，未检查该覆盖层。

rc.8 在共享 `check_session_binding` 中校验：权限字段缺省或空数组可接受；非空数组只接受 action/resource 字符串及 effect=deny 的精确三字段规则。allow、ask、null、错误类型和未知规则字段一律拒绝。不会清除原 Session 的权限来强行通过。摘要仅保存规则哈希。

已有续跑在预算预留与模型启动前检查；完成结果写入前再次检查。首个新 Session 的检查仍是执行后检查。此修复不是 OS 沙箱，也不能阻止有相同系统权限的其他进程在检查与执行之间篡改原生数据库。默认信任宿主与协调者，不把被恶意控制的宿主作为已隔离环境。

## 源码依据

- [v2.2.5 Session.Info](https://github.com/anomalyco/opencode/blob/v2.2.5/packages/schema/src/session.ts)：permissions 是可选 Ruleset。
- [v2.2.5 permission.ts](https://github.com/anomalyco/opencode/blob/v2.2.5/packages/core/src/permission.ts)：configured 合并 Agent、Session；evaluate 使用最后匹配项。已配置 deny 先于 saved permissions 检查。
- [v2.2.5 API](https://github.com/anomalyco/opencode/blob/v2.2.5/packages/protocol/src/groups/permission.ts)：permission.create 是原生判定接口，不是工具主体执行。

## 验证

- 修复前新增用例复现：权限 allow/ask/畸形结构未被拒绝，正常绑定未包含权限摘要。修复后 16 个 session binding 测试通过，包含 4 个新增测试方法及多个反例。
- 续跑反例：已有 session allow 导致拒绝，状态、预算、执行日志均保持原样，不产生第二次 attempt。
- 运行后反例：session allow 导致 PROTOCOL_ERROR，不生成 worker-result，不接受完成声明。
- 真实 Linux x86_64 / OpenCode 2.2.5：缺省、空数组、追加 deny 均得到原生 shell deny 且通过绑定；shell allow 得到原生 allow，但被新绑定门禁拒绝。原生 token/cost 全为零，权限不被修改。
- 原生收据：[SESSION_PERMISSION_EVIDENCE.json](SESSION_PERMISSION_EVIDENCE.json)。仅含无秘密摘要，不含原生会话日志、凭证、源码路径。

复现命令（显式指定已安装官方二进制，不使用会注入凭证的包装器）：

```sh
PYTHONDONTWRITEBYTECODE=1 python tools/probe_session_permissions.py --opencode /absolute/path/to/native/opencode
python -m unittest discover -s opencode-delegate/scripts -p 'test_*.py' -v
python tools/test_install.py
python tools/check_real_events.py
python tools/build_release.py --check
```

探测在新建临时 HOME/XDG 中只创建测试 Session 和调用权限判定 API，不启动模型、工具主体或后台共享服务。它不替代 F05 的实际工具链权限验收，也不把本机 Linux 结果推广到 macOS/ARM64。

## 本地最终回归

- 236 Runner 测试通过（63.526 秒）；15 安装器测试通过；13 事件回放通过（5 原生、8 派生）。
- manifest、Python AST 语法和 diff whitespace 检查通过。
- 安装预览首次目标目录命名不符合安装器要求，被保护性拒绝；改为末级目录 `opencode-delegate` 后通过。未执行正式安装。
- 上述为本机 Linux 检查，不继承旧提交或其他平台 CI 结果。

## Issue #1 关闭差距

| 条目 | 本轮贡献 | 仍需证据 |
|---|---|---|
| F05 | 修复并验证 Session 权限覆盖门禁 | 精确最终版本的真实读写、拒绝、续跑、超时恢复与验收 |
| F10 | 保留已有来源、目录、模型与 Agent 绑定 | 最终版本真实规则继承、变化与压缩覆盖 |
| F12 | 原有 5 原生捕获 + 8 派生故障继续回放 | 明确各事件来源与最终运行时覆盖，派生不能冒充原生 |
| F13 | 保留已有真实组件扫描与根目录阻断证据 | 代表性大仓完整生命周期及多检查测量 |
| F14 | 复核 rc.6/rc.7 已有同基线路线摘要 | 同条件完整时钟及独立原始证据；不自行启动被禁止的 Codex 对照 |
| F15 | 原生零模型探测明确不计作成本对照 | 协调者与执行器实际用量和总时间；不可见项保持 UNKNOWN |

本轮独立按源代码追踪、恶意输入及合法输入复查，没有把实现者自检称为独立第三方审查。未合并 PR、未关闭 Issue、未发布稳定认证声明。
