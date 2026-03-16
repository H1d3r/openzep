import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from graphiti_core import Graphiti
from graphiti_core.nodes import EntityNode
from graphiti_core.prompts.models import Message
from pydantic import BaseModel

logger = logging.getLogger(__name__)

DEFAULT_MAX_CONTEXT_TOKENS = 4000
CHARS_PER_TOKEN = 4


def _coerce_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


class SummaryResponse(BaseModel):
    summary: str


@dataclass
class TokenBudget:
    max_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS
    used_tokens: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.max_tokens - self.used_tokens)

    def consume(self, text: str) -> bool:
        estimated_tokens = max(1, len(text) // CHARS_PER_TOKEN)
        if self.used_tokens + estimated_tokens > self.max_tokens:
            return False
        self.used_tokens += estimated_tokens
        return True


@dataclass
class AnnotatedFact:
    uuid: str
    fact: str
    created_at: datetime | None = None
    valid_at: datetime | None = None
    invalid_at: datetime | None = None
    expired_at: datetime | None = None
    score: float | None = None

    @property
    def is_currently_valid(self) -> bool:
        now = datetime.now(timezone.utc)
        if self.invalid_at and self.invalid_at <= now:
            return False
        if self.expired_at and self.expired_at <= now:
            return False
        return True

    def format_with_dates(self) -> str:
        parts = [f"- {self.fact}"]
        date_parts: list[str] = []
        if self.valid_at:
            date_parts.append(f"since {self.valid_at.strftime('%Y-%m-%d')}")
        if self.invalid_at:
            date_parts.append(f"until {self.invalid_at.strftime('%Y-%m-%d')}")
        elif self.expired_at:
            date_parts.append(f"expired {self.expired_at.strftime('%Y-%m-%d')}")
        else:
            date_parts.append("present")
        if date_parts:
            parts.append(f" ({' - '.join(date_parts)})")
        return "".join(parts)


@dataclass
class ContextBlockConfig:
    max_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS
    max_facts: int = 20
    include_summary: bool = True
    include_dates: bool = True
    filter_invalid: bool = True
    min_score: float = 0.0
    summary_instructions: list[str] | None = None


@dataclass
class ContextBlock:
    context: str
    user_summary: str = ""
    facts: list[AnnotatedFact] = field(default_factory=list)
    token_count: int = 0


async def generate_user_summary(
    graphiti: Graphiti,
    user_id: str,
    group_ids: list[str],
    instructions: list[str] | None = None,
) -> str:
    try:
        nodes = await EntityNode.get_by_group_ids(
            graphiti.driver,
            group_ids=group_ids,
            limit=10,
        )
    except Exception:
        nodes = []

    try:
        edges = await graphiti.search(
            query=f"important facts about {user_id}",
            group_ids=group_ids,
            num_results=8,
        )
    except Exception:
        edges = []

    facts = [getattr(edge, "fact", "").strip() for edge in edges if getattr(edge, "fact", "").strip()]
    if not nodes and not facts:
        return ""

    entity_lines = [
        f"- {node.name}: {node.summary or 'no summary'}"
        for node in nodes
        if getattr(node, "name", "")
    ]
    instruction_block = "\n".join(f"- {item}" for item in (instructions or []))
    prompt = (
        "Summarize the user in 2 concise sentences.\n"
        "Focus on stable preferences, identity, and active issues.\n"
        "Return JSON with a single key named summary."
    )
    if instruction_block:
        prompt += f"\nAdditional instructions:\n{instruction_block}"

    facts_block = "\n".join(f"- {fact}" for fact in facts[:6]) or "- No facts found"
    entities_block = "\n".join(entity_lines[:6]) or "- No entities found"
    messages = [
        Message(role="system", content=prompt),
        Message(
            role="user",
            content=(
                f"User ID: {user_id}\n\n"
                f"Entities:\n{entities_block}\n\n"
                f"Facts:\n{facts_block}"
            ),
        ),
    ]

    try:
        response = await graphiti.llm_client.generate_response(
            messages=messages,
            response_model=SummaryResponse,
        )
        summary = ""
        if isinstance(response, dict):
            summary = str(response.get("summary", "")).strip()
        if summary:
            return summary
    except Exception as exc:
        logger.warning("Failed to generate user summary: %s", exc)

    return "; ".join(facts[:3])


async def assemble_context_block(
    graphiti: Graphiti,
    user_id: str,
    group_ids: list[str],
    query: str = "",
    config: ContextBlockConfig | None = None,
) -> ContextBlock:
    cfg = config or ContextBlockConfig()
    budget = TokenBudget(max_tokens=cfg.max_tokens)

    try:
        raw_edges = await graphiti.search(
            query=query or f"important recent facts about {user_id}",
            group_ids=group_ids,
            num_results=max(cfg.max_facts * 2, cfg.max_facts),
        )
    except Exception as exc:
        logger.error("Context assembly search failed: %s", exc)
        raw_edges = []

    candidates: list[AnnotatedFact] = []
    for edge in raw_edges:
        score = getattr(edge, "score", None)
        if score is not None and score < cfg.min_score:
            continue

        annotated = AnnotatedFact(
            uuid=getattr(edge, "uuid", ""),
            fact=getattr(edge, "fact", "").strip() or str(edge),
            created_at=_coerce_datetime(getattr(edge, "created_at", None)),
            valid_at=_coerce_datetime(getattr(edge, "valid_at", None)),
            invalid_at=_coerce_datetime(getattr(edge, "invalid_at", None)),
            expired_at=_coerce_datetime(getattr(edge, "expired_at", None)),
            score=score,
        )
        if cfg.filter_invalid and not annotated.is_currently_valid:
            continue
        candidates.append(annotated)

    candidates.sort(
        key=lambda fact: (
            fact.score if fact.score is not None else 0.0,
            fact.created_at.timestamp() if fact.created_at else 0.0,
        ),
        reverse=True,
    )
    candidates = candidates[: cfg.max_facts]

    user_summary = ""
    if cfg.include_summary:
        user_summary = await generate_user_summary(
            graphiti=graphiti,
            user_id=user_id,
            group_ids=group_ids,
            instructions=cfg.summary_instructions,
        )

    sections: list[str] = []
    included_facts: list[AnnotatedFact] = []

    if user_summary:
        summary_block = f"<USER_SUMMARY>\n{user_summary}\n</USER_SUMMARY>"
        if budget.consume(summary_block):
            sections.append(summary_block)
        else:
            user_summary = ""

    fact_lines: list[str] = []
    for fact in candidates:
        line = fact.format_with_dates() if cfg.include_dates else f"- {fact.fact}"
        if not budget.consume(line):
            break
        fact_lines.append(line)
        included_facts.append(fact)

    if fact_lines:
        sections.append("<FACTS>\n" + "\n".join(fact_lines) + "\n</FACTS>")

    return ContextBlock(
        context="\n\n".join(sections),
        user_summary=user_summary,
        facts=included_facts,
        token_count=budget.used_tokens,
    )
