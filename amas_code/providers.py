"""LiteLLM wrapper — one function for all providers."""
import time
import litellm

from amas_code import ui

# Suppress litellm's noisy debug logs
litellm.suppress_debug_info = True

_RETRYABLE = ("503", "429", "overloaded", "unavailable", "rate limit", "high demand", "disconnected", "apiconnectionerror", "connection reset", "connection error")
_MAX_RETRIES = 10


def complete(messages: list[dict], tools: list[dict] | None, config: dict, on_chunk=None) -> dict:
    """Call LLM with streaming. Returns the final assembled message dict.

    Args:
        messages: Conversation messages list.
        tools: Tool schemas (or None for Phase 1 no-tools mode).
        config: Config dict with model, api_key, api_base, etc.
        on_chunk: Optional callback(text_chunk) for streaming UI updates.

    Returns:
        Complete assistant message dict with role, content, and optionally tool_calls.
    """
    kwargs = {
        "model": config["model"],
        "messages": messages,
        "stream": config.get("stream", True),
        "max_tokens": 128000,
        "drop_params": True,
    }

    if tools:
        kwargs["tools"] = tools
    if config.get("api_key"):
        kwargs["api_key"] = config["api_key"]
    if config.get("api_base"):
        kwargs["api_base"] = config["api_base"]

    for attempt in range(_MAX_RETRIES):
        try:
            response = litellm.completion(**kwargs)
            break
        except Exception as e:
            err_str = str(e).lower()
            if attempt < _MAX_RETRIES - 1 and any(k in err_str for k in _RETRYABLE):
                ui.warning(f"API error (attempt {attempt + 1}/{_MAX_RETRIES}), retrying in 5s…")
                time.sleep(5)
            else:
                ui.error(f"LLM API error: {e}")
                return {"role": "assistant", "content": f"Error calling model: {e}"}

    if not config.get("stream", True):
        msg = response.choices[0].message
        return {"role": "assistant", "content": msg.content or "", "tool_calls": getattr(msg, "tool_calls", None)}

    return _stream(response, kwargs, on_chunk)


def _stream(response, kwargs: dict, on_chunk) -> dict:
    """Consume a streaming response, retrying on transient errors (non-recursive)."""
    for attempt in range(_MAX_RETRIES):
        content_parts = []
        tool_calls_map = {}

        try:
            for chunk in response:
                delta = chunk.choices[0].delta if chunk.choices else None
                if not delta:
                    continue

                if delta.content:
                    content_parts.append(delta.content)
                    if on_chunk:
                        on_chunk(delta.content)

                if hasattr(delta, "tool_calls") and delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index if (hasattr(tc, "index") and tc.index is not None) else 0
                        if idx not in tool_calls_map:
                            tool_calls_map[idx] = {
                                "id": getattr(tc, "id", "") or "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        entry = tool_calls_map[idx]
                        if tc.id:
                            entry["id"] = tc.id
                        if hasattr(tc, "function") and tc.function:
                            if tc.function.name:
                                entry["function"]["name"] = tc.function.name
                            if tc.function.arguments:
                                entry["function"]["arguments"] += tc.function.arguments
            break  # Stream completed successfully

        except KeyboardInterrupt:
            ui.warning("Generation interrupted.")
            break

        except Exception as e:
            err_str = str(e).lower()
            is_retryable = any(k in err_str for k in _RETRYABLE)
            # Only retry if nothing printed yet — avoids duplicate output
            if is_retryable and not content_parts and not tool_calls_map and attempt < _MAX_RETRIES - 1:
                ui.warning(f"Streaming error, retrying in 5s… ({attempt + 1}/{_MAX_RETRIES - 1})")
                time.sleep(5)
                try:
                    response = litellm.completion(**kwargs)
                except Exception:
                    pass
                continue
            ui.error(f"Streaming error: {e}")
            break

    result = {"role": "assistant", "content": "".join(content_parts)}
    if tool_calls_map:
        result["tool_calls"] = [tool_calls_map[i] for i in sorted(tool_calls_map)]
    return result
