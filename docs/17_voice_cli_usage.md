# 语音 CLI 使用说明

## 当前运行时形态

`src/app/main_voice.py` 是语音入口。它复用与文本 CLI 相同的应用运行时工厂、`Coordinator`、`DialogueEngine`、记忆层、reply guard、scheduler adapter 和 assist-llm 约束。

当前本地流程为：

1. 录制或接受键入输入
2. 通过配置的 ASR provider 转写语音输入
3. 将文本送入 `Coordinator.process_user_message(...)`
4. 通过配置的 TTS 路径合成最终回复
5. 播放音频并发出语音可观测性事件

当前本地配置中 auto-listen 已启用，因此默认行为是持续的"聆听 → 思考 → 说话"循环。使用 `--manual` 切换回旧的按 Enter 录音模式。

## 当前 Provider

- 录音器：`BlockingWavRecorder`，默认带端点检测。
- ASR：`sherpa_onnx_sensevoice`，使用 `asr_model` 指定的本地 SenseVoice 模型路径。
- TTS：`cosyvoice_local`，通过本地运行时 URL 和语音 profiles 路由。
- 播放：`BlockingAudioPlayback`，默认启用流式播放。

配置中保留了旧的 HTTP ASR/TTS 字段作为向前兼容/本地回退设置。当前 API key 值是本地项目配置，不受首轮治理变更影响。

## 配置

语音配置位于 `src/config/voice_config.yaml`。

相关本地运行时配置：

- `src/config/voice_profiles.yaml`
- `src/config/local_tts_runtime.yaml`

重要字段：

- `enabled` —— 是否启用
- `recording_mode` —— 录音模式
- `auto_listen_enabled` —— 是否启用自动监听
- `asr_provider` —— ASR 提供商
- `asr_model` —— ASR 模型路径
- `asr_compute_device` —— 计算设备
- `tts_provider` —— TTS 提供商
- `default_voice_profile_id` —— 默认音色 profile
- `voice_profiles_path` —— profiles 文件路径
- `local_tts_enabled` —— 是否启用本地 TTS
- `primary_tts_runtime_url` —— 主 TTS 运行时 URL
- `clone_tts_runtime_url` —— 克隆 TTS 运行时 URL
- `stream_playback_enabled` —— 是否启用流式播放
- `tts_warmup_on_boot` —— 启动时是否预热 TTS
- `debug_save_input_audio` —— 是否保存输入音频
- `temp_audio_dir` —— 临时音频目录

## 依赖

项目现在有 `pyproject.toml` 并带 `dev` 和 `voice` extras。

运行测试：

```powershell
uv run --with pytest --with pyyaml --with numpy --python 3.12 --no-project pytest -q
```

进行语音运行时开发时，在你实际用于麦克风访问的 Python 环境中安装或运行 voice extras：

```powershell
uv run --extra voice --python 3.12 python src/app/main_voice.py --list-devices
```

在 Windows 上，如果麦克风依赖安装在 Conda 中，请从同一解释器启动 CLI。使用其他启动器可能使已安装的音频包看起来不存在。

## 如何运行

列出设备：

```powershell
python src/app/main_voice.py --list-devices
```

启动默认的自动监听循环：

```powershell
python src/app/main_voice.py
```

强制手动模式：

```powershell
python src/app/main_voice.py --manual
```

按需启动本地 TTS sidecar：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_local_primary_tts.ps1
powershell -ExecutionPolicy Bypass -File scripts/run_local_clone_tts.ps1
```

## 命令与行为

- 手动模式下空输入会录制一轮语音。
- 直接键入的文本同样经过相同的文本 Coordinator，然后被合成语音。
- `/memory ...`、`/trace ...` 和 `/badcase ...` 仍然是键盘命令。
- 语音形式的斜杠命令保持禁用，除非 `allow_spoken_commands: true`。
- `Ctrl+C` 退出自动监听模式。

## 可观测性

语音模式保留现有的 `TurnTrace`，并添加独立的 `voice_*` 事件。语音事件包括来源渠道、音频时长、ASR/TTS provider 名称、延迟、转写预览、播放状态、错误阶段以及下游 coordinator turn id（当可用时）。

典型事件：

- `voice_turn_started` —— 语音轮次开始
- `voice_recording_completed` —— 录音完成
- `voice_transcription_completed` —— 转写完成
- `voice_text_turn_started` —— 文本轮次开始
- `voice_tts_completed` —— TTS 合成完成
- `voice_playback_completed` —— 播放完成
- `voice_turn_completed` —— 语音轮次完成
- `voice_turn_failed` —— 语音轮次失败

## 调试音频文件

当 `debug_save_input_audio` 或 `debug_save_output_audio` 启用时，生成的音频文件写入 `temp_audio_dir`，当前为 `artifacts/voice/tmp`。该目录被视为本地运行时产物，不在默认仓库边界内。

## 当前限制

- 无唤醒词。
- 无 barge-in（播放中打断）。
- 无原始音频记忆。
- 无独立的语音专属场景推断。
- 自定义 `output_device` 仍是为支持设备选择的播放路径预留的。

语音模式不创建第二个记忆存储。它写入与文本 CLI 相同的记忆系统。
