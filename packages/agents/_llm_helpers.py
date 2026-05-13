"""Internal helpers shared by the analyst / debate / judge narrators.

Centralises the instructor structured-output call pattern (OpenAI client
or LiteLLM-backed client) so token / cost tracking is wired in one place.
"""

from __future__ import annotations

from typing import Any, TypeVar

from packages.shared.observability import record_token_usage

T = TypeVar("T")


async def openai_create_tracked(
    client: Any,
    *,
    model: str,
    response_model: type[T],
    **kwargs: Any,
) -> T:
    """Call ``client.chat.completions.create`` (instructor wrapper) and record usage.

    Parameters
    ----------
    client
        An ``instructor`` async client (``from_openai`` or ``from_litellm``).
    model
        Model id used for the API call and cost lookup (OpenAI or LiteLLM).
    response_model
        Pydantic class instructor should populate.
    **kwargs
        Forwarded verbatim (e.g. ``messages``, ``max_tokens``, ``temperature``,
        ``system``).
    """
    create_with_completion = getattr(client.chat.completions, "create_with_completion", None)
    if create_with_completion is not None:
        try:
            parsed, completion = await create_with_completion(
                model=model,
                response_model=response_model,
                **kwargs,
            )
        except (TypeError, AttributeError):
            parsed = None
            completion = None
        else:
            usage = getattr(completion, "usage", None)
            if usage is not None:
                record_token_usage(
                    model,
                    int(getattr(usage, "prompt_tokens", 0) or 0),
                    int(getattr(usage, "completion_tokens", 0) or 0),
                )
            return parsed  # type: ignore[no-any-return]

    parsed = await client.chat.completions.create(
        model=model,
        response_model=response_model,
        **kwargs,
    )
    return parsed  # type: ignore[no-any-return]


__all__ = ["openai_create_tracked"]
