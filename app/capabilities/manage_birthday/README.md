# manage_birthday

`manage_birthday` 用于记录、查询和删除生日，并自动生成生日提醒。

当前支持 3 个动作：

- `action=create`：创建生日记录
- `action=list`：查询生日记录，可选按 `name` 或 `status` 筛选
- `action=delete`：按 `birthday_id` 删除生日记录；若 `name` 能唯一定位，也可按名字删除

同一个 `action` 也支持批量 `items`。例如同时记录同一个人的阳历和农历生日时，可以一次请求里传两条 item，capability 会逐条执行并分别返回成功或失败结果。

## Request

创建生日：

```json
{
  "input": {
    "action": "create",
    "name": "妈妈",
    "birthday": "08-03",
    "calendar_type": "lunar",
    "notes": "提前准备蛋糕"
  },
  "context": {
    "request_id": "task-123",
    "session_id": "session-456",
    "user_id": "user-789"
  }
}
```

查询生日：

```json
{
  "input": {
    "action": "list",
    "status": "active"
  },
  "context": {
    "request_id": "task-123",
    "session_id": "session-456",
    "user_id": "user-789"
  }
}
```

按名字查询生日：

```json
{
  "input": {
    "action": "list",
    "name": "妈妈"
  },
  "context": {
    "request_id": "task-123",
    "session_id": "session-456",
    "user_id": "user-789"
  }
}
```

删除生日：

```json
{
  "input": {
    "action": "delete",
    "birthday_id": "birthday-id-1"
  },
  "context": {
    "request_id": "task-123",
    "session_id": "session-456",
    "user_id": "user-789"
  }
}
```

## Supported Birthday Formats

- `05-12`
- `05/12`
- `5月12日`
- `1990-05-12`
- `1990/05/12`
- `1990年5月12日`

推荐上游 skill 预先把生日归一化成：

- `birthday = MM-DD`
- `birth_year = YYYY`（如果用户明确提供）
- `calendar_type = solar | lunar`
- `is_leap_month = true | false`

## Reminder Rules

当前提醒规则固定为：

- 生日前 `7天`，上午 `09:00`
- 生日前 `1天`，上午 `09:00`

如果当前这次生日已经来不及再发这两条提醒，会自动顺延到下一次还能发出提醒的生日。
删除生日后，尚未发送的 pending occurrence 会统一取消。

## Success Response

创建生日：

```json
{
  "status": "success",
  "data": {
    "action": "create",
    "birthday_id": "birthday-id-1",
    "name": "妈妈",
    "birthday": "08-03",
    "calendar_type": "lunar",
    "status": "active",
    "next_birthday": "2026-09-14",
    "summary": "已记录生日：妈妈，按农历 08-03 提醒，下一次生日是 2026-09-14，并生成 2 条提醒。"
  }
}
```

查询生日：

```json
{
  "status": "success",
  "data": {
    "action": "list",
    "total": 1,
    "birthdays": [
      {
        "id": "birthday-id-1",
        "name": "妈妈",
        "next_birthday": "2026-09-14",
        "status": "active"
      }
    ],
    "summary": "共找到 1 条生日记录。"
  }
}
```

按名字查询生日：

```json
{
  "status": "success",
  "data": {
    "action": "list",
    "total": 1,
    "birthdays": [
      {
        "id": "birthday-id-1",
        "name": "妈妈",
        "next_birthday": "2026-09-14",
        "status": "active"
      }
    ],
    "summary": "共找到 1 条名字为 妈妈 的生日记录。"
  }
}
```

删除生日：

```json
{
  "status": "success",
  "data": {
    "action": "delete",
    "birthday_id": "birthday-id-1",
    "name": "妈妈",
    "status": "deleted",
    "cancelled_occurrence_ids": [
      "occ-1"
    ],
    "summary": "已删除生日记录：妈妈。"
  }
}
```

## Storage Notes

- 生日主记录写入 `runtime-data/manage_birthday/birthdays.json`
- 生日提醒 occurrence 写入 `runtime-data/reminders/occurrences.json`
- worker 投递记录继续写入 `runtime-data/reminders/deliveries.json`
- 根目录可通过环境变量 `CAPABILITY_DATA_DIR` 覆盖

## Error Codes

- `invalid_request`
- `invalid_input`
- `invalid_action`
- `invalid_status`
- `invalid_calendar_type`
- `invalid_birth_year`
- `invalid_birthday`
- `birthday_not_found`
- `birthday_not_deletable`
- `birthday_schedule_unavailable`
- `internal_error`
