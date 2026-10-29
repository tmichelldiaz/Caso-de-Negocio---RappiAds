# Prueba técnica Rappi Ads – Data Business Analyst

Análisis del rendimiento de las campañas de Rappi Ads: limpieza de datos, resumen por campaña,
clasificación, reporte de calidad, dashboard interactivo y análisis de negocio.

## Contenido

| Ruta | Qué es |
|---|---|
| `sql/solution.sql` | Parte 1. Tablas limpias, resumen por campaña, clasificación y resumen semanal |
| `sql/insights.sql` | Parte 4. Una consulta por cada pregunta de negocio |
| `sql/run_sql.py` | Ejecuta los dos SQL en DuckDB y exporta los resultados a `outputs/` |
| `python/analysis.py` | Parte 2. Validaciones sobre los archivos originales y `DATA_QUALITY_REPORT.csv` |
| `outputs/` | `CAMPAIGN_DAILY_CLEAN.csv`, `CAMPAIGN_SUMMARY.csv`, `DATA_QUALITY_REPORT.csv` y tablas adicionales |
| `visualization/dashboard.html` | Parte 3. Dashboard HTML interactivo (pestañas Dashboard e Insights) |
| `visualization/build_dashboard.py` | Genera `dashboard.html` a partir de `outputs/` y la plantilla |
| `agent/` | Extra opcional: agente que responde preguntas sobre las campañas desde el dashboard |
| `AI_USAGE.md` | Uso de inteligencia artificial y validaciones |

## Motor SQL

**DuckDB** (Python, paquete `duckdb`). Las transformaciones usan sintaxis compatible con Snowflake:
`CREATE OR REPLACE TABLE`, CTEs, `QUALIFY ROW_NUMBER()`, `TRY_CAST`, `NULLIF`, `DATE_TRUNC`, `DATEDIFF`,
`COUNT(*) FILTER`. Lo único propio de DuckDB es la carga de los CSV (`read_csv`), que en Snowflake
se reemplaza por un `COPY INTO` desde un stage.

## Cómo ejecutarlo

### Opción recomendada: Docker (funciona igual en cualquier computador)

```bash
docker compose up --build
```

Genera todas las tablas, el reporte de calidad y el dashboard dentro del contenedor. Luego abrir
**http://localhost:8080/dashboard.html**. Para que el chat del agente responda, crear antes
`agent/.env` a partir de `agent/.env.example` con una API key de OpenRouter; sin ella, el dashboard
funciona igual.

### Opción local con Python

Requisitos: Python 3.10 o superior.

```bash
pip install -r requirements.txt
```

Desde la carpeta raíz del proyecto, en este orden:

```bash
python sql/run_sql.py                  # Parte 1 y consultas de la Parte 4 -> outputs/
python python/analysis.py              # Parte 2 -> outputs/DATA_QUALITY_REPORT.csv
python visualization/build_dashboard.py  # Parte 3 -> visualization/dashboard.html
```

Todo se puede correr desde cero las veces que sea: las tablas se recrean con `CREATE OR REPLACE`
y los archivos de `outputs/` se sobrescriben.

El dashboard se abre con doble clic en `visualization/dashboard.html`. Los datos y Chart.js van
incrustados en el archivo, así que funciona sin internet (solo la tipografía se carga desde la web).

### Agente (opcional)

El panel derecho del dashboard conecta con un agente (LangChain + modelo gratuito de OpenRouter) que
responde con datos de las tablas. Para usarlo:

1. Copiar `agent/.env.example` como `agent/.env` y poner una API key de OpenRouter.
2. Ejecutar `python agent/server.py` (queda en `http://localhost:8000`).
3. Abrir el dashboard. El panel muestra "Conectado".

Sin el agente, el dashboard funciona igual; el chat solo avisa que no está disponible.

## Supuestos y decisiones

**Limpieza (`CAMPAIGN_DAILY_CLEAN`)**
- Los CSV se cargan como texto y se tipan con `TRY_CAST`. Un valor mal formado queda nulo y lo
  descarta la validación de métricas nulas, en vez de romper la carga.
- **Primero se deduplica y después se valida.** La versión con mayor `UPDATED_AT` reemplaza a las
  anteriores. Si esa versión viene con errores, el día se excluye en lugar de volver a una versión
  vieja que ya fue corregida. Validar primero dejaría 8.986 filas en vez de 8.984.
- **Desempate:** con el mismo `UPDATED_AT` se conserva el mayor `ROW_ID` (se asume que es consecutivo
  según llegada). Los 15 empates de estos datos son copias exactas, así que el criterio no cambia
  las métricas, solo hace que el resultado sea siempre el mismo.
- La vigencia incluye el día de inicio y el de fin (`BETWEEN START_DATE AND END_DATE`).
- Se descartan: campaña nula o inexistente, cualquier métrica nula o negativa, clics mayores que
  impresiones y fecha fuera de vigencia. Resultado: de **9.176 registros quedan 8.984**.

**Resumen y clasificación (`CAMPAIGN_SUMMARY`)**
- Se parte de `CAMPAIGNS` con `LEFT JOIN`, para que las campañas sin días válidos aparezcan y
  queden como `WITHOUT_DATA`.
- CTR = clics / impresiones; CPM = inversión / impresiones × 1.000; ROAS = ventas / inversión;
  % consumido = inversión / presupuesto; restante = presupuesto − inversión (negativo = se pasó).
  Todas las divisiones usan `NULLIF` para evitar errores por cero.
- La clasificación sigue el orden del enunciado y se calcula con los valores **sin redondear**;
  el redondeo solo se aplica en la salida. Si CTR o ROAS son nulos, la campaña no queda `AT_RISK`.
- Resultado: ON_TRACK 117 · AT_RISK 99 · CANCELLED 24 · WITHOUT_DATA 9 · MISSING_TARGET 6 · OVER_BUDGET 5.

**Resumen semanal (`CAMPAIGN_WEEKLY_SUMMARY`)**
- Por país, maker, campaña y semana. La semana empieza el lunes (`DATE_TRUNC('week')`, igual en
  Snowflake con `WEEK_START = 0`).

**Prioridad (`CAMPAIGN_PRIORITY`, adicional)**
- Fecha de corte: último `EVENT_DATE` válido, **2026-09-30**. El mayor `UPDATED_AT` de la tabla limpia
  es 2026-10-01 14:20; las filas de octubre de los datos originales estaban fuera de vigencia.
- Solo tienen puntaje las campañas ACTIVE que aún no terminan (52), porque son las que se pueden corregir.
- `PRIORITY_SCORE` (0–100) = 40% brecha de ROAS + 20% brecha de CTR + 40% sobre-ritmo de gasto
  (% presupuesto consumido / % tiempo transcurrido − 1). Una campaña activa sin datos recibe 100.

**Dashboard**
- El estado de salud se calcula con toda la vida de la campaña y no cambia con el filtro de fechas.
  Los indicadores, gráficos y la tabla sí se recalculan con el rango elegido.
- Budget es la suma del presupuesto de las campañas filtradas; Budget Consumed es la inversión del
  rango sobre ese presupuesto.
- En los gráficos frente a la meta, las metas se ponderan: ROAS por inversión, CTR y CPM por impresiones.

**Análisis (`insights.sql`)**
- Se excluyen las campañas `CANCELLED`, porque no reflejan cómo rinde una campaña completa.

## Parte 4 – Análisis de negocio

Antes de los hallazgos, una advertencia que cambia la lectura de los datos: **cada país tiene un solo
objetivo de campaña** (AR, CO y MX solo TRAFFIC; BR, CR y PE solo CONVERSION; CL, EC y UY solo AWARENESS).
Comparar el ROAS absoluto entre países es engañoso: Ecuador tiene el ROAS más bajo (1,18) pero cumple
su meta, porque sus campañas son de visibilidad. Por eso todo se compara contra la meta.

### 1. Tres hallazgos

**Hallazgo 1. El bajo rendimiento se concentra en las campañas TRAFFIC, y Colombia es el caso más grave.**
Los únicos países bajo su meta de ROAS son CO (88,7%), AR (97,7%) y MX (99,7%), los tres de objetivo
TRAFFIC. En Colombia, por cada US$1 invertido se esperaban US$1,50 en ventas y llegan US$1,33: unos
$126K menos de lo esperado sobre $744K invertidos. 17 de sus 29 campañas están AT_RISK y concentran
el 59% de su inversión. No es un mercado puntual: es un tipo de campaña.

**Hallazgo 2. Cuando una campaña falla, falla en clics y en ventas a la vez.**
De 221 campañas evaluadas, el 45,3% falla CTR y ROAS al mismo tiempo, el 46,6% cumple ambas metas y
solo el 8,1% falla en una sola. Las que fallan ambas manejan $2,63M (44% de la inversión). Si el anuncio
no consigue clics, tampoco vende, así que el problema empieza en el anuncio (creativo, segmentación,
ubicación) más que en el precio o la compra.

**Hallazgo 3. El presupuesto se ejecuta de menos, no de más.**
Las 179 campañas terminadas usaron solo el 72,6% de su presupuesto: quedaron **$1,8M sin ejecutar**.
Las 52 activas gastan a un ritmo de 0,79 (donde deberían llevar US$100 llevan US$79) y tienen $830K
por ejecutar. Si Rappi cobra por entrega, eso es ingreso que no se factura. El sobregasto es bajo
(5 campañas, $24,9K, todas terminadas), pero 4 de las 5 se pasaron exactamente un 12%: parece un tope
de sobre-entrega del sistema.

Además, la inversión en riesgo está concentrada: Sierra Market, Horizonte y Río Claro tienen el 28,5%
del dinero en campañas AT_RISK u OVER_BUDGET. Horizonte ya no tiene campañas activas: su próxima
conversación con Rappi es la renovación.

### 2. Campañas que requieren atención inmediata

| Campaña | Maker · país | Motivo | Días restantes |
|---|---|---|---|
| CMP-0232 | La Estación · MX | Activa sin ningún dato válido ($52K de presupuesto) | 4 |
| CMP-0087 | Unión Foods · EC | Activa sin ningún dato válido ($48K de presupuesto) | 18 |
| CMP-0046 | Gran Valle · AR | ROAS 1,07 vs meta 1,65; CTR 0,80% vs 1,26% | 3 |
| CMP-0030 | Pampa Foods · CL | ROAS 0,83 vs meta 1,26; CTR 0,50% vs 0,74% | 12 |
| CMP-0220 | Cielo Drinks · CO | ROAS 1,00 vs meta 1,47; CTR 0,80% vs 1,21% | 8 |

- **Primero las dos campañas sin datos:** no se sabe si se están mostrando ni si venden, y una campaña
  que no se mide no se puede defender frente al anunciante ni cobrar con confianza. CMP-0232 termina en
  4 días, así que si es un problema de configuración queda muy poco tiempo para arreglarlo.
- **Después, las AT_RISK con mayor brecha y pocos días.** CMP-0046 termina en 3 días: ya casi no se
  puede mejorar el resultado, pero sí preparar la conversación con el anunciante. CMP-0030 y CMP-0220
  todavía tienen 8 a 12 días para ajustar creativos y segmentación.
- Las campañas OVER_BUDGET no están en la lista porque ya terminaron: no hay nada que pausar, lo que
  corresponde es revisar la facturación del excedente.

La lista completa está en "Atender primero" del dashboard y en `outputs/insights/INSIGHT_5_URGENT.csv`.

### 3. Información adicional que solicitaría antes de recomendar una acción

1. **Modelo de cobro:** si se cobra por impresión, por clic o por presupuesto comprometido. Define si
   los $1,8M sin ejecutar son ingreso perdido o solo menor entrega.
2. **Modelo de atribución:** ventana de días y criterio (último clic, vista). El ROAS depende por completo
   de cómo se atribuyen las ventas.
3. **Estado real de CMP-0232 y CMP-0087:** si están entregando anuncios y si el tracking funciona.
4. **Configuración de sobre-entrega:** si existe un tope del 12% y si ese excedente se factura.
5. **Cómo se fijan las metas:** si las de TRAFFIC se basan en datos históricos o se negocian con el
   anunciante. Puede que el problema de Colombia sea la meta y no la campaña.
6. **Historial de renovaciones por maker y motivos de cancelación**, para estimar el riesgo real de
   perder a Sierra Market, Horizonte o Río Claro.
7. **Datos de creativos, formatos y segmentación por campaña**, para confirmar si el bajo CTR viene del anuncio.

### 4. Dos controles para que los problemas de calidad no vuelvan a ocurrir

**Control 1. Validación en la ingesta, con cuarentena.**
Antes de cargar los datos diarios a la tabla de consumo, una etapa de validación con las mismas reglas
de este análisis: campaña existente, métricas no nulas ni negativas, clics ≤ impresiones, fecha dentro
de la vigencia y una sola fila por `CAMPAIGN_ID + EVENT_DATE` (*upsert* por `UPDATED_AT`). Lo que no pasa
va a una tabla de cuarentena con el motivo, no a la tabla final. El `DATA_QUALITY_REPORT` se genera en
cada carga con umbrales (por ejemplo, alertar si más del 1% de los registros falla) y se envía a quien
administra el origen.

**Control 2. Reglas sobre el estado y la configuración de las campañas.**
- No permitir activar una campaña sin metas de CTR y ROAS (evita `MISSING_TARGET`).
- Un proceso diario que pase a `FINISHED` las campañas `ACTIVE` cuya fecha de fin ya pasó (hoy hay 5).
- Una alerta cuando una campaña activa lleva más de 48 horas sin datos (hoy CMP-0232 y CMP-0087
  llevan todo el periodo).

## Conclusiones

- La calidad de los datos importa: sin limpiar, la inversión se sobreestima en unos $111K y
  4 campañas AT_RISK (CMP-0028, CMP-0046, CMP-0170 y CMP-0225) se verían como ON_TRACK.
  CMP-0046 está entre las urgentes: con los datos crudos nadie la miraría.
- El rendimiento se debe leer siempre contra la meta y considerando el objetivo de la campaña. En estos
  datos, mirar el ROAS absoluto lleva a conclusiones equivocadas.
- La mayor oportunidad no está en el sobregasto sino en el presupuesto que no se ejecuta, y en mejorar
  los anuncios de las campañas TRAFFIC, donde fallan clics y ventas al mismo tiempo.

## Extras (fuera de lo pedido)

- **Puntaje de prioridad** (`CAMPAIGN_PRIORITY`) para ordenar las campañas activas por urgencia, con
  el motivo en texto.
- **Pestaña Insights** en el dashboard con las 5 preguntas de negocio, calculadas en `sql/insights.sql`.
- **Agente** (LangChain + OpenRouter) que responde preguntas en lenguaje natural sobre las campañas.
  No decide la prioridad: consulta las tablas con herramientas y explica los resultados. Su contexto de
  negocio, el diccionario de tablas y las reglas de respuesta están en `agent/context.md`.

## Tiempo utilizado

[Completar: horas en la parte obligatoria y en los extras]
