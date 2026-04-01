# get_volleyball_match_list

`get_volleyball_match_list` 用于查询排球相关数据。

它支持三类查询：

- 比赛列表查询
- 可用比赛日期查询
- 指定日期的球员统计查询

## Request

```json
{
  "input": {
    "query_type": "list",
    "page_num": 1,
    "page_size": 10
  },
  "context": {
    "request_id": "req-123",
    "session_id": "session-456",
    "user_id": "user-789",
    "progress_context": {
      "enabled": true,
      "protocol": "jsonl_file",
      "path": "/tmp/tianai-skill-progress.jsonl",
      "scope": "skill:get_volleyball_match_list"
    }
  }
}
```

说明：

- `query_type` 可选值：`list`、`dates`、`match_dates`、`available_dates`、`day_stat`
- 当传入 `match_date` 时，会优先执行指定日期统计查询
- 当 `query_type=day_stat` 时，必须提供 `match_date`
- `page_num`、`page_size` 仅对比赛列表查询生效

## Success Response

比赛列表查询：

```json
{
  "status": "success",
  "data": {
    "query_type": "list",
    "page_num": 1,
    "page_size": 10,
    "total": 25,
    "pages": 3,
    "available_dates": [
      "2026-03-28",
      "2026-03-29"
    ],
    "matches": [
      {
        "id": 1,
        "name": "周末友谊赛",
        "team_a_score": 3,
        "team_b_score": 1,
        "winner": "A队",
        "locked": 1,
        "scorekeeper_id": 2,
        "created_at": "2026-03-29 10:00:00"
      }
    ],
    "result": "排球比赛列表查询成功，第1页，每页10条，总数 25。部分结果：周末友谊赛（3:1，胜方 A队）。",
    "summary": "排球比赛列表查询成功，第1页，每页10条，总数 25。部分结果：周末友谊赛（3:1，胜方 A队）。"
  },
  "error": null,
  "meta": {
    "capability": "get_volleyball_match_list",
    "duration_ms": 120
  }
}
```

日期查询：

```json
{
  "status": "success",
  "data": {
    "query_type": "dates",
    "available_dates": [
      "2026-03-28",
      "2026-03-29"
    ],
    "result": "共有 2 个有比赛的日期，部分日期：2026-03-28, 2026-03-29。",
    "summary": "共有 2 个有比赛的日期，部分日期：2026-03-28, 2026-03-29。"
  },
  "error": null,
  "meta": {
    "capability": "get_volleyball_match_list",
    "duration_ms": 35
  }
}
```

指定日期统计查询：

```json
{
  "status": "success",
  "data": {
    "query_type": "day_stat",
    "match_date": "2026-03-29",
    "stats": [
      {
        "player_id": 1,
        "player_name": "张三",
        "match_date": "2026-03-29",
        "score_count": 12,
        "win_count": 2,
        "lose_count": 1,
        "scorekeeper_count": 1,
        "total_count": 3,
        "discount_count": 0,
        "result_count": 3,
        "actual_count": 3,
        "faqiu_count": 4,
        "erchuan_count": 2,
        "kouqiu_count": 6
      }
    ],
    "result": "2026-03-29 的排球每日统计查询成功，共 1 名球员。部分结果：张三（得分 12，胜 2，负 1，实记 3）。",
    "summary": "2026-03-29 的排球每日统计查询成功，共 1 名球员。部分结果：张三（得分 12，胜 2，负 1，实记 3）。"
  },
  "error": null,
  "meta": {
    "capability": "get_volleyball_match_list",
    "duration_ms": 40
  }
}
```

## Business Error Response

```json
{
  "status": "error",
  "data": null,
  "error": {
    "code": "volleyball_query_failed",
    "message": "404 Client Error"
  },
  "meta": {
    "capability": "get_volleyball_match_list",
    "duration_ms": 30
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
    "message": "field 'match_date' is required when query_type is 'day_stat'"
  },
  "meta": {
    "capability": "get_volleyball_match_list",
    "duration_ms": 1
  }
}
```

## Error Codes

- `invalid_input`
- `invalid_query_type`
- `volleyball_query_failed`
- `internal_error`

## HTTP Semantics

- `HTTP 200`：业务成功或业务错误
- `HTTP 400`：`invalid_request` / `invalid_input`
- `HTTP 500`：`internal_error` / `invalid_output`
- `HTTP 504`：`capability_timeout`

## Detail Steps

当前 capability 会按需上报以下 detail steps：

- `normalize_query_input` / `规范化查询参数`
- `fetch_volleyball_data` / `查询排球比赛数据`
- `format_volleyball_result` / `整理排球查询结果`

## Local Run

```bash
cd /Users/tianjunce/Projects/GitHub/TianCapability
conda activate Tian3.10_clean
uvicorn app.main:app --reload --host 127.0.0.1 --port 8012
```

## Curl Example

```bash
curl -X POST http://127.0.0.1:8012/capabilities/get_volleyball_match_list \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "query_type": "list",
      "page_num": 1,
      "page_size": 10
    },
    "context": {
      "request_id": "task-123",
      "session_id": "session-456",
      "user_id": "user-789",
      "progress_context": {
        "enabled": true,
        "protocol": "jsonl_file",
        "path": "/tmp/tianai-skill-progress.jsonl",
        "scope": "skill:get_volleyball_match_list"
      }
    }
  }'
```

## Minimum Test Cases

- success case：`query_type=list`
- success case：`query_type=dates`
- success case：`query_type=day_stat, match_date=2026-03-29`
- invalid_input case：`query_type=day_stat` 但缺少 `match_date`
- business_error case：上游接口异常
- progress case：开启 `progress_context` 并验证 JSONL 输出
