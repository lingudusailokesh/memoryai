from collections.abc import Sequence
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON
from sqlalchemy.types import TypeDecorator


class Embedding(TypeDecorator[list[float]]):
    """pgvector `vector(dim)` on Postgres; a JSON list elsewhere (the SQLite unit tests use that)."""

    impl = Vector
    cache_ok = True

    def __init__(self, dim: int) -> None:
        self.dim = dim
        super().__init__(dim)

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Sequence[float] | None, dialect: Any) -> list[float] | None:
        return None if value is None else [float(x) for x in value]

    def process_result_value(self, value: Any, dialect: Any) -> list[float] | None:
        return None if value is None else [float(x) for x in value]
