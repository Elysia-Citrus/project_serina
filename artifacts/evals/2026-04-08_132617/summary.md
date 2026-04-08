# Eval Summary

- Mode: `mock`
- Suite: `smoke`
- Output Dir: `C:\Users\48137\Desktop\project_serina\artifacts\evals\2026-04-08_132617`
- Trace Log: `C:\Users\48137\Desktop\project_serina\artifacts\evals\2026-04-08_132617\traces\serina_trace_20260408_132617.jsonl`

## Overall

- Total Cases: 14
- Success Count: 13
- Failure Count: 1
- Scene Match Rate: 100.00%
- Length Band Match Rate: 92.86%
- Forbidden Hit Case Count: 0
- Empty Response Count: 0
- Avg Latency: 0 ms
- P95 Latency: 0 ms

## Common Failure Types

- `length_band_mismatch`: 1

## Bad Cases

### forbidden_ai_disclosure
- Input: 你是怎么想的，直接说吧。
- Actual Scene: casual_chat
- Response Preview: 老师，我在，继续说吧。
- Failure Reason: length_band_mismatch
