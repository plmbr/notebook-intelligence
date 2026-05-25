# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import copy


def sanitize_chat_history_tool_calls(messages: list[dict] | None) -> list[dict]:
    """Drop UI-only tool-call metadata before replaying chat history.

    History persistence stores frontend replay metadata such as
    ``ui_tool_parameters`` and ``ui_message_parts`` inside assistant
    ``tool_calls``. Those shapes are not provider-native tool calls and can
    trigger request validation errors when the prior assistant turn is sent
    back to the model on a later request.
    """
    if messages is None:
        return []

    sanitized_messages = copy.deepcopy(messages)
    for message in sanitized_messages:
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue

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

    return sanitized_messages
