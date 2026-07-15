# get_base_basic_data

`get_base_basic_data` 是基地级查询能力。输入优先使用 `area_id`；仅提供 `area_name` 时，先从当前用户可见基地中解析出唯一 `area.id`，随后仍按基地 ID 查询。

## 查询模式

当前能力只有 `areaMode`，不提供设备运维模式。天气、生育期和生育期 preset 分别调用：

- `/screen/getAreaMet`
- `/aipp/area-rice-stage`
- `/aipp/area-device-presets`

有 `area_id` 时绝不因接口失败而回退到 `Area.met_num`、`Area.ricestage_num` 或 `monitor_num`。返回中的 `device_refs` 仅保留为当前配置展示和旧调用方兼容，不用于天气或生育期历史查询。虫情与农事建议尚不属于 WEATHER/RICE_STAGE 绑定履历范围，继续使用其既有设备字段和接口。

该能力当前不查询截图和生育期范围。需要这些模块的基地级调用方应分别使用 `/aipp/area-screenshots` 和 `/aipp/area-rice-stage-boundaries/active`；范围的 `date` 使用后端 `END_OF_DAY` 语义。旧设备号接口仍由 RiceAI 保留给设备运维和旧直达场景，本能力不调用。

## 日期语义

`start_date`、`end_date` 格式均为本地日期 `YYYY-MM-DD`，对调用方保持两端按自然日包含。调用历史接口时转换为半开区间：

```text
[start_date 00:00:00, end_date + 1 day 00:00:00)
```

不使用 `23:59:59`，也不经过 UTC 转换。preset 使用 `end_date` 查询该自然日有效设备的点位。

## 返回和异常

原有天气、生育期、虫情、农事建议和紧凑时间轴字段保持不变；新增可选的 `query_mode=area`、`module_statuses`，天气和生育期块也附带 `binding_status` 与 `coverage`。

- `NORMAL`：正常返回。
- `PARTIAL_COVERAGE`：保留已有数据并增加 warning。
- `NOT_CONFIGURED`：返回空数据和明确状态。
- `NEEDS_REVIEW`：返回空的生育期相关块，不使用当前设备字段兜底。
- `DATA_INCONSISTENT`：停止使用该模块数据并返回明确状态。
- `NO_PERMISSION`、`AREA_NOT_FOUND`：保留稳定错误状态和 warning。

单个模块失败不会清空其他模块。已知异常基地缺少可信 RICE_STAGE 履历时，天气仍可返回，生育期和 preset 返回 `NEEDS_REVIEW`。本能力不读取 `monitor_num`。
