# Capability Development Spec

这份文档定义 `capability-service` 的平台开发规范。

目标不是描述某一个 capability，而是约束所有后续 capability 的统一边界、协议、目录、错误码和测试要求。

## 1. 平台边界

`capability-service` 只负责能力执行。

它负责：

- capability 的统一 HTTP 执行入口
- 参数校验后的业务执行
- 对外部平台 / 外部 API / providers / adapters 的调用
- 可选的 progress detail steps 上报

它不负责：

- session 管理
- trace / task 生命周期
- message 结构
- UI 渲染
- `need_input` 对话追问

这些都继续留在 AI runtime。

当前集成模型：

- 标准 skill 已收敛为 `SKILL.md + skill.json`
- AI runtime 直接调用 capability-service
- 不再走 `skill.py` / subprocess 桥接模式

## 2. 统一请求协议

所有 capability 必须接收同一外层请求壳：

```json
{
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
      "protocol": "redis",
      "key": "skill-progress:task-123",
      "scope": "skill:get_weather"
    }
  }
}
```

如果当前实例没有启用 Redis progress backend，AI runtime 会自动退回成：

```json
{
  "enabled": true,
  "protocol": "jsonl_file",
  "path": "/abs/path/to/progress.jsonl",
  "scope": "skill:get_weather"
}
```

规则：

- `input` 是 capability 自己的业务输入
- `context` 是平台级上下文
- `request_id` 必填
- AI runtime 当前会稳定传入 `request_id`、`session_id`、`user_id`、`progress_context`
- `session_id` 应视为运行时基线字段
- `user_id` 应视为运行时基线字段
- `progress_context` 是可选增强能力

说明：

- capability 可以忽略自己不需要的上下文字段
- 但如果 capability 有用户级业务数据，就应使用 `context.user_id` 做数据隔离

## 3. 统一响应协议

所有 capability 必须返回同一外层响应壳。

业务成功：

```json
{
  "status": "success",
  "data": {
    "city": "杭州",
    "date": "今天",
    "summary": "杭州今天晴，当前25°C，最高25°C，最低16°C。"
  },
  "error": null,
  "meta": {
    "capability": "get_weather",
    "duration_ms": 123
  }
}
```

业务错误：

```json
{
  "status": "error",
  "data": null,
  "error": {
    "code": "city_not_found",
    "message": "未找到城市代码: 杭州xx"
  },
  "meta": {
    "capability": "get_weather",
    "duration_ms": 123
  }
}
```

规则：

- `status` 在 v1 只允许 `success | error`
- `need_input` 不出现在 capability-service 协议里
- `error.code` 必须稳定且文档化
- 不接受只抛异常然后依赖 message 猜错误类型

## 4. HTTP 语义

平台级 HTTP 语义固定如下：

- `HTTP 200`：能力已正常执行，并返回业务成功或业务错误
- `HTTP 400`：`invalid_request` / `invalid_input`
- `HTTP 500`：`internal_error` / `invalid_output`
- `HTTP 504`：`capability_timeout`

平台错误示例：

```json
{
  "status": "error",
  "data": null,
  "error": {
    "code": "invalid_input",
    "message": "'city' is a required property"
  },
  "meta": {
    "capability": "get_weather",
    "duration_ms": 2
  }
}
```

## 5. progress 协议

`progress_context` 是增强项，不是所有 capability 都必须支持。

v1 保留：

```json
{
  "enabled": true,
  "protocol": "redis",
  "key": "skill-progress:task-123",
  "scope": "skill:get_weather"
}
```

并兼容回退形式：

```json
{
  "enabled": true,
  "protocol": "jsonl_file",
  "path": "/abs/path/to/progress.jsonl",
  "scope": "skill:get_weather"
}
```

事件格式：

```json
{"op":"upsert","step_id":"resolve_city_code","label":"解析城市编码","status":"running"}
{"op":"upsert","step_id":"resolve_city_code","label":"解析城市编码","status":"success"}
```

规则：

- `progress_context` 是临时写入通道，不是持久化存储
- `protocol` 字段必须保留，不能只传 `path` 或 `key`
- capability-service 只负责写 detail steps
- 不支持 progress 的 capability 也必须能正常执行
- 当前 capability-service 应至少兼容：
  - `protocol=redis`
  - `protocol=jsonl_file`

## 6. 用户隔离与数据存储

AI runtime 现在已经稳定提供 `context.user_id`。

这意味着：

- capability-service 可以正式按用户隔离业务数据
- 用户级能力应以 `context.user_id` 作为主隔离键
- `context.session_id` 可以作为会话级辅助维度，但不替代用户归属

存储边界要求：

- capability-service 自己负责业务数据存储
- 运行时默认优先使用 capability-service 自己的 MySQL 业务表
- `CAPABILITY_DATA_DIR` 或显式 `CAPABILITY_STORAGE_BACKEND=json` 只作为测试 / 本地文件模式回退
- 不依赖 AI runtime 的 `data/`、`memory/` 或其他内部目录
- 不把 capability 的持久化数据写回 AI runtime 仓库

适用场景示例：

- memo
- todo
- 收藏
- 用户偏好配置

## 7. 错误码规范

平台级错误码固定集合：

- `invalid_request`
- `invalid_input`
- `invalid_output`
- `internal_error`
- `capability_timeout`

业务错误码规则：

- 由各 capability 自己定义
- 必须稳定
- 必须写进该 capability 的 README
- 必须能区分主要失败场景

示例：

- `city_not_found`
- `weather_fetch_failed`
- `weather_parse_failed`

## 8. 目录规范

一个 capability = 一个目录。

最小结构：

```text
app/capabilities/<name>/
├── manifest.yaml
├── handler.py
└── README.md
```

允许共享：

- `clients/`
- `providers/`
- `adapters/`
- `utils/`

不允许共享：

- 具体 capability 的业务编排逻辑

## 9. manifest 规范

每个 capability 的 `manifest.yaml` 至少要定义：

- `name`
- `kind`
- `description`
- `path`
- `timeout_seconds`
- `supports_progress`
- `input_schema`
- `output_schema`

示例：

```yaml
name: get_weather
kind: tool
description: 获取指定城市的天气信息

path: /capabilities/get_weather
method: POST
timeout_seconds: 10
supports_progress: true

input_schema:
  type: object
  additionalProperties: false
  properties:
    city:
      type: string
      minLength: 1
    date:
      type: string
      minLength: 1
  required:
    - city

output_schema:
  type: object
  additionalProperties: false
  properties:
    city:
      type: string
    date:
      type: string
    city_code:
      type: string
    weather:
      type: object
    summary:
      type: string
  required:
    - city
    - date
    - city_code
    - weather
    - summary
```

规则：

- endpoint 路径固定为 `/capabilities/{name}`
- `input_schema` / `output_schema` 必须与实现保持一致
- manifest 是 capability 的平台契约，不是仅供文档展示

## 10. 开发者 README 规范

每个 capability 的 `README.md` 至少要包含：

- 输入示例
- 成功响应示例
- 平台错误示例或说明
- 业务错误示例
- 错误码列表
- progress steps 说明（如果支持）
- 本地运行方式
- `curl` 调用示例
- 最小测试用例说明

要求：

- 示例优先，不要只写抽象字段名
- 错误码必须文档化
- progress 是增强项，要写清是否支持

## 11. 测试规范

每个 capability 至少要覆盖：

- `success case`
- `invalid_input case`
- `业务错误 case`
- `progress 开启 case`（如果 `supports_progress=true`）

建议测试形态：

- handler 级单测
- API 级集成测试
- progress 文件输出测试

## 12. 版本与兼容

- v1 先稳定 `{input, context}` / `{status, data, error, meta}` 外壳
- 不频繁改外层协议
- 如果以后字段变化，优先通过 manifest / config 映射兼容
- 不要把映射逻辑重新散落回 AI runtime 主链

## 13. 当前共识

- capability-service 已经是 AI runtime 的统一执行后端
- 后续新能力默认按本规范开发
- 不再回退到 `skill.py` 模式

## 14. 开工清单

新建一个 capability 时，至少完成以下内容：

1. 新建 `app/capabilities/<name>/`
2. 编写 `manifest.yaml`
3. 编写 `handler.py`
4. 编写 `README.md`
5. 补齐 success / invalid_input / business_error / progress 用例
6. 确认错误码稳定、可文档化、可复用
