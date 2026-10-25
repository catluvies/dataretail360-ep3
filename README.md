# DataRetail 360 · EP3

IDY1102 Estructuras y Visualización de Datos · Sección 003D
Anyara Rosso · Robert Groom

Pipeline ETL en Python que integra las fuentes del caso DataRetail 360 en un esquema estrella,
siguiendo la arquitectura Medallion: Bronze (dato crudo) → Silver (dato limpio) → Gold (modelo dimensional).

## Qué hay

| Carpeta | Contenido |
|---|---|
| `src/` | Código del pipeline: generador de datos, capas Bronze, Silver y Gold, validaciones |
| `sql/` | Esquema estrella y vistas para consultar las ventas |
| `notebooks/` | `EP3_evidencias.ipynb`: el pipeline ejecutado paso a paso, con sus resultados |
| `docs/` | Modelo estrella (imagen y archivo de Draw.io), diagrama de arquitectura y capa semántica |

## Cómo ejecutarlo

Requiere Python 3.11.

```bash
pip install pandas sqlalchemy pyarrow matplotlib jupyter
python -m src.generar_fuentes
python -m src.pipeline --todo --reiniciar
python -m src.documentacion
```

El primer comando crea los datos de prueba del caso (siete archivos por lote) y el segundo los carga
en las tres capas. Cada lote termina con `EXITOSA` en el log y 9 validaciones `OK`. El tercero
regenera los diagramas de `docs/` desde el esquema real de Gold.
Después se puede abrir `notebooks/EP3_evidencias.ipynb` para ver la evidencia.
