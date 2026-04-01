from __future__ import annotations

from datetime import date, timedelta

"""
Portions of this module are adapted from cnlunardate (MIT License),
Copyright (c) 2019 Y.B. Pan.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


MIN_LUNAR_YEAR = 1900
MAX_LUNAR_YEAR = 2100

_LUNAR_YEAR_DATA = [
    0x04BD8, 0x04AE0, 0x0A570, 0x054D5, 0x0D260, 0x0D950, 0x16554, 0x056A0, 0x09AD0, 0x055D2,
    0x04AE0, 0x0A5B6, 0x0A4D0, 0x0D250, 0x1D255, 0x0B540, 0x0D6A0, 0x0ADA2, 0x095B0, 0x14977,
    0x04970, 0x0A4B0, 0x0B4B5, 0x06A50, 0x06D40, 0x1AB54, 0x02B60, 0x09570, 0x052F2, 0x04970,
    0x06566, 0x0D4A0, 0x0EA50, 0x06E95, 0x05AD0, 0x02B60, 0x186E3, 0x092E0, 0x1C8D7, 0x0C950,
    0x0D4A0, 0x1D8A6, 0x0B550, 0x056A0, 0x1A5B4, 0x025D0, 0x092D0, 0x0D2B2, 0x0A950, 0x0B557,
    0x06CA0, 0x0B550, 0x15355, 0x04DA0, 0x0A5B0, 0x14573, 0x052B0, 0x0A9A8, 0x0E950, 0x06AA0,
    0x0AEA6, 0x0AB50, 0x04B60, 0x0AAE4, 0x0A570, 0x05260, 0x0F263, 0x0D950, 0x05B57, 0x056A0,
    0x096D0, 0x04DD5, 0x04AD0, 0x0A4D0, 0x0D4D4, 0x0D250, 0x0D558, 0x0B540, 0x0B6A0, 0x195A6,
    0x095B0, 0x049B0, 0x0A974, 0x0A4B0, 0x0B27A, 0x06A50, 0x06D40, 0x0AF46, 0x0AB60, 0x09570,
    0x04AF5, 0x04970, 0x064B0, 0x074A3, 0x0EA50, 0x06B58, 0x055C0, 0x0AB60, 0x096D5, 0x092E0,
    0x0C960, 0x0D954, 0x0D4A0, 0x0DA50, 0x07552, 0x056A0, 0x0ABB7, 0x025D0, 0x092D0, 0x0CAB5,
    0x0A950, 0x0B4A0, 0x0BAA4, 0x0AD50, 0x055D9, 0x04BA0, 0x0A5B0, 0x15176, 0x052B0, 0x0A930,
    0x07954, 0x06AA0, 0x0AD50, 0x05B52, 0x04B60, 0x0A6E6, 0x0A4E0, 0x0D260, 0x0EA65, 0x0D530,
    0x05AA0, 0x076A3, 0x096D0, 0x04AFB, 0x04AD0, 0x0A4D0, 0x1D0B6, 0x0D250, 0x0D520, 0x0DD45,
    0x0B5A0, 0x056D0, 0x055B2, 0x049B0, 0x0A577, 0x0A4B0, 0x0AA50, 0x1B255, 0x06D20, 0x0ADA0,
    0x14B63, 0x09370, 0x049F8, 0x04970, 0x064B0, 0x168A6, 0x0EA50, 0x06B20, 0x1A6C4, 0x0AAE0,
    0x0A2E0, 0x0D2E3, 0x0C960, 0x0D557, 0x0D4A0, 0x0DA50, 0x05D55, 0x056A0, 0x0A6D0, 0x055D4,
    0x052D0, 0x0A9B8, 0x0A950, 0x0B4A0, 0x0B6A6, 0x0AD50, 0x055A0, 0x0ABA4, 0x0A5B0, 0x052B0,
    0x0B273, 0x06930, 0x07337, 0x06AA0, 0x0AD50, 0x14B55, 0x04B60, 0x0A570, 0x054E4, 0x0D160,
    0x0E968, 0x0D520, 0x0DAA0, 0x16AA6, 0x056D0, 0x04AE0, 0x0A9D4, 0x0A2D0, 0x0D150, 0x0F252,
    0x0D520,
]

_LUNAR_YEAR_FIRST_DAY_IN_SOLAR = [
    0x0ED83F, 0x0EDA53, 0x0EDC48, 0x0EDE3D, 0x0EE050, 0x0EE244, 0x0EE439, 0x0EE64D, 0x0EE842, 0x0EEA36,
    0x0EEC4A, 0x0EEE3E, 0x0EF052, 0x0EF246, 0x0EF43A, 0x0EF64E, 0x0EF843, 0x0EFA37, 0x0EFC4B, 0x0EFE41,
    0x0F0054, 0x0F0248, 0x0F043C, 0x0F0650, 0x0F0845, 0x0F0A38, 0x0F0C4D, 0x0F0E42, 0x0F1037, 0x0F124A,
    0x0F143E, 0x0F1651, 0x0F1846, 0x0F1A3A, 0x0F1C4E, 0x0F1E44, 0x0F2038, 0x0F224B, 0x0F243F, 0x0F2653,
    0x0F2848, 0x0F2A3B, 0x0F2C4F, 0x0F2E45, 0x0F3039, 0x0F324D, 0x0F3442, 0x0F3636, 0x0F384A, 0x0F3A3D,
    0x0F3C51, 0x0F3E46, 0x0F403B, 0x0F424E, 0x0F4443, 0x0F4638, 0x0F484C, 0x0F4A3F, 0x0F4C52, 0x0F4E48,
    0x0F503C, 0x0F524F, 0x0F5445, 0x0F5639, 0x0F584D, 0x0F5A42, 0x0F5C35, 0x0F5E49, 0x0F603E, 0x0F6251,
    0x0F6446, 0x0F663B, 0x0F684F, 0x0F6A43, 0x0F6C37, 0x0F6E4B, 0x0F703F, 0x0F7252, 0x0F7447, 0x0F763C,
    0x0F7850, 0x0F7A45, 0x0F7C39, 0x0F7E4D, 0x0F8042, 0x0F8254, 0x0F8449, 0x0F863D, 0x0F8851, 0x0F8A46,
    0x0F8C3B, 0x0F8E4F, 0x0F9044, 0x0F9237, 0x0F944A, 0x0F963F, 0x0F9853, 0x0F9A47, 0x0F9C3C, 0x0F9E50,
    0x0FA045, 0x0FA238, 0x0FA44C, 0x0FA641, 0x0FA836, 0x0FAA49, 0x0FAC3D, 0x0FAE52, 0x0FB047, 0x0FB23A,
    0x0FB44E, 0x0FB643, 0x0FB837, 0x0FBA4A, 0x0FBC3F, 0x0FBE53, 0x0FC048, 0x0FC23C, 0x0FC450, 0x0FC645,
    0x0FC839, 0x0FCA4C, 0x0FCC41, 0x0FCE36, 0x0FD04A, 0x0FD23D, 0x0FD451, 0x0FD646, 0x0FD83A, 0x0FDA4D,
    0x0FDC43, 0x0FDE37, 0x0FE04B, 0x0FE23F, 0x0FE453, 0x0FE648, 0x0FE83C, 0x0FEA4F, 0x0FEC44, 0x0FEE38,
    0x0FF04C, 0x0FF241, 0x0FF436, 0x0FF64A, 0x0FF83E, 0x0FFA51, 0x0FFC46, 0x0FFE3A, 0x10004E, 0x100242,
    0x100437, 0x10064B, 0x100841, 0x100A53, 0x100C48, 0x100E3C, 0x10104F, 0x101244, 0x101438, 0x10164C,
    0x101842, 0x101A35, 0x101C49, 0x101E3D, 0x102051, 0x102245, 0x10243A, 0x10264E, 0x102843, 0x102A37,
    0x102C4B, 0x102E3F, 0x103053, 0x103247, 0x10343B, 0x10364F, 0x103845, 0x103A38, 0x103C4C, 0x103E42,
    0x104036, 0x104249, 0x10443D, 0x104651, 0x104846, 0x104A3A, 0x104C4E, 0x104E43, 0x105038, 0x10524A,
    0x10543E, 0x105652, 0x105847, 0x105A3B, 0x105C4F, 0x105E45, 0x106039, 0x10624C, 0x106441, 0x106635,
    0x106849,
]


class LunarCalendarError(ValueError):
    pass


def lunar_date_to_solar(year: int, month: int, day: int, *, is_leap_month: bool = False) -> date:
    year = int(year)
    month = int(month)
    day = int(day)
    is_leap_month = bool(is_leap_month)

    _validate_year(year)
    _validate_month(month)

    solar_first_day = _solar_first_day(year)
    days_offset = 0

    for current_month, days_in_month, current_is_leap_month in _iter_lunar_months(year):
        if current_month == month and current_is_leap_month == is_leap_month:
            if day < 1 or day > days_in_month:
                raise LunarCalendarError(f"day {day} must be in 1..{days_in_month}")
            return solar_first_day + timedelta(days=days_offset + day - 1)
        days_offset += days_in_month

    if is_leap_month:
        raise LunarCalendarError(f"month {month} is not leap in {year}")
    raise LunarCalendarError(f"month {month} must be in 1..12")


def find_next_lunar_date(
    *,
    month: int,
    day: int,
    is_leap_month: bool = False,
    on_or_after: date,
) -> date:
    month = int(month)
    day = int(day)
    _validate_month(month)
    start_year = max(MIN_LUNAR_YEAR, on_or_after.year - 1)

    for year in range(start_year, MAX_LUNAR_YEAR + 1):
        try:
            candidate = lunar_date_to_solar(year, month, day, is_leap_month=is_leap_month)
        except LunarCalendarError:
            continue
        if candidate >= on_or_after:
            return candidate

    raise LunarCalendarError("无法在支持范围内找到下一个农历日期")


def validate_lunar_month_day(
    *,
    month: int,
    day: int,
    is_leap_month: bool = False,
) -> None:
    month = int(month)
    day = int(day)
    _validate_month(month)

    for year in range(MIN_LUNAR_YEAR, MAX_LUNAR_YEAR + 1):
        try:
            lunar_date_to_solar(year, month, day, is_leap_month=is_leap_month)
            return
        except LunarCalendarError:
            continue

    if is_leap_month:
        raise LunarCalendarError(f"闰{month}月{day}日不在当前支持范围内")
    raise LunarCalendarError(f"农历 {month}月{day}日不在当前支持范围内")


def _validate_year(year: int) -> None:
    if year < MIN_LUNAR_YEAR or year > MAX_LUNAR_YEAR:
        raise LunarCalendarError(f"year {year} must be in {MIN_LUNAR_YEAR}..{MAX_LUNAR_YEAR}")


def _validate_month(month: int) -> None:
    if month < 1 or month > 12:
        raise LunarCalendarError(f"month {month} must be in 1..12")


def _solar_first_day(year: int) -> date:
    encoded = _LUNAR_YEAR_FIRST_DAY_IN_SOLAR[year - MIN_LUNAR_YEAR]
    return date(
        _bits(encoded, 15, 9),
        _bits(encoded, 4, 5),
        _bits(encoded, 5, 0),
    )


def _iter_lunar_months(year: int) -> list[tuple[int, int, bool]]:
    encoded = _LUNAR_YEAR_DATA[year - MIN_LUNAR_YEAR]
    leap_month = _bits(encoded, 4, 0)
    leap_month_is_long = _bits(encoded, 1, 16) == 1
    normal_month_bits = _bits(encoded, 12, 4)

    months: list[tuple[int, int, bool]] = []
    for month in range(1, 13):
        days_in_month = 30 if _bits(normal_month_bits, 1, 12 - month) == 1 else 29
        if year == MAX_LUNAR_YEAR and month == 12:
            days_in_month = 1
        months.append((month, days_in_month, False))
        if leap_month == month:
            months.append((month, 30 if leap_month_is_long else 29, True))
    return months


def _bits(value: int, width: int, shift: int) -> int:
    return (value >> shift) & ((1 << width) - 1)
