# Traductor PDF

[Español](README.md) · [English](README.en.md) · [Français](README.fr.md) · [Deutsch](README.de.md)

Traduce libros en PDF de inglés, francés, alemán, italiano, portugués o latín al español, y te devuelve un PDF que se lee como un libro: con sus imágenes, su índice y sus números de página. Funciona con PDF de texto y con escaneos.

> **EN** · Translates whole PDF books from English, French, German, Italian, Portuguese or Latin into Spanish, keeping images and layout. [Read more](README.en.md).
>
> **FR** · Traduit des livres PDF entiers de l'anglais, du français, de l'allemand, de l'italien, du portugais ou du latin vers l'espagnol, en gardant les images et la mise en page. [Lire la suite](README.fr.md).
>
> **DE** · Übersetzt ganze PDF-Bücher aus dem Englischen, Französischen, Deutschen, Italienischen, Portugiesischen oder Lateinischen ins Spanische, mit Bildern und Layout. [Weiterlesen](README.de.md).

## Por qué existe

Hoy una IA traduce bien. El problema aparece cuando le pides un libro entero: casi siempre se niega por derechos de autor, o te traduce un par de páginas y se detiene. Este programa resuelve eso. Va página por página, en tu computador, con el motor que tú elijas, y al final te entrega el libro completo en tu idioma.

El conocimiento no debería depender de hablar inglés. Que viva el conocimiento.

## Lo más rápido

En Windows: sigue los pasos de PowerShell de la sección siguiente.

Desde el código, con Python 3.10 o más nuevo:

```bash
pip install -r requirements.txt
python3 main.py                                # te pregunta todo paso a paso
python3 main.py libro.pdf --yes --yes-cloud --engine web   # directo, sin preguntas
python3 main.py libro.pdf --yes --yes-cloud --engine web --origen fr   # el original está en francés
```

Para PDF escaneados instala también Tesseract (`brew install tesseract` en Mac, `sudo apt install tesseract-ocr` en Linux, el instalador de UB-Mannheim en Windows). Si además instalas RapidOCR (`pip install rapidocr onnxruntime`), cada página se lee con los dos y se queda con lo mejor de cada lectura.

## En Windows, paso a paso con PowerShell

Abre PowerShell (tecla Windows, escribe «PowerShell» y Enter) y pega los comandos de a uno.

1. Instala Python y Git. Solo la primera vez:

   ```powershell
   winget install -e --id Python.Python.3.12
   winget install -e --id Git.Git
   ```

   Cierra PowerShell y ábrelo de nuevo, para que reconozca lo que acabas de instalar.

2. Descarga el traductor e instala lo que necesita:

   ```powershell
   cd $HOME
   git clone https://github.com/deltorodurruti/traductor-pdf.git
   cd traductor-pdf
   py -m pip install -r requirements.txt
   ```

3. Traduce un libro. El resultado queda en tu Escritorio como «mi libro traducido.pdf» (si no encuentra el Escritorio, junto al PDF original):

   ```powershell
   py main.py "$HOME\Downloads\mi libro.pdf" --yes --yes-cloud --engine web
   ```

4. Si el PDF es escaneado, instala Tesseract y agrégalo al `Path`. Después vuelve a abrir PowerShell:

   ```powershell
   winget install -e --id UB-Mannheim.TesseractOCR
   $p = [Environment]::GetEnvironmentVariable("Path", "User")
   [Environment]::SetEnvironmentVariable("Path", "$p;C:\Program Files\Tesseract-OCR", "User")
   ```

5. Para traducir con un modelo en la nube, guarda tu clave y elige el motor:

   ```powershell
   Set-Content -Path "$HOME\.groq_key" -Value "TU_CLAVE" -NoNewline
   py main.py "$HOME\Downloads\mi libro.pdf" --yes --yes-cloud --engine groq
   ```

La próxima vez basta con `cd $HOME\traductor-pdf` y el comando del paso 3. Para actualizar: `git pull`.

## Un libro entero con un comando

Por ahora este flujo corre en Mac y Linux; en Windows usa `main.py` como en la sección anterior.


```bash
traducir_libro "/ruta/a/mi libro.pdf" --todo
```

Crea su carpeta de trabajo, traduce, completa lo que haya quedado sin traducir, arma el libro (portada, índice, texto justificado, figuras del original) y lo revisa. El PDF final queda en `libros_esp/`. Si lo cortas, al volver a lanzarlo sigue donde iba.

| Opción | Qué hace |
|--------|----------|
| (nada) | traduce y completa; deja el HTML listo |
| `--maquetar` | además arma el libro y entrega el PDF |
| `--revisar` | revisa el PDF entregado: restos sin traducir, basura de OCR |
| `--todo` | las dos anteriores |
| `-n` | muestra lo que haría, sin tocar nada |

Para tener los comandos a mano desde cualquier carpeta:

```bash
ln -s "$PWD/traducir_libro.py" ~/.local/bin/traducir_libro
ln -s "$PWD/estado.py"         ~/.local/bin/estado
ln -s "$PWD/flujo.sh"          ~/.local/bin/flujo
```

`estado` te muestra en qué va cada libro: etapa, porcentaje, tiempo que falta y cuánto cupo les queda a tus claves gratis. `flujo --noche` deja traduciendo toda la cola mientras duermes.

## Motores de traducción

Se elige con `--engine`. Sin clave funcionan `web` (Google), `edge` (Microsoft, rápido y bueno), `argos` y `opus` (sin internet) y `ollama` (un modelo en tu propio equipo). Si usas `--yes` sin `--engine`, se usa `ollama`.

Con un modelo grande en la nube la traducción mejora bastante. Hay varios con plan gratis; basta con guardar la clave en un archivo de texto en tu carpeta personal:

| Servicio | `--engine` | Archivo de la clave |
|----------|------------|---------------------|
| Groq | `groq` | `~/.groq_key` |
| Gemini | `gemini` | `~/.gemini_key` |
| Mistral | `mistral` | `~/.mistral_key` |
| OpenRouter | `openrouter` | `~/.openrouter_key` |
| Cloudflare Workers AI | `cloudflare` | `~/.cloudflare_key` |
| SambaNova | `sambanova` | `~/.sambanova_key` |
| Requesty | `requesty` | `~/.requesty_key` |

```bash
echo 'TU_CLAVE' > ~/.groq_key && chmod 600 ~/.groq_key
```

Los planes gratis tienen cupo diario. Cuando se acaba, el programa espera y sigue solo, o rota a otra clave. Con `--borrador edge --engine groq`, Microsoft hace el borrador y el modelo grande solo lo corrige: gasta la mitad de cupo.

Ojo: con un motor en línea, el texto del libro sale de tu equipo. Por eso, si usas `--yes`, el programa te pide además `--yes-cloud` como confirmación.

## Otras opciones de `main.py`

| Opción | Qué hace |
|--------|----------|
| `--origen {en,fr,de,it,pt,la}` | idioma del original |
| `--solo` | solo la traducción, sin el original al lado |
| `--calidad 1-5` | cuántas pasadas de revisión hace el modelo |
| `--ocr {auto,force,off}` | cuándo leer las páginas como imagen |
| `--max-pages N` | traduce solo las primeras N páginas, para probar |
| `--no-pdf` | deja solo el HTML |
| `--out archivo.html` | dónde guardar el resultado |

Los nombres propios y las palabras en otros alfabetos (griego, hebreo, cirílico) no se tocan. Si un libro tiene términos que quieres conservar tal cual, ponlos en un `glosario.txt` dentro de la carpeta del libro, uno por línea.

## Cómo funciona

1. Lee el PDF y separa texto e imágenes.
2. Las páginas escaneadas pasan por OCR.
3. Traduce bloque por bloque y guarda cada bloque en una caché, así nada se traduce dos veces.
4. Arma el resultado en HTML y PDF. Tu PDF original nunca se modifica.

## Dudas

Si algo no te funciona, abre un *issue* y te ayudo.

La traducción automática se equivoca a veces. Por eso existe el modo bilingüe: el original y la traducción lado a lado, para comparar.
