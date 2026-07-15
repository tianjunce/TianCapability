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

天气接口优先解析 `/screen/getAreaMet` 的 `rows[].metrics` 结构，并继续输出兼容的 `temp`、`hum` 三序列。`coverage.status` 与 `binding_status` 只表示设备绑定履历覆盖；`data_status` 独立表示实际温湿度数据完整度（`NORMAL`、`PARTIAL_DATA`、`NO_DATA`）。空值保持为 `null`，不会转换成 `0`。

天气指标先识别四情语义 key（`airTemperature` / `air_temperature`、`airHumidity` / `air_humidity`），再按 `sensorName` 识别管控指标（空气/环境/大气温度与湿度）。`sensor_N` 仅是设备内位置，不用于推断业务类型；`sort` 也不单独参与分类，因此传感器顺序变化不会改变温湿度归类。数值 `0`、`0.0` 均属于有效数据，只有 `None` 视为空值。

生育期概览当前仍使用 `/aipp/area-device-presets` 返回的第一项 preset，并在 `rice_stage_overview` 中通过 `preset_selection=FIRST_AVAILABLE` 明确该策略，同时返回完整 `available_presets`。概览结果只代表所选第一点位，不代表所有点位；本轮不新增 preset 输入参数。

## 返回和异常

原有天气、生育期、虫情、农事建议和紧凑时间轴字段保持不变；新增可选的 `query_mode=area`、`module_statuses`，天气和生育期块也附带 `binding_status` 与 `coverage`。天气块额外提供 `data_status`、`latest_data_date`、`data_date_count`、`empty_date_count` 和可选的 `schema_warnings`。

- `NORMAL`：正常返回。
- `PARTIAL_COVERAGE`：保留已有数据并增加 warning。
- `NOT_CONFIGURED`：返回空数据和明确状态。
- `NEEDS_REVIEW`：返回空的生育期相关块，不使用当前设备字段兜底。
- `DATA_INCONSISTENT`：停止使用该模块数据并返回明确状态。
- `NO_PERMISSION`、`AREA_NOT_FOUND`：保留稳定错误状态和 warning。

单个模块失败不会清空其他模块。当 RiceAI 接口实时返回 RICE_STAGE `NEEDS_REVIEW` 时，天气仍可返回，生育期和 preset 返回空块；Capability 不按固定 `area_id` 推断异常状态。本能力不读取 `monitor_num`。
