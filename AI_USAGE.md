# Uso de inteligencia artificial

## Herramientas

| Herramienta | Para qué |
|---|---|
| **Claude Code** (Anthropic, modelo Claude Opus 5.5) | Asistente de desarrollo, usado por limitaciones de tiempo |
| **OpenRouter – `nvidia/nemotron-3.5-super-vl:free`** | Modelo que usa el agente del dashboard (extra). Alternos: `google/gemma-4-31b-it:free` y `google/gemma-4-26b-a4b-it:free` |

## Cómo trabajé con la IA

Usé Claude Code como asistente bajo mi dirección. Yo definí el enfoque, di las instrucciones de qué
construir y cómo, tomé las decisiones de negocio y de diseño, y revisé y validé los resultados. La IA
generó el código a partir de esas instrucciones para poder cumplir con el tiempo de la prueba.

**Lo que definí yo**
- El análisis del problema de negocio antes de empezar: qué significa priorizar campañas y qué le
  sirve al equipo comercial de Rappi Ads.
- Ir más allá de lo pedido con un agente integrado al dashboard, a partir de mi experiencia previa en Rappi.
- Las preguntas de negocio de la pestaña Insights: elegí 5 de una lista más amplia y cambié las que no
  respondían a lo que buscaba.
- El diseño del dashboard: la identidad visual de Rappi Ads, qué gráficos mostrar, qué métricas incluir
  (CTR, CPM y ROAS frente a la meta) y cómo presentar las explicaciones para que sirvan tanto a un
  perfil técnico como a uno de negocio.
- El contexto de negocio que recibe el agente: Rappi Ads, el diccionario de las tablas, el significado
  de las métricas y para qué existe el agente.

**Partes en las que se apoyó con IA**
- **SQL (Parte 1) y Python (Parte 2):** generación del código a partir de mis instrucciones, y
  documentación de los supuestos en comentarios.
- **Dashboard (Parte 3):** HTML, CSS y JavaScript, iterando según mis indicaciones.
- **Análisis (Parte 4):** consultas de `insights.sql` y redacción de los hallazgos.
- **Agente (extra):** código del servidor (FastAPI), del agente (LangChain) y de sus herramientas de consulta.
- **Documentación:** README y este archivo.

## Recomendaciones de la IA que adopté

- Usar **DuckDB** con sintaxis compatible con Snowflake, para que la solución sea reproducible en local.
- **Deduplicar antes de validar**, para no volver a una versión vieja de un registro ya corregido.
- Que el agente **no decida la prioridad**: las reglas y el puntaje se calculan en SQL, y el agente solo
  consulta y explica. Así cada número se puede auditar.
- Comparar el rendimiento **contra la meta** y no en valor absoluto, porque cada país tiene un solo
  objetivo de campaña.
- Mantener Trademark y Campaign como filtros ocultos ("Más filtros") en lugar de borrarlos, porque el
  enunciado los exige.
- Empaquetar todo con **Docker** para que funcione igual en cualquier computador.

## Validaciones realizadas

**Datos y SQL**
- Reproduje la limpieza en pandas, de forma independiente al SQL: las 8.984 filas de
  `CAMPAIGN_DAILY_CLEAN` coinciden una a una por `ROW_ID` y la inversión total coincide ($6.684.557,75).
- Comprobé que los 15 empates de `UPDATED_AT` son copias exactas, así que el desempate no cambia las métricas.
- Comparé la clasificación con datos crudos y limpios: 4 campañas AT_RISK se verían como ON_TRACK sin limpiar.
- Verifiqué que los conteos cuadran: 52 activas con puntaje + 5 activas vencidas + 179 terminadas +
  24 canceladas = 260 campañas.
- Revisé que redondear las salidas no cambiara ninguna clasificación.
- Ejecuté todo desde cero en una copia limpia del proyecto y obtuve los mismos resultados.

**Dashboard**
- Con filtro MX desde el 2026-09-01, los indicadores del dashboard coinciden con los calculados
  directamente sobre las tablas (inversión $348.421, ROAS 1,51, CTR 1,23%).
- Probé cada filtro, las pestañas y los gráficos en el navegador, y revisé que la consola no tuviera errores.

**Agente**
- Probé sus herramientas por separado y comparé sus resultados con las tablas.
- Hice preguntas reales y verifiqué las cifras de cada respuesta contra las tablas.

## Limitaciones

- El agente usa un modelo gratuito: las respuestas pueden tardar entre 10 y 60 segundos, y los modelos
  gratuitos de OpenRouter cambian o se saturan. Por eso prueba una lista de modelos en orden. Los números
  siempre vienen de las herramientas, pero la redacción debe revisarse.
- Los modelos gratuitos pueden registrar las consultas. Aquí no hay riesgo porque los datos son de
  prueba; con datos reales habría que usar un modelo con una política de privacidad adecuada.
