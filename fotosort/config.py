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

# Složky pro třídění (vytvoří je až culling krok).
CULL_FOLDERS = {"good": "_vyber", "unsure": "_nejiste", "delete": "_ke_smazani"}

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
# Z technicky v pořádku fotek: horních X % do _vyber, spodních Y % do _ke_smazani/slabe, zbytek _nejiste.
VYBER_TOP = 0.40
SLABE_BOTTOM = 0.20
# Absolutní pojistky (LAION skóre, typicky 3–7): do výběru jen od VYBER_MIN_SCORE,
# do „slabé“ jen pod SLABE_MAX_SCORE. Díky tomu focení samých dobrých fotek nic nevyhodí
# a focení samých slabých nic nevynese do výběru. Odladěno zatím jen na ~50 fotkách.
VYBER_MIN_SCORE = 4.5
SLABE_MAX_SCORE = 4.5
# Kategorie pro _vyber/<kategorie> (přepínač --kategorie). Klíč = název složky, hodnota = popisy pro CLIP.
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
# Když si CLIP není jistý ani jednou kategorií, fotka jde do _vyber/ostatni.
CATEGORY_MIN_PROB = 0.30
