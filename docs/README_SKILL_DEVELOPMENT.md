# Skill Development Guide

这份文档面向本仓库后续所有 skill 开发。

当前平台已经不是“只写 capability 就够了”的模式。

每开发一个新 skill，至少要同时交付三类产物：

1. `capability-service` 里的 capability 实现
2. 系统路由使用的 `SKILL.md`
3. 运行时调用配置使用的 `skill.json`

如果只写 capability，不补 `SKILL.md + skill.json`，系统很可能：

- 不会选中这个 skill
- 选中了也组不出正确参数
- 调用成功后拿不到稳定输出字段

## 1. 三个文件各自负责什么

### Capability

位置：

```text
app/capabilities/<skill_name>/
├── manifest.yaml
├── handler.py
└── README.md
```

职责：

- 定义真实执行能力
- 定义 HTTP 输入输出契约
- 定义稳定错误码
- 提供测试与 README

### SKILL.md

位置：

```text
TianAI1.5/backend/app/skills/<skill_name>/SKILL.md
```

职责：

- 顶部 `name` / `description` 给系统首轮路由提供语义依据
- 正文给 prepare 阶段提供参数抽取与归一化规则
- 帮助开发者把“路由提示”和“组参规则”分开写清楚

### skill.json

位置：

```text
TianAI1.5/backend/app/skills/<skill_name>/skill.json
```

职责：

- 告诉 runtime 如何把 `prepared_payload` 映射成 capability 请求
- 告诉 runtime 如何把 capability 成功响应映射成 skill 输出
- 定义 runner、超时、progress scope

## 2. 开发顺序

推荐按下面顺序开发：

1. 先定 capability 契约：`input`、`output`、错误码、超时
2. 再写 `SKILL.md`：顶部 `description` 怎么让系统选中它，正文怎么让 prepare 阶段准备参数
3. 最后写 `skill.json`：把 prepare 阶段的参数映射到 capability 输入，把 capability 输出映射回 skill 结果

不要反过来写。

如果 `SKILL.md` 先写得很宽，而 capability 实际没支持，系统会被误导。

如果 `skill.json` 先写了映射，而 capability 契约还没定，后面很容易反复返工。

## 3. SKILL.md 怎么写

### 3.1 顶部元数据必须存在

`SKILL.md` 开头第一段必须是连续的元数据块，至少包含：

```md
name: get_weather
description: 查询指定地点当前或未来 7 天内的天气，支持直接解析今天、明天、后天、周末、下周一、具体日期等日期表达，不需要上层先换算成具体年月日。
```

原因：

- 运行时扫描 catalog 时，只会先读顶部 `name` 和 `description`
- 如果这里缺失，skill 可能不会进入 catalog
- 如果这里写得太弱，系统初始路由阶段可能根本不会选中这个 skill

### 3.2 `description` 不是摘要，而是“首轮路由提示”

`description` 必须直接写出：

- 这个 skill 解决什么问题
- 支持哪些关键自然语言表达
- 是否需要上层先做归一化

不要只写这种泛描述：

```md
description: 查询天气信息。
```

这类描述对系统路由几乎没有帮助。

更好的写法：

```md
description: 查询指定地点当前或未来 7 天内的天气，支持直接解析今天、明天、后天、周末、下周一、具体日期等日期表达，不需要上层先换算成具体年月日。
```

### 3.3 正文不是给路由看的，而是给 prepare 阶段看的

这是后续写 `SKILL.md` 最容易混掉的一点。

系统当前的实际读取方式是：

- 交流脑只看顶部 `name` / `description`
- 执行脑在已经决定调用 skill 后，才看正文准备参数

这意味着：

- 正文不承担“让系统选中这个 skill”的职责
- 正文里反复写“什么请求应该进入这个 skill”运行时价值很低
- 如果你想强化首轮选中概率，应把关键信号写进 `description`

正文更应该聚焦：

- 要提取哪些槽位
- 槽位如何归一化
- 哪些信息缺失时要补问
- 哪些表达当前 capability 还不支持，不能硬凑参数

### 3.4 正文至少覆盖这几块

建议 `SKILL.md` 至少包含：

- 参数准备目标
- 常见原句与槽位映射
- 必要输入
- 归一化规则
- 当前能力边界
- 缺失信息处理
- 当前不要伪造成可执行参数的情况
- 执行结果要求
- 错误处理
- 当前 v1 执行入口

### 3.5 常见原句要服务于抽槽，不是重复做路由判断

不要只写抽象定义，要写真实用户句子，但这些句子的用途应该是帮助 prepare 阶段抽参数。

例如：

- `杭州今天天气如何`
- `北京周末天气怎么样`
- `我后天去西安，我应该穿什么衣服`

重点不是在正文里再说“它该不该进 `get_weather`”，而是明确：

- `location` 应抽成什么
- `date` 应抽成什么
- 哪部分话术只是上层回答时要继续利用的上下文

### 3.6 必须明确边界

边界要写的是“参数准备边界”，不是再重复一遍 skill 选择边界。

更准确地说，要写两类：

1. 哪些表达当前 capability 可以稳定转成参数
2. 哪些表达当前 capability 还不能稳定转成参数

例如 `get_weather`：

- 支持按天查询：`今天`、`后天`、`周末`
- 暂不支持按时段查询：`今晚 8 点`、`明天下午`

如果这一点不写清，prepare 阶段就容易把不支持的表达硬凑成参数。

### 3.7 composite intent 也要写成“参数视角”

很多用户问题不是“纯工具问题”，而是：

- `我后天去西安，我应该穿什么衣服`
- `北京周末会下雨吗，要不要带伞`

正文里更应该写清：

- 哪部分内容要提成 skill 参数
- 哪部分内容保留给上层继续生成最终回答

例如 `get_weather`：

- `location=西安`
- `date=后天`
- “穿什么衣服”不是 capability 输入，但上层后续回答仍可利用天气结果继续生成穿衣建议

## 4. skill.json 怎么写

### 4.1 当前 runner 只支持 `capability_http`

运行时代码当前只接受：

```json
{
  "runner": "capability_http"
}
```

其他 runner 现在不会跑通。

### 4.2 基本模板

```json
{
  "runner": "capability_http",
  "capability_name": "get_weather",
  "timeout_seconds": 20,
  "progress_scope": "skill:get_weather",
  "request_input": {
    "city": {
      "from": "prepared_payload.slots.location",
      "required": true
    },
    "date": {
      "from": "prepared_payload.slots.date",
      "default": "今天"
    }
  },
  "success_output": {
    "result": {
      "from": "data.summary",
      "required": true
    },
    "weather": {
      "from": "data.weather",
      "required": true
    }
  }
}
```

### 4.3 `request_input` 的语义

`request_input` 是把 runtime 的 source 映射到 capability `input`。

当前 source 可稳定使用的顶层字段包括：

- `user_id`
- `session_id`
- `trace_id`
- `task_id`
- `skill_name`
- `prepared_payload`

最常用的路径是：

- `prepared_payload.slots.xxx`
- `prepared_payload.constraints.xxx`
- `prepared_payload.context.xxx`

### 4.4 每个映射项都必须有 `from`

这是一个非常容易踩坑的点。

下面这种写法是错的：

```json
{
  "date": {
    "default": "今天"
  }
}
```

当前 runtime 会直接报错，因为每个映射项都必须有 `from`。

正确写法：

```json
{
  "date": {
    "from": "prepared_payload.slots.date",
    "default": "今天"
  }
}
```

### 4.5 `default` 和 `required` 的规则

当前行为是：

- 先按 `from` 取值
- 如果值缺失、为 `null`、或空字符串，再看 `default`
- 如果没有 `default`，且 `required=true`，则构建请求时报错
- 如果既不 `required`，也没有 `default`，这个字段会被忽略

### 4.6 `success_output` 的语义

`success_output` 是把 capability 成功响应 body 映射回 skill 输出。

source 直接是 capability 响应 JSON，例如：

```json
{
  "status": "success",
  "data": {
    "summary": "杭州今天晴",
    "weather": {}
  },
  "meta": {
    "capability": "get_weather"
  }
}
```

所以常见路径包括：

- `data.summary`
- `data.weather`
- `data.city_code`
- `data.matched_date`
- `meta.capability`

### 4.7 `timeout_seconds` 要和 capability 对齐

`skill.json` 里的 `timeout_seconds` 会直接决定 runtime 的 HTTP 调用超时。

它应该：

- 不小于 capability 的 `manifest.yaml` 超时
- 最好与 capability timeout 保持一致

否则容易出现：

- capability 还没超时，runtime 先断掉
- runtime 等太短，长链路能力无法完成

### 4.8 `progress_scope` 要稳定

推荐固定写成：

```json
"progress_scope": "skill:<skill_name>"
```

例如：

```json
"progress_scope": "skill:get_weather"
```

这样 capability 写出的 progress detail steps 才能和 skill 侧一致。

## 5. capability、SKILL.md、skill.json 三者如何保持一致

开发时至少检查这几项：

- `capability_name` 与 capability 目录名一致
- `SKILL.md` 顶部 `name` 与 skill 目录名一致
- `skill.json.request_input` 的字段名与 capability `input_schema` 一致
- `skill.json.success_output` 的路径与 capability 实际 success body 一致
- `SKILL.md` 声称支持的能力，capability 真的支持
- `SKILL.md` 声称不支持的能力，skill.json 不要偷偷透传对应字段

## 6. 设计原则

### 原则 1：路由描述要偏“能力边界”，不是偏“实现细节”

系统初始阶段通常只看 `description`，所以你要让它快速判断：

- 该不该选这个 skill
- 有没有必要先准备参数

### 原则 2：不要把未来想做的能力写成已经支持

如果 capability 只支持按天，不支持按小时，就不要在 `SKILL.md` 里写：

- `今晚8点`
- `明天下午`
- `周六上午`

### 原则 3：也不要把已经支持的表达漏掉

如果 capability 已经能直接解析：

- `后天`
- `周末`
- `下周一`

那 `description` 和正文里都要写出来。

否则系统可能会误判“没有换算后天是几号几日的功能”。

### 原则 4：skill 负责“选中”，capability 负责“真执行”

分工应该是：

- `SKILL.md`：让系统知道什么时候选这个 skill
- `skill.json`：把 prepare 结果稳定映射成请求
- capability：真正做参数解释、调用外部源、返回结构化结果

不要把 capability 已经能做的自然语言解析，又强行要求上层先做一遍。

## 7. 新 skill 开发 Checklist

每开发一个新 skill，至少检查：

- 已新增 `app/capabilities/<name>/manifest.yaml`
- 已新增 `app/capabilities/<name>/handler.py`
- 已新增 `app/capabilities/<name>/README.md`
- 已在系统侧新增 `SKILL.md`
- 已在系统侧新增 `skill.json`
- `SKILL.md` 顶部 `name` 和 `description` 完整
- `description` 直接写出核心自然语言表达
- `skill.json` 中每个映射项都有 `from`
- `request_input` / `success_output` 都不为空
- `timeout_seconds` 与 capability 对齐
- 至少准备 3 到 5 条真实用户句子做路由检查
- 至少准备 success / invalid_input / business_error / progress 用例

## 8. 推荐联调方式

联调一个新 skill 时，建议按下面顺序验证：

1. capability 本身用 `curl` 跑通
2. 确认 capability success body 与 `skill.json.success_output` 一致
3. 检查 `SKILL.md` 的 `description` 是否足够让系统在初始阶段选中它
4. 检查 prepare 阶段是否真的把参数放进了 `prepared_payload.slots`
5. 检查 runtime 最终构出的 capability request 是否符合 `manifest.yaml`

## 9. 参考实现

当前最完整的参考是：

- capability：`app/capabilities/get_weather/`
- system skill：`TianAI1.5/backend/app/skills/get_weather/`

后续新 skill 可以直接以它为模板，但必须根据自己的真实能力边界改写，不要复制后不做收敛。
