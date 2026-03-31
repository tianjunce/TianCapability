# get_weather

`get_weather` 是 capability-service 的示例 capability。

它负责：

- 根据城市名解析天气城市编码
- 优先抓取中国气象局 `weather.cma.cn` 的城市详情页
- 在 CMA 站点拦截或解析失败时回退到 `weather.com.cn`
- 支持按日期表达选择未来 7 天内的目标天气
- 解析并整理结果
- 可选上报 detail steps

当前稳定支持的 `date` 表达包括：

- `今天`
- `明天`
- `后天`
- `大后天`
- `3天后`
- `最近`
- `最近几天` / `最近这几天` / `近几天`
- `最近一周` / `未来一周` / `这一周`
- `这周` / `本周` / `这个星期`
- `周一` / `星期一` / `礼拜一`
- `本周六` / `这周日`
- `下周一`
- `周末` / `本周末` / `下周末`
- `2026-04-04`
- `04-04`

当前还不稳定支持：

- `今晚 8 点`
- `明天下午`
- `周六上午`

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
    "date": "周末",
    "matched_date": "2026-04-04 ~ 2026-04-05",
    "city_code": "58457",
    "weather": {
      "weather": "晴 / 多云",
      "temp_current": "22",
      "temp_high_day": "24",
      "temp_low_night": "12"
    },
    "forecast_days": [
      {
        "date": "2026-04-04",
        "weekday": "周六",
        "weather": "晴",
        "temp_current": "22",
        "temp_high_day": "22",
        "temp_low_night": "12"
      },
      {
        "date": "2026-04-05",
        "weekday": "周日",
        "weather": "多云",
        "temp_current": "24",
        "temp_high_day": "24",
        "temp_low_night": "15"
      }
    ],
    "summary": "杭州周末天气：4月4日（周六）晴，12~22°C；4月5日（周日）多云，15~24°C。",
    "source": "cma"
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
- `date_not_supported`
- `date_out_of_range`
- `weather_fetch_failed`
- `weather_parse_failed`
- `internal_error`

## Source Notes

- 当前实现会先尝试解析 `https://weather.cma.cn/web/text/area.html` 与省级文字页，动态发现城市详情页，再从 `https://weather.cma.cn/web/weather/<city_code>.html` 提取天气信息。
- 当 `date` 命中单日时，返回单日天气；当 `date` 命中范围表达（例如 `周末`）时，`forecast_days` 会包含多天结果。
- 请求开始时会先按城市名别名读取当日缓存，例如 `杭州` 与 `杭州市` 可以命中同一份缓存；只有缓存未命中时才继续解析城市并访问上游天气站点。
- 同一城市在同一天内成功抓到过 CMA 主链路返回的完整 7 天预报后，会直接复用本地缓存，不会重复请求上游天气站点。
- 缓存文件固定写入 `app/capabilities/get_weather/.cache/forecast-cache.json`，便于排查与手动管理。
- 读取或写入缓存时会自动清掉非当天条目，缓存文件不会无限累积。
- 如果 CMA 站点对当前请求环境返回拦截页，或页面结构无法解析，会自动回退到现有 `weather.com.cn` 逻辑；回退结果只用于当前请求，不写入缓存，避免把降级数据误当成完整 7 天缓存。
- 因为存在回退路径，返回里的 `city_code` 可能是 CMA 城市页编码，例如 `58457`，也可能是旧源编码，例如 `101210101`。

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
      "date": "周末"
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
- recent_days case：`date=最近几天`
- this_week case：`date=这周`
- exact_date case：`date=2026-04-04`
- weekend case：`date=周末`
- relative_date case：`date=明天`
- cma_parse case：验证 7 天预报首页与逐小时温度提取
- fallback case：CMA 抓取失败时自动回退旧天气源
- invalid_input case：缺少 `city`
- date_not_supported case：`date=今晚8点`
- date_out_of_range case：`date=下周末`
- business_error case：`city=不存在的城市`
- progress case：开启 `progress_context` 并验证 JSONL 输出
