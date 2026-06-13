# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import copy
import logging


log = logging.getLogger(__name__)


def _sanitize_tool_calls(message: dict) -> None:
    tool_calls = message.get("tool_calls")
    if tool_calls is None:
        return

    if not isinstance(tool_calls, list):
        message.pop("tool_calls", None)
        return

    valid_tool_calls = []
    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            continue

        tool_call_type = tool_call.get("type")
        if tool_call_type == "function":
            function_payload = tool_call.get("function")
            if tool_call.get("id") and isinstance(function_payload, dict):
                valid_tool_calls.append(tool_call)
        elif tool_call_type == "custom":
            custom_payload = tool_call.get("custom")
            if tool_call.get("id") and custom_payload is not None:
                valid_tool_calls.append(tool_call)

    if valid_tool_calls:
        message["tool_calls"] = valid_tool_calls
    else:
        message.pop("tool_calls", None)


def _is_empty_assistant_message(message: dict) -> bool:
    return (
        message.get("role") == "assistant"
        and message.get("content") is None
        and not message.get("tool_calls")
    )


def sanitize_chat_history_tool_calls(messages: list[dict] | None) -> list[dict]:
    """Drop UI-only tool-call metadata before replaying chat history.

    History persistence stores richer replay-only transcript chunks in
    ``ui_parts``. Those UI-only shapes must be stripped before the prior
    assistant turn is sent back to the model on a later request. We also
    defensively validate ``tool_calls`` so malformed history rows do not
    reach providers.
    """
    if messages is None:
        return []

    prepared_messages: list[dict] = []
    for message in copy.deepcopy(messages):
        if not isinstance(message, dict):
            continue
        message.pop("ui_parts", None)
        _sanitize_tool_calls(message)
        prepared_messages.append(message)

    sanitized_messages: list[dict] = []
    index = 0
    while index < len(prepared_messages):
        message = prepared_messages[index]
        role = message.get("role")

        if role == "assistant" and message.get("tool_calls"):
            tool_calls = message["tool_calls"]
            tool_call_ids = {
                tool_call.get("id")
                for tool_call in tool_calls
                if isinstance(tool_call, dict) and tool_call.get("id")
            }
            matched_tool_messages = []
            matched_tool_call_ids = set()
            next_index = index + 1

            while next_index < len(prepared_messages):
                tool_message = prepared_messages[next_index]
                if tool_message.get("role") != "tool":
                    break

                tool_call_id = tool_message.get("tool_call_id")
                if tool_call_id in tool_call_ids:
                    matched_tool_messages.append(tool_message)
                    matched_tool_call_ids.add(tool_call_id)
                next_index += 1

            if matched_tool_call_ids:
                message["tool_calls"] = [
                    tool_call
                    for tool_call in tool_calls
                    if tool_call.get("id") in matched_tool_call_ids
                ]
            else:
                message.pop("tool_calls", None)

            if not _is_empty_assistant_message(message):
                sanitized_messages.append(message)
            sanitized_messages.extend(matched_tool_messages)
            index = next_index
            continue

        if role == "tool":
            index += 1
            continue

        if not _is_empty_assistant_message(message):
            sanitized_messages.append(message)
        index += 1

    return sanitized_messages
