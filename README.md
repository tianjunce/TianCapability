# Capability Service

`capability-service` 是 AI runtime 的统一能力执行后端。

当前定位很明确：

- AI runtime 负责 skill 选择、`need_input`、trace/task 生命周期、progress builder
- capability-service 负责标准化 capability 执行
- AI runtime 直接调用 capability-service
- capability-service 不负责 session / task / trace / message / UI
- capability-service 的用户级业务数据由自身存储，按 `context.user_id` 做隔离

## 平台文档

- 平台开发规范：[`docs/README_CAPABILITY_DEVELOPMENT.md`](docs/README_CAPABILITY_DEVELOPMENT.md)
- skill 开发规范：[`docs/README_SKILL_DEVELOPMENT.md`](docs/README_SKILL_DEVELOPMENT.md)
- 示例 capability：[`app/capabilities/get_weather/README.md`](app/capabilities/get_weather/README.md)

## 当前能力

- `get_weather`
- `set_reminder`
- `manage_todo`
- `manage_birthday`
- `capture_idea`

其中当前业务型 skill 的 v1 状态是：

- `set_reminder`：创建、查询、修改、取消单次提醒，支持同 action 的批量 `items`
- `manage_todo`：创建、查询、修改、完成、删除待办，支持同 action 的批量 `items`
- `manage_birthday`：创建、查询、删除阳历/农历生日记录，支持同 action 的批量 `items`
- `capture_idea`：记录、查询、删除灵感正文、可选标题和标签，支持同 action 的批量 `items`

## 当前 worker

- `app.workers.reminder_worker`：扫描到期 reminder occurrence，并调用通知 API 发送提醒

提醒 worker 的 API 配置默认从仓库根目录 [`.env.local`](/Users/tianjunce/Projects/GitHub/TianCapability/.env.local) 读取。
提醒接口契约见 [`docs/README_REMINDER_NOTIFICATION_API.md`](docs/README_REMINDER_NOTIFICATION_API.md)。

当前本地已完成一次真实联调：

- `reminder_worker -> TianAI1.5 /api/internal/notifications/reminders`
- 测试用户：`admin`
- 后端已返回 `accepted`

## Reminder Worker

单次扫描：

```bash
cd /Users/tianjunce/Projects/GitHub/TianCapability
conda activate Tian3.10_clean
python -m app.workers.reminder_worker --once
```

常驻轮询：

```bash
cd /Users/tianjunce/Projects/GitHub/TianCapability
conda activate Tian3.10_clean
python -m app.workers.reminder_worker --poll-seconds 10
```

默认会读取仓库根目录 [`.env.local`](/Users/tianjunce/Projects/GitHub/TianCapability/.env.local)：

```bash
REMINDER_NOTIFICATION_API_URL=http://<你的-backend>/api/internal/notifications/reminders
REMINDER_NOTIFICATION_API_TOKEN=<和 backend 一致的 token>
```

## 本地运行

```bash
cd /Users/tianjunce/Projects/GitHub/TianCapability
conda activate Tian3.10_clean
uvicorn app.main:app --reload --host 127.0.0.1 --port 8012
```

## 基础检查

```bash
curl http://127.0.0.1:8012/health
curl http://127.0.0.1:8012/capabilities
```

## 测试

```bash
cd /Users/tianjunce/Projects/GitHub/TianCapability
conda activate Tian3.10_clean
python -m unittest discover -s tests -p 'test_*.py'
```

当前回归结果：`86` 个测试通过。

## 调用示例

```bash
curl -X POST http://127.0.0.1:8012/capabilities/get_weather \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "city": "杭州",
      "date": "今天"
    },
    "context": {
      "request_id": "task-123",
      "session_id": "session-456",
      "user_id": "user-789",
      "progress_context": {
        "enabled": true,
        "protocol": "jsonl_file",
        "path": "/tmp/tianai-skill-progress.jsonl",
        "scope": "skill:get_weather"
      }
    }
  }'
```

## 平台约定摘要

- 请求统一为 `{input, context}`
- 响应统一为 `{status, data, error, meta}`
- endpoint 路径固定为 `/capabilities/{name}`
- AI runtime 当前会稳定提供 `request_id / session_id / user_id / progress_context`
- `HTTP 200` 表示业务成功或业务错误
- `HTTP 400/500/504` 表示平台级错误
- `progress_context` v1 继续使用 `jsonl_file`
- 用户级能力应以 `context.user_id` 作为隔离键，并存储在 capability-service 自己的业务目录或数据库中
- 不要依赖 AI runtime 的 `data/`、`memory/` 或其他内部目录做 capability 数据存储

更完整的规范、错误码约定、manifest 规则和测试要求，都在开发规范文档里。
