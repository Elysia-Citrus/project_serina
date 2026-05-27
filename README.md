# Project Serina

Project Serina 当前是一个本地桌面 `agent` 原型，文本 CLI 和语音 CLI 复用同一条对话、记忆、回复质量控制主链路。目标不是一次性做成“最强系统”，而是先把人格、记忆、语音输入输出和回归护栏做成可信、克制、可维护的基础设施。

当前已完成的主链路：
- CLI 多轮聊天
- voice CLI、本地 ASR/TTS runtime 接入
- `persona / policy / runtime / voice` 配置
- `Coordinator / DialogueEngine / PromptBuilder / LLMGateway / Provider` 分层
- `profile / episodic / session continuity / startup memory` 记忆链路
- `retrieval -> prompt -> generate -> postprocess -> reply_guard -> write_turn`
- 规则化 memory write / retrieve
- reply guard、guard retry、受控 assist-llm lane
- pytest regression eval + unittest smoke tests
- `/memory ...` review / manual override 命令
- `/trace ...` 和 `/badcase ...` 开发命令
- explicit follow-up 的 scheduler adapter

仓库边界：
- `src/`、`tests/`、`docs/`、`scripts/`、`evals/` 是主项目维护边界。
- `memory_selection/` 和 `Neuro/` 是本地外部参考资料，不属于默认测试、打包或依赖扫描范围。
- `artifacts/`、`data/`、`.tmp_test_workspaces/` 是本地运行/测试产物位置。
- 当前 API key 保持本地配置形态；如果未来上传远端，再单独做密钥迁移。

推荐先看这些文档：
- [docs/README_docs_index.md](docs/README_docs_index.md)
- [docs/05_architecture.md](docs/05_architecture.md)
- [docs/08_eval_framework_guide.md](docs/08_eval_framework_guide.md)
- [docs/09_memory_reply_guard_v0.1.md](docs/09_memory_reply_guard_v0.1.md)
- [docs/10_memory_reply_guard_v0.2.md](docs/10_memory_reply_guard_v0.2.md)
- [docs/11_reply_guard_regression_hardening.md](docs/11_reply_guard_regression_hardening.md)
- [docs/13_assist_llm_lane.md](docs/13_assist_llm_lane.md)
- [docs/17_voice_cli_usage.md](docs/17_voice_cli_usage.md)

依赖入口：

```powershell
uv run --extra dev --python 3.12 pytest -q
```

如果继续使用无项目模式：

```powershell
uv run --with pytest --with pyyaml --with numpy --python 3.12 --no-project pytest -q
```

常用测试命令：

```powershell
uv run --with pytest --with pyyaml --with numpy --python 3.12 --no-project pytest -q
uv run --python 3.12 --no-project python -m unittest discover -s tests -v
```
