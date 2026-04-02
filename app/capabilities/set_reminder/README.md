# set_reminder

`set_reminder` 用于管理单次提醒。

当前支持 4 个动作：

- `action=create`：创建提醒
- `action=list`：查询当前用户的提醒记录
- `action=update`：优先按 `reminder_id` 修改提醒；若 `content` 能唯一定位，也可直接修改
- `action=cancel`：取消一条提醒

同一个 `action` 也支持批量 `items`，会逐条执行并把成功和失败分别写进返回结果。

## Request

创建提醒：

```json
{
  "input": {
    "action": "create",
    "content": "交电费",
    "remind_at": "2026-04-02 09:00",
    "note": "到点先看余额"
  },
  "context": {
    "request_id": "task-123",
    "session_id": "session-456",
    "user_id": "user-789"
  }
}
```

查询提醒：

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

修改提醒：

```json
{
  "input": {
    "action": "update",
    "reminder_id": "2e3b9c6d0f4d4d5b89e3d4b4d7c9a111",
    "remind_at": "2026-04-02 10:00",
    "note": "改到十点"
  },
  "context": {
    "request_id": "task-123",
    "session_id": "session-456",
    "user_id": "user-789"
  }
}
```

取消提醒：

```json
{
  "input": {
    "action": "cancel",
    "reminder_id": "2e3b9c6d0f4d4d5b89e3d4b4d7c9a111"
  },
  "context": {
    "request_id": "task-123",
    "session_id": "session-456",
    "user_id": "user-789"
  }
}
```

## Supported Datetime Formats

- `2026-04-02 09:00`
- `2026/04/02 09:00`
- `2026-04-02T09:00`
- `2026-04-02 09:00:00`

当前仍不直接支持未归一化时间表达，例如：

- `明天下午三点`
- `两个小时后`

这些表达应由上游 skill prepare 阶段先换算成具体 `remind_at`。

当前 capability 侧涉及“当前时间”的判断统一按中国北京时区（`Asia/Shanghai`）执行。

## Success Response

创建提醒：

```json
{
  "status": "success",
  "data": {
    "action": "create",
    "reminder_id": "2e3b9c6d0f4d4d5b89e3d4b4d7c9a111",
    "occurrence_id": "a7b5643a72974a5a8b64ef31eaf9b222",
    "content": "交电费",
    "note": "到点先看余额",
    "remind_at": "2026-04-02T09:00:00",
    "status": "active",
    "summary": "已创建提醒：2026-04-02 09:00 提醒你 交电费。备注：到点先看余额"
  }
}
```

查询提醒：

```json
{
  "status": "success",
  "data": {
    "action": "list",
    "total": 1,
    "reminders": [
      {
        "id": "2e3b9c6d0f4d4d5b89e3d4b4d7c9a111",
        "content": "交电费",
        "remind_at": "2026-04-02T09:00:00",
        "status": "active"
      }
    ],
    "summary": "共找到 1 条提醒记录。"
  }
}
```

修改提醒：

```json
{
  "status": "success",
  "data": {
    "action": "update",
    "reminder_id": "2e3b9c6d0f4d4d5b89e3d4b4d7c9a111",
    "occurrence_id": "new-occurrence-id",
    "content": "交电费",
    "note": "改到十点",
    "remind_at": "2026-04-02T10:00:00",
    "status": "active",
    "cancelled_occurrence_ids": [
      "old-occurrence-id"
    ],
    "summary": "已更新提醒：2026-04-02T10:00:00 提醒你 交电费。"
  }
}
```

取消提醒：

```json
{
  "status": "success",
  "data": {
    "action": "cancel",
    "reminder_id": "2e3b9c6d0f4d4d5b89e3d4b4d7c9a111",
    "content": "交电费",
    "remind_at": "2026-04-02T09:00:00",
    "status": "cancelled",
    "cancelled_occurrence_ids": [
      "a7b5643a72974a5a8b64ef31eaf9b222"
    ],
    "summary": "已取消提醒：交电费，原提醒时间 2026-04-02T09:00:00。"
  }
}
```

## Storage Notes

- 默认运行时主记录写入 MySQL：
  - `capability_reminder_records`
  - `capability_reminder_occurrence_records`
  - `capability_reminder_delivery_records`
- 如果显式设置 `CAPABILITY_STORAGE_BACKEND=json`，或在测试里使用 `CAPABILITY_DATA_DIR`，会退回 JSON 文件模式
- `runtime-data/` 现在主要用于历史数据与测试，不再是默认运行时真源
- 所有业务数据按 `context.user_id` 归属

## Worker

最小 worker 入口：

```bash
cd /Users/tianjunce/Projects/GitHub/TianCapability
conda activate Tian3.10_clean
python -m app.workers.reminder_worker --once
```

常驻轮询：

```bash
python -m app.workers.reminder_worker --poll-seconds 10
```

默认会读取仓库根目录的 [`.env.local`](/Users/tianjunce/Projects/GitHub/TianCapability/.env.local)：

```bash
REMINDER_NOTIFICATION_API_URL=http://<你的-backend>/api/internal/notifications/reminders
REMINDER_NOTIFICATION_API_TOKEN=<和 backend 一致的 token>
DB_LOGIN_USER=<mysql-user>
DB_LOGIN_PASSWORD=<url-encoded-password>
DB_HOST=<host:port/database>
```

提醒接口字段定义见 [README_REMINDER_NOTIFICATION_API.md](/Users/tianjunce/Projects/GitHub/TianCapability/docs/README_REMINDER_NOTIFICATION_API.md)。

## Error Codes

- `invalid_request`
- `invalid_input`
- `invalid_action`
- `invalid_status`
- `invalid_datetime`
- `reminder_in_past`
- `reminder_not_found`
- `reminder_not_editable`
- `ambiguous_reminder`
- `reminder_not_cancellable`
- `internal_error`
