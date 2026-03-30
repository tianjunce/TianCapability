# get_weather

`get_weather` 是 capability-service 的示例 capability。

它负责：

- 根据城市名解析天气城市编码
- 抓取 `weather.com.cn` 的天气页面
- 解析并整理结果
- 可选上报 detail steps

## Request

```json
{
  "input": {
    "city": "杭州",
    "date": "今天"
  },
  "context": {
    "request_id": "req-123",
    "session_id": "session-456",
    "user_id": "user-789",
    "progress_context": {
      "enabled": true,
      "protocol": "jsonl_file",
      "path": "/tmp/tianai-skill-progress.jsonl",
      "scope": "skill:get_weather"
    }
  }
}
```

`get_weather` 当前是无状态 capability，不依赖用户级持久化数据，但仍应接受并透传 `request_id`、`session_id`、`user_id`、`progress_context` 这组平台上下文。

## Success Response

```json
{
  "status": "success",
  "data": {
    "city": "杭州",
    "date": "今天",
    "city_code": "101210101",
    "weather": {
      "weather": "晴",
      "temp_current": "25",
      "temp_high_day": "25",
      "temp_low_night": "16"
    },
    "summary": "杭州今天晴，当前25°C，最高25°C，最低16°C。"
  },
  "error": null,
  "meta": {
    "capability": "get_weather",
    "duration_ms": 123
  }
}
```

## Business Error Response

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
    "duration_ms": 12
  }
}
```

## Platform Error Response

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

## Error Codes

- `invalid_input`
- `city_not_found`
- `weather_fetch_failed`
- `weather_parse_failed`
- `internal_error`

## HTTP Semantics

- `HTTP 200`：业务成功或业务错误
- `HTTP 400`：`invalid_request` / `invalid_input`
- `HTTP 500`：`internal_error` / `invalid_output`
- `HTTP 504`：`capability_timeout`

## Detail Steps

当前 capability 会按需上报以下 detail steps：

- `resolve_city_code` / `解析城市编码`
- `fetch_weather_source` / `查询天气源`
- `format_weather_result` / `整理天气结果`

## Local Run

```bash
cd /Users/tianjunce/Projects/GitHub/TianCapability
conda activate Tian3.10_clean
uvicorn app.main:app --reload --host 127.0.0.1 --port 8012
```

## Curl Example

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

## Minimum Test Cases

- success case：`city=杭州`
- invalid_input case：缺少 `city`
- business_error case：`city=不存在的城市`
- progress case：开启 `progress_context` 并验证 JSONL 输出
