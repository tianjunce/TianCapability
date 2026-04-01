from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import uuid4

from app.services.lunar_calendar import (
    LunarCalendarError,
    find_next_lunar_date,
    lunar_date_to_solar,
    validate_lunar_month_day,
)
from app.services.repositories import BirthdayRepository, ReminderOccurrenceRepository


_DATE_WITH_YEAR_PATTERNS = (
    re.compile(r"^(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})$"),
    re.compile(r"^(?P<year>\d{4})/(?P<month>\d{1,2})/(?P<day>\d{1,2})$"),
    re.compile(r"^(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日?$"),
)
_MONTH_DAY_PATTERNS = (
    re.compile(r"^(?P<month>\d{1,2})-(?P<day>\d{1,2})$"),
    re.compile(r"^(?P<month>\d{1,2})/(?P<day>\d{1,2})$"),
    re.compile(r"^(?P<month>\d{1,2})月(?P<day>\d{1,2})日?$"),
)
_BIRTHDAY_REMINDER_TIME = time(9, 0, 0)


class BirthdayValidationError(RuntimeError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class BirthdayService:
    def __init__(
        self,
        *,
        birthday_repository: BirthdayRepository | None = None,
        occurrence_repository: ReminderOccurrenceRepository | None = None,
    ) -> None:
        self.birthday_repository = birthday_repository or BirthdayRepository()
        self.occurrence_repository = occurrence_repository or ReminderOccurrenceRepository()

    def create_birthday(
        self,
        *,
        user_id: str,
        name: str,
        birthday: str,
        calendar_type: str | None = None,
        birth_year: Any = None,
        is_leap_month: Any = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        normalized_name = str(name or "").strip()
        normalized_birthday = str(birthday or "").strip()
        normalized_calendar_type = _normalize_calendar_type(calendar_type)
        normalized_birth_year = _normalize_birth_year(birth_year)
        normalized_is_leap_month = _normalize_is_leap_month(is_leap_month)
        normalized_notes = str(notes or "").strip() or None

        if not normalized_user_id:
            raise BirthdayValidationError(code="invalid_request", message="context.user_id is required")
        if not normalized_name:
            raise BirthdayValidationError(code="invalid_input", message="field 'name' is required")
        if not normalized_birthday:
            raise BirthdayValidationError(code="invalid_input", message="field 'birthday' is required")

        parsed_birthday = _parse_birthday_value(
            value=normalized_birthday,
            calendar_type=normalized_calendar_type,
            is_leap_month=normalized_is_leap_month,
        )
        resolved_birth_year = _resolve_birth_year(
            explicit_birth_year=normalized_birth_year,
            inferred_birth_year=parsed_birthday["birth_year"],
        )

        created_at_value = _now()
        next_birthday_date, reminder_plan = _build_next_birthday_schedule(
            calendar_type=normalized_calendar_type,
            month=parsed_birthday["month"],
            day=parsed_birthday["day"],
            is_leap_month=normalized_is_leap_month,
            reference_now=created_at_value,
        )

        birthday_id = uuid4().hex
        created_at = created_at_value.isoformat(timespec="seconds")
        occurrence_ids: list[str] = []
        calendar_display = _format_calendar_display(
            calendar_type=normalized_calendar_type,
            birthday_value=parsed_birthday["birthday"],
            is_leap_month=normalized_is_leap_month,
        )

        birthday_record = {
            "id": birthday_id,
            "user_id": normalized_user_id,
            "name": normalized_name,
            "birthday": parsed_birthday["birthday"],
            "calendar_type": normalized_calendar_type,
            "birth_year": resolved_birth_year,
            "is_leap_month": normalized_is_leap_month,
            "notes": normalized_notes,
            "status": "active",
            "next_birthday": next_birthday_date.isoformat(),
            "occurrence_ids": [],
            "reminder_plan": reminder_plan,
            "created_at": created_at,
            "updated_at": created_at,
        }

        for plan_item in reminder_plan:
            occurrence_id = uuid4().hex
            occurrence_ids.append(occurrence_id)
            self.occurrence_repository.create(
                {
                    "id": occurrence_id,
                    "user_id": normalized_user_id,
                    "source_type": "birthday",
                    "source_label": "生日提醒",
                    "source_id": birthday_id,
                    "remind_at": plan_item["remind_at"],
                    "title": f"{normalized_name}生日提醒",
                    "content": _build_birthday_occurrence_content(
                        name=normalized_name,
                        stage_label=plan_item["label"],
                        birthday_date=next_birthday_date,
                        calendar_display=calendar_display,
                        notes=normalized_notes,
                    ),
                    "payload_json": {
                        "name": normalized_name,
                        "birthday": parsed_birthday["birthday"],
                        "calendar_type": normalized_calendar_type,
                        "birth_year": resolved_birth_year,
                        "is_leap_month": normalized_is_leap_month,
                        "birthday_date": next_birthday_date.isoformat(),
                        "stage": plan_item["stage"],
                        "stage_label": plan_item["label"],
                        "notes": normalized_notes,
                    },
                    "dedupe_key": f"birthday:{birthday_id}:{plan_item['stage']}:{plan_item['remind_at']}",
                    "status": "pending",
                    "created_at": created_at,
                    "updated_at": created_at,
                }
            )

        birthday_record["occurrence_ids"] = occurrence_ids
        self.birthday_repository.create(birthday_record)

        summary = (
            f"已记录生日：{normalized_name}，按{calendar_display}提醒，"
            f"下一次生日是 {next_birthday_date.isoformat()}，并生成 {len(occurrence_ids)} 条提醒。"
        )

        return {
            "birthday_id": birthday_id,
            "name": normalized_name,
            "birthday": parsed_birthday["birthday"],
            "calendar_type": normalized_calendar_type,
            "birth_year": resolved_birth_year,
            "is_leap_month": normalized_is_leap_month,
            "notes": normalized_notes,
            "status": "active",
            "next_birthday": next_birthday_date.isoformat(),
            "occurrence_ids": occurrence_ids,
            "reminder_plan": reminder_plan,
            "summary": summary,
        }


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _normalize_calendar_type(value: str | None) -> str:
    normalized_value = str(value or "solar").strip().lower()
    if normalized_value in {"solar", "gregorian", "公历", "陽曆", "阳历"}:
        return "solar"
    if normalized_value in {"lunar", "chinese_lunar", "农历", "農曆", "阴历", "陰曆"}:
        return "lunar"
    raise BirthdayValidationError(code="invalid_calendar_type", message="calendar_type must be solar or lunar")


def _normalize_birth_year(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        normalized_value = int(value)
    except (TypeError, ValueError) as exc:
        raise BirthdayValidationError(code="invalid_birth_year", message="birth_year must be an integer") from exc
    if normalized_value < 1 or normalized_value > 9999:
        raise BirthdayValidationError(code="invalid_birth_year", message="birth_year must be in 1..9999")
    return normalized_value


def _normalize_is_leap_month(value: Any) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, bool):
        return value
    normalized_value = str(value).strip().lower()
    if normalized_value in {"true", "1", "yes", "y", "是"}:
        return True
    if normalized_value in {"false", "0", "no", "n", "否"}:
        return False
    raise BirthdayValidationError(code="invalid_input", message="is_leap_month must be a boolean")


def _parse_birthday_value(
    *,
    value: str,
    calendar_type: str,
    is_leap_month: bool,
) -> dict[str, int | str | None]:
    parsed = _extract_birthday_parts(value)
    month = parsed["month"]
    day = parsed["day"]
    year = parsed["year"]

    if calendar_type == "solar":
        if year is not None:
            try:
                date(year, month, day)
            except ValueError as exc:
                raise BirthdayValidationError(code="invalid_birthday", message="不支持的阳历生日格式") from exc
        else:
            try:
                date(2000, month, day)
            except ValueError as exc:
                raise BirthdayValidationError(code="invalid_birthday", message="不支持的阳历生日格式") from exc
    else:
        try:
            if year is not None:
                lunar_date_to_solar(year, month, day, is_leap_month=is_leap_month)
            else:
                validate_lunar_month_day(month=month, day=day, is_leap_month=is_leap_month)
        except LunarCalendarError as exc:
            raise BirthdayValidationError(code="invalid_birthday", message=str(exc)) from exc

    return {
        "birthday": f"{month:02d}-{day:02d}",
        "month": month,
        "day": day,
        "birth_year": year,
    }


def _extract_birthday_parts(value: str) -> dict[str, int | None]:
    for pattern in _DATE_WITH_YEAR_PATTERNS:
        matched = pattern.match(value)
        if matched is None:
            continue
        return {
            "year": int(matched.group("year")),
            "month": int(matched.group("month")),
            "day": int(matched.group("day")),
        }

    for pattern in _MONTH_DAY_PATTERNS:
        matched = pattern.match(value)
        if matched is None:
            continue
        return {
            "year": None,
            "month": int(matched.group("month")),
            "day": int(matched.group("day")),
        }

    raise BirthdayValidationError(
        code="invalid_birthday",
        message="不支持的生日格式，请使用 MM-DD 或 YYYY-MM-DD",
    )


def _resolve_birth_year(
    *,
    explicit_birth_year: int | None,
    inferred_birth_year: int | None,
) -> int | None:
    if explicit_birth_year is None:
        return inferred_birth_year
    if inferred_birth_year is None:
        return explicit_birth_year
    if explicit_birth_year != inferred_birth_year:
        raise BirthdayValidationError(code="invalid_birth_year", message="birth_year 与 birthday 中的年份不一致")
    return explicit_birth_year


def _build_next_birthday_schedule(
    *,
    calendar_type: str,
    month: int,
    day: int,
    is_leap_month: bool,
    reference_now: datetime,
) -> tuple[date, list[dict[str, str]]]:
    search_from = reference_now.date()

    for _ in range(20):
        birthday_date = _find_next_birthday_date(
            calendar_type=calendar_type,
            month=month,
            day=day,
            is_leap_month=is_leap_month,
            on_or_after=search_from,
        )
        reminder_plan = _build_birthday_reminder_plan(
            birthday_date=birthday_date,
            reference_now=reference_now,
        )
        if reminder_plan:
            return birthday_date, reminder_plan
        search_from = birthday_date + timedelta(days=1)

    raise BirthdayValidationError(code="birthday_schedule_unavailable", message="无法在支持范围内生成生日提醒")


def _find_next_birthday_date(
    *,
    calendar_type: str,
    month: int,
    day: int,
    is_leap_month: bool,
    on_or_after: date,
) -> date:
    if calendar_type == "solar":
        year = on_or_after.year
        while year <= 9999:
            try:
                candidate = date(year, month, day)
            except ValueError:
                year += 1
                continue
            if candidate >= on_or_after:
                return candidate
            year += 1
        raise BirthdayValidationError(code="birthday_schedule_unavailable", message="无法生成下一个阳历生日")

    try:
        return find_next_lunar_date(
            month=month,
            day=day,
            is_leap_month=is_leap_month,
            on_or_after=on_or_after,
        )
    except LunarCalendarError as exc:
        raise BirthdayValidationError(code="birthday_schedule_unavailable", message=str(exc)) from exc


def _build_birthday_reminder_plan(
    *,
    birthday_date: date,
    reference_now: datetime,
) -> list[dict[str, str]]:
    birthday_datetime = datetime.combine(birthday_date, _BIRTHDAY_REMINDER_TIME)
    candidates = (
        ("birthday_minus_7_days", "生日前7天提醒", birthday_datetime - timedelta(days=7)),
        ("birthday_minus_1_day", "生日前1天提醒", birthday_datetime - timedelta(days=1)),
    )

    plan: list[dict[str, str]] = []
    for stage, label, remind_at_value in candidates:
        if remind_at_value < reference_now:
            continue
        plan.append(
            {
                "stage": stage,
                "label": label,
                "remind_at": remind_at_value.isoformat(timespec="seconds"),
                "birthday_date": birthday_date.isoformat(),
            }
        )
    return plan


def _format_calendar_display(
    *,
    calendar_type: str,
    birthday_value: str,
    is_leap_month: bool,
) -> str:
    if calendar_type == "solar":
        return f"阳历 {birthday_value}"
    if is_leap_month:
        return f"农历 闰{birthday_value}"
    return f"农历 {birthday_value}"


def _build_birthday_occurrence_content(
    *,
    name: str,
    stage_label: str,
    birthday_date: date,
    calendar_display: str,
    notes: str | None,
) -> str:
    content = f"{stage_label}：{name} 的生日是 {birthday_date.isoformat()}（{calendar_display}）。"
    if notes:
        content = f"{content} 备注：{notes}"
    return content
