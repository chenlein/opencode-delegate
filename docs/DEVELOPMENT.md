# 开发与验证

从仓库根目录执行，不需要 API Key，不调用模型：

```bash
export PYTHONDONTWRITEBYTECODE=1
python3 -m unittest discover -s opencode-delegate/scripts -p 'test_*.py' -v
python3 tools/test_install.py
python3 tools/test_real_event_corpus.py
python3 tools/check_real_events.py
python3 tools/test_release_evidence.py
python3 tools/build_release.py --check
```

rc.8 整体审查基线包含 236 项 Runner、16 项安装、6 项事件语料完整性、6 项发行证据测试，合计 264 项离线测试；另有 26 项事件回放（13 原生、13 明确派生）。回放不等于 26 次模型任务，离线测试不能代替真实 CLI 认证。详见 [整体审查](FINAL_REVIEW_RC8.md)。

CI 覆盖 Ubuntu Python 3.9/3.11/3.13 和 macOS Python 3.11/3.13；是否通过必须查看对应提交的 Actions，不能继承历史结果。

## 构建发行包

```bash
export PYTHONDONTWRITEBYTECODE=1
# 仅修改安装输入后才重新生成 MANIFEST，并审查差异。
python3 tools/build_release.py
python3 tools/build_release.py --check --output /absolute/new-release.zip
```

输出路径必须尚不存在。构建器校验安装清单、事件语料和经审查的嵌套证据，不打包用户任务日志或凭证。仅修改 README/docs 时不需要重写安装输入清单。

## 贡献约定

- 先明确问题、复现与验收条件，再提交最小修改及回归测试。
- 不通过放宽权限、跳过固定检查或修改原测试预期掩盖失败。
- 文档区分当前使用说明、版本变化和历史证据；不要在 README 累加开发流水。
- 不提交用户源码、凭证、私有路径或原始会话日志；公开仓库尚未指定开源许可证。

历史审查与修复记录保留在 docs 中。它们按记录时点解释，不覆盖当前 [验收裁定](ISSUE1_ACCEPTANCE_DECISION.md)。
