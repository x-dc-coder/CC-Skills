from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class ColumnModel:
    name: str
    dataType: str
    nullable: bool = True
    isPrimaryKey: bool = False
    isUnique: bool = False
    defaultValue: str | None = None
    comment: str | None = None


@dataclass
class TableModel:
    id: str
    name: str
    schema: str | None = None
    columns: list[ColumnModel] = field(default_factory=list)
    primaryKey: list[str] = field(default_factory=list)
    uniqueSets: list[list[str]] = field(default_factory=list)


@dataclass
class RelationModel:
    id: str
    kind: str
    fromTable: str
    fromColumns: list[str]
    toTable: str
    toColumns: list[str]
    cardinality: str = "N:1"
    nullable: bool = True
    constraintName: str | None = None


@dataclass
class DiagramModel:
    tables: list[TableModel] = field(default_factory=list)
    relations: list[RelationModel] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
