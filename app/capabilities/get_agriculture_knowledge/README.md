# get_agriculture_knowledge

`get_agriculture_knowledge` 用于查询农业知识库。

当前支持三类知识库：

- `rice`
- `morel`
- `dzjym`

当前实现会：

- 调用 `http://115.239.197.198:8688/login` 获取 token
- 调用 `http://115.239.197.198:8688/chat/api/knowledge/query`
- 使用 `kb_type` 作为上游接口的 `project`
- 使用 `query` 作为上游接口的 `message`

当前版本不使用 Redis 缓存 token。
