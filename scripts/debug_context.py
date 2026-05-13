from __future__ import annotations

import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv


async def main() -> None:
    # Keep consistent with FastAPI app startup.
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    from packages.data.context_builder import ContextBuilder, _build_default_providers

    providers, screener, nse, gdelt = _build_default_providers("IN")
    builder = ContextBuilder(providers, screener=screener, nse=nse, gdelt=gdelt)
    ctx = await builder.build("TCS", "IN")
    print(f"keys={len(ctx)}")
    print("sample_keys=", json.dumps(sorted(ctx.keys())[:60], indent=2))

    from packages.core.rule_evaluator import RuleEvaluator

    rules_path = Path(__file__).resolve().parents[1] / "packages" / "core" / "rules.json"
    evaluator = RuleEvaluator(rules_path)
    result = evaluator.evaluate("TCS", "IN", ctx)
    print("\n--- Evaluation summary ---")
    print(result.summary())


if __name__ == "__main__":
    asyncio.run(main())

