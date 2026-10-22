# Dos consumidores locales de la golden copy (runbook)

En un banco la golden copy no se usa sola: la consumen otros sistemas. Esta carpeta levanta dos,
en tu máquina con Podman, alimentados con lo que el hub ya tiene en gold y silver
([ADR 0014](../docs/adr/0014-consumidores-locales.md)):

1. **OpenSearch, el buscador de contrapartes.** Un analista escribe un nombre como lo recuerda y
   encuentra la empresa con todos sus códigos. Es OpenSearch, el fork de Elasticsearch 7.10 que
   mantiene la Linux Foundation (licencia Apache 2.0): el Query DSL de los archivos `.json` es
   casi el mismo que en Elasticsearch.
2. **Oracle Free (Oracle AI Database 26ai Free), el sistema de riesgo** que suma la exposición
   por grupo económico recorriendo el árbol de consolidación con `CONNECT BY` y con `WITH`
   recursivo.

Ninguno es parte del hub: reciben una copia y no escriben nada de vuelta. **La cartera de Oracle
es sintética** (ADR 0013): LEIs reales con montos y préstamos inventados. Las cifras de exposición
de abajo no son un hallazgo.

| Archivo | Qué hace |
|---|---|
| `compose.yaml` | los dos contenedores, con versión fija, límite de memoria y puertos solo en `127.0.0.1` |
| `.env.example` | la forma de `local/.env` (la contraseña de Oracle; `.env` lo ignora git) |
| `exportar.py` | corre los SELECT en Athena y baja los CSV de resultados |
| `cargar_opensearch.py` | arma un documento por empresa (`refhub.contrapartes`) y lo carga con la Bulk API |
| `opensearch/indice.json` | settings y mapping del índice `contrapartes` |
| `opensearch/consultas/*.json` | consultas de ejemplo en Query DSL |
| `cargar_oracle.py` | crea el usuario `RIESGO`, las tablas (`oracle/esquema.sql`) y las llena |
| `oracle/consultas/*.sql` | consultas de ejemplo: árbol, exposición por grupo y comparación |

## Requisitos

- Podman (o Docker) con `podman-compose` (o `docker compose`). Las imágenes oficiales pesan
  (comprimidas, lo que se baja) 1,16 GB OpenSearch `3.9.0` y 0,90 GB Oracle Free
  `23.26.3.0-lite`; ya descomprimidas, 1,7 GB y 1,82 GB. La variante lite de
  Oracle es la base entera sin los componentes opcionales; la completa pesa 3,7 GB comprimida.
  Oracle la sirve sin login.
- Unos 4 GB de RAM libres para la máquina de Podman (WSL en Windows) con los dos prendidos:
  medido con las consultas ya corridas, 1,59 GB OpenSearch (tope de 2 GB) y 2,29 GB Oracle
  (tope de 3 GB).
- Credenciales de AWS para exportar (solo lectura) y uv: `uv sync --group local` instala
  `boto3` y `oracledb` (modo thin: no hace falta el Instant Client de Oracle).

En Windows conviene un entorno virtual en una ruta corta (por ejemplo
`$env:UV_PROJECT_ENVIRONMENT = "$HOME\refhub-local\venv"`). Los CSV van a `~/refhub-local/datos`
(o a la carpeta de `REFHUB_LOCAL_DATOS`), fuera del repo.

## Pasos

Desde la raíz del repo (PowerShell).

**1. La contraseña de Oracle**, una sola vez. Es de una base local de desarrollo: se genera
al azar y queda en `local/.env`, que git ignora.

```powershell
uv run python -c "import secrets; print('ORACLE_PWD=Refhub' + secrets.token_hex(8) + '1')" | Out-File -Encoding ascii local/.env
```

**2. Exportar de Athena** (siete SELECT en el workgroup `refhub-dev`, unos 300 MB leídos en
total, menos de un centavo):

```powershell
uv run --group local python local/exportar.py
```

**3. Prender** (si la máquina de Podman está apagada: `podman machine start`):

```powershell
cd local
podman-compose up -d
podman logs -f refhub-oracle   # esperar "DATABASE IS READY TO USE!" y cortar con Ctrl+C
cd ..
```

**4. Cargar:**

```powershell
uv run --group local python local/cargar_opensearch.py
uv run --group local python local/cargar_oracle.py
```

**5. Consultar.** OpenSearch, con `curl.exe` (en PowerShell, `curl` a secas es otro comando):

```powershell
curl.exe -s -H "Content-Type: application/json" "http://127.0.0.1:9200/contrapartes/_search?pretty" --data-binary "@local/opensearch/consultas/01_difusa_berkshire.json"
```

Oracle, con SQL*Plus adentro del contenedor: compose monta `oracle/consultas/` en `/consultas`
(solo lectura), así el archivo llega tal cual, con sus tildes. La contraseña sale de `local/.env`:

```powershell
$clave = (Get-Content local/.env | Select-String '^ORACLE_PWD=').Line.Split('=', 2)[1]
podman exec refhub-oracle sqlplus -s "riesgo/$clave@FREEPDB1" "@/consultas/01_arbol_connect_by.sql"
```

**6. Apagar.** `down` borra los contenedores pero no los volúmenes: los datos cargados siguen
ahí la próxima vez que se prendan.

```powershell
cd local
podman-compose down
```

Para borrar también los datos: `podman-compose down -v`.

## OpenSearch: el buscador de contrapartes

**Qué se indexa.** Un documento por empresa, armado por `refhub.contrapartes.armar_documentos`
(las reglas tienen tests en `tests/test_contrapartes.py`): la clave es el LEI; una empresa de la
SEC sin LEI entra por su CIK (`CIK-0000000000`); dos CIKs con el mismo LEI son un documento. El
alcance es la golden copy entera (8.029 CIKs) más las empresas de EE. UU. de GLEIF con registro
`ISSUED` o `LAPSED` (342.373): **346.831 documentos, 83,5 MB de índice**. Cada documento trae
sus ISINs (una empresa tiene 128.314), FIGIs, tickers y CIKs.

**El mapping** (`opensearch/indice.json`) es explícito y estricto (`dynamic: strict`: un campo
que no está declarado es un error, no un campo nuevo adivinado):

- `nombres` (texto) con el analizador `nombres`: minúsculas, sin tildes (`asciifolding`) y sin las
  formas legales (`inc`, `corp`, `llc`...), la misma lista que `refhub.names`. Así "Berkshire
  Hathaway Inc." y "BERKSHIRE HATHAWAY INC" quedan iguales y lo que pesa en la búsqueda es el
  nombre, no el "Inc.".
- Un `keyword` por esquema (`lei`, `ciks`, `isins`, `figis`, `tickers`): un código no se analiza.
  Con texto analizado, `BRK-B` se partiría en `brk` y `b`.
- `identificadores`: los mismos códigos juntados con `copy_to` en un `keyword` que compara en
  minúscula (`normalizer`). Buscar por LEI, ISIN, CIK o ticker es una sola consulta.

**Resultados reales** (22-oct-2026, sobre la foto de gold del 21-oct):

`01_difusa_berkshire.json`: `match` sobre `nombres` con `fuzziness: AUTO` y `operator: and` (las
dos palabras tienen que estar, con hasta dos letras de diferencia en las largas), más un `should`
que sube a las empresas de la golden copy. "berkshire hathway" (le falta una "a"):

| Puntaje | Nombre | LEI | Tickers |
|---:|---|---|---|
| 12,19 | BERKSHIRE HATHAWAY INC. | 5493000C01ZX7D35SD85 | BRK-A, BRK-B |
| 7,05 | BERKSHIRE HATHAWAY ENERGY COMPANY | 549300JD0S5IZJE9LY15 | |
| 7,05 | BERKSHIRE HATHAWAY FINANCE CORPORATION | 549300RLHFT5RU20WM87 | |
| 6,28 | Berkshire Hathaway Specialty Insurance Company | 254900P4F4Z4OXQ6I912 | |
| 5,15 | Berkshire Hathaway Life Insurance Company of Nebraska | 254900FB258ZV9OKJW14 | |

La controlante sale primera, y abajo sus controladas de EE. UU., que vienen de GLEIF: justo lo
que necesita un analista que va a cargar un préstamo y no sabe a qué entidad del grupo.

`02_difusa_apple.json`: "apple computer" (el nombre de Apple hasta 2007) con `operator: or`.
Ningún registro se llama así hoy; 221 documentos tienen alguna de las dos palabras:

| Puntaje | Nombre | LEI | Tickers |
|---:|---|---|---|
| 8,47 | Apple Inc. | HWUPKR0MPOU8FGXBT394 | AAPL |
| 8,19 | SUPER MICRO COMPUTER, INC. | 54930022CZO1N2UGVW07 | SMCI, SMCIP |
| 7,82 | COMPUGEN LTD | (sin LEI) | CGEN |
| 7,75 | Alpha Compute Corp | (sin LEI) | ALP |
| 7,23 | Apple Hospitality REIT, Inc. | 549300EVZAR0FBZO4F16 | APLE |

Apple sale primera, pero la búsqueda difusa también encuentra "Compugen" y "Compute" a dos letras
de "computer". Es el motivo por el que el cruce de la golden copy **no** usa búsqueda difusa
(ADR 0008): acá una persona mira y elige; en el cruce, un falso positivo sumaría exposición a
quien no es.

`03_por_identificador.json`: `terms` sobre `identificadores` con cuatro códigos de esquemas
distintos: un ISIN (`US5949181045`), un CIK (`0001067983`), un LEI (`8I5DZWZKVSZI1NUHU748`) y un
ticker en minúscula (`aapl`). Devuelve cuatro empresas, puntaje 1,0 cada una (una búsqueda
exacta no ordena por relevancia):

| Código buscado | Empresa | LEI |
|---|---|---|
| ISIN US5949181045 | MICROSOFT CORPORATION | INR2EJN1ERAN0W5ZP974 |
| CIK 0001067983 | BERKSHIRE HATHAWAY INC. | 5493000C01ZX7D35SD85 |
| LEI 8I5DZWZKVSZI1NUHU748 | JPMORGAN CHASE & CO. | 8I5DZWZKVSZI1NUHU748 |
| ticker aapl | Apple Inc. | HWUPKR0MPOU8FGXBT394 |

`04_agregacion_por_camino.json`: las empresas de la golden copy por el camino que les dio el LEI,
con cuántas tienen LEI, cuántas quedaron ambiguas y cuántas en conflicto (`terms` con
sub-agregaciones `filter`):

| Camino | Documentos | Con LEI | Ambiguas | En conflicto |
|---|---:|---:|---:|---:|
| sin candidato | 3.765 | 0 | 0 | 0 |
| códigos | 2.684 | 2.684 | 0 | 54 |
| nombre | 1.572 | 1.553 | 19 | 0 |

Son 8.021 documentos y no 8.029 CIKs porque 8 LEIs los eligieron dos CIKs cada uno, y acá son un
documento. Por eso hay 2.684 por códigos y no los 2.686 CIKs de `gold.scorecard_cruce`.

## Oracle: el sistema de riesgo

**Qué se carga** (usuario `RIESGO` en la base `FREEPDB1`):

| Tabla | Filas | De dónde |
|---|---:|---|
| `relaciones_directas` | 127.213 | `IS_DIRECTLY_CONSOLIDATED_BY` vigentes de `silver.gleif_relaciones` |
| `entidades` | 169.598 | nombre y país de esas empresas y de la cartera (`silver.gleif_lei`) |
| `cartera_sintetica` | 296 | `gold.cartera_sintetica`: **montos inventados** |
| `controlante_publicada` | 281 | la controlante final de GLEIF para cada LEI de la cartera (`gold.grupos`) |

"Vigente" es el mismo criterio de `gold.grupos` (ADR 0013): relación `ACTIVE` y sin fecha de fin
pasada.

La carga tarda unos 8 segundos (`executemany` de a 50 mil filas); la de OpenSearch, unos 50.

La vista `cabeza_por_prestamo` (en `oracle/esquema.sql`) pone cada préstamo al lado de las dos
cabezas posibles de su grupo: la que sale de **subir por el árbol** de consolidación directa
(`CONNECT BY` hacia arriba, hasta que no hay más controlante) y la **controlante final
publicada** por GLEIF, la que usa gold.

**Resultados reales** (22-oct-2026, Oracle AI Database 26ai Free 23.26.3; montos inventados):

`01_arbol_connect_by.sql`: el árbol de FABER FIVE S.R.L. (`815600CBA3B99EDBA070`), de la
controlante hacia abajo, con `START WITH`, `CONNECT BY PRIOR`, `LEVEL` y `SYS_CONNECT_BY_PATH`
(el camino usa los últimos 6 caracteres de cada LEI para que entre en pantalla):

```text
NIVEL EMPRESA                                                        CAMINO
    1 "RATTI S.P.A. SOCIETA' BENEFIT" O IN FORMA ABBREVIATA "RATTI   /C0D147
    1 WIZARD - S.R.L.                                                /3A9415
    2   MANIFATTURA LANE GAETANO MARZOTTO & FIGLI S.P.A. O PIU' BR   /3A9415/7BE215
    3     MARZOTTO WOOL MANUFACTURING S.R.L.                         /3A9415/7BE215/1D3E14
    4       BIELLA MANIFATTURE TESSILI S.R.L.                        /3A9415/7BE215/1D3E14/54FD26
    3     MARZOTTO LAB S.R.L.                                        /3A9415/7BE215/281442
    4       SAMETEX, spol. s r.o.                                    /3A9415/7BE215/281442/T78F41
    4       LINIFICIO E CANAPIFICIO NAZIONALE S.R.L. SOCIETA' BENE   /3A9415/7BE215/281442/66B623
```

`02_arbol_with_recursivo.sql`: la misma consulta en SQL estándar (`WITH` recursivo, con
`SEARCH DEPTH FIRST` para el orden del árbol y `CYCLE` contra ciclos). **Da exactamente las
mismas 8 filas, en el mismo orden.** `CONNECT BY` es más corto; `WITH` recursivo corre en
cualquier base que siga el estándar.

`03_exposicion_rollup.sql`: la exposición por grupo con la cabeza del árbol, con
`GROUP BY ROLLUP (grupo, empresa)`: una sola consulta da el préstamo de cada empresa, el subtotal
de cada grupo y el total. Los cinco grupos más expuestos entre los que tienen más de una empresa
con préstamos (resumido: la consulta muestra también cada empresa):

| Grupo (cabeza del árbol) | Empresas con préstamos | Subtotal (USD, inventado) |
|---|---:|---:|
| LOUIS DREYFUS COMPANY B.V. | 9 | 23.217.000 |
| M&T BANK CORPORATION | 9 | 22.185.000 |
| EFG International AG | 8 | 19.630.000 |
| EUROCLEAR HOLDING | 8 | 18.804.000 |
| FABER FIVE S.R.L. | 7 | 17.253.000 |
| **Total de los cinco** | | **101.089.000** |

El préstamo más grande de la cartera es de 11,8 millones; sumados por grupo, cinco grupos
pasan los 17. Es lo que la exposición por grupo tiene que hacer visible.

`04_arbol_contra_publicada.sql`: las dos cabezas lado a lado, préstamo por préstamo:

| Resultado | Préstamos | Monto (USD, inventado) |
|---|---:|---:|
| iguales: la empresa es su propio grupo | 168 | 963.763.000 |
| iguales: misma cabeza | 108 | 277.913.000 |
| distintos: la empresa no declara controlante directa | 16 | 30.918.000 |
| distintos: el árbol corta antes de la cabeza publicada | 4 | 10.112.000 |
| distintos: GLEIF no publica controlante final | 0 | 0 |

**276 de 296 préstamos (93 %) caen en el mismo grupo; 20 no.** Y los 20 van para el mismo lado:
el árbol **parte** grupos (las controladas quedan sueltas o en un subgrupo), nunca junta dos.
Los grupos que cambian:

| Grupo según GLEIF | Con la controlante publicada | Recorriendo el árbol |
|---|---:|---:|
| PETROLIAM NASIONAL BERHAD (PETRONAS) | 21.584.000 | 13.788.000 |
| THE AES CORPORATION | 15.618.000 | 9.656.000 |
| SOCIETE COOPERATIVE AGRICOLE NATUP | 15.591.000 | 10.304.000 |
| AFFILIATED MANAGERS GROUP, INC. | 14.076.000 | 6.793.000 |
| FLUOR CORPORATION | 13.493.000 | 11.311.000 |
| DANAHER CORPORATION | 13.062.000 | 9.566.000 |
| REINSURANCE GROUP OF AMERICA, INCORPORATED | 12.088.000 | 6.454.000 |
| PAN AMERICAN SILVER CORP. | 9.234.000 | 7.740.000 |
| CF INDUSTRIES HOLDINGS, INC. | 8.000.000 | 6.104.000 |

Con la controlante publicada, PETRONAS es el **tercer** grupo más expuesto (21,6 millones, lo
mismo que da `refhub_gold_dev.exposicion_por_grupo` en Athena, con 10 empresas). Recorriendo el
árbol, cuatro de sus controladas (Petco Trading Labuan, Amplus Energy Solutions, Gentari
Renewables India y Petronas Energy Canada) declaran a PETRONAS como controlante final pero **no
declaran ninguna controlante directa**: el árbol no tiene por dónde subir, quedan como grupos
sueltos y PETRONAS baja a 13,8 millones, fuera de los cinco de arriba. Los otros casos son
parecidos: en Affiliated Managers Group, AIM Partnership y Artemis Investment Services suben
hasta Artemis Investment Management, que no declara a su controlante directa, y el árbol corta
ahí. Para los cinco grupos de `03`, los dos enfoques dan lo mismo, y coinciden con gold.

## Cuándo conviene cada enfoque

| | Controlante final publicada (gold, ADR 0013) | Recorrer el árbol (`CONNECT BY` / `WITH` recursivo) |
|---|---|---|
| Qué necesita | que la fuente publique la cabeza | solo el padre directo de cada empresa |
| Cómo se consulta | un join | una consulta recursiva |
| Si falta un eslabón | no importa: la cabeza la declara cada empresa | el grupo se parte y la exposición se esconde |
| Da el camino intermedio | no | sí (`SYS_CONNECT_BY_PATH`, `LEVEL`) |
| Lo que muestra esta cartera | 21,6 M en PETRONAS | 13,8 M en PETRONAS: 7,8 M sin ver |

- **Para sumar exposición, la publicada**, cuando existe: es más simple y, con GLEIF, más
  completa. Un grupo partido en dos esconde riesgo, que es el error caro en crédito (el mismo
  criterio por el que el ADR 0013 cuenta las relaciones LAPSED).
- **Recorrer el árbol conviene** cuando la fuente solo publica el padre directo (registros
  societarios, un sistema interno de vinculadas), cuando hace falta el camino (quién controla a
  quién en el medio, por ejemplo para ver qué subholding concentra el riesgo) o para auditar la
  cabeza publicada: si el árbol llega a una cabeza distinta, alguna de las dos está mal cargada.
- **`CONNECT BY` o `WITH` recursivo** dan lo mismo. `CONNECT BY` es más corto y es lo que se
  encuentra en los sistemas de riesgo escritos sobre Oracle; `WITH` recursivo es el estándar y
  corre también en PostgreSQL, SQL Server o Trino. Para código nuevo, el estándar.

## Cosas a saber

- **Si la imagen de Oracle se corta a mitad de la descarga** (por ejemplo, si se cae la máquina
  de Podman), puede quedar una capa incompleta: el contenedor arranca, dice
  `gzip: ... unexpected end of file` y `DATABASE SETUP WAS NOT SUCCESSFUL`. Se arregla borrando
  el contenedor, el volumen y la imagen (`podman rm -f refhub-oracle`,
  `podman volume rm refhub-local_oracle-datos`,
  `podman rmi container-registry.oracle.com/database/free:23.26.3.0-lite`) y bajándola de nuevo.
- **La imagen lite no trae el tablespace `USERS`**: el usuario `RIESGO` tiene
  `UNLIMITED TABLESPACE` y usa el que la base tiene por defecto.
- **El log de Oracle muestra la contraseña** la primera vez que arranca (el script de la imagen
  la imprime al cambiarla). Es la de una base local: no la reuses en otro lado.
- **Los datos son una foto.** Para actualizarlos: `exportar.py` y los dos `cargar_*.py` de nuevo.
  Las cargas recrean todo (el índice y las tablas), así que se pueden correr las veces que haga
  falta.
