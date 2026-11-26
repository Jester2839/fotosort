"""Pevné nastavení. Měň tady, ne v kódu."""

from pathlib import Path

LIBRARY_ROOT = Path(r"C:\Users\jakub\OneDrive\Dokumenty\_Foto")

PHOTO_EXTS = {".arw", ".jpg", ".jpeg"}
RAW_EXTS = {".arw"}
VIDEO_EXTS = {".mp4"}

# Nová akce se navrhne, když mezi dvěma dny s fotkami je aspoň tolik celých dnů bez fotek.
DEFAULT_GAP_DAYS = 2

# Složky, které vzniknou v každé nové akci hned při importu.
EVENT_SUBFOLDERS_ON_IMPORT = ("_upraveno",)
VIDEO_SUBFOLDER = "video"

# Složka pro vyřazené fotky (vytvoří ji až culling krok). Celá se po kontrole smaže.
CULL_FOLDERS = {"delete": "_ke_smazani"}
# Starší verze třídily i do těchto složek; undo je pořád umí uklidit.
LEGACY_CULL_FOLDERS = ("_vyber", "_nejiste")

# Výběr a Nejisté zůstávají ve složce akce a dostanou hodnocení + klíčová slova v XMP,
# která Lightroom Classic načte při importu. Hvězdičky si pak v LR klidně přepiš.
XMP_RATING = {"good": 3, "unsure": 1}
KEYWORD_ROOT = "Fotosort"
BUCKET_KEYWORD = {"good": "Výběr", "unsure": "Nejisté"}
CATEGORY_KEYWORD = {"detail": "Detail", "landscape_hory": "Krajina", "lidi": "Lidi",
                    "street_architektura": "Město", "zvirata": "Zvířata", "ostatni": "Ostatní"}

# Přísnost (GUI posuvník, CLI --prisnost): (horní podíl do výběru, spodní podíl do „slabé“).
# U mírné jde do _ke_smazani jen technicky špatné, všechno ostatní zůstane.
STRICTNESS = {1: (0.40, 0.0), 2: (0.40, 0.20), 3: (0.30, 0.30)}
DEFAULT_STRICTNESS = 2

# Lightroom Classic pro tlačítko „Otevřít Lightroom“ v GUI.
LIGHTROOM_EXE = Path(r"C:\Program Files\Adobe\Adobe Lightroom Classic\Lightroom.exe")

# --- Technické třídění ---
# Neostrá = ostrost pod BLUR_ABS, nebo hluboko pod mediánem focení (BLUR_RELATIVE × medián).
# Kalibrováno na Jakubových fotkách: rozmazané 36–93, ostré (i měkké se zlatým světlem) od ~135.
# Čistě relativní práh vyhazoval měkčí ostré fotky z focení, kde jsou jiné fotky extrémně ostré.
BLUR_ABS = 100
BLUR_RELATIVE = 0.12
# Série: snímky, mezi kterými je max. tolik sekund…
SERIES_GAP_S = 2
# …nebo jsou skoro stejné (rozdíl otisku v bitech z 64) a do tolika sekund od sebe.
SIMILAR_HASH_BITS = 10
SIMILAR_GAP_S = 30
# Kolik nejostřejších snímků ze série nechat: 1 + délka série // tohle číslo.
SERIES_KEEP_PER = 8
# Expozice se hodnotí jen u samotných JPG (RAW se dá vytáhnout): podíl černých/bílých pixelů.
CLIP_LIMIT_JPG = 0.40
# Log přesunů pro --undo; leží v _ke_smazani, ne mezi fotkami.
CULL_LOG = "_fotosort_log.csv"

# --- Zavřené oči (MediaPipe) ---
# Obličej se počítá, jen když je široký aspoň tolik z šířky snímku (lidi v pozadí se ignorují).
FACE_MIN_WIDTH = 0.06
# Skóre mrknutí 0–1; víc = zavřené. Obě oči musí být nad prahem.
EYES_CLOSED = 0.5

# --- AI hodnocení (CLIP + LAION aesthetic) ---
# Z technicky v pořádku fotek: horních X % = výběr (★★★), spodních Y % do _ke_smazani/slabe,
# zbytek nejisté (★). Podíly podle přísnosti viz STRICTNESS výše.
# Absolutní pojistky (LAION skóre, typicky 3–7): do výběru jen od VYBER_MIN_SCORE,
# do „slabé“ jen pod SLABE_MAX_SCORE. Díky tomu focení samých dobrých fotek nic nevyhodí
# a focení samých slabých nic nevynese do výběru. Odladěno zatím jen na ~50 fotkách.
VYBER_MIN_SCORE = 4.5
SLABE_MAX_SCORE = 4.5
# Kategorie obsahu → klíčové slovo Fotosort|Obsah|… (viz CATEGORY_KEYWORD). Hodnota = popisy pro CLIP.
CATEGORIES = {
    "detail": ["a close-up detail photo of an object", "a macro photo of a plant or flower",
               "a close-up photo of texture or pattern"],
    "landscape_hory": ["a landscape photo of nature", "a photo of mountains", "a photo of the sea or a lake",
                       "a photo of a valley, forest or hills", "a photo of a cliff above a fjord",
                       "a landscape with tiny people far away"],
    "lidi": ["a portrait photo of a person", "a photo of a person", "a photo of a couple or friends",
             "a person climbing a rock wall with a rope and harness"],
    "street_architektura": ["a street photo in a city", "a photo of a building, architecture",
                            "a photo of a town square or old streets"],
    "zvirata": ["a photo of an animal", "a photo of a bird", "a photo of sheep, cows or horses",
                "a flock of sheep on a hillside", "a photo of a dog or a cat"],
}
# Když si CLIP není jistý ani jednou kategorií, fotka dostane „Ostatní“.
CATEGORY_MIN_PROB = 0.30
