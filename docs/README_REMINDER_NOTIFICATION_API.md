# Reminder Notification API

这份文档定义 `TianCapability` 的 `reminder_worker` 调用 AI 助手侧统一提醒接口时使用的 API 契约。

目标很明确：

- `TianCapability` 只负责判断“哪条提醒到时间了”
- `TianCapability` 只调用一个统一提醒接口
- AI 助手侧自己决定后续如何分发，例如 UI、微信，或其他渠道

当前 v1 不做多渠道投递协议，不在 capability 侧拆渠道。

这份文档已经按当前 `TianAI1.5` 后端真实实现对齐，并在本地完成过一次真实联调。

## 1. 调用方式

- Method: `POST`
- Content-Type: `application/json`
- URL: 由环境变量 `REMINDER_NOTIFICATION_API_URL` 配置
- 可选鉴权：
  - 如果配置了 `REMINDER_NOTIFICATION_API_TOKEN`
  - 请求头会带 `Authorization: Bearer <token>`

## 1.1 Capability 侧配置位置

默认配置位置：

- [`.env.local`](/Users/tianjunce/Projects/GitHub/TianCapability/.env.local)

当前 worker 会按以下优先级读取：

- 进程环境变量
- 仓库根目录 `.env.local`
- 仓库根目录 `.env`

当前建议直接在 `.env.local` 中填写：

```bash
REMINDER_NOTIFICATION_API_URL=http://<你的-backend>/api/internal/notifications/reminders
REMINDER_NOTIFICATION_API_TOKEN=<和 backend 一致的 token>
```

## 2. 请求体

### 示例

```json
{
  "source": "reminder_worker",
  "user_id": "zhangsan",
  "title": "交电费",
  "content": "到点先看余额",
  "reminder_source": {
    "type": "set_reminder",
    "label": "自定义提醒"
  },
  "metadata": {
    "occurrence_id": "a7b5643a72974a5a8b64ef31eaf9b222",
    "source_type": "set_reminder",
    "source_label": "自定义提醒",
    "source_id": "2e3b9c6d0f4d4d5b89e3d4b4d7c9a111",
    "remind_at": "2026-04-02T09:00:00",
    "dedupe_key": "set_reminder:2e3b9c6d0f4d4d5b89e3d4b4d7c9a111:2026-04-02T09:00:00",
    "payload": {
      "content": "交电费",
      "note": "到点先看余额"
    }
  }
}
```

### 字段定义

#### 顶层字段

- `source: string`
  - 固定值：`reminder_worker`
  - 表示这次调用来自 capability 侧的提醒 worker

- `user_id: string`
  - 必填
  - 提醒目标用户名
  - 该值来自 capability 上下文里的 `context.user_id`
  - 字段名当前沿用 `user_id`，但在当前系统里它的实际语义就是用户名
  - 注意：不要改成 `username`
  - `TianAI1.5` 当前内部接口模型实际要求的字段名就是 `user_id`

- `title: string`
  - 必填
  - 提醒标题，适合直接展示在通知标题位置

- `content: string`
  - 必填
  - 提醒正文
  - 当前 `set_reminder` 的生成规则是：
    - 如果用户提供了 `note`，这里传 `note`
    - 如果没有 `note`，这里传提醒内容本身

- `reminder_source: object`
  - 必填
  - 表示这条提醒来自什么业务

#### `reminder_source`

- `type: string`
  - 必填
  - 机器可读的提醒来源类型
  - 当前已使用值：
    - `set_reminder`
  - 预留后续值：
    - `todo`
    - `birthday`
    - `idea`

- `label: string`
  - 必填
  - 面向用户展示的提醒来源文案
  - 当前示例：
    - `自定义提醒`
    - 后续可扩展为 `待办事项提醒`、`生日提醒`

#### `metadata`

- `occurrence_id: string`
  - 必填
  - 本次触发的提醒 occurrence 唯一 ID

- `source_type: string`
  - 必填
  - 与 `reminder_source.type` 等价
  - 保留在 metadata 中，便于兼容日志和内部处理

- `source_label: string`
  - 必填
  - 与 `reminder_source.label` 等价

- `source_id: string`
  - 必填
  - 业务主记录 ID
  - 例如提醒主记录 ID、待办 ID、生日记录 ID

- `remind_at: string`
  - 必填
  - 原始提醒时间，ISO 8601 本地时间格式
  - 示例：`2026-04-02T09:00:00`

- `dedupe_key: string`
  - 必填
  - 幂等去重 key
  - AI 助手侧建议按这个字段做防重

- `payload: object`
  - 必填
  - 原始业务载荷
  - 当前 `set_reminder` 至少包含：
    - `content`
    - `note`

## 3. AI 助手侧职责建议

AI 助手侧收到这条请求后，应负责：

- 判断最终如何提醒用户
- 决定是否发 UI、微信，或只发其中一路
- 记录自身的通知分发状态
- 结合 `dedupe_key` 做幂等

`TianCapability` 不关心最终渠道明细，只关心这次统一提醒接口调用是否成功。

## 4. 成功响应

### 成功判定

当前 capability 侧的成功判定非常简单：

- 任何 `HTTP 2xx` 都视为成功

建议 AI 助手侧返回 JSON。

### 推荐成功响应示例

```json
{
  "status": "accepted",
  "notification_id": "notif_123",
  "message": "queued"
}
```

### 当前本地联调结果

已经用以下条件实际打通过一次：

- 接口：`POST /api/internal/notifications/reminders`
- 顶层目标字段：`user_id=admin`
- reminder source：`set_reminder / 自定义提醒`
- 后端返回：

```json
{
  "status": "accepted",
  "notification_id": "notif_xxx",
  "message": "queued"
}
```

### 推荐字段

- `status: string`
  - 推荐值：`accepted`

- `notification_id: string`
  - 可选
  - AI 助手侧自己的通知记录 ID

- `message: string`
  - 可选
  - 简短说明，例如 `queued`

## 5. 失败语义

以下情况 capability 侧会记为失败：

- 非 `HTTP 2xx`
- 请求超时
- 网络错误

失败后：

- `occurrence.status` 会记为 `failed`
- `deliveries.json` 会写一条失败投递记录
- `last_error` 会记录错误信息

当前 v1 还没有自动重试策略。

## 6. 幂等建议

AI 助手侧建议至少按 `metadata.dedupe_key` 做幂等。

原因：

- capability worker 当前是单次扫描模型
- 后续加重试或重新扫描时，可能再次发送同一条 occurrence
- `dedupe_key` 是防止重复提醒用户的最稳定键

## 7. 当前已知 reminder_source 约定

当前实际已接入：

- `set_reminder` / `自定义提醒`

后续计划扩展：

- `todo` / `待办事项提醒`
- `birthday` / `生日提醒`
- `idea` / `灵感提醒`

AI 助手侧应按“未知 type 也能正常处理”的方式实现，不要写死只接受某一个值。

## 8. 当前实现位置

参考代码：

- capability 侧提醒创建：[app/services/reminder_service.py](/Users/tianjunce/Projects/GitHub/TianCapability/app/services/reminder_service.py)
- capability 侧提醒分发：[app/services/reminder_dispatch_service.py](/Users/tianjunce/Projects/GitHub/TianCapability/app/services/reminder_dispatch_service.py)
- worker 入口：[app/workers/reminder_worker.py](/Users/tianjunce/Projects/GitHub/TianCapability/app/workers/reminder_worker.py)
