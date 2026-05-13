"""Cross-cutting observability primitives for the agent runtime."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


# Per-million-token USD pricing for the OpenAI models we call.
# Source: OpenAI public pricing (May 2026).
_PRICING_PER_MTOK: dict[str, tuple[float, float]] = {
    "gpt-4o":          (2.50,  10.00),
    "gpt-4o-mini":     (0.15,   0.60),
    "gpt-4o-2024-11-20": (2.50, 10.00),
    "gpt-4-turbo":     (10.00, 30.00),
}
_DEFAULT_PRICING = (2.50, 10.00)  # fall back to gpt-4o pricing


@dataclass(frozen=True)
class TokenUsage:
    model: str
    input_tokens: int
    output_tokens: int


@dataclass
class TokenLedger:
    entries: list[TokenUsage] = field(default_factory=list)

    def record(self, model: str, input_tokens: int, output_tokens: int) -> None:
        if input_tokens < 0 or output_tokens < 0:
            return
        self.entries.append(
            TokenUsage(model=model, input_tokens=input_tokens, output_tokens=output_tokens)
        )

    @property
    def total_input_tokens(self) -> int:
        return sum(e.input_tokens for e in self.entries)

    @property
    def total_output_tokens(self) -> int:
        return sum(e.output_tokens for e in self.entries)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    def cost_usd(self) -> float:
        cost = 0.0
        for e in self.entries:
            in_rate, out_rate = _PRICING_PER_MTOK.get(e.model, _DEFAULT_PRICING)
            cost += e.input_tokens  * in_rate  / 1_000_000
            cost += e.output_tokens * out_rate / 1_000_000
        return round(cost, 6)


_LEDGER: ContextVar[TokenLedger | None] = ContextVar("token_ledger", default=None)


def get_token_ledger() -> TokenLedger | None:
    return _LEDGER.get()


def set_token_ledger(ledger: TokenLedger | None) -> Token[TokenLedger | None]:
    return _LEDGER.set(ledger)


def reset_token_ledger(token: Token[TokenLedger | None]) -> None:
    _LEDGER.reset(token)


def record_token_usage(model: str, input_tokens: int, output_tokens: int) -> None:
    ledger = _LEDGER.get()
    if ledger is None:
        return
    ledger.record(model, input_tokens, output_tokens)


EventPublisher = Callable[[str, str, dict[str, Any]], Awaitable[None]]

_PUBLISHER: ContextVar[EventPublisher | None] = ContextVar("event_publisher", default=None)
_RUN_ID:    ContextVar[str | None]            = ContextVar("run_id", default=None)


def set_run_context(
    run_id: str, publisher: EventPublisher | None
) -> tuple[Token[str | None], Token[EventPublisher | None]]:
    rid_token = _RUN_ID.set(run_id)
    pub_token = _PUBLISHER.set(publisher)
    return rid_token, pub_token


def reset_run_context(
    tokens: tuple[Token[str | None], Token[EventPublisher | None]],
) -> None:
    rid_token, pub_token = tokens
    _RUN_ID.reset(rid_token)
    _PUBLISHER.reset(pub_token)


def get_run_id() -> str | None:
    return _RUN_ID.get()


async def publish_event(event_type: str, data: dict[str, Any]) -> None:
    publisher = _PUBLISHER.get()
    run_id    = _RUN_ID.get()
    if publisher is None or run_id is None:
        return
    try:
        await publisher(run_id, event_type, data)
    except Exception:
        pass


__all__ = [
    "EventPublisher",
    "TokenLedger",
    "TokenUsage",
    "get_run_id",
    "get_token_ledger",
    "publish_event",
    "record_token_usage",
    "reset_run_context",
    "reset_token_ledger",
    "set_run_context",
    "set_token_ledger",
]
