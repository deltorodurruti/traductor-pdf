# PDF-Übersetzer

[Español](README.md) · [English](README.en.md) · [Français](README.fr.md) · [Deutsch](README.de.md)

Übersetzt PDF-Bücher aus dem Englischen, Französischen, Deutschen, Italienischen, Portugiesischen oder Lateinischen ins Spanische und gibt dir ein PDF zurück, das sich wie ein Buch liest: mit Bildern, Inhaltsverzeichnis und Seitenzahlen. Funktioniert mit Text-PDFs und mit Scans.

## Warum es das gibt

KI übersetzt heute gut. Das Problem fängt an, wenn man ein ganzes Buch will: Meistens lehnt sie wegen des Urheberrechts ab, oder sie übersetzt ein paar Seiten und hört auf. Dieses Programm löst das. Es arbeitet Seite für Seite, auf deinem eigenen Rechner, mit der Übersetzungsmaschine deiner Wahl, und am Ende hast du das ganze Buch in deiner Sprache.

Wissen sollte nicht davon abhängen, ob man Englisch spricht. Es lebe das Wissen.

## Schnellstart

Unter Windows: den PowerShell-Schritten im nächsten Abschnitt folgen.

Aus dem Quellcode, mit Python 3.10 oder neuer:

```bash
pip install -r requirements.txt
python3 main.py                                # fragt alles Schritt für Schritt ab
python3 main.py buch.pdf --yes --yes-cloud --engine edge    # direkt, ohne Fragen
python3 main.py buch.pdf --yes --yes-cloud --engine edge --origen de   # das Original ist auf Deutsch
```

Für gescannte PDFs zusätzlich Tesseract installieren (`brew install tesseract` auf dem Mac, `sudo apt install tesseract-ocr` unter Linux, den UB-Mannheim-Installer unter Windows). Mit RapidOCR (`pip install rapidocr onnxruntime`) wird jede Seite von beiden gelesen, und das Programm behält jeweils das bessere Ergebnis.

## Unter Windows, Schritt für Schritt mit PowerShell

Öffne PowerShell (Windows-Taste, „PowerShell“ eintippen, Enter) und füge die Befehle einzeln ein.

1. Python und Git installieren. Nur beim ersten Mal:

   ```powershell
   winget install -e --id Python.Python.3.12
   winget install -e --id Git.Git
   ```

   PowerShell schließen und neu öffnen, damit es die neuen Programme findet.

2. Den Übersetzer herunterladen und installieren, was er braucht:

   ```powershell
   cd $HOME
   git clone https://github.com/deltorodurruti/traductor-pdf.git
   cd traductor-pdf
   py -m pip install -r requirements.txt
   ```

3. Ein Buch übersetzen. Das Ergebnis landet auf deinem Desktop als „mein buch traducido.pdf“ (gibt es keinen Desktop-Ordner, neben dem Original-PDF):

   ```powershell
   py main.py "$HOME\Downloads\mein buch.pdf" --yes --yes-cloud --engine edge
   ```

4. Bei gescannten PDFs Tesseract installieren und zum `Path` hinzufügen. Danach PowerShell neu öffnen:

   ```powershell
   winget install -e --id UB-Mannheim.TesseractOCR
   $p = [Environment]::GetEnvironmentVariable("Path", "User")
   [Environment]::SetEnvironmentVariable("Path", "$p;C:\Program Files\Tesseract-OCR", "User")
   ```

5. Für die Übersetzung mit einem Cloud-Modell den Schlüssel speichern und die Maschine wählen:

   ```powershell
   Set-Content -Path "$HOME\.groq_key" -Value "DEIN_SCHLUESSEL" -NoNewline
   py main.py "$HOME\Downloads\mein buch.pdf" --yes --yes-cloud --engine groq
   ```

Beim nächsten Mal reicht `cd $HOME\traductor-pdf` und der Befehl aus Schritt 3. Aktualisieren: `git pull`.

## Ein ganzes Buch mit einem Befehl

Dieser Ablauf läuft vorerst nur auf Mac und Linux; unter Windows `main.py` wie im Abschnitt oben verwenden.


```bash
traducir_libro "/pfad/zu/mein buch.pdf" --todo
```

Das Programm legt einen Arbeitsordner an, übersetzt, ergänzt, was unübersetzt geblieben ist, setzt das Buch (Titelseite, Inhaltsverzeichnis, Blocksatz, die Abbildungen des Originals) und prüft es. Das fertige PDF landet in `libros_esp/`. Wenn du abbrichst, macht es beim nächsten Start dort weiter, wo es war.

| Option | Was sie tut |
|--------|-------------|
| (keine) | übersetzt und ergänzt; das HTML ist danach fertig |
| `--maquetar` | setzt zusätzlich das Buch und liefert das PDF |
| `--revisar` | prüft das gelieferte PDF auf englische Reste und OCR-Müll |
| `--todo` | beides zusammen |
| `-n` | zeigt, was es tun würde, ohne etwas anzufassen |

Damit die Befehle aus jedem Ordner funktionieren:

```bash
ln -s "$PWD/traducir_libro.py" ~/.local/bin/traducir_libro
ln -s "$PWD/estado.py"         ~/.local/bin/estado
ln -s "$PWD/flujo.sh"          ~/.local/bin/flujo
```

`estado` zeigt, wo jedes Buch steht: Schritt, Prozent, verbleibende Zeit und wie viel Kontingent deine kostenlosen Schlüssel noch haben. `flujo --noche` arbeitet die ganze Warteschlange ab, während du schläfst.

## Übersetzungsmaschinen

Auswahl mit `--engine`. Ohne Schlüssel laufen `edge` (Microsoft, schnell und gut; die Empfehlung), `web` (Google, das manchmal Anfragen abweist und Blöcke unübersetzt lässt), `argos` und `opus` (offline) sowie `ollama` (ein Modell auf deinem eigenen Rechner). Mit `--yes` ohne `--engine` wird `ollama` verwendet.

Ein großes Modell in der Cloud übersetzt deutlich besser. Mehrere Anbieter haben einen kostenlosen Tarif; es reicht, den Schlüssel in einer Textdatei im Home-Ordner zu speichern:

| Dienst | `--engine` | Schlüsseldatei |
|--------|------------|----------------|
| Groq | `groq` | `~/.groq_key` |
| Gemini | `gemini` | `~/.gemini_key` |
| Mistral | `mistral` | `~/.mistral_key` |
| OpenRouter | `openrouter` | `~/.openrouter_key` |
| Cloudflare Workers AI | `cloudflare` | `~/.cloudflare_key` |
| SambaNova | `sambanova` | `~/.sambanova_key` |
| Requesty | `requesty` | `~/.requesty_key` |

```bash
echo 'DEIN_SCHLUESSEL' > ~/.groq_key && chmod 600 ~/.groq_key
```

Kostenlose Tarife haben ein Tageskontingent. Ist es aufgebraucht, wartet das Programm und macht von selbst weiter oder wechselt zu einem anderen Schlüssel. Mit `--borrador edge --engine groq` schreibt Microsoft den Entwurf und das große Modell korrigiert ihn nur; das verbraucht halb so viel Kontingent.

Achtung: Mit einer Online-Maschine verlässt der Text des Buchs deinen Rechner. Deshalb verlangt das Programm bei `--yes` zusätzlich `--yes-cloud` als Bestätigung.

## Weitere Optionen von `main.py`

| Option | Was sie tut |
|--------|-------------|
| `--origen {en,fr,de,it,pt,la}` | Sprache des Originals |
| `--solo` | nur die Übersetzung, ohne das Original daneben |
| `--calidad 1-5` | wie viele Korrekturdurchgänge das Modell macht |
| `--ocr {auto,force,off}` | wann Seiten als Bild gelesen werden |
| `--max-pages N` | übersetzt nur die ersten N Seiten, zum Testen |
| `--no-pdf` | nur das HTML |
| `--out datei.html` | wohin das Ergebnis gespeichert wird |

Eigennamen und Wörter in anderen Schriften (Griechisch, Hebräisch, Kyrillisch) bleiben unangetastet. Wenn ein Buch Begriffe enthält, die genau so bleiben sollen, schreib sie in eine `glosario.txt` im Ordner des Buchs, einen pro Zeile.

## So funktioniert es

1. Liest das PDF und trennt Text und Bilder.
2. Gescannte Seiten laufen durch die Texterkennung (OCR).
3. Übersetzt Block für Block und speichert jeden Block im Cache, damit nichts doppelt übersetzt wird.
4. Erstellt das Ergebnis als HTML und PDF. Dein Original-PDF wird nie verändert.

## Fragen

Wenn etwas nicht klappt, eröffne ein *Issue*, und ich helfe dir.

Maschinelle Übersetzung liegt manchmal daneben. Dafür gibt es den zweisprachigen Modus: Original und Übersetzung nebeneinander, zum Vergleichen.
