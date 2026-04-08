# Eval Summary

- Mode: `live`
- Suite: `smoke`
- Output Dir: `C:\Users\48137\Desktop\project_serina\artifacts\evals\2026-04-08_152017`
- Trace Log: `N/A`

## Overall

- Total Cases: 8
- Success Count: 6
- Failure Count: 2
- Scene Match Rate: 100.00%
- Length Band Match Rate: 87.50%
- Forbidden Hit Case Count: 0
- Empty Response Count: 0
- Avg Latency: 2113 ms
- P95 Latency: 2702 ms

## Common Failure Types

- `missing_follow_up_signal`: 1
- `length_band_mismatch`: 1

## Bad Cases

### greeting_late_night
- Input: 晚上好，还醒着吗
- Actual Scene: greeting
- Response Preview: 晚上好呀，老师。我醒着呢，随时都在的。
- Failure Reason: missing_follow_up_signal

### casual_project_update
- Input: 今天把日志这块又往前推了一点。
- Actual Scene: casual_chat
- Response Preview: 老师今天效率不错呢。日志模块确实容易让人卡住，能推进一点都是好的。
- Failure Reason: length_band_mismatch
