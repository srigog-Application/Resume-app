import json
import pathlib

import pydantic
import pydantic_core

from cvengine import __description__

from .models.cvengine_model import CVEngineModel


def generate_json_schema() -> dict:
    """Generate JSON Schema (Draft-07) from CVEngine Pydantic models.

    Why:
        IDEs and validators need machine-readable schema for autocompletion
        and real-time validation. Custom generator adds CVEngine-specific
        metadata like title, description, and canonical schema URL.

    Returns:
        Draft-07 JSON Schema dictionary.
    """

    class CVEngineSchemaGenerator(pydantic.json_schema.GenerateJsonSchema):
        def generate(
            self,
            schema: pydantic_core.CoreSchema,
            mode: pydantic.json_schema.JsonSchemaMode = "validation",
        ) -> pydantic.json_schema.JsonSchemaValue:
            json_schema = super().generate(schema, mode=mode)
            json_schema["title"] = "CVEngine"
            json_schema["description"] = __description__
            json_schema["$id"] = (
                "https://raw.githubusercontent.com/cvengine/cvengine/main/schema.json"
            )
            json_schema["$schema"] = "http://json-schema.org/draft-07/schema#"
            return json_schema

    return CVEngineModel.model_json_schema(schema_generator=CVEngineSchemaGenerator)


def generate_json_schema_file(json_schema_path: pathlib.Path) -> None:
    """Generate and save JSON Schema to file.

    Args:
        json_schema_path: Target file path for schema output.
    """
    schema = generate_json_schema()
    schema_json = json.dumps(schema, indent=2, ensure_ascii=False)
    json_schema_path.write_text(schema_json, encoding="utf-8")
