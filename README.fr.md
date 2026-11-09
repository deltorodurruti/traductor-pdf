# Traducteur PDF

[Español](README.md) · [English](README.en.md) · [Français](README.fr.md) · [Deutsch](README.de.md)

Traduit des livres PDF de l'anglais, du français, de l'allemand, de l'italien, du portugais ou du latin vers l'espagnol, et vous rend un PDF qui se lit comme un livre : avec ses images, sa table des matières et ses numéros de page. Fonctionne avec les PDF texte comme avec les PDF scannés.

## Pourquoi ce projet

Une IA traduit bien aujourd'hui. Le problème arrive quand on lui demande un livre entier : la plupart du temps elle refuse à cause du droit d'auteur, ou elle traduit deux pages et s'arrête. Ce programme règle ça. Il avance page par page, sur votre ordinateur, avec le moteur de votre choix, et à la fin vous avez le livre complet dans votre langue.

Le savoir ne devrait pas dépendre de l'anglais. Vive le savoir.

## Démarrage rapide

Sous Windows : installez [Python](https://www.python.org/downloads/) 3.10 ou plus récent, double-cliquez sur `Instalar.cmd` (une seule fois) puis sur `Traducir.cmd`, qui ouvre le traducteur dans le navigateur.

Depuis le code, avec Python 3.10 ou plus récent :

```bash
pip install -r requirements.txt
python3 main.py                                 # vous guide pas à pas
python3 main.py livre.pdf --yes --yes-cloud --engine web    # directement, sans questions
python3 main.py livre.pdf --yes --yes-cloud --engine web --origen fr   # l'original est en français
```

Pour les PDF scannés, installez aussi Tesseract (`brew install tesseract` sur Mac, `sudo apt install tesseract-ocr` sous Linux, l'installateur UB-Mannheim sous Windows). Si vous ajoutez RapidOCR (`pip install rapidocr onnxruntime`), chaque page est lue par les deux et le programme garde le meilleur de chaque lecture.

## Sous Windows, pas à pas avec PowerShell

Ouvrez PowerShell (touche Windows, tapez « PowerShell », puis Entrée) et collez les commandes une par une.

1. Installez Python et Git. Seulement la première fois :

   ```powershell
   winget install -e --id Python.Python.3.12
   winget install -e --id Git.Git
   ```

   Fermez PowerShell et rouvrez-le pour qu'il trouve ce que vous venez d'installer.

2. Téléchargez le traducteur et installez ce dont il a besoin :

   ```powershell
   cd $HOME
   git clone https://github.com/deltorodurruti/traductor-pdf.git
   cd traductor-pdf
   py -m pip install -r requirements.txt
   ```

3. Traduisez un livre. Le résultat arrive sur votre Bureau sous le nom « mon livre traducido.pdf » (s'il ne trouve pas le Bureau, à côté du PDF d'origine) :

   ```powershell
   py main.py "$HOME\Downloads\mon livre.pdf" --yes --yes-cloud --engine web
   ```

4. Si le PDF est scanné, installez Tesseract et ajoutez-le au `Path`. Puis rouvrez PowerShell :

   ```powershell
   winget install -e --id UB-Mannheim.TesseractOCR
   $p = [Environment]::GetEnvironmentVariable("Path", "User")
   [Environment]::SetEnvironmentVariable("Path", "$p;C:\Program Files\Tesseract-OCR", "User")
   ```

5. Pour traduire avec un modèle dans le cloud, enregistrez votre clé et choisissez le moteur :

   ```powershell
   Set-Content -Path "$HOME\.groq_key" -Value "VOTRE_CLE" -NoNewline
   py main.py "$HOME\Downloads\mon livre.pdf" --yes --yes-cloud --engine groq
   ```

La fois suivante, il suffit de `cd $HOME\traductor-pdf` et de la commande de l'étape 3. Pour mettre à jour : `git pull`.

## Un livre entier en une commande

Pour l'instant, ce flux tourne sous Mac et Linux ; sous Windows, utilisez `main.py` comme dans la section précédente.


```bash
traducir_libro "/chemin/vers/mon livre.pdf" --todo
```

Le programme crée un dossier de travail, traduit, complète ce qui est resté non traduit, met le livre en page (couverture, table des matières, texte justifié, figures de l'original) et le vérifie. Le PDF final arrive dans `libros_esp/`. Si vous l'interrompez, il reprend là où il en était.

| Option | Effet |
|--------|-------|
| (aucune) | traduit et complète ; laisse le HTML prêt |
| `--maquetar` | met aussi le livre en page et livre le PDF |
| `--revisar` | vérifie le PDF livré : restes non traduits, déchets d'OCR |
| `--todo` | les deux précédentes |
| `-n` | montre ce qu'il ferait, sans rien toucher |

Pour lancer les commandes depuis n'importe quel dossier :

```bash
ln -s "$PWD/traducir_libro.py" ~/.local/bin/traducir_libro
ln -s "$PWD/estado.py"         ~/.local/bin/estado
ln -s "$PWD/flujo.sh"          ~/.local/bin/flujo
```

`estado` montre où en est chaque livre : étape, pourcentage, temps restant et quota restant sur vos clés gratuites. `flujo --noche` traduit toute la file d'attente pendant que vous dormez.

## Moteurs de traduction

On choisit avec `--engine`. Sans clé : `web` (Google), `edge` (Microsoft, rapide et de bonne qualité), `argos` et `opus` (hors ligne) et `ollama` (un modèle sur votre machine). Avec `--yes` sans `--engine`, c'est `ollama` qui est utilisé.

Un grand modèle dans le cloud donne une traduction nettement meilleure. Plusieurs ont une offre gratuite ; il suffit d'enregistrer la clé dans un fichier texte de votre dossier personnel :

| Service | `--engine` | Fichier de la clé |
|---------|------------|-------------------|
| Groq | `groq` | `~/.groq_key` |
| Gemini | `gemini` | `~/.gemini_key` |
| Mistral | `mistral` | `~/.mistral_key` |
| OpenRouter | `openrouter` | `~/.openrouter_key` |
| Cloudflare Workers AI | `cloudflare` | `~/.cloudflare_key` |
| SambaNova | `sambanova` | `~/.sambanova_key` |
| Requesty | `requesty` | `~/.requesty_key` |

```bash
echo 'VOTRE_CLE' > ~/.groq_key && chmod 600 ~/.groq_key
```

Les offres gratuites ont un quota quotidien. Quand il est épuisé, le programme attend puis continue seul, ou passe à une autre clé. Avec `--borrador edge --engine groq`, Microsoft fait le brouillon et le grand modèle se contente de le corriger : cela consomme moitié moins de quota.

Attention : avec un moteur en ligne, le texte du livre quitte votre ordinateur. C'est pourquoi, avec `--yes`, le programme demande aussi `--yes-cloud` pour confirmer.

## Autres options de `main.py`

| Option | Effet |
|--------|-------|
| `--origen {en,fr,de,it,pt,la}` | langue de l'original |
| `--solo` | la traduction seule, sans l'original à côté |
| `--calidad 1-5` | nombre de passes de relecture du modèle |
| `--ocr {auto,force,off}` | quand lire les pages comme des images |
| `--max-pages N` | ne traduit que les N premières pages, pour tester |
| `--no-pdf` | seulement le HTML |
| `--out fichier.html` | où enregistrer le résultat |

Les noms propres et les mots dans d'autres alphabets (grec, hébreu, cyrillique) restent intacts. Si un livre contient des termes à garder tels quels, mettez-les dans un `glosario.txt` dans le dossier du livre, un par ligne.

## Comment ça marche

1. Lit le PDF et sépare le texte des images.
2. Les pages scannées passent par l'OCR.
3. Traduit bloc par bloc et garde chaque bloc en cache : rien n'est traduit deux fois.
4. Produit le résultat en HTML et en PDF. Votre PDF d'origine n'est jamais modifié.

## Questions

Si quelque chose ne marche pas, ouvrez une *issue* et je vous aiderai.

La traduction automatique se trompe parfois. C'est pour ça qu'il existe le mode bilingue : l'original et la traduction côte à côte, pour comparer.
