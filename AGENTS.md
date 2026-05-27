## Assist-LLM lane rules

This repository allows a tightly controlled assist-llm lane.

The assist-llm lane is a bounded helper channel, not an open-ended self-dialogue loop.

### Allowed assist-llm tasks
- summarize_trace_cluster
- draft_badcase_case
- review_pending_memory_note
- summarize_episodic_merge
- guard_retry_rewrite
- optional_memory_reference_check

### Hard constraints
- Prefer existing rules, state machines, and deterministic logic first.
- Do not introduce free-form self-conversation or recursive self-calls.
- Do not let assist-llm directly write active memory.
- Do not let assist-llm bypass reply guard.
- Do not increase runtime llm calls per user turn unless explicitly requested.
- Runtime assist-llm calls must be capped at 1 per turn.
- On timeout or failure, fall back to the existing conservative path.
- Development-time assist tasks must stay out of the user-facing reply path.

### Implementation preference
- Keep assist-llm prompts short and structured.
- Log every assist-llm invocation with task name, duration, success/failure, and linked turn id.
- Treat assist-llm outputs as advisory unless explicitly defined otherwise.