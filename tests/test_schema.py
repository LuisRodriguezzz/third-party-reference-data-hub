"""Tests del esquema declarado (CREATE TABLE y comparación), sin Spark."""

import pytest

from refhub.schema import Column, create_table_sql, schema_problems

TABLA = (
    Column("id", "string", "Identificador"),
    Column("cuando", "timestamp", "Fecha y hora (UTC)"),
    Column("nota", "string", "Comentario libre", nullable=True),
)


def como_spark(columns, **cambios):
    """El esquema tal como lo describiría Spark: (nombre, tipo, acepta_nulos)."""
    return [(c.name, cambios.get(c.name, c.type), c.nullable) for c in columns]


def test_create_table_sql_declara_tipos_not_null_y_descripciones():
    assert create_table_sql("glue_catalog.db.t", TABLA, partitioned_by="id") == (
        "CREATE TABLE IF NOT EXISTS glue_catalog.db.t (\n"
        "  `id` string NOT NULL COMMENT 'Identificador',\n"
        "  `cuando` timestamp NOT NULL COMMENT 'Fecha y hora (UTC)',\n"
        "  `nota` string COMMENT 'Comentario libre'\n"
        ")\n"
        "USING iceberg\n"
        "PARTITIONED BY (`id`)\n"
        "TBLPROPERTIES ('format-version' = '2')"
    )


def test_sin_particion_no_hay_partitioned_by():
    assert "PARTITIONED BY" not in create_table_sql("db.t", TABLA)


def test_la_particion_tiene_que_ser_una_columna():
    with pytest.raises(ValueError, match="partición"):
        create_table_sql("db.t", TABLA, partitioned_by="otra")


def test_no_puede_haber_columnas_repetidas():
    with pytest.raises(ValueError, match="repetidas"):
        create_table_sql("db.t", (*TABLA, Column("id", "string", "Otra vez")))


@pytest.mark.parametrize(
    ("args", "error"),
    [
        (("cuando", "timestmap", "Fecha"), "tipo"),  # error de tipeo: falla acá, no en Glue
        (("Cuando", "timestamp", "Fecha"), "Nombre"),  # mayúsculas
        (("cuando", "timestamp", "  "), "descripción"),
        (("cuando", "timestamp", "La 'fecha'"), "comillas"),
        (("cuando", "timestamp", "x" * 256), "255"),
    ],
)
def test_una_columna_mal_declarada_falla_al_importar(args, error):
    with pytest.raises(ValueError, match=error):
        Column(*args)


def test_si_coincide_no_hay_problemas():
    assert schema_problems(TABLA, como_spark(TABLA)) == []


def test_el_orden_de_las_columnas_no_importa():
    assert schema_problems(TABLA, reversed(como_spark(TABLA))) == []


def test_detecta_un_tipo_distinto():
    # Lo que pasaría si alguien borra el to_timestamp: la fecha llega como texto.
    real = como_spark(TABLA, cuando="string")
    assert schema_problems(TABLA, real) == ["cuando: se esperaba timestamp, llegó string"]


def test_detecta_columnas_que_faltan_y_que_sobran():
    real = [*como_spark(TABLA[:2]), ("motivo", "string", True)]
    assert schema_problems(TABLA, real) == ["falta la columna nota", "sobra la columna motivo"]


def test_la_nulabilidad_solo_se_compara_si_se_pide():
    # Spark marca casi todo como "puede ser nulo": en un DataFrame no se compara.
    todo_nullable = [(name, type_, True) for name, type_, _ in como_spark(TABLA)]
    assert schema_problems(TABLA, todo_nullable) == []
    # En la tabla ya creada sí: el catálogo sabe cuáles son NOT NULL.
    assert schema_problems(TABLA, todo_nullable, check_nullable=True) == [
        "id: se esperaba NOT NULL",
        "cuando: se esperaba NOT NULL",
    ]
