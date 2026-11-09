# Herramientas

Los scripts de este directorio complementan la traducción y maquetación de libros PDF.

- `completar_bloques.py`: traduce bloques que aún aparecen en inglés en un HTML.
- `paginas_con_tablas.py`: ajusta páginas que contienen tablas.
- `traducir_in_situ.py`: traduce textos de un PDF y conserva su diseño.
- `maquetar_versos.py`: conserva la estructura de textos con versos al generar el PDF.
- `voces_libro.py`: lista los términos detectados en un libro.
- `pulir.py`: aplica correcciones tipográficas al HTML.
- `auditar_imagenes.py` y `pegar_figuras.py`: comparan las imágenes del original con la salida.
- `libro.sh`: ejecuta el flujo completo de traducción y revisión del PDF.

Los motores remotos requieren consentimiento explícito con `--yes-cloud` o `TRADUCTOR_NUBE_OK=1`.
