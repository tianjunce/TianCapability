# capture_idea

`capture_idea` 用于记录、查询和删除灵感、碎片想法或临时念头。

当前支持 3 个动作：

- `action=create`：记录灵感
- `action=list`：查询灵感
- `action=delete`：按 `idea_id` 删除灵感；若 `title` 或 `content` 能唯一定位，也可直接删除

同一个 `action` 也支持批量 `items`，可以一次记录多条灵感，并把每条 item 的成功或失败分别返回。

## Request

记录灵感：

```json
{
  "input": {
    "action": "create",
    "title": "家长作业提醒工具",
    "content": "做一个给家长用的作业提醒工具，重点是晚间统一提醒和周报汇总。",
    "tags": ["产品", "教育"]
  },
  "context": {
    "request_id": "task-123",
    "session_id": "session-456",
    "user_id": "user-789"
  }
}
```

查询灵感：

```json
{
  "input": {
    "action": "list",
    "tag": "产品"
  },
  "context": {
    "request_id": "task-123",
    "session_id": "session-456",
    "user_id": "user-789"
  }
}
```

删除灵感：

```json
{
  "input": {
    "action": "delete",
    "idea_id": "idea-id-1"
  },
  "context": {
    "request_id": "task-123",
    "session_id": "session-456",
    "user_id": "user-789"
  }
}
```

## Input Notes

- `content` 是创建时必填
- `title` 可选
- `tags` 可选，建议上游归一化成字符串数组
- `list` 动作支持可选 `tag` 过滤

## Success Response

记录灵感：

```json
{
  "status": "success",
  "data": {
    "action": "create",
    "idea_id": "idea-id-1",
    "title": "家长作业提醒工具",
    "content": "做一个给家长用的作业提醒工具，重点是晚间统一提醒和周报汇总。",
    "tags": [
      "产品",
      "教育"
    ],
    "status": "active",
    "summary": "已记录灵感：家长作业提醒工具。"
  }
}
```

查询灵感：

```json
{
  "status": "success",
  "data": {
    "action": "list",
    "total": 1,
    "ideas": [
      {
        "id": "idea-id-1",
        "title": "家长作业提醒工具",
        "tags": [
          "产品",
          "教育"
        ]
      }
    ],
    "summary": "共找到 1 条标签为 产品 的灵感记录。"
  }
}
```

删除灵感：

```json
{
  "status": "success",
  "data": {
    "action": "delete",
    "idea_id": "idea-id-1",
    "status": "deleted",
    "summary": "已删除灵感：家长作业提醒工具。"
  }
}
```

## Storage Notes

- 灵感主记录写入 `runtime-data/capture_idea/ideas.json`
- 根目录可通过环境变量 `CAPABILITY_DATA_DIR` 覆盖

## Error Codes

- `invalid_request`
- `invalid_input`
- `invalid_action`
- `invalid_status`
- `invalid_tags`
- `idea_not_found`
- `idea_not_deletable`
- `internal_error`
