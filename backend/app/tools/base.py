from abc import ABC, abstractmethod


class Tool(ABC):
    name: str
    # Shown to the model when it selects a tool.
    description: str = ""
    # JSON Schema for the tool's arguments, sent to the model as `input_schema`.
    input_schema: dict = {"type": "object", "properties": {}}
    # Every permission this tool may require, declared for discovery/UI.
    permissions_required: set[str] = set()

    @abstractmethod
    async def execute(self, arguments: dict) -> dict:
        raise NotImplementedError

    def definition(self) -> dict:
        """The tool as the Messages API expects it."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
