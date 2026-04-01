# capture_idea

`capture_idea` 用于记录一条灵感、碎片想法或临时念头。

当前 v1 只负责：

- 创建灵感主记录
- 保存可选字段：`title`、`tags`

当前 v1 还不负责：

- 查询灵感列表
- 搜索灵感
- 修改灵感
- 删除灵感
- 把灵感转成待办或提醒

## Request

```json
{
  "input": {
    "title": "家长作业提醒工具",
    "content": "做一个给家长用的作业提醒工具，重点是晚间统一提醒和周报汇总。",
    "tags": ["产品", "教育"]
  },
  "context": {
    "request_id": "task-123",
    "session_id": "session-456",
    "user_id": "user-789",
    "progress_context": {
      "enabled": true,
      "protocol": "jsonl_file",
      "path": "/tmp/tianai-skill-progress.jsonl",
      "scope": "skill:capture_idea"
    }
  }
}
```

## Input Notes

- `content` 是必填
- `title` 可选
- `tags` 可选，建议上游归一化成字符串数组

如果用户没有单独给标题，可以只传 `content`。

## Success Response

```json
{
  "status": "success",
  "data": {
    "idea_id": "4d978f4f8a2a48d9a3dd8f3d1e1e1111",
    "title": "家长作业提醒工具",
    "content": "做一个给家长用的作业提醒工具，重点是晚间统一提醒和周报汇总。",
    "tags": [
      "产品",
      "教育"
    ],
    "status": "active",
    "summary": "已记录灵感：家长作业提醒工具。"
  },
  "error": null,
  "meta": {
    "capability": "capture_idea",
    "duration_ms": 8
  }
}
```

## Storage Notes

- 灵感主记录写入 `runtime-data/capture_idea/ideas.json`
- 根目录可通过环境变量 `CAPABILITY_DATA_DIR` 覆盖

## Error Codes

- `invalid_request`
- `invalid_input`
- `invalid_tags`
- `internal_error`

## Detail Steps

- `validate_user_scope` / `校验用户上下文`
- `persist_idea` / `保存灵感记录`
- `format_idea_result` / `整理灵感结果`
