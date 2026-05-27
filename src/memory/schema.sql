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
