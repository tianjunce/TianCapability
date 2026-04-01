# manage_birthday

`manage_birthday` 用于创建一条生日记录，并生成生日提醒。

当前 v1 只负责：

- 创建生日主记录
- 支持阳历和农历生日
- 支持记录可选字段：`birth_year`、`notes`、`is_leap_month`
- 为“下一次还来得及提醒的生日”生成 `前7天` 和 `前1天` 的 reminder occurrence

当前 v1 还不负责：

- 查询生日列表
- 修改生日
- 删除生日
- 自动续生未来多年的生日 occurrence

## Request

```json
{
  "input": {
    "name": "妈妈",
    "birthday": "08-03",
    "calendar_type": "lunar",
    "notes": "提前准备蛋糕"
  },
  "context": {
    "request_id": "task-123",
    "session_id": "session-456",
    "user_id": "user-789",
    "progress_context": {
      "enabled": true,
      "protocol": "jsonl_file",
      "path": "/tmp/tianai-skill-progress.jsonl",
      "scope": "skill:manage_birthday"
    }
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

当前 v1 的提醒规则固定为：

- 生日前 `7天`，上午 `09:00`
- 生日前 `1天`，上午 `09:00`

如果当前这次生日已经来不及再发这两条提醒，会自动顺延到下一次还能发出提醒的生日。

对于农历生日：

- 会按农历原始月日换算到下一次对应的公历日期
- 如果是闰月生日，只有存在对应闰月的年份才会生成提醒
- 如果某个农历月没有这一天，比如三十在某年不存在，会顺延到下一次存在该农历日期的年份

## Success Response

```json
{
  "status": "success",
  "data": {
    "birthday_id": "4d978f4f8a2a48d9a3dd8f3d1e1e1111",
    "name": "妈妈",
    "birthday": "08-03",
    "calendar_type": "lunar",
    "birth_year": null,
    "is_leap_month": false,
    "notes": "提前准备蛋糕",
    "status": "active",
    "next_birthday": "2026-09-14",
    "occurrence_ids": [
      "b1",
      "b2"
    ],
    "reminder_plan": [
      {
        "stage": "birthday_minus_7_days",
        "label": "生日前7天提醒",
        "remind_at": "2026-09-07T09:00:00",
        "birthday_date": "2026-09-14"
      },
      {
        "stage": "birthday_minus_1_day",
        "label": "生日前1天提醒",
        "remind_at": "2026-09-13T09:00:00",
        "birthday_date": "2026-09-14"
      }
    ],
    "summary": "已记录生日：妈妈，按农历 08-03 提醒，下一次生日是 2026-09-14，并生成 2 条提醒。"
  },
  "error": null,
  "meta": {
    "capability": "manage_birthday",
    "duration_ms": 16
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
- `invalid_calendar_type`
- `invalid_birth_year`
- `invalid_birthday`
- `birthday_schedule_unavailable`
- `internal_error`

## Detail Steps

- `validate_user_scope` / `校验用户上下文`
- `persist_birthday` / `保存生日记录`
- `format_birthday_result` / `整理生日结果`
