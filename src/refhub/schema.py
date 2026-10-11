"""Esquema declarado de una tabla: qué columnas tiene, de qué tipo y si aceptan nulos.

Es la mitad "estructura" del contrato de silver; la otra mitad, las reglas por fila que
deciden la cuarentena, está en contract.py. Con el esquema escrito acá, y no deducido del
DataFrame que toque escribir:

1. El job crea cada tabla con un CREATE TABLE explícito: tipos, NOT NULL y descripciones.
2. Antes de escribir, compara el DataFrame con lo declarado y frena si no coincide.

Acá no hay Spark: son datos y funciones puras que se prueban con pytest.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

# Los tipos que usamos, escritos como los nombra Spark (DataType.simpleString()). Así el mismo
# texto sirve para el CREATE TABLE y para comparar con el esquema de un DataFrame.
TYPES = frozenset({"string", "date", "timestamp", "bigint"})
_NAME = re.compile(r"_?[a-z][a-z0-9_]*")  # minúsculas y guiones bajos, como en bronze


@dataclass(frozen=True)
class Column:
    """Una columna declarada. Por defecto es obligatoria (NOT NULL): aceptar nulos se pide."""

    name: str
    type: str
    description: str
    nullable: bool = False

    def __post_init__(self):
        # Un error de tipeo ('timestmap') tiene que fallar en pytest, no en Glue.
        if not _NAME.fullmatch(self.name):
            raise ValueError(f"Nombre de columna inválido: {self.name!r}")
        if self.type not in TYPES:
            raise ValueError(f"{self.name}: el tipo {self.type!r} no está en {sorted(TYPES)}")
        if not self.description.strip():
            raise ValueError(f"{self.name}: falta la descripción")
        # La descripción va entre comillas simples en el SQL: sin comillas ni barras adentro,
        # no hay nada que escapar. 255 es el máximo que guarda el catálogo de Glue.
        if "'" in self.description or "\\" in self.description:
            raise ValueError(f"{self.name}: la descripción no puede tener comillas simples ni \\")
        if len(self.description) > 255:
            raise ValueError(f"{self.name}: la descripción pasa los 255 caracteres")


def create_table_sql(
    table: str, columns: Sequence[Column], partitioned_by: str | None = None
) -> str:
    """CREATE TABLE IF NOT EXISTS (Spark SQL, Iceberg) con tipos, NOT NULL y descripciones.

    IF NOT EXISTS: si la tabla ya existe, no hace nada; tampoco la cambia. Por eso el job,
    después de correrlo, compara la tabla real con lo declarado (ver schema_problems).
    """
    names = [c.name for c in columns]
    repeated = sorted({n for n in names if names.count(n) > 1})
    if repeated:
        raise ValueError(f"Columnas repetidas: {repeated}")
    if partitioned_by is not None and partitioned_by not in names:
        raise ValueError(f"La partición {partitioned_by!r} no es una de las columnas")

    # Los nombres van entre comillas invertidas: así un nombre que empieza con _ no molesta.
    lines = [
        f"  `{c.name}` {c.type}{'' if c.nullable else ' NOT NULL'} COMMENT '{c.description}'"
        for c in columns
    ]
    sql = f"CREATE TABLE IF NOT EXISTS {table} (\n" + ",\n".join(lines) + "\n)\nUSING iceberg"
    if partitioned_by is not None:
        sql += f"\nPARTITIONED BY (`{partitioned_by}`)"
    return sql + "\nTBLPROPERTIES ('format-version' = '2')"


def schema_problems(
    expected: Sequence[Column],
    actual: Iterable[tuple[str, str, bool]],
    *,
    check_nullable: bool = False,
) -> list[str]:
    """Qué no coincide entre el esquema declarado y uno real. Lista vacía si coinciden.

    `actual` son tuplas (nombre, tipo, acepta_nulos), como salen de un esquema de Spark:
    [(f.name, f.dataType.simpleString(), f.nullable) for f in df.schema.fields].
    El orden de las columnas no importa: Spark escribe por nombre.

    check_nullable: comparar también si aceptan nulos. Sirve para la tabla ya creada (el
    catálogo sabe cuáles son NOT NULL), no para un DataFrame: Spark marca casi todas sus
    columnas como "pueden ser nulas" aunque nunca lo sean. Al escribir, el NOT NULL lo hace
    cumplir la tabla: si aparece un nulo en una columna NOT NULL, la escritura falla.
    """
    real = {name: (type_, nullable) for name, type_, nullable in actual}
    declared = {c.name for c in expected}
    problems = []
    for c in expected:
        if c.name not in real:
            problems.append(f"falta la columna {c.name}")
            continue
        type_, nullable = real[c.name]
        if type_ != c.type:
            problems.append(f"{c.name}: se esperaba {c.type}, llegó {type_}")
        if check_nullable and nullable != c.nullable:
            esperado = "que acepte nulos" if c.nullable else "NOT NULL"
            problems.append(f"{c.name}: se esperaba {esperado}")
    problems += [f"sobra la columna {name}" for name in real if name not in declared]
    return problems
