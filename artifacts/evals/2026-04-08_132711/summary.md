# Eval Summary

- Mode: `live`
- Suite: `smoke`
- Output Dir: `C:\Users\48137\Desktop\project_serina\artifacts\evals\2026-04-08_132711`
- Trace Log: `N/A`

## Overall

- Total Cases: 2
- Success Count: 1
- Failure Count: 1
- Scene Match Rate: 100.00%
- Length Band Match Rate: 100.00%
- Forbidden Hit Case Count: 0
- Empty Response Count: 0
- Avg Latency: 1655 ms
- P95 Latency: 1718 ms

## Common Failure Types

- `missing_follow_up_signal`: 1

## Bad Cases

### greeting_late_night
- Input: 晚上好，还醒着吗
- Actual Scene: greeting
- Response Preview: 晚上好呀，老师。我醒着呢，随时都在。
- Failure Reason: missing_follow_up_signal
