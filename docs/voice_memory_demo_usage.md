# Voice Memory Demo Usage

## 一键启动

```powershell
cd C:\Users\48137\Desktop\project_serina_pro\project_serina
.\scripts\run_voice_memory_demo.ps1
```

默认是手动模式：按 Enter 录一轮语音，等待 ASR、LLM、TTS 完成后继续下一轮。

常用参数：

```powershell
.\scripts\run_voice_memory_demo.ps1 -DryRun
.\scripts\run_voice_memory_demo.ps1 -Manual
.\scripts\run_voice_memory_demo.ps1 -AutoListen
.\scripts\run_voice_memory_demo.ps1 -NoTTS
.\scripts\run_voice_memory_demo.ps1 -SkipServices
.\scripts\run_voice_memory_demo.ps1 -ResetMemory
```

`-DryRun` 只检查路径和打印命令，不启动服务，不删除记忆。`-NoTTS` 会跳过 GPT-SoVITS 启动并向 `main_voice.py` 传入 `--no-tts`，适合先排查 ASR、LLM 和记忆主链路。`-ResetMemory` 只删除 `data/serina.db*`，会做项目根目录校验。

## 前置条件

- Windows PowerShell。
- Python 3.12 可通过 `py -3.12` 调用。
- 已有 ffmpeg、麦克风、扬声器。
- 同级目录存在 `my-neuro`：

```text
C:\Users\48137\Desktop\project_serina_pro
  my-neuro
  project_serina
```

- my-neuro ASR：`my-neuro/full-hub/asr_api.py`，端口 `1000`。
- GPT-SoVITS v2：`my-neuro/full-hub/tts-hub/GPT-SoVITS-Bundle/api_v2.py`，端口 `5000`。
- DeepSeek / LLM key 仍由 `src/config/runtime_config.yaml` 或环境变量提供。

## 启动后会发生什么

1. 打印 ASR、TTS、SQLite 配置摘要。
2. 检查 ASR `http://127.0.0.1:1000/vad/status`。
3. 检查 TTS `http://127.0.0.1:5000/docs`。
4. 缺服务时启动 my-neuro ASR 与 GPT-SoVITS `api_v2.py`。
5. 调用 `/set_sovits_weights?weights_path=role_voice_api/neuro/merge.pth`。
6. 进入 `src/app/main_voice.py --manual`。
7. 按 Enter 录音，ASR 结果进入原文本对话链路。
8. 生成回复后使用 GPT-SoVITS v2 播放。
9. 每轮写入 `conversation_turns`、`memory_entries`、session memory。

如果使用 `-NoTTS`，第 3 到第 5 步的 GPT-SoVITS 检查、启动和权重加载会跳过；助手只输出文字回复，不播放语音。

## 打断 TTS

播放中可以：

- 按 ESC。
- 直接对麦克风说话，RMS 超过 `interrupt_rms_threshold` 时触发。

对应配置在 `src/config/voice_config.yaml`：

```yaml
interrupt_enabled: true
keyboard_interrupt_enabled: true
microphone_interrupt_enabled: true
interrupt_rms_threshold: 600
```

## 验证短期记忆

短期记忆不用新表。现有 `Coordinator.session.history` 会保留最近 `max_history_turns` 轮，默认 `8`，并由 prompt builder 注入 LLM messages。

验证方式：

1. 第一轮说：“我等下要做语音记忆 demo。”
2. 第二轮问：“刚才我说等下要做什么？”
3. 如果回答能承接上一轮，说明短期 history 正常注入。

## 验证长期记忆

查看完整轮次：

```powershell
sqlite3 data\serina.db "select turn_index, source_channel, substr(user_text,1,40), substr(assistant_text,1,40) from conversation_turns order by completed_at desc limit 5;"
```

查看抽取记忆：

```powershell
sqlite3 data\serina.db "select memory_type, memory_class, substr(content,1,80) from memory_entries order by updated_at desc limit 5;"
```

如果没有安装 `sqlite3` CLI，也可以用任意 SQLite browser 打开 `data/serina.db`。

## 常见失败

- ASR 未启动：确认 `http://127.0.0.1:1000/vad/status` 可访问。
- TTS 权重未加载：确认脚本输出 `Loaded SoVITS weights`。
- TTS 路径错误：确认 `my-neuro/full-hub/tts-hub/GPT-SoVITS-Bundle/role_voice_api/neuro/merge.pth` 存在。
- 转译后 CLI 退出或 TTS 干扰排查：先运行 `.\scripts\run_voice_memory_demo.ps1 -NoTTS`，确认 ASR 失败时会显示 `[voice error: transcribing] ...` 并回到下一轮提示。
- 麦克风无输入：运行 `py -3.12 src/app/main_voice.py --list-devices`。
- DeepSeek key 缺失：检查 `src/config/runtime_config.yaml` 或对应环境变量。
- 端口占用：如果 1000 或 5000 已有服务，脚本会优先复用，不会杀掉用户原本开的服务。

## 文字 CLI 回归

语音模式是可选入口，不影响文字 CLI：

```powershell
py -3.12 src/app/main.py
```
