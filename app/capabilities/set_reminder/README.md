# set_reminder

`set_reminder` 用于创建一个精确到日期时间的单次提醒。

当前 v1 只负责：

- 校验用户级上下文
- 保存提醒主记录
- 生成一条统一的 `occurrence`
- 供独立的 `reminder_worker` 后续扫描和发送通知

当前 v1 还不负责：

- 取消提醒
- 修改提醒
- 列出提醒
- 多渠道通知编排

## Request

```json
{
  "input": {
    "content": "交电费",
    "remind_at": "2026-04-02 09:00",
    "note": "到点先看余额"
  },
  "context": {
    "request_id": "task-123",
    "session_id": "session-456",
    "user_id": "user-789",
    "progress_context": {
      "enabled": true,
      "protocol": "jsonl_file",
      "path": "/tmp/tianai-skill-progress.jsonl",
      "scope": "skill:set_reminder"
    }
  }
}
```

## Supported Datetime Formats

- `2026-04-02 09:00`
- `2026/04/02 09:00`
- `2026-04-02T09:00`
- `2026-04-02 09:00:00`

当前不支持：

- `明天下午三点`
- `两个小时后`
- 重复提醒规则

## Success Response

```json
{
  "status": "success",
  "data": {
    "reminder_id": "2e3b9c6d0f4d4d5b89e3d4b4d7c9a111",
    "occurrence_id": "a7b5643a72974a5a8b64ef31eaf9b222",
    "content": "交电费",
    "note": "到点先看余额",
    "remind_at": "2026-04-02T09:00:00",
    "status": "active",
    "summary": "已创建提醒：2026-04-02 09:00 提醒你 交电费。备注：到点先看余额"
  },
  "error": null,
  "meta": {
    "capability": "set_reminder",
    "duration_ms": 12
  }
}
```

## Storage Notes

- 提醒主记录写入 `runtime-data/set_reminder/reminders.json`
- 统一提醒 occurrence 写入 `runtime-data/reminders/occurrences.json`
- worker 投递记录写入 `runtime-data/reminders/deliveries.json`
- 根目录可通过环境变量 `CAPABILITY_DATA_DIR` 覆盖
- 所有业务数据按 `context.user_id` 归属

## Worker

最小 worker 入口：

```bash
cd /Users/tianjunce/Projects/GitHub/TianCapability
conda activate Tian3.10_clean
python -m app.workers.reminder_worker --once
```

默认会读取仓库根目录的 [`.env.local`](/Users/tianjunce/Projects/GitHub/TianCapability/.env.local)：

```bash
REMINDER_NOTIFICATION_API_URL=http://<你的-backend>/api/internal/notifications/reminders
REMINDER_NOTIFICATION_API_TOKEN=<和 backend 一致的 token>
```

如果你临时想覆盖，也可以直接 `export` 同名环境变量。

提醒接口请求体的准确字段定义见 [README_REMINDER_NOTIFICATION_API.md](/Users/tianjunce/Projects/GitHub/TianCapability/docs/README_REMINDER_NOTIFICATION_API.md)。
当前与 `TianAI1.5` 对齐后的顶层目标字段名是 `user_id`，值语义是用户名。

当前 worker 会：

- 扫描 `pending` 且已到期的 occurrence
- 调用 `REMINDER_NOTIFICATION_API_URL`
- 成功后把 occurrence 标记为 `delivered`
- 失败后把 occurrence 标记为 `failed`

当前还不包含重试、静默时段和多渠道分发策略。

## Error Codes

- `invalid_request`
- `invalid_input`
- `invalid_datetime`
- `reminder_in_past`
- `internal_error`

## Detail Steps

- `validate_user_scope` / `校验用户上下文`
- `persist_reminder` / `保存提醒记录`
- `format_reminder_result` / `整理提醒结果`
