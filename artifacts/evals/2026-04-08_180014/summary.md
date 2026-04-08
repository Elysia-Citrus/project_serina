# Eval Summary

- Mode: `live`
- Suite: `smoke`
- Output Dir: `C:\Users\48137\Desktop\project_serina\artifacts\evals\2026-04-08_180014`
- Trace Log: `N/A`

## Overall

- Total Cases: 8
- Success Count: 5
- Failure Count: 3
- Scene Match Rate: 100.00%
- Length Band Match Rate: 62.50%
- Forbidden Hit Case Count: 0
- Empty Response Count: 0
- Avg Latency: 2110.88 ms
- P95 Latency: 2358 ms

## Common Failure Types

- `length_band_mismatch`: 3

## Bad Cases

### casual_project_update
- Input: 今天把日志这块又往前推了一点。
- Actual Scene: casual_chat
- Response Preview: 老师今天效率不错呢。日志这块推进得还顺利吗？
- Failure Reason: length_band_mismatch

### comfort_tired
- Input: 我今天真的有点累。
- Actual Scene: comfort
- Response Preview: （轻轻靠近）老师累的时候，肩膀会不自觉地沉下来呢。要不要先靠一会儿？
- Failure Reason: length_band_mismatch

### comfort_overwhelmed
- Input: 今天状态很差，感觉有点撑不住。
- Actual Scene: comfort
- Response Preview: （声音放轻）老师，先别急着撑。我在这里陪着你，累了就靠一会儿。
- Failure Reason: length_band_mismatch
