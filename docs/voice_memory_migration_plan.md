# Voice + Memory Demo Migration Plan

> **状态：此方案已执行完毕。** 当前实现见 `src/app/main_voice.py`、`src/voice/` 子系统和 `src/memory/` 模块。本文档保留为实现记录，供追溯方案设计意图。

## 当前项目结构分析

本项目当前主体是 Python 桌面/终端 agent。文字 CLI 主入口是 `src/app/main.py`，语音 CLI 可选入口是 `src/app/main_voice.py`。本阶段没有合并前端页面，Live2D 只保留事件总线。

现有文字数据流：

```text
src/app/main.py
  -> Coordinator.process_user_message()
  -> DialogueEngine.generate_reply()
  -> build_prompt_package()
  -> LLMGateway / provider
  -> reply guard / postprocess
  -> MemoryManager.write_turn()
  -> terminal output
```

现有语音数据流：

```text
src/app/main_voice.py
  -> recorder
  -> ASR provider
  -> Coordinator.process_user_message()
  -> SpeechSynthesisService
  -> TTS provider
  -> AudioPlayback
```

关键位置：

- 主入口：`src/app/main.py`，可选语音入口 `src/app/main_voice.py`。
- 对话主循环：`src/app/main.py` 的终端循环，语音循环在 `src/app/main_voice.py`。
- LLM 调用位置：`src/llm/gateway.py` 及 provider。
- prompt 构造位置：`src/dialogue/prompt_builder.py`。
- 短期记忆：`Coordinator.session.history`，由 `max_history_turns` 控制最近多轮注入。
- 当前 STT：已有 ASR provider 框架，已新增 `myneuro_asr`。
- 当前 SQLite：`src/memory/store.py`，默认 `data/serina.db`。
- 当前 memory 模块：`src/memory/manager.py`、`reader.py`、`writer.py`、`store.py`。

## 新增模块

语音模块：

- `src/voice/stt_service.py`
- `src/voice/tts_service.py`
- `src/voice/audio_player.py`
- `src/voice/vad.py`
- `src/voice/voice_loop.py`

记忆模块：

- `src/memory/types.py`
- `src/memory/embedding.py`
- `src/memory/retriever.py`
- `src/memory/prompt_injector.py`
- `src/memory/schema.sql`

集成模块：

- `src/integrations/myneuro_asr_client.py`
- `src/integrations/myneuro_gpt_sovits_v2_client.py`
- `src/integrations/myneuro_memos_client.py`

Avatar 预留：

- `src/avatar/event_bus.py`

脚本与文档：

- `scripts/run_voice_memory_demo.ps1`
- `docs/voice_memory_developer_guide.md`
- `docs/voice_memory_demo_usage.md`

## 需要改动的现有文件

- `src/config/models.py`：扩展 voice 配置字段。
- `src/config/loader.py`：加载 my-neuro ASR、GPT-SoVITS v2、MemOS URL、interrupt 配置。
- `src/config/voice_config.yaml`：默认切到 `myneuro_asr` 与 `gpt_sovits_v2`。
- `src/config/voice_profiles.yaml`：默认角色音色指向 GPT-SoVITS v2 clone profile。
- `src/voice/asr.py`：注册 `MyNeuroASRProvider`。
- `src/voice/tts.py`：注册 `GPTSoVITSv2TTSProvider`。
- `src/voice/playback.py`：支持 `stop()` 与 interrupt token。
- `src/voice/controller.py`：播放期间启动 interrupt monitor，向 Coordinator 传入语音来源元数据。
- `src/app/coordinator.py`：保存完整 `conversation_turns`，但保持原文字 CLI 调用兼容。
- `src/memory/models.py`：新增 `ConversationTurn` 与语音/来源元数据字段。
- `src/memory/store.py`：schema v6，新增 `conversation_turns` 表。
- `src/memory/manager.py`：新增 `record_conversation_turn()`。

## STT / TTS / Memory 接口设计

STT：

```python
class STTService(Protocol):
    def transcribe(self, recorded_audio: RecordedAudio, *, language: str) -> ASRResult: ...
```

默认实现 `myneuro_asr`：

- URL：`http://127.0.0.1:1000/v1/upload_audio`
- 请求：multipart，字段名 `file`
- 响应：解析 `status` 与 `text`

TTS：

```python
class TTSService(Protocol):
    def synthesize_stream(
        self,
        request: TTSRequest,
        *,
        interrupt_token: InterruptToken | None = None,
    ) -> Iterable[AudioChunkLike]: ...
```

默认实现 `gpt_sovits_v2`：

- URL：`http://127.0.0.1:5000/tts`
- 服务：GPT-SoVITS-Bundle `api_v2.py`
- 参数：`text`、`text_lang`、`ref_audio_path`、`prompt_text`、`prompt_lang`、`text_split_method`、`batch_size`、`media_type`、`streaming_mode`
- 音色权重：demo 脚本调用 `/set_sovits_weights?weights_path=role_voice_api/neuro/merge.pth`

Memory：

```python
class MemoryStore:
    def save_conversation_turn(turn: ConversationTurn) -> str: ...

class MemoryRetriever:
    def retrieve(query: str, session_id: str | None, limit: int) -> list[RetrievedMemory]: ...

class MemoryWriter:
    def extract_and_write(turn: MemoryTurnInput) -> MemoryWriteResult: ...
```

当前实际落点：

- 完整轮次：`conversation_turns`
- 长期事实/偏好/任务：`memory_entries`
- 当前 session 连续性：`session_memory_entries`
- 跨 session 摘要：`session_continuity_entries`

Avatar：

```python
class AvatarEventBus:
    def emit(event_type: str, payload: dict[str, object] | None = None) -> None: ...
```

本阶段只发 `tts_start`、`tts_interrupt`、`tts_end` 等事件，不接 Live2D。

## 可打断 TTS 事件流

```text
assistant reply ready
  -> synthesize_reply_stream()
  -> create InterruptToken
  -> AvatarEventBus.emit("tts_start")
  -> VoiceInterruptMonitor starts
      -> keyboard watcher: ESC
      -> microphone watcher: RMS >= interrupt_rms_threshold
  -> AudioPlayback.play_stream(..., interrupt_token)
  -> interrupt happens
      -> interrupt_token.interrupt(reason)
      -> AudioPlayback.stop(reason)
      -> current simpleaudio PlayObject.stop()
      -> stream loop stops before playing more chunks
      -> AvatarEventBus.emit("tts_interrupt")
  -> AvatarEventBus.emit("tts_end")
```

## SQLite Memory Schema

Schema v6 新增：

```sql
CREATE TABLE IF NOT EXISTS conversation_turns (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  turn_index INTEGER NOT NULL,
  source_channel TEXT NOT NULL,
  user_text TEXT NOT NULL,
  assistant_text TEXT NOT NULL,
  raw_asr_text TEXT,
  scene TEXT,
  started_at TEXT NOT NULL,
  completed_at TEXT NOT NULL,
  llm_provider TEXT,
  llm_model TEXT,
  asr_provider TEXT,
  tts_provider TEXT,
  latency_json TEXT,
  metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_conversation_turns_session
ON conversation_turns(session_id, turn_index);

CREATE INDEX IF NOT EXISTS idx_conversation_turns_created
ON conversation_turns(completed_at DESC);
```

写入规则：

- 每轮完整原文写入 `conversation_turns`。
- 抽取后的长期事实、偏好、任务写入 `memory_entries`。
- 当前会话连续性写入 `session_memory_entries`。
- 跨 session 摘要写入 `session_continuity_entries`。

## 最小可运行 Demo 路线

1. 启动 `scripts/run_voice_memory_demo.ps1`。
2. 脚本检查 my-neuro ASR `/vad/status`。
3. 脚本检查 GPT-SoVITS v2 `/docs`。
4. 缺服务时只启动本脚本自己的子进程。
5. 加载 `role_voice_api/neuro/merge.pth`。
6. 进入 `src/app/main_voice.py --manual`。
7. 按 Enter 录音一轮。
8. ASR 文本进入原 Coordinator 链路。
9. TTS 播放，ESC 或直接说话可打断。
10. SQLite 同时保存完整轮次与抽取记忆。

## 最小改动路径

保持 `src/app/main.py` 不变或近似不变；所有新增能力挂在可选 voice mode、配置文件和 provider registry 上。原文字 CLI 仍走 `Coordinator.process_user_message(user_input)` 默认参数，语音 CLI 只额外传 `source_channel`、`raw_asr_text`、`asr_provider`。

第一批修改文件：

- `src/config/models.py`
- `src/config/loader.py`
- `src/config/voice_config.yaml`
- `src/config/voice_profiles.yaml`
- `src/voice/asr.py`
- `src/voice/tts.py`
- `src/voice/playback.py`
- `src/voice/controller.py`
- `src/app/coordinator.py`
- `src/memory/models.py`
- `src/memory/store.py`
- `src/memory/manager.py`
- `scripts/run_voice_memory_demo.ps1`
