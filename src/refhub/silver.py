"""Lo que repiten los jobs de silver de foto completa (ISIN↔LEI, SEC y relaciones de GLEIF).

Son funciones sueltas que reciben `spark` y `s3` por parámetro: este módulo no importa pyspark
ni boto3, porque la Lambda también importa refhub y no los tiene. Cada job sigue diciendo de
arriba abajo qué hace; esto le ahorra solo los pasos que son iguales en los tres (ver la
revisión del hito 9 en docs/adr/0006).
"""

from importlib.resources import files

from refhub.bronze import file_name


def full_refresh_flag(value: str) -> bool:
    """El parámetro --FULL_REFRESH del job -> bool. Solo acepta "true" o "false".

    Un "True" o un "si" no pasa en silencio: con un typo, el job correría en modo normal y no
    recalcularía nada, sin que nadie se entere.
    """
    if value not in ("true", "false"):
        raise ValueError(f"--FULL_REFRESH tiene que ser true o false, no {value!r}")
    return value == "true"


def create_tables(spark, silver_db: str, ddl_names: list[str]) -> None:
    """Crea las tablas con su DDL (src/refhub/ddl/<nombre>.sql). Si ya existen, no las toca."""
    for name in ddl_names:
        ddl = files("refhub").joinpath(f"ddl/{name}.sql").read_text(encoding="utf-8")
        spark.sql(ddl.format(db=silver_db))


def latest_landing_key(s3, bucket: str, prefix: str) -> str:
    """El archivo más nuevo de una carpeta de landing (por ejemplo landing/sec/).

    Se ordena por el nombre del archivo y no por la carpeta dt=: los nombres de las tres fuentes
    llevan la fecha y la hora de publicación, y en un mismo día puede haber varios.
    """
    pages = s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
    keys = [obj["Key"] for page in pages for obj in page.get("Contents", [])]
    if not keys:
        raise ValueError(f"No hay archivos en {prefix}: primero corré la Lambda")
    return max(keys, key=file_name)


def already_in_silver(spark, table: str, name: str) -> bool:
    """¿La tabla ya tiene ese archivo? En una foto completa todas las filas vienen del mismo."""
    current = spark.table(table).select("_archivo").limit(1).collect()
    return bool(current) and current[0]["_archivo"] == name
