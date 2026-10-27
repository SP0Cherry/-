"""Tool implementations for the CampusClaw MCP server.

Naming rule from the course host side: tool names must start with a lowercase
letter and must not contain hyphens, so they can be used verbatim as host
function names. ``TOOLS`` below is validated against that rule at import time.
"""

from __future__ import annotations

import math
import re

_TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class ToolError(ValueError):
    """Invalid tool arguments, reported to the caller as a readable tool error."""


# ------------------------------------------------------------------ tools


_FORMULAS = {
    "牛顿第二定律": "F = m·a（合外力等于质量乘以加速度）",
    "欧姆定律": "U = I·R（电压等于电流乘以电阻）",
    "勾股定理": "a² + b² = c²（直角三角形两直角边平方和等于斜边平方）",
    "动能定理": "E_k = ½·m·v²（动能等于二分之一质量乘以速度平方）",
    "理想气体状态方程": "p·V = n·R·T",
    "光合作用": "6CO₂ + 6H₂O → C₆H₁₂O₆ + 6O₂（需要光照和叶绿体）",
    "导数定义": "f'(x) = lim_{Δx→0} [f(x+Δx) − f(x)] / Δx",
    "贝叶斯公式": "P(A|B) = P(B|A)·P(A) / P(B)",
    "复利公式": "A = P·(1 + r/n)^(n·t)",
}

_FORMULA_ALIASES = {
    "newton": "牛顿第二定律",
    "ohm": "欧姆定律",
    "pythagoras": "勾股定理",
    "kinetic": "动能定理",
    "ideal gas": "理想气体状态方程",
    "photosynthesis": "光合作用",
    "derivative": "导数定义",
    "bayes": "贝叶斯公式",
    "compound interest": "复利公式",
}


def _lookup_formula(topic: str) -> str | None:
    normalized = topic.strip().lower()
    for alias, key in _FORMULA_ALIASES.items():
        if alias in normalized:
            return key
    for key in _FORMULAS:
        if key.lower() in normalized or normalized in key.lower():
            return key
    return None


def formula_hint(arguments: dict) -> str:
    topic = str(arguments.get("topic", "")).strip()
    if not topic:
        raise ToolError("缺少参数 topic（公式或知识点名称）")

    key = _lookup_formula(topic)
    if key is None:
        return (
            f"未收录「{topic}」的公式提示。可查询："
            + "、".join(_FORMULAS)
            + "。"
        )
    return f"{key}：{_FORMULAS[key]}"


# Multiplicative unit groups (all factors are relative to the base unit).
_UNIT_GROUPS = {
    "length": {
        "m": 1.0,
        "km": 1000.0,
        "dm": 0.1,
        "cm": 0.01,
        "mm": 0.001,
        "mi": 1609.344,
        "yd": 0.9144,
        "ft": 0.3048,
        "in": 0.0254,
    },
    "mass": {
        "kg": 1.0,
        "g": 0.001,
        "mg": 0.000001,
        "t": 1000.0,
        "lb": 0.45359237,
        "oz": 0.028349523125,
    },
    "time": {"s": 1.0, "ms": 0.001, "min": 60.0, "h": 3600.0, "day": 86400.0},
    "data": {
        "b": 1.0,
        "kb": 1024.0,
        "mb": 1048576.0,
        "gb": 1073741824.0,
        "tb": 1099511627776.0,
    },
}

_TEMPERATURE_UNITS = {"c", "f", "k"}

_UNIT_ALIASES = {
    "米": "m",
    "千米": "km",
    "公里": "km",
    "厘米": "cm",
    "毫米": "mm",
    "克": "g",
    "千克": "kg",
    "公斤": "kg",
    "毫克": "mg",
    "吨": "t",
    "秒": "s",
    "毫秒": "ms",
    "分钟": "min",
    "小时": "h",
    "天": "day",
    "字节": "b",
    "摄氏度": "c",
    "华氏度": "f",
    "开尔文": "k",
}


def _number(value) -> float:
    if isinstance(value, bool):
        raise ToolError("参数 value 必须是数字")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ToolError("参数 value 必须是数字") from None
    if not math.isfinite(number):
        raise ToolError("参数 value 必须是有限数字")
    return number


def _group_of(unit: str) -> str | None:
    for group, factors in _UNIT_GROUPS.items():
        if unit in factors:
            return group
    if unit in _TEMPERATURE_UNITS:
        return "temperature"
    return None


def _to_celsius(value: float, unit: str) -> float:
    if unit == "c":
        return value
    if unit == "f":
        return (value - 32.0) * 5.0 / 9.0
    return value - 273.15


def _from_celsius(value: float, unit: str) -> float:
    if unit == "c":
        return value
    if unit == "f":
        return value * 9.0 / 5.0 + 32.0
    return value + 273.15


def _format(number: float) -> str:
    text = f"{number:.10g}"
    return "0" if text in ("-0", "") else text


def unit_convert(arguments: dict) -> str:
    value = _number(arguments.get("value"))
    from_unit = str(arguments.get("from", "")).strip().lower()
    to_unit = str(arguments.get("to", "")).strip().lower()
    from_unit = _UNIT_ALIASES.get(from_unit, from_unit)
    to_unit = _UNIT_ALIASES.get(to_unit, to_unit)

    if not from_unit or not to_unit:
        raise ToolError("缺少单位参数 from / to")

    from_group = _group_of(from_unit)
    to_group = _group_of(to_unit)
    if from_group is None:
        raise ToolError(f"未知单位：{from_unit}")
    if to_group is None:
        raise ToolError(f"未知单位：{to_unit}")
    if from_group != to_group:
        raise ToolError(
            f"不能把 {from_group} 单位 {from_unit} 转换为 {to_group} 单位 {to_unit}"
        )

    if from_group == "temperature":
        result = _from_celsius(_to_celsius(value, from_unit), to_unit)
    else:
        factors = _UNIT_GROUPS[from_group]
        result = value * factors[from_unit] / factors[to_unit]

    return f"{_format(value)} {from_unit} = {_format(result)} {to_unit}"


# -------------------------------------------------------------- registry


TOOLS = {
    "formula_hint": {
        "description": (
            "查询常见课程公式的提示（物理、化学、数学、金融）。"
            "参数 topic 传入公式名或知识点，例如“牛顿第二定律”“勾股定理”“光合作用”。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "公式或知识点名称，如：牛顿第二定律、勾股定理、光合作用",
                }
            },
            "required": ["topic"],
            "additionalProperties": False,
        },
        "handler": formula_hint,
    },
    "unit_convert": {
        "description": (
            "换算长度、质量、时间、数据量或温度单位，返回一句可读的文本结果。"
            "例如 value=1.5, from=km, to=m。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "value": {"type": "number", "description": "待转换的数值"},
                "from": {
                    "type": "string",
                    "description": "源单位，如 m、km、kg、h、mb、c（摄氏度）",
                },
                "to": {
                    "type": "string",
                    "description": "目标单位，如 cm、g、min、gb、f（华氏度）",
                },
            },
            "required": ["value", "from", "to"],
            "additionalProperties": False,
        },
        "handler": unit_convert,
    },
}

for _name in TOOLS:
    if not _TOOL_NAME_PATTERN.fullmatch(_name):
        raise RuntimeError(
            f"非法工具名 {_name!r}：必须以小写字母开头且不含连字符"
        )
