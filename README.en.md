# PDF Translator

[Español](README.md) · [English](README.en.md) · [Français](README.fr.md) · [Deutsch](README.de.md)

Translates PDF books from English, French, German, Italian, Portuguese or Latin into Spanish, and gives you back a PDF that reads like a book: images, table of contents and page numbers included. It works with text PDFs and with scans.

## Why this exists

AI can translate well these days. The trouble starts when you ask it for a whole book: it usually refuses because of copyright, or it does a couple of pages and stops. This program gets around that. It goes page by page, on your own computer, with the engine you pick, and at the end you get the complete book in your language.

Knowledge shouldn't depend on speaking English. Long live knowledge.

## Quick start

On Windows: follow the PowerShell steps in the next section.

From source, with Python 3.10 or newer:

```bash
pip install -r requirements.txt
python3 main.py                                # asks you everything step by step
python3 main.py book.pdf --yes --yes-cloud --engine web    # straight through, no questions
python3 main.py book.pdf --yes --yes-cloud --engine web --origen fr   # the original is in French
```

For scanned PDFs, also install Tesseract (`brew install tesseract` on Mac, `sudo apt install tesseract-ocr` on Linux, the UB-Mannheim installer on Windows). If you add RapidOCR (`pip install rapidocr onnxruntime`), every page is read by both and the best of each reading is kept.

## On Windows, step by step with PowerShell

Open PowerShell (Windows key, type "PowerShell", Enter) and paste the commands one at a time.

1. Install Python and Git. Only the first time:

   ```powershell
   winget install -e --id Python.Python.3.12
   winget install -e --id Git.Git
   ```

   Close PowerShell and open it again so it picks up what you just installed.

2. Download the translator and install what it needs:

   ```powershell
   cd $HOME
   git clone https://github.com/deltorodurruti/traductor-pdf.git
   cd traductor-pdf
   py -m pip install -r requirements.txt
   ```

3. Translate a book. The result lands on your Desktop as "my book traducido.pdf" (if there's no Desktop folder, next to the original PDF):

   ```powershell
   py main.py "$HOME\Downloads\my book.pdf" --yes --yes-cloud --engine web
   ```

4. If the PDF is scanned, install Tesseract and add it to your `Path`. Then reopen PowerShell:

   ```powershell
   winget install -e --id UB-Mannheim.TesseractOCR
   $p = [Environment]::GetEnvironmentVariable("Path", "User")
   [Environment]::SetEnvironmentVariable("Path", "$p;C:\Program Files\Tesseract-OCR", "User")
   ```

5. To translate with a cloud model, save your key and pick the engine:

   ```powershell
   Set-Content -Path "$HOME\.groq_key" -Value "YOUR_KEY" -NoNewline
   py main.py "$HOME\Downloads\my book.pdf" --yes --yes-cloud --engine groq
   ```

Next time, just `cd $HOME\traductor-pdf` and run the command from step 3. To update: `git pull`.

## A whole book with one command

For now this workflow runs on Mac and Linux; on Windows use `main.py` as in the section above.


```bash
traducir_libro "/path/to/my book.pdf" --todo
```

It sets up a work folder, translates, fills in whatever was left untranslated, lays the book out (cover, table of contents, justified text, the original figures) and checks it. The final PDF lands in `libros_esp/`. If you stop it, running it again picks up where it left off.

| Option | What it does |
|--------|--------------|
| (none) | translate and fill in; leaves the HTML ready |
| `--maquetar` | also lays out the book and delivers the PDF |
| `--revisar` | checks the delivered PDF for leftover English and OCR junk |
| `--todo` | both of the above |
| `-n` | shows what it would do without touching anything |

To call the commands from any folder:

```bash
ln -s "$PWD/traducir_libro.py" ~/.local/bin/traducir_libro
ln -s "$PWD/estado.py"         ~/.local/bin/estado
ln -s "$PWD/flujo.sh"          ~/.local/bin/flujo
```

`estado` shows where each book is: stage, percentage, time left, and how much quota your free keys still have. `flujo --noche` keeps translating the whole queue while you sleep.

## Translation engines

Pick one with `--engine`. These need no key: `web` (Google), `edge` (Microsoft, fast and good), `argos` and `opus` (offline) and `ollama` (a model on your own machine). With `--yes` and no `--engine`, it uses `ollama`.

A large cloud model gives noticeably better translations. Several have free plans; just save the key in a text file in your home folder:

| Service | `--engine` | Key file |
|---------|------------|----------|
| Groq | `groq` | `~/.groq_key` |
| Gemini | `gemini` | `~/.gemini_key` |
| Mistral | `mistral` | `~/.mistral_key` |
| OpenRouter | `openrouter` | `~/.openrouter_key` |
| Cloudflare Workers AI | `cloudflare` | `~/.cloudflare_key` |
| SambaNova | `sambanova` | `~/.sambanova_key` |
| Requesty | `requesty` | `~/.requesty_key` |

```bash
echo 'YOUR_KEY' > ~/.groq_key && chmod 600 ~/.groq_key
```

Free plans have a daily quota. When it runs out, the program waits and carries on, or switches to another key. With `--borrador edge --engine groq`, Microsoft writes the draft and the large model only corrects it, which uses half the quota.

Keep in mind that with an online engine, the book's text leaves your computer. That's why, with `--yes`, the program also asks for `--yes-cloud` as confirmation.

## Other `main.py` options

| Option | What it does |
|--------|--------------|
| `--origen {en,fr,de,it,pt,la}` | language of the original |
| `--solo` | translation only, without the original alongside |
| `--calidad 1-5` | how many review passes the model makes |
| `--ocr {auto,force,off}` | when to read pages as images |
| `--max-pages N` | translate only the first N pages, for testing |
| `--no-pdf` | HTML only |
| `--out file.html` | where to save the result |

Proper names and words in other alphabets (Greek, Hebrew, Cyrillic) are left alone. If a book has terms you want kept exactly as they are, list them in a `glosario.txt` inside the book's folder, one per line.

## How it works

1. Reads the PDF and separates text from images.
2. Scanned pages go through OCR.
3. Translates block by block and caches each block, so nothing gets translated twice.
4. Builds the result as HTML and PDF. Your original PDF is never modified.

## Questions

If something doesn't work for you, open an *issue* and I'll help.

Machine translation gets things wrong sometimes. That's what the bilingual mode is for: original and translation side by side, so you can compare.
