"""La respuesta de la API de permisos: ¿esta aplicación puede usar este dataset para este propósito?

No evalúa políticas: busca la fila en la tabla de decisiones que compiló el CI con
`refhub.licencias` y publicó junto al código de su versión (ADR 0012). Por eso no necesita
rdflib, responde en lo que tarda un diccionario y cada respuesta dice de qué versión de las
políticas salió.
"""

from dataclasses import dataclass

CAMPOS = ("app", "dataset", "proposito")


class PedidoInvalido(ValueError):
    """El pedido no se puede responder: falta un campo o nombra algo que el catálogo no tiene.

    Es una clase aparte para que la API conteste 400 (el error es de quien pide) solo en este
    caso, y cualquier otra falla siga siendo un error del servicio.
    """


@dataclass(frozen=True)
class Tabla:
    version_politicas: str
    # (app, dataset, propósito) -> la decisión compilada.
    decisiones: dict[tuple[str, str, str], dict]


def cargar(contenido: dict) -> Tabla:
    """La tabla a partir del `decisiones.json` ya leído."""
    decisiones = {tuple(d[campo] for campo in CAMPOS): d for d in contenido["decisiones"]}
    return Tabla(contenido["version_politicas"], decisiones)


def decidir(tabla: Tabla, pedido: dict) -> dict:
    """La decisión para `{app, dataset, proposito}`, con la regla, las obligaciones y la versión.

    Un nombre que no está en la tabla es un error, no un "no": si la API negara en silencio un
    nombre mal escrito, quien pide no podría distinguir "la licencia no lo permite" de "pediste
    mal", y un banco tiene que poder saber por qué se le negó algo.
    """
    if not isinstance(pedido, dict):
        raise PedidoInvalido('el pedido tiene que ser un objeto {"app", "dataset", "proposito"}')
    faltan = [c for c in CAMPOS if not isinstance(pedido.get(c), str) or not pedido.get(c)]
    if faltan:
        raise PedidoInvalido(f"faltan campos (como texto): {', '.join(faltan)}")

    clave = tuple(pedido[campo] for campo in CAMPOS)
    decision = tabla.decisiones.get(clave)
    if decision is None:
        # La tabla tiene todas las combinaciones (el producto cartesiano que arma `compilar`):
        # si la clave no está, es porque alguno de los tres nombres no existe. Se dice cuál.
        for posicion, campo in enumerate(CAMPOS):
            if clave[posicion] not in {c[posicion] for c in tabla.decisiones}:
                raise PedidoInvalido(f"{campo} desconocido: {clave[posicion]!r}")

    return {
        "permitido": decision["permitido"],
        "motivo": decision["motivo"],
        "regla": decision["regla"],
        "obligaciones": decision["obligaciones"],
        "decidido_en": decision["decidido_en"],
        "version_politicas": tabla.version_politicas,
    }
