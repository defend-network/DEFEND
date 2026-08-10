from __future__ import annotations

import ast
import math
import operator

from tool_sdk import (
    DataClassification,
    DefendTool,
    RiskLevel,
    SideEffect,
    ToolContext,
    ToolError,
    ToolErrorCode,
    ToolResult,
)
from bootstrap_models import CalculatorInput, CalculatorOutput


_ALLOWED_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

MAX_AST_NODES = 100
MAX_POWER_EXPONENT = 1024
MAX_INTEGER_BITS = 4096


def _count_nodes(node: ast.AST) -> int:
    return sum(1 for _ in ast.walk(node))


def _safe_eval(node: ast.AST) -> float | int:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)

    if isinstance(node, ast.Constant):
        # bool is a subclass of int; reject it explicitly.
        if type(node.value) not in (int, float):
            raise ValueError("Only int and float constants are allowed.")
        if isinstance(node.value, float) and not math.isfinite(node.value):
            raise ValueError("Non-finite constants are not allowed.")
        return node.value

    if isinstance(node, ast.UnaryOp):
        operand = _safe_eval(node.operand)
        op = _ALLOWED_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unary operator not allowed: {type(node.op).__name__}")
        result = op(operand)
        if isinstance(result, int) and result.bit_length() > MAX_INTEGER_BITS:
            raise ValueError("Integer result too large.")
        if isinstance(result, float) and not math.isfinite(result):
            raise ValueError("Non-finite result.")
        return result

    if isinstance(node, ast.BinOp):
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)

        op = _ALLOWED_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Operator not allowed: {type(node.op).__name__}")

        if isinstance(node.op, ast.Pow):
            if not isinstance(right, (int, float)):
                raise ValueError("Invalid exponent.")
            if abs(right) > MAX_POWER_EXPONENT:
                raise ValueError("Exponent too large.")

            # Prevent computing enormous integer powers in the first place.
            if isinstance(left, int) and isinstance(right, int) and right >= 0:
                if left not in (-1, 0, 1):
                    estimated_bits = max(1, left.bit_length()) * right
                    if estimated_bits > MAX_INTEGER_BITS:
                        raise ValueError("Integer power result would be too large.")

        result = op(left, right)

        if isinstance(result, int) and result.bit_length() > MAX_INTEGER_BITS:
            raise ValueError("Integer result too large.")

        if isinstance(result, float) and not math.isfinite(result):
            raise ValueError("Non-finite result.")

        return result

    raise ValueError(f"Unsupported expression node: {type(node).__name__}")


class CalculatorTool(DefendTool[CalculatorInput, CalculatorOutput]):
    name = "calculator.evaluate"
    description = "Evaluate a simple mathematical expression safely."
    version = "1.0.0"

    input_model = CalculatorInput
    output_model = CalculatorOutput

    permissions = frozenset()
    risk_level = RiskLevel.LOW
    side_effect = SideEffect.NONE
    idempotent = True
    parallel_safe = True
    max_input_classification = DataClassification.PUBLIC
    max_output_classification = DataClassification.PUBLIC
    timeout_seconds = 5.0

    async def execute(
        self,
        args: CalculatorInput,
        context: ToolContext,
    ) -> ToolResult[CalculatorOutput]:
        try:
            tree = ast.parse(args.expression, mode="eval")

            if _count_nodes(tree) > MAX_AST_NODES:
                raise ValueError("Expression too complex.")

            value = _safe_eval(tree)

            if isinstance(value, float) and value.is_integer():
                value = int(value)

            warnings: list[str] = []
            exact = str(value) if isinstance(value, int) else None

            try:
                approximate = float(value)
                if not math.isfinite(approximate):
                    approximate = None
                    warnings.append("Approximate float representation is non-finite.")
            except (OverflowError, ValueError):
                approximate = None
                warnings.append("Result is too large for a float approximation.")

            data = CalculatorOutput(
                expression=args.expression,
                exact=exact,
                approximate=approximate,
                display=str(value),
                warnings=warnings,
            )

            return ToolResult(ok=True, data=data)

        except Exception as exc:
            return ToolResult(
                ok=False,
                error=ToolError(
                    code=ToolErrorCode.INVALID_INPUT,
                    message=str(exc),
                    retryable=False,
                ),
            )
