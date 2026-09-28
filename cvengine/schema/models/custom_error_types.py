from enum import StrEnum


class CustomPydanticErrorTypes(StrEnum):
    entry_validation = "cvengine_entry_validation_error"
    other = "cvengine_other_error"
