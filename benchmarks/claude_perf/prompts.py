"""Prompt bank for the Claude Code performance benchmark."""

PROMPTS: dict[str, dict] = {
    "short": {
        "text": "What is 2+2?",
        "description": "Trivial one-liner",
    },
    "medium": {
        "text": "Explain the difference between a list and a tuple in Python in 3 sentences.",
        "description": "One paragraph",
    },
    "code": {
        "text": (
            "Write a Python function that finds the longest common subsequence "
            "of two strings. Include type hints."
        ),
        "description": "Code generation",
    },
    "long": {
        "text": (
            "Compare merge sort and quicksort: time complexity, space complexity, "
            "stability, and when to prefer each. Be concise."
        ),
        "description": "Multi-step reasoning",
    },
}
