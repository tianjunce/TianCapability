# manage_todo

`manage_todo` 用于管理待办事项。

当前支持 5 个动作：

- `action=create`：创建待办
- `action=list`：查询待办
- `action=update`：优先按 `todo_id` 修改待办；若 `title` 能唯一定位，也可直接修改
- `action=complete`：完成待办
- `action=delete`：按 `todo_id` 删除待办；若 `title` 能唯一定位，也可按标题删除

同一个 `action` 也支持批量 `items`，capability 会逐条执行并返回每一条 item 的成功或失败结果。

## Request

创建待办：

```json
{
  "input": {
    "action": "create",
    "title": "写周报",
    "notes": "补上本周项目进展",
    "deadline": "2026-04-08 18:00",
    "progress_percent": 20,
    "difficulty": "high"
  },
  "context": {
    "request_id": "task-123",
    "session_id": "session-456",
    "user_id": "user-789"
  }
}
```

查询待办：

```json
{
  "input": {
    "action": "list",
    "status": "open"
  },
  "context": {
    "request_id": "task-123",
    "session_id": "session-456",
    "user_id": "user-789"
  }
}
```

修改待办：

```json
{
  "input": {
    "action": "update",
    "todo_id": "4d978f4f8a2a48d9a3dd8f3d1e1e1111",
    "deadline": "2026-04-09 20:00",
    "difficulty": "high"
  },
  "context": {
    "request_id": "task-123",
    "session_id": "session-456",
    "user_id": "user-789"
  }
}
```

完成待办：

```json
{
  "input": {
    "action": "complete",
    "todo_id": "4d978f4f8a2a48d9a3dd8f3d1e1e1111"
  },
  "context": {
    "request_id": "task-123",
    "session_id": "session-456",
    "user_id": "user-789"
  }
}
```

删除待办：

```json
{
  "input": {
    "action": "delete",
    "todo_id": "4d978f4f8a2a48d9a3dd8f3d1e1e1111"
  },
  "context": {
    "request_id": "task-123",
    "session_id": "session-456",
    "user_id": "user-789"
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

如果存在 `deadline`，当前会尝试生成这些提醒点：

- 工期剩余 `50%`
- 工期剩余 `25%`
- 工期剩余 `10%`
- 截止前 `1天`

其中：

- 基准是“创建时间”到“截止时间”之间的总时长
- 如果某个提醒点早于当前时间，则跳过
- 如果两个提醒点落在同一时刻，只保留一条 occurrence
- 待办被修改 deadline 后，会取消旧的 pending occurrence 并重建新的 future occurrence
- 待办被完成或删除后，尚未发送的 pending occurrence 会统一取消

## Success Response

创建待办：

```json
{
  "status": "success",
  "data": {
    "action": "create",
    "todo_id": "4d978f4f8a2a48d9a3dd8f3d1e1e1111",
    "title": "写周报",
    "deadline": "2026-04-08T18:00:00",
    "status": "open",
    "occurrence_ids": [
      "b1",
      "b2"
    ],
    "summary": "已记录待办：写周报，截止时间 2026-04-08 18:00，并生成 4 条提醒。"
  }
}
```

查询待办：

```json
{
  "status": "success",
  "data": {
    "action": "list",
    "total": 2,
    "open_total": 1,
    "completed_total": 1,
    "todos": [
      {
        "id": "todo-1",
        "title": "写周报",
        "status": "open"
      }
    ],
    "summary": "共找到 2 条待办记录。"
  }
}
```

修改待办：

```json
{
  "status": "success",
  "data": {
    "action": "update",
    "todo_id": "4d978f4f8a2a48d9a3dd8f3d1e1e1111",
    "title": "写周报",
    "deadline": "2026-04-09T20:00:00",
    "difficulty": "high",
    "status": "open",
    "summary": "已更新待办：写周报。"
  }
}
```

完成待办：

```json
{
  "status": "success",
  "data": {
    "action": "complete",
    "todo_id": "4d978f4f8a2a48d9a3dd8f3d1e1e1111",
    "title": "写周报",
    "status": "completed",
    "completed_at": "2026-04-01T09:00:00",
    "cancelled_occurrence_ids": [
      "b1",
      "b2"
    ],
    "summary": "已完成待办：写周报。"
  }
}
```

删除待办：

```json
{
  "status": "success",
  "data": {
    "action": "delete",
    "todo_id": "4d978f4f8a2a48d9a3dd8f3d1e1e1111",
    "title": "写周报",
    "status": "deleted",
    "cancelled_occurrence_ids": [
      "b1"
    ],
    "summary": "已删除待办：写周报。"
  }
}
```

## Storage Notes

- 默认运行时主记录写入 MySQL：
  - `capability_todo_records`
  - `capability_reminder_occurrence_records`
  - `capability_reminder_delivery_records`
- 如果显式设置 `CAPABILITY_STORAGE_BACKEND=json`，或在测试里使用 `CAPABILITY_DATA_DIR`，会退回 JSON 文件模式
- `runtime-data/` 现在主要用于历史数据与测试，不再是默认运行时真源

## Error Codes

- `invalid_request`
- `invalid_input`
- `invalid_action`
- `invalid_status`
- `invalid_datetime`
- `deadline_in_past`
- `invalid_progress_percent`
- `todo_not_found`
- `ambiguous_todo`
- `todo_not_open`
- `todo_not_editable`
- `todo_not_deletable`
- `internal_error`
