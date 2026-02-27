import asyncio
import json
import logging

import openai

from app.config import (
    NEBIUS_API_KEY,
    NEBIUS_BASE_URL,
    PRIMARY_MODEL,
    MAP_MODEL,
    LLM_TEMPERATURE,
    LLM_MAX_TOKENS,
)
from app.prompts import (
    SINGLE_CALL_SYSTEM_PROMPT,
    SINGLE_CALL_USER_TEMPLATE,
    MAP_SYSTEM_PROMPT,
    REDUCE_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)


class LLMError(Exception):
    pass


def create_openai_client() -> openai.AsyncOpenAI:
    """Create an AsyncOpenAI client pointed at Nebius Token Factory."""
    return openai.AsyncOpenAI(
        api_key=NEBIUS_API_KEY,
        base_url=NEBIUS_BASE_URL,
    )


async def call_llm(
    prompt: str,
    system_prompt: str,
    model: str,
    client: openai.AsyncOpenAI,
) -> dict:
    """Call the LLM and return a parsed JSON dict. Retries once on JSON errors."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]

    for attempt in range(2):
        logger.debug(f"LLM call attempt {attempt + 1} — model={model}")
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=LLM_TEMPERATURE,
                max_tokens=LLM_MAX_TOKENS,
                response_format={"type": "json_object"},
            )
        except openai.OpenAIError as exc:
            raise LLMError(f"LLM API error: {exc}") from exc

        raw = response.choices[0].message.content or ""
        logger.debug(f"LLM raw response ({len(raw)} chars)")

        usage = response.usage
        if usage:
            logger.debug(
                f"LLM token usage — model={model}, "
                f"prompt={usage.prompt_tokens}, completion={usage.completion_tokens}, "
                f"total={usage.total_tokens}"
            )

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            if attempt == 0:
                logger.warning("LLM returned invalid JSON — retrying with fix request")
                # Ask the model to fix its own output
                messages = messages + [
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": (
                            "Your response was not valid JSON. "
                            "Please return ONLY a valid JSON object, no markdown, no extra text."
                        ),
                    },
                ]
            else:
                raise LLMError(f"LLM returned invalid JSON after retry: {raw[:200]!r}")

    raise LLMError("LLM call failed after all retries")


async def summarize_single(
    context: str,
    client: openai.AsyncOpenAI,
) -> dict:
    """Single-call summarization using the primary model."""
    logger.info(f"Single LLM call — model={PRIMARY_MODEL}")
    prompt = SINGLE_CALL_USER_TEMPLATE.format(context=context)
    result = await call_llm(prompt, SINGLE_CALL_SYSTEM_PROMPT, PRIMARY_MODEL, client)
    logger.info("Single LLM call complete")
    return result


async def summarize_map_reduce(
    chunks: list[str],
    tree_and_readme: str,
    client: openai.AsyncOpenAI,
) -> dict:
    """Map-reduce summarization: cheap map over chunks, primary model for reduce."""
    logger.info(f"Map step: {len(chunks)} chunks — model={MAP_MODEL}")

    # Map: extract from each chunk in parallel
    map_results = await asyncio.gather(
        *[call_llm(chunk, MAP_SYSTEM_PROMPT, MAP_MODEL, client) for chunk in chunks],
        return_exceptions=True,
    )

    partial_analyses: list[str] = []
    for i, result in enumerate(map_results):
        if isinstance(result, Exception):
            logger.warning(f"Map chunk {i} failed: {result}")
            continue
        partial_analyses.append(
            f"### Partial Analysis {i + 1}\n"
            f"Purpose: {result.get('purpose', 'N/A')}\n"
            f"Technologies: {', '.join(result.get('technologies', []))}\n"
            f"Structure notes: {result.get('structure_notes', 'N/A')}\n"
        )

    successful_chunks = len(partial_analyses)
    logger.info(f"Map step complete: {successful_chunks}/{len(chunks)} chunks succeeded")

    if not partial_analyses:
        raise LLMError("All map steps failed — no partial analyses to reduce")

    # Reduce: synthesize all partial analyses
    reduce_prompt = (
        f"{tree_and_readme}\n\n"
        f"## Partial Analyses\n\n"
        + "\n".join(partial_analyses)
    )

    logger.info(f"Reduce step — model={PRIMARY_MODEL}")
    result = await call_llm(reduce_prompt, REDUCE_SYSTEM_PROMPT, PRIMARY_MODEL, client)
    logger.info("Map-reduce complete")
    return result
