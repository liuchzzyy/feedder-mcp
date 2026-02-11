"""MCP prompt handler for feedder-mcp."""

from typing import Any, Dict, List, Optional


class PromptHandler:
    """Handles prompt listing and rendering."""

    def get_prompts(self) -> List[Any]:
        prompts: List[Dict[str, Any]] = [
            {
                "name": "feedder-mcp_research_prompt",
                "description": "Template for providing research interests.",
                "arguments": [
                    {
                        "name": "topic",
                        "description": "Research topic or area of interest",
                        "required": True,
                    }
                ],
            }
        ]

        try:
            from mcp.types import Prompt, PromptArgument  # type: ignore[import-untyped]

            return [
                Prompt(
                    name=p["name"],
                    description=p["description"],
                    arguments=[
                        PromptArgument(**arg) for arg in p.get("arguments", [])
                    ],
                )
                for p in prompts
            ]
        except Exception:
            return prompts

    def render_prompt(self, name: str, arguments: Optional[Dict[str, Any]]) -> List[Any]:
        args = arguments or {}
        if name != "feedder-mcp_research_prompt":
            raise ValueError(f"Unknown prompt: {name}")

        topic = str(args.get("topic", "")).strip()
        if not topic:
            raise ValueError("Prompt argument 'topic' is required")

        message = (
            "Provide a concise research prompt that describes your interests. "
            f"Topic: {topic}"
        )

        try:
            from mcp.types import PromptMessage, TextContent  # type: ignore[import-untyped]

            return [
                PromptMessage(
                    role="user",
                    content=[TextContent(type="text", text=message)],
                )
            ]
        except Exception:
            return [{"role": "user", "content": message}]
