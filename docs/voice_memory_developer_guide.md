# Voice Memory Developer Guide

## 项目目标与当前阶段边界

本阶段目标是快速跑通一个可写进简历的终端 demo：语音输入、语音输出、可打断 TTS、长期记忆落 SQLite。项目仍是 Python-first，不做 Live2D 前端合并，只预留 `AvatarEventBus`。

非目标：

- 不重写原文字聊天。
- 不复制 my-neuro 全部 RAG/MemOS 能力。
- 不在本阶段实现 Live2D 页面。
- 不把外部服务硬编码进业务代码，地址集中写在配置里。

## 快速启动教程

文字 CLI：

```powershell
cd C:\Users\48137\Desktop\project_serina_pro\project_serina
py -3.12 src/app/main.py
```

语音 CLI 一键 demo：

```powershell
cd C:\Users\48137\Desktop\project_serina_pro\project_serina
.\scripts\run_voice_memory_demo.ps1
```

只检查路径与命令：

```powershell
.\scripts\run_voice_memory_demo.ps1 -DryRun
```

只排查 ASR、LLM 和记忆，暂时不启动或播放 TTS：

```powershell
.\scripts\run_voice_memory_demo.ps1 -NoTTS
```

列音频设备：

```powershell
py -3.12 src/app/main_voice.py --list-devices
```

my-neuro ASR 默认服务：

```text
my-neuro/1.ASR.bat
my-neuro/full-hub/asr_api.py
http://127.0.0.1:1000/v1/upload_audio
http://127.0.0.1:1000/vad/status
```

GPT-SoVITS v2 默认服务：

```text
my-neuro/full-hub/tts-hub/GPT-SoVITS-Bundle/api_v2.py
http://127.0.0.1:5000/tts
```

demo 脚本使用：

```powershell
runtime\python.exe api_v2.py -a 127.0.0.1 -p 5000 -c GPT_SoVITS/configs/tts_infer.yaml
```

## 入口文件说明

`src/app/main.py`：

文字终端入口，加载配置，构造 runtime，进入用户输入循环。

`src/app/main_voice.py`：

语音终端入口，负责构造 recorder、ASR provider、speech synthesis service、playback 和 voice controller。

`src/voice/controller.py`：

单轮语音流程编排。录音、ASR、调用 Coordinator、TTS、播放、错误降级都在这里。

`src/voice/voice_loop.py`：

播放期间的 interrupt monitor。监听 ESC 和麦克风 RMS，触发 `AudioPlayback.stop()`。

`src/memory/manager.py`：

记忆门面。负责 retrieve、write、session memory、conversation turn 保存。

`src/llm/gateway.py`：

LLM 调用网关。DialogueEngine 不直接绑定具体 provider。

## 运行原理

文字链路：

```text
main.py
  -> Coordinator.process_user_message()
  -> DialogueEngine.generate_reply()
  -> prompt_builder.build_prompt_package()
  -> LLMGateway.generate()
  -> reply guard / postprocess
  -> MemoryManager.write_turn()
  -> TerminalUIAdapter.display_assistant_message()
```

语音链路：

```text
main_voice.py
  -> AudioRecorder.capture/open_chunk_source
  -> MyNeuroASRProvider.transcribe()
  -> Coordinator.process_user_message(source_channel="voice")
  -> GPTSoVITSv2TTSProvider.synthesize_stream()
  -> BlockingAudioPlayback.play_stream()
```

`main_voice.py --no-tts` 会把本次运行的 `tts_provider` 临时覆盖为 `none`。这不会修改配置文件，适合排查转译阶段异常：ASR 成功后仍进入 Coordinator，助手回复只显示文字。

TTS interrupt：

```text
create InterruptToken
  -> VoiceInterruptMonitor starts
  -> ESC or microphone RMS threshold
  -> token.interrupt(reason)
  -> playback.stop(reason)
  -> current PlayObject.stop()
  -> stream loop stops
```

SQLite memory：

- `conversation_turns`：每轮完整原始对话。
- `memory_entries`：长期事实、偏好、任务。
- `session_memory_entries`：当前 session 的短期连续性候选。
- `session_continuity_entries`：跨 session 摘要。

短期记忆：

- 直接复用 `Coordinator.session.history`。
- `runtime_config.yaml` 的 `max_history_turns` 默认保留最近 8 轮。
- prompt builder 会把最近 history 放进 LLM messages。

## 配置说明

核心 runtime 配置：`src/config/runtime_config.yaml`

- LLM provider/model/key/base URL。
- `max_history_turns`。
- memory 开关和 SQLite 路径。

语音配置：`src/config/voice_config.yaml`

关键字段：

```yaml
asr_provider: myneuro_asr
myneuro_asr_url: http://127.0.0.1:1000/v1/upload_audio

tts_provider: gpt_sovits_v2
gpt_sovits_v2_url: http://127.0.0.1:5000/tts
gpt_sovits_v2_ref_audio_path: role_voice_api/neuro/01.wav
gpt_sovits_v2_prompt_lang: en
gpt_sovits_v2_text_lang: zh
gpt_sovits_v2_streaming_mode: true

interrupt_enabled: true
keyboard_interrupt_enabled: true
microphone_interrupt_enabled: true
interrupt_rms_threshold: 600
```

音色 profile：`src/config/voice_profiles.yaml`

默认 `serina_main` 指向 my-neuro 的 GPT-SoVITS v2 角色音色。

## 常见调试

设备列表：

```powershell
py -3.12 src/app/main_voice.py --list-devices
```

ASR 健康检查：

```powershell
Invoke-WebRequest http://127.0.0.1:1000/vad/status -UseBasicParsing
```

ASR-only smoke：

```powershell
.\scripts\run_voice_memory_demo.ps1 -NoTTS
```

如果 ASR 或转译阶段抛异常，语音 CLI 应显示 `[voice error: transcribing] ...` 并回到下一轮输入提示，而不是退出进程。

TTS 健康检查：

```powershell
Invoke-WebRequest http://127.0.0.1:5000/docs -UseBasicParsing
```

SQLite 检查：

```powershell
sqlite3 data\serina.db ".tables"
```

临时音频：

- 输入临时音频：`artifacts/voice/tmp`
- `debug_save_input_audio: true` 时会保留录音文件。
- `debug_save_output_audio: true` 时会保留 TTS 输出。

日志：

- `runtime_config.yaml` 的 `enable_file_logging` 和 `log_dir` 控制文件日志。

## 扩展教程

替换 ASR：

1. 在 `src/integrations` 新增 client。
2. 在 `src/voice/asr.py` 新增 provider。
3. 在 `build_asr_provider()` 注册 provider name。
4. 在 `voice_config.yaml` 切换 `asr_provider`。
5. 加 fake HTTP server 单测。

替换 TTS：

1. 在 `src/integrations` 新增 client。
2. 在 `src/voice/tts.py` 新增 provider。
3. 实现 `synthesize()`；如果支持分块，实现 `synthesize_stream()`。
4. 在 `build_tts_provider()` 注册。
5. 更新 `voice_profiles.yaml`。

接 MemOS：

当前 `src/integrations/myneuro_memos_client.py` 只是适配点。第一版默认仍写 SQLite。后续可以在 `MemoryManager` 内增加双写或远端同步，但不要让 MemOS 成为文字 CLI 的硬依赖。

接 Live2D：

使用 `src/avatar/event_bus.py` 订阅事件：

```python
bus.subscribe(lambda event: print(event.event_type, event.payload))
```

可先消费：

- `tts_start`
- `tts_interrupt`
- `tts_end`

## 最小贡献流程

1. 小步改动，优先 provider / adapter 边界。
2. 保持 `src/app/main.py` 文字 CLI 可运行。
3. 跑最小测试：

```powershell
py -3.12 -m unittest tests.test_voice_config_loader tests.test_voice_asr tests.test_myneuro_integrations tests.test_audio_player_interrupt tests.test_voice_controller tests.test_memory_store_migration
```

4. demo 改动先跑：

```powershell
.\scripts\run_voice_memory_demo.ps1 -DryRun
```

5. 清理目录只用白名单路径，不写递归通配删除。
