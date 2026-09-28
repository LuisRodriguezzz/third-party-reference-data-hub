# ADR 0002 · Guardar el archivo tal cual antes de procesarlo

- Estado: aceptado
- Fecha: 2026-09-28

## Contexto

GLEIF publica todos los días un delta con los LEIs que cambiaron, como un zip con un CSV
adentro. Ese archivo es el punto de partida de todo el hub: si lo procesamos directo al
bajarlo y algo sale mal (un bug en la lectura, una regla de validación equivocada, un cambio
de formato del proveedor), no queda nada para volver atrás.

## Decisión

Guardar el zip sin tocar en `landing/gleif/dt=AAAA-MM-DD/`, con el nombre que le da GLEIF.
La validación y las transformaciones leen siempre desde esa copia, nunca desde la red.

- La descarga es idempotente: si el archivo ya existe, no se vuelve a bajar.
- Se descarga a un archivo `.part` y se renombra al terminar, para que nunca quede un zip a
  medias con el nombre final.

## Por qué

- **Reprocesar sin volver a descargar:** si cambia una regla o el formato de algún campo, se
  corre de nuevo sobre el archivo guardado.
- **No depender del proveedor:** GLEIF hoy mantiene el histórico, pero un proveedor pago
  puede cobrar por cada descarga, limitar el acceso o corregir un archivo ya publicado.
- **Linaje y auditoría:** se puede mostrar exactamente qué se recibió y cuándo.
- Es la capa landing de la arquitectura medallion del hub.

## Alternativa descartada

Validar mientras se descarga y guardar solo las filas válidas. Es más simple, pero un error
en el código haría perder filas sin forma de recuperarlas, y no quedaría evidencia de lo que
mandó el proveedor.

## Consecuencias

- Ocupa almacenamiento: menos de 1 MB por día para el delta, un costo despreciable en S3.
- Los archivos de landing no se modifican ni se borran a mano; en S3 conviene definir una
  regla de ciclo de vida más adelante.
