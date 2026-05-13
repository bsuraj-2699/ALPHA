"""
RuleEvaluator - Deterministic scoring engine for the Financial Analysis system.

This is intentionally LLM-free. The Strategy Judge agent will call this and only
add natural-language explanation on top. Keeping the scoring deterministic means
same inputs always produce same outputs - which is what you need for finance.
"""

from __future__ import annotations

import json
import operator as op
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Literal


# Map condition tier names to numeric scores (0-100 scale per rule)
TIER_SCORES = {
    "strong_buy": 100,
    "buy": 75,
    "neutral": 50,
    "sell": 25,
    "strong_sell": 0,
}

Signal = Literal["STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"]


# ---------------------------------------------------------------------------
# Safe expression evaluator
# ---------------------------------------------------------------------------
# We support the simple condition grammar used in rules.json without resorting
# to eval(). This avoids code-injection risk if rules ever come from RAG or
# user input.

_OPERATORS = {
    ">=": op.ge, "<=": op.le, "==": op.eq, "!=": op.ne,
    ">": op.gt, "<": op.lt,
}


def _coerce(token: str, ctx: dict[str, Any]) -> Any:
    token = token.strip()
    if not token:
        return None
    # Boolean literals
    if token == "true":
        return True
    if token == "false":
        return False
    # String literal (single-quoted)
    if token.startswith("'") and token.endswith("'"):
        return token[1:-1]
    # Numeric literal
    try:
        if "." in token:
            return float(token)
        return int(token)
    except ValueError:
        pass
    # Simple variable lookup
    if token in ctx:
        return ctx[token]
    # Attribute access (e.g. sector.buy_max) - one level deep
    if "." in token:
        parts = token.split(".")
        cur = ctx.get(parts[0])
        for p in parts[1:]:
            if isinstance(cur, dict):
                cur = cur.get(p)
            else:
                return None
        return cur
    # Function-like helpers in expression
    fn_match = re.match(r"^abs\((.+)\)$", token)
    if fn_match:
        inner = _eval_arithmetic(fn_match.group(1), ctx)
        return abs(inner) if inner is not None else None
    # Arithmetic expression
    if any(c in token for c in "+-*/()"):
        return _eval_arithmetic(token, ctx)
    # 'in [list]' / 'in name' handled by caller
    return None


def _eval_arithmetic(expr: str, ctx: dict[str, Any]) -> float | None:
    """
    Very small arithmetic evaluator. Supports + - * / and parentheses on
    numeric variables and literals. No eval(), no AST exec.
    """
    # Tokenize
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_.]*|\d+\.?\d*|[()+\-*/]", expr)
    if not tokens:
        return None
    # Substitute variables
    subbed: list[str] = []
    for t in tokens:
        if t in "()+-*/" or re.match(r"^\d+\.?\d*$", t):
            subbed.append(t)
        else:
            val = _coerce(t, ctx)
            if val is None:
                return None
            subbed.append(str(float(val)) if isinstance(val, (int, float)) else "0")
    # Shunting-yard → RPN
    prec = {"+": 1, "-": 1, "*": 2, "/": 2}
    output: list[str] = []
    stack: list[str] = []
    for tk in subbed:
        if re.match(r"^-?\d+\.?\d*$", tk):
            output.append(tk)
        elif tk in prec:
            while stack and stack[-1] in prec and prec[stack[-1]] >= prec[tk]:
                output.append(stack.pop())
            stack.append(tk)
        elif tk == "(":
            stack.append(tk)
        elif tk == ")":
            while stack and stack[-1] != "(":
                output.append(stack.pop())
            if stack:
                stack.pop()
    while stack:
        output.append(stack.pop())
    # Evaluate RPN
    rpn_stack: list[float] = []
    for tk in output:
        if tk in prec:
            if len(rpn_stack) < 2:
                return None
            b = rpn_stack.pop()
            a = rpn_stack.pop()
            if tk == "+": rpn_stack.append(a + b)
            elif tk == "-": rpn_stack.append(a - b)
            elif tk == "*": rpn_stack.append(a * b)
            elif tk == "/": rpn_stack.append(a / b if b != 0 else 0)
        else:
            try:
                rpn_stack.append(float(tk))
            except ValueError:
                return None
    return rpn_stack[0] if rpn_stack else None


def _eval_atom(atom: str, ctx: dict[str, Any]) -> bool:
    """Evaluate a single boolean atom like 'a >= b' or 'x in [1,2,3]' or 'x == true'."""
    atom = atom.strip()
    # 'x in [..]'
    in_match = re.match(r"^(.+?)\s+in\s+\[(.+)\]$", atom)
    if in_match:
        left = _coerce(in_match.group(1).strip(), ctx)
        items = [s.strip().strip("'\"") for s in in_match.group(2).split(",")]
        return str(left) in items
    # 'x in name' (named list in ctx)
    in_named = re.match(r"^(.+?)\s+in\s+([A-Za-z_][A-Za-z0-9_]*)$", atom)
    if in_named:
        left = _coerce(in_named.group(1).strip(), ctx)
        right = ctx.get(in_named.group(2).strip(), [])
        return str(left) in [str(x) for x in (right or [])]
    # Find comparison operator
    for symbol in (">=", "<=", "==", "!=", ">", "<"):
        if symbol in atom:
            left_str, right_str = atom.split(symbol, 1)
            left = _coerce(left_str, ctx)
            right = _coerce(right_str, ctx)
            if left is None or right is None:
                return False
            try:
                return _OPERATORS[symbol](left, right)
            except TypeError:
                return False
    return False


def evaluate_condition(expr: str, ctx: dict[str, Any]) -> bool:
    """
    Evaluate a condition string with AND / OR connectives and parentheses.
    Grammar (informal):
        cond := atom | cond AND cond | cond OR cond | (cond)
        atom := <value> <op> <value>  |  <value> in [list]  |  <value> in <name>
    """
    expr = expr.strip()
    if not expr:
        return False
    # Strip outer parens if balanced
    while expr.startswith("(") and expr.endswith(")"):
        depth = 0
        stripped_ok = True
        for i, ch in enumerate(expr):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i < len(expr) - 1:
                    stripped_ok = False
                    break
        if stripped_ok:
            expr = expr[1:-1].strip()
        else:
            break
    # Split on top-level OR (lowest precedence)
    parts = _split_top_level(expr, " OR ")
    if len(parts) > 1:
        return any(evaluate_condition(p, ctx) for p in parts)
    # Then AND
    parts = _split_top_level(expr, " AND ")
    if len(parts) > 1:
        return all(evaluate_condition(p, ctx) for p in parts)
    # Single atom
    return _eval_atom(expr, ctx)


def _split_top_level(s: str, sep: str) -> list[str]:
    """Split string on `sep` only when not inside parentheses or brackets."""
    parts: list[str] = []
    depth = 0
    last = 0
    i = 0
    while i < len(s):
        ch = s[i]
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif depth == 0 and s[i:i + len(sep)] == sep:
            parts.append(s[last:i].strip())
            last = i + len(sep)
            i += len(sep)
            continue
        i += 1
    parts.append(s[last:].strip())
    return parts


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class RuleResult:
    rule_id: str
    rule_name: str
    category: str
    tier: str  # strong_buy / buy / neutral / sell / strong_sell / skipped
    score: float  # 0-100; meaningless when skipped=True
    confidence_weight: float
    category_weight: float
    matched_condition: str | None
    skipped: bool = False
    skipped_reason: str | None = None


@dataclass
class PillarResult:
    pillar: str
    score: float  # 0-100, weighted average of rule scores in pillar
    rules_evaluated: int
    rules_skipped: int
    rule_results: list[RuleResult] = field(default_factory=list)


@dataclass
class OverrideResult:
    override_id: str
    name: str
    triggered: bool
    action: str
    rationale: str


@dataclass
class PillarEvaluation:
    """Scoped result of running RuleEvaluator over a subset of rule categories.

    Used by the per-pillar analyst agents — each analyst owns one or more
    rule categories (e.g. fundamental analyst owns ``fundamentals`` and
    ``balance_sheet``) and gets a focused view back instead of the full
    8-pillar evaluation.
    """

    categories: list[str]
    rule_results: list["RuleResult"]
    per_category_scores: dict[str, float]
    aggregate_score: float
    rules_evaluated: int
    rules_skipped: int


@dataclass
class EvaluationResult:
    ticker: str
    market: str
    composite_score: float
    signal: Signal
    action: str
    notes: str
    pillar_scores: dict[str, float]
    pillar_details: list[PillarResult]
    overrides_triggered: list[OverrideResult]
    final_signal_after_overrides: Signal
    final_action: str
    rules_evaluated_count: int
    rules_skipped_count: int
    # Honest-coverage fields. ``data_coverage_pct`` = (rules we actually
    # evaluated) / (rules in scope for this market) * 100. Decision agents
    # use this to cap position size when data is thin.
    skipped_rules: list[str] = field(default_factory=list)
    evaluated_rule_count: int = 0
    data_coverage_pct: float = 100.0

    def summary(self) -> str:
        lines = [
            f"=== {self.ticker} ({self.market}) ===",
            f"Composite Score: {self.composite_score:.1f}/100  →  {self.final_signal_after_overrides}",
            f"Action: {self.final_action}",
            "",
            "Pillar Scores:",
        ]
        for pillar, score in self.pillar_scores.items():
            lines.append(f"  {pillar:20s} {score:5.1f}")
        active_overrides = [o for o in self.overrides_triggered if o.triggered]
        if active_overrides:
            lines.append("")
            lines.append("⚠️  Overrides Triggered:")
            for ovr in active_overrides:
                lines.append(f"  [{ovr.override_id}] {ovr.name} → {ovr.action}")
        lines.append("")
        lines.append(
            f"Rules: {self.rules_evaluated_count} evaluated, {self.rules_skipped_count} skipped "
            f"(data coverage {self.data_coverage_pct:.0f}%)"
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# The evaluator itself
# ---------------------------------------------------------------------------

class RuleEvaluator:
    """
    Loads rules.json once, then evaluates a ticker given a context dict of
    facts (data points). The context is what the agents assemble from
    Upstox / Yahoo / Screener / NSE / GDELT.
    """

    # Per-category weight in the composite. Derived from the original
    # framework formula:
    #   composite = Fundamentals*0.25 + Technicals*0.20 + Sentiment*0.15
    #             + Valuation*0.18 + Macro*0.10 + Risk*0.12
    # where Fundamentals = mean(fundamentals, balance_sheet) and
    # Technicals = trend*0.625 + momentum*0.375.
    CATEGORY_WEIGHTS: dict[str, float] = {
        "fundamentals": 0.125,   # 0.25 / 2
        "balance_sheet": 0.125,  # 0.25 / 2
        "trend":         0.125,  # 0.20 * 0.625
        "momentum":      0.075,  # 0.20 * 0.375
        "sentiment":     0.15,
        "valuation":     0.18,
        "macro":         0.10,
        "risk":          0.12,
    }

    def __init__(self, rules_path: str | Path):
        rules_path = Path(rules_path)
        with rules_path.open() as f:
            self.spec = json.load(f)
        self.rules = self.spec["rules"]
        self.overrides = self.spec["override_rules"]
        self.thresholds = self.spec["thresholds"]
        # Kept for back-compat with external callers; new code reads
        # CATEGORY_WEIGHTS instead.
        self.formula_weights = {
            "fundamentals": 0.25,
            "balance_sheet": 0.0,
            "trend": 0.0,
            "momentum": 0.0,
            "sentiment": 0.15,
            "valuation": 0.18,
            "macro": 0.10,
            "risk": 0.12,
        }

    # ----- public API -------------------------------------------------------

    def evaluate(
        self,
        ticker: str,
        market: str,
        ctx: dict[str, Any],
        category_weights: dict[str, float] | None = None,
        mode: str | None = None,
    ) -> EvaluationResult:
        """
        Args:
            ticker: e.g. "RELIANCE.NS" or "AAPL"
            market: "IN" or "US"
            ctx: dict of data points (see rules.json data_required fields)
            category_weights: optional override for the class-level
                ``CATEGORY_WEIGHTS`` table, used by run modes (intraday /
                short-term / long-term) to reshape the composite. Missing
                categories default to 0.0 — i.e. those rules drop out of
                the composite entirely. ``None`` (the default) preserves
                the original framework weights.
            mode: optional run mode (``intraday`` / ``short_term`` /
                ``long_term``). When the mode declares a ``thresholds``
                array under ``modes.<mode>`` in ``rules.json``, the
                composite-to-signal mapping uses those bands instead of
                the universal ones. Modes without a custom block fall
                back to the default thresholds, preserving legacy
                behaviour for any caller that omits ``mode``.
        """
        ctx = dict(ctx)  # don't mutate caller's
        ctx.setdefault("market", market)

        # 1. Evaluate every rule
        per_pillar: dict[str, list[RuleResult]] = {}
        all_results: list[RuleResult] = []
        rules_in_scope = 0  # rules that apply to this market (skipped or not)
        evaluated = skipped = 0
        skipped_rule_ids: list[str] = []
        for rule in self.rules:
            in_scope = market in rule["markets"]
            if in_scope:
                rules_in_scope += 1
            res = self._evaluate_rule(rule, ctx, market)
            per_pillar.setdefault(rule["category"], []).append(res)
            all_results.append(res)
            if res.skipped:
                # Only count "data missing" skips toward coverage; out-of-scope
                # rules are not data gaps, they simply don't apply.
                if in_scope:
                    skipped += 1
                    skipped_rule_ids.append(res.rule_id)
            else:
                evaluated += 1

        # 2. Compute pillar scores (weighted average within each pillar,
        #    excluding skipped rules from numerator and denominator).
        pillar_results: list[PillarResult] = []
        pillar_scores: dict[str, float] = {}
        for pillar, results in per_pillar.items():
            score = self._weighted_pillar_score(results)
            pillar_scores[pillar] = score
            pillar_results.append(PillarResult(
                pillar=pillar,
                score=score,
                rules_evaluated=sum(1 for r in results if not r.skipped),
                rules_skipped=sum(1 for r in results if r.skipped),
                rule_results=results,
            ))

        # 3. Composite over evaluated rules only — skipped rules are
        #    excluded from both the numerator and the denominator so the
        #    score reflects what we actually have data for. The optional
        #    ``category_weights`` override lets per-mode runs reshape the
        #    composite without rebuilding the evaluator instance.
        composite = self._composite_score(all_results, category_weights)

        # 4. Coverage = evaluated / in-scope * 100. When no rules apply to
        #    this market we report 100 % (vacuously full coverage) to avoid
        #    gating on a divide-by-zero.
        coverage = (evaluated / rules_in_scope * 100.0) if rules_in_scope else 100.0

        # 5. Map to signal — use the mode-specific bands when defined
        #    (rules.json modes.<mode>.thresholds), else the universal block.
        thresholds = self._thresholds_for_mode(mode)
        signal, action, notes = self._signal_from_score(composite, thresholds)

        # 6. Apply override rules
        overrides_triggered = self._evaluate_overrides(ctx)
        final_signal, final_action = self._apply_overrides(signal, action, overrides_triggered)

        return EvaluationResult(
            ticker=ticker,
            market=market,
            composite_score=composite,
            signal=signal,
            action=action,
            notes=notes,
            pillar_scores=pillar_scores,
            pillar_details=pillar_results,
            overrides_triggered=overrides_triggered,
            final_signal_after_overrides=final_signal,
            final_action=final_action,
            rules_evaluated_count=evaluated,
            rules_skipped_count=skipped,
            skipped_rules=skipped_rule_ids,
            evaluated_rule_count=evaluated,
            data_coverage_pct=coverage,
        )

    def evaluate_pillar(
        self,
        ticker: str,
        market: str,
        ctx: dict[str, Any],
        categories: str | list[str] | tuple[str, ...],
    ) -> PillarEvaluation:
        """Evaluate only the rules whose ``category`` is in ``categories``.

        Returns per-category weighted-average scores plus a default
        ``aggregate_score`` (mean of category scores). Analysts that need a
        non-uniform aggregator (e.g. technicals = trend*0.625 + momentum*0.375)
        should compute their own aggregate from ``per_category_scores``.
        """
        if isinstance(categories, str):
            cats = [categories]
        else:
            cats = list(categories)
        if not cats:
            raise ValueError("evaluate_pillar requires at least one category")

        ctx = dict(ctx)
        ctx.setdefault("market", market)

        per_category_results: dict[str, list[RuleResult]] = {c: [] for c in cats}
        rule_results: list[RuleResult] = []
        evaluated = skipped = 0

        for rule in self.rules:
            if rule["category"] not in per_category_results:
                continue
            res = self._evaluate_rule(rule, ctx, market)
            per_category_results[rule["category"]].append(res)
            rule_results.append(res)
            if res.skipped:
                skipped += 1
            else:
                evaluated += 1

        per_category_scores = {
            cat: self._weighted_pillar_score(results) if results else 50.0
            for cat, results in per_category_results.items()
        }

        # Default aggregator: simple mean of categories that had at least
        # one evaluated rule. Analysts can override this for framework-
        # correct blends (e.g. technicals = trend*0.625 + momentum*0.375).
        active_scores = [
            per_category_scores[cat]
            for cat, results in per_category_results.items()
            if any(not r.skipped for r in results)
        ]
        aggregate = sum(active_scores) / len(active_scores) if active_scores else 50.0

        return PillarEvaluation(
            categories=cats,
            rule_results=rule_results,
            per_category_scores=per_category_scores,
            aggregate_score=aggregate,
            rules_evaluated=evaluated,
            rules_skipped=skipped,
        )

    # ----- internals --------------------------------------------------------

    def _evaluate_rule(self, rule: dict, ctx: dict[str, Any], market: str) -> RuleResult:
        # Skip if market not in scope
        if market not in rule["markets"]:
            return RuleResult(
                rule_id=rule["id"], rule_name=rule["name"], category=rule["category"],
                tier="skipped", score=0.0,
                confidence_weight=rule["confidence_weight"],
                category_weight=rule["category_weight"],
                matched_condition=None,
                skipped=True,
                skipped_reason=f"Market {market} not in rule scope",
            )

        # Build sector-aware context if rule has sector_adjustments
        local_ctx = dict(ctx)
        if "sector_adjustments" in rule:
            sector = ctx.get("sector", "default")
            adj = rule["sector_adjustments"].get(sector, rule["sector_adjustments"]["default"])
            local_ctx["sector"] = adj  # so 'sector.buy_max' resolves

        # Check data availability
        for required in rule["data_required"]:
            if required not in ctx and not self._is_optional_or_market_specific(required, market):
                return RuleResult(
                    rule_id=rule["id"], rule_name=rule["name"], category=rule["category"],
                    tier="skipped", score=0.0,
                    confidence_weight=rule["confidence_weight"],
                    category_weight=rule["category_weight"],
                    matched_condition=None,
                    skipped=True,
                    skipped_reason=f"Missing data: {required}",
                )

        # Evaluate condition tiers in priority order: most extreme first
        tier_order = ["strong_buy", "buy", "sell", "strong_sell", "neutral"]
        for tier in tier_order:
            cond = rule["conditions"].get(tier)
            if cond and evaluate_condition(cond, local_ctx):
                return RuleResult(
                    rule_id=rule["id"], rule_name=rule["name"], category=rule["category"],
                    tier=tier, score=TIER_SCORES[tier],
                    confidence_weight=rule["confidence_weight"],
                    category_weight=rule["category_weight"],
                    matched_condition=cond,
                )

        # No condition matched → neutral
        return RuleResult(
            rule_id=rule["id"], rule_name=rule["name"], category=rule["category"],
            tier="neutral", score=50.0,
            confidence_weight=rule["confidence_weight"],
            category_weight=rule["category_weight"],
            matched_condition=None,
        )

    def _is_optional_or_market_specific(self, key: str, market: str) -> bool:
        # Some keys end with _IN or _US
        return key.endswith(f"_{market}") or key.endswith("_US") or key.endswith("_IN")

    def _weighted_pillar_score(self, results: list[RuleResult]) -> float:
        """
        Weighted by (confidence_weight * category_weight) within the pillar.
        Skipped rules are excluded from numerator AND denominator so missing
        data does not pull the pillar toward neutral. A pillar with zero
        evaluated rules returns 50.0 as a labelled placeholder — callers
        check ``PillarResult.rules_evaluated`` to know it is empty.
        """
        evaluated = [r for r in results if not r.skipped]
        if not evaluated:
            return 50.0
        total_weight = sum(r.confidence_weight * r.category_weight for r in evaluated)
        if total_weight == 0:
            return 50.0
        weighted_sum = sum(r.score * r.confidence_weight * r.category_weight for r in evaluated)
        return weighted_sum / total_weight

    def _composite_score(
        self,
        all_results: list[RuleResult],
        category_weights: dict[str, float] | None = None,
    ) -> float:
        """
        Honest composite: weighted average across rules we *actually*
        evaluated.

            composite = sum(score * w for evaluated rules)
                      / sum(w for evaluated rules)

        Where each rule's weight ``w`` is::

            category_weights[rule.category]
              * rule.category_weight
              * rule.confidence_weight

        ``category_weights`` defaults to the class-level
        ``CATEGORY_WEIGHTS`` (the original framework split). Per-mode
        runs (intraday / short-term / long-term) pass an override so
        weights for unused pillars collapse to 0; rules in those
        categories then have ``w == 0`` and are dropped from both sums.

        Skipped rules contribute nothing to either sum — their absence
        is reflected in ``data_coverage_pct``, not in a fake neutral
        score. If every rule is skipped, returns 50.0 so downstream
        threshold logic keeps producing a valid signal mapping.
        """
        weights = category_weights if category_weights is not None else self.CATEGORY_WEIGHTS
        num = 0.0
        den = 0.0
        for r in all_results:
            if r.skipped:
                continue
            pw = weights.get(r.category, 0.0)
            w = pw * r.category_weight * r.confidence_weight
            if w <= 0:
                continue
            num += r.score * w
            den += w
        if den == 0:
            return 50.0
        return num / den

    def _signal_from_score(
        self,
        score: float,
        thresholds: list[dict[str, Any]] | None = None,
    ) -> tuple[Signal, str, str]:
        bands = thresholds if thresholds is not None else self.thresholds
        for t in bands:
            if t["min"] <= score <= t["max"]:
                return t["signal"], t["action"], t["notes"]
        return "HOLD", "Hold existing", "Score outside defined ranges"

    def _thresholds_for_mode(
        self, mode: str | None
    ) -> list[dict[str, Any]] | None:
        """Return rules.json ``modes.<mode>.thresholds`` if the spec defines
        them, else ``None`` so the universal top-level thresholds win."""
        if mode is None:
            return None
        modes_block = self.spec.get("modes")
        if not isinstance(modes_block, dict):
            return None
        mode_block = modes_block.get(mode)
        if not isinstance(mode_block, dict):
            return None
        bands = mode_block.get("thresholds")
        if isinstance(bands, list) and bands:
            return bands
        return None

    def _evaluate_overrides(self, ctx: dict[str, Any]) -> list[OverrideResult]:
        results = []
        for ovr in self.overrides:
            # Skip if any required data is absent — we don't fire overrides on incomplete data
            missing = [k for k in ovr["data_required"] if k not in ctx]
            if missing:
                results.append(OverrideResult(
                    override_id=ovr["id"], name=ovr["name"],
                    triggered=False, action=ovr["action"],
                    rationale=f"Skipped: missing {missing}",
                ))
                continue
            triggered = evaluate_condition(ovr["trigger"], ctx)
            results.append(OverrideResult(
                override_id=ovr["id"], name=ovr["name"],
                triggered=triggered, action=ovr["action"],
                rationale=ovr["rationale"] if triggered else "Not triggered",
            ))
        return results

    def _apply_overrides(
        self, signal: Signal, action: str, overrides: list[OverrideResult]
    ) -> tuple[Signal, str]:
        for ovr in overrides:
            if not ovr.triggered:
                continue
            if ovr.action == "FORCE_STRONG_SELL":
                return "STRONG_SELL", f"OVERRIDE [{ovr.override_id}]: {ovr.name} — Full exit immediately"
            if ovr.action == "FORCE_SELL":
                return "SELL", f"OVERRIDE [{ovr.override_id}]: {ovr.name} — Trim/exit position"
            if ovr.action == "PAUSE_BUY" and signal in ("STRONG_BUY", "BUY"):
                return "HOLD", f"OVERRIDE [{ovr.override_id}]: {ovr.name} — BUY paused, reassess thesis"
            if ovr.action == "BLOCK_BUY" and signal in ("STRONG_BUY", "BUY"):
                return "HOLD", f"OVERRIDE [{ovr.override_id}]: {ovr.name} — Concentration cap; cannot add"
        return signal, action
