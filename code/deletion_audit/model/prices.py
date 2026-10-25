"""Model prices and token-estimate constants used by the budget guard.

Source for every price: ``research/13_sonnet55_api_facts.md`` §2, confirmed by
``research/verify/13_verify.md`` C20-C24 (platform.claude.com/docs/en/about-claude/pricing and
claude.com/pricing, checked 2026-10-24). Synchronous Messages API rates, USD per million tokens.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens for one model."""

    input: float
    output: float
    cache_write_5m: float
    cache_write_1h: float
    cache_read: float


PRICES: dict[str, ModelPrice] = {
    # research/13 §2; verify/13 C20 (input $2), C21 (output $10, thinking billed as output),
    # C22 (5-minute write $2.50), C23 (1-hour write $4), C24 (cache read $0.10 since 2026-10-07).
    "claude-sonnet-5-5": ModelPrice(input=2.00, output=10.00, cache_write_5m=2.50,
                                    cache_write_1h=4.00, cache_read=0.10),
}

TOOL_SYSTEM_PROMPT_TOKENS = 286
"""Tokens the API adds when tools are sent with tool_choice auto or none (research/13 §2;
verify/13 C28)."""

MAX_IMAGE_TOKENS = 4_784
"""Largest token cost of one image on Sonnet 5.5's high-resolution tier (research/13 §6;
verify/13 C95/C96). Used as the per-image upper bound."""

STRUCTURED_OUTPUT_MARGIN_TOKENS = 1_000
"""Allowance for the system prompt the API injects for structured outputs (verify/13 C45 says
one is injected; its size is not documented, so this figure is an assumption, not a fact)."""
