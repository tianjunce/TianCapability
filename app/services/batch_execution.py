from __future__ import annotations

from typing import Any, Awaitable, Callable, Type


async def execute_batch(
    *,
    action: str,
    items: list[dict[str, Any]],
    execute_item: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    validation_error_cls: Type[Exception],
    summary_label: str,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    success_count = 0
    failure_count = 0

    for index, item in enumerate(items):
        try:
            item_result = await execute_item(item)
        except validation_error_cls as exc:  # type: ignore[misc]
            error_code = str(getattr(exc, "code", "invalid_input"))
            error_message = str(getattr(exc, "message", str(exc)))
            results.append(
                {
                    "index": index,
                    "status": "error",
                    "error": {
                        "code": error_code,
                        "message": error_message,
                    },
                }
            )
            failure_count += 1
            continue

        results.append(
            {
                "index": index,
                "status": "success",
                "data": item_result,
            }
        )
        success_count += 1

    if failure_count == 0:
        summary = f"批量{summary_label}完成：{success_count} 条全部成功。"
    elif success_count == 0:
        summary = f"批量{summary_label}完成：{failure_count} 条全部失败。"
    else:
        summary = f"批量{summary_label}完成：成功 {success_count} 条，失败 {failure_count} 条。"

    return {
        "action": action,
        "batch": True,
        "item_count": len(items),
        "success_count": success_count,
        "failure_count": failure_count,
        "results": results,
        "summary": summary,
    }
