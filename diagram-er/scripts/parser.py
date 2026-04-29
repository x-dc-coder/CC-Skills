from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlglot import exp, parse
from sqlglot.errors import ParseError

from scripts.models import ColumnModel, DiagramModel, TableModel


@dataclass
class _PendingFK:
    from_table_id: str
    from_columns: list[str]
    to_table_id: str
    to_columns: list[str]
    constraint_name: str | None
    nullable: bool


def ddl_to_model(sql: str, dialect: str = "mysql") -> dict:
    """解析 SQL DDL 为模型（单表模式，不处理关系）"""
    model = DiagramModel()
    tables: dict[str, TableModel] = {}

    try:
        statements = parse(sql, read=dialect)
    except ParseError as exc:
        model.warnings.append(f"SQL parse error: {exc}")
        return model.to_dict()

    for stmt in statements:
        try:
            if isinstance(stmt, exp.Create) and (stmt.kind or "").upper() == "TABLE":
                _handle_create_table(stmt, tables)
            elif isinstance(stmt, exp.Alter) and (stmt.kind or "").upper() == "TABLE":
                _handle_alter_table(stmt, tables)
        except Exception as exc:
            model.warnings.append(f"Failed to process statement `{stmt.sql()}`: {exc}")

    model.tables = list(tables.values())
    return model.to_dict()


def _handle_create_table(
    stmt: exp.Create,
    tables: dict[str, TableModel],
) -> None:
    schema_expr = stmt.this
    if not isinstance(schema_expr, exp.Schema):
        return

    table_expr = schema_expr.this
    table_id, table_name, table_schema = _table_identity(table_expr)

    table = TableModel(id=table_id, name=table_name, schema=table_schema)
    columns_by_name: dict[str, ColumnModel] = {}

    for expr in schema_expr.expressions or []:
        if isinstance(expr, exp.ColumnDef):
            column = _parse_column(expr)
            table.columns.append(column)
            columns_by_name[column.name] = column

            if column.isPrimaryKey and column.name not in table.primaryKey:
                table.primaryKey.append(column.name)
            if column.isUnique:
                table.uniqueSets.append([column.name])

        elif isinstance(expr, exp.PrimaryKey):
            cols = _identifier_list(expr.expressions)
            table.primaryKey = cols
            for col_name in cols:
                if col_name in columns_by_name:
                    columns_by_name[col_name].isPrimaryKey = True
                    columns_by_name[col_name].nullable = False

        elif isinstance(expr, exp.UniqueColumnConstraint):
            cols = _identifier_list(expr.expressions)
            if cols:
                table.uniqueSets.append(cols)
                if len(cols) == 1 and cols[0] in columns_by_name:
                    columns_by_name[cols[0]].isUnique = True

        elif isinstance(expr, exp.Constraint):
            _handle_named_constraint(expr, table, columns_by_name)

    tables[table.id] = table


def _handle_alter_table(
    stmt: exp.Alter,
    tables: dict[str, TableModel],
) -> None:
    table_id, _, _ = _table_identity(stmt.this)
    table = tables.get(table_id)
    if table is None:
        return

    columns_by_name = {c.name: c for c in table.columns}

    for action in stmt.args.get("actions") or []:
        if isinstance(action, exp.AddConstraint):
            for item in action.expressions or []:
                if isinstance(item, exp.Constraint):
                    _handle_named_constraint(item, table, columns_by_name)


def _handle_named_constraint(
    expr: exp.Constraint,
    table: TableModel,
    columns_by_name: dict[str, ColumnModel],
) -> None:
    for inner in expr.expressions or []:
        if isinstance(inner, exp.PrimaryKey):
            cols = _identifier_list(inner.expressions)
            table.primaryKey = cols
            for col_name in cols:
                if col_name in columns_by_name:
                    columns_by_name[col_name].isPrimaryKey = True
                    columns_by_name[col_name].nullable = False

        elif isinstance(inner, exp.UniqueColumnConstraint):
            cols = _identifier_list(inner.expressions)
            if cols:
                table.uniqueSets.append(cols)
                if len(cols) == 1 and cols[0] in columns_by_name:
                    columns_by_name[cols[0]].isUnique = True


def _parse_column(col: exp.ColumnDef) -> ColumnModel:
    name = col.this.name
    data_type = col.kind.sql() if col.kind is not None else "UNKNOWN"

    nullable = True
    is_pk = False
    is_unique = False
    default_value: str | None = None
    comment: str | None = None

    for c in col.args.get("constraints") or []:
        kind = c.kind
        if isinstance(kind, exp.PrimaryKeyColumnConstraint):
            is_pk = True
            nullable = False
        elif isinstance(kind, exp.UniqueColumnConstraint):
            is_unique = True
        elif isinstance(kind, exp.NotNullColumnConstraint):
            nullable = False
        elif isinstance(kind, exp.DefaultColumnConstraint):
            default_value = kind.this.sql() if kind.this is not None else None
        elif isinstance(kind, exp.CommentColumnConstraint):
            if kind.this is not None:
                comment = getattr(kind.this, "this", None) or kind.this.sql()

    return ColumnModel(
        name=name,
        dataType=data_type,
        nullable=nullable,
        isPrimaryKey=is_pk,
        isUnique=is_unique,
        defaultValue=default_value,
        comment=comment,
    )


def _table_identity(table_expr: exp.Expression, default_schema: str | None = None) -> tuple[str, str, str | None]:
    if isinstance(table_expr, exp.Table):
        schema = table_expr.db or default_schema
        name = table_expr.name
    else:
        name = table_expr.sql()
        schema = default_schema

    table_id = f"{schema}.{name}" if schema else name
    return table_id, name, schema


def _identifier_list(expressions: Iterable[exp.Expression]) -> list[str]:
    names: list[str] = []
    for e in expressions or []:
        if isinstance(e, exp.Identifier):
            names.append(e.name)
        elif isinstance(e, exp.Column):
            names.append(e.name)
        else:
            names.append(e.sql())
    return names
