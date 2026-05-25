# Data reference

Este archivo resume la granularidad temporal del parquet generado por el feature store (Reporte construido el 23/5/2026).

Cada fila representa un par `pozo-mes` con features y targets reales.

## Rango historico

- Fecha minima: `2006-02-01`
- Fecha maxima: `2026-04-01`
- Meses disponibles: `243`

## Data points pozo-mes (por mes)

- Minimo: `114`
- Media: `1648.01`
- Mediana: `1315.00`
- Maximo: `4847`


## Ultimos meses disponibles

| Mes | Filas pozo-mes | Pozos unicos |
|---|---:|---:|
| 2025-05 | 4407 | 4407 |
| 2025-06 | 4466 | 4466 |
| 2025-07 | 4482 | 4482 |
| 2025-08 | 4547 | 4547 |
| 2025-09 | 4597 | 4597 |
| 2025-10 | 4629 | 4629 |
| 2025-11 | 4675 | 4675 |
| 2025-12 | 4704 | 4704 |
| 2026-01 | 4736 | 4736 |
| 2026-02 | 4768 | 4768 |
| 2026-03 | 4809 | 4809 |
| 2026-04 | 4847 | 4847 |

## Filas en ventanas recientes

| Ventana | Filas pozo-mes | Pozos unicos |
|---|---:|---:|
| Ultimos 1 meses | 4847 | 4847 |
| Ultimos 3 meses | 14424 | 4853 |
| Ultimos 6 meses | 28539 | 4856 |
| Ultimos 12 meses | 55667 | 4859 |
| Ultimos 18 meses | 81273 | 4859 |

## Conclusion

El umbral de warning de 100 filas es conservador para monitoreo global: incluso el mes con menor volumen tiene mas de 100 filas pozo-mes. Se mantiene como resguardo para escenarios de bajo volumen, filtros por segmento o monitoreo por pozo.
