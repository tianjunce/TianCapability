# manage_todo

`manage_todo` 用于创建一条待办事项。

当前 v1 只负责：

- 创建待办主记录
- 保存可选字段：`notes`、`deadline`、`progress_percent`、`difficulty`
- 当存在 `deadline` 时，自动生成待办提醒 occurrence

当前 v1 还不负责：

- 查询待办列表
- 修改待办
- 完成待办
- 删除待办

## Request

```json
{
  "input": {
    "title": "写周报",
    "notes": "补上本周项目进展",
    "deadline": "2026-04-08 18:00",
    "progress_percent": 20,
    "difficulty": "high"
  },
  "context": {
    "request_id": "task-123",
    "session_id": "session-456",
    "user_id": "user-789",
    "progress_context": {
      "enabled": true,
      "protocol": "jsonl_file",
      "path": "/tmp/tianai-skill-progress.jsonl",
      "scope": "skill:manage_todo"
    }
  }
}
```

## Supported Deadline Formats

- `2026-04-08 18:00`
- `2026/04/08 18:00`
- `2026-04-08T18:00`
- `2026-04-08`

日期格式不带时间时，会默认按当天 `23:59` 处理。

## Reminder Plan

如果存在 `deadline`，当前 v1 会尝试生成这些提醒点：

- 工期剩余 `50%`
- 工期剩余 `25%`
- 工期剩余 `10%`
- 截止前 `1天`

其中：

- 基准是“创建时间”到“截止时间”之间的总时长
- 如果某个提醒点早于当前时间，则跳过
- 如果两个提醒点落在同一时刻，只保留一条 occurrence

## Success Response

```json
{
  "status": "success",
  "data": {
    "todo_id": "4d978f4f8a2a48d9a3dd8f3d1e1e1111",
    "title": "写周报",
    "notes": "补上本周项目进展",
    "deadline": "2026-04-08T18:00:00",
    "progress_percent": 20,
    "difficulty": "high",
    "status": "open",
    "occurrence_ids": [
      "b1",
      "b2",
      "b3",
      "b4"
    ],
    "reminder_plan": [
      {
        "stage": "remaining_50_percent",
        "label": "工期剩余50%提醒",
        "remind_at": "2026-04-05T06:00:00"
      }
    ],
    "summary": "已记录待办：写周报，截止时间 2026-04-08 18:00，并生成 4 条提醒。"
  },
  "error": null,
  "meta": {
    "capability": "manage_todo",
    "duration_ms": 16
  }
}
```

## Storage Notes

- 待办主记录写入 `runtime-data/manage_todo/todos.json`
- 待办提醒 occurrence 继续写入 `runtime-data/reminders/occurrences.json`
- worker 投递记录继续写入 `runtime-data/reminders/deliveries.json`
- 根目录可通过环境变量 `CAPABILITY_DATA_DIR` 覆盖

## Error Codes

- `invalid_request`
- `invalid_input`
- `invalid_datetime`
- `deadline_in_past`
- `invalid_progress_percent`
- `internal_error`

## Detail Steps

- `validate_user_scope` / `校验用户上下文`
- `persist_todo` / `保存待办记录`
- `format_todo_result` / `整理待办结果`
