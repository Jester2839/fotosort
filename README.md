# fotosort

Import fotek ze Sony a6700 do knihovny `_Foto` a (později) hrubé třídění.

## Instalace

```
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Import z karty

```
python -m fotosort import             # najde kartu sama, ptá se na rozdělení a názvy
python -m fotosort import --dry-run   # jen ukáže plán
python -m fotosort import --card E:\ --gap 3
```

Co se stane:

1. Najde disk se složkou `DCIM`, načte fotky (`.ARW`, `.JPG`) a videa (`PRIVATE\M4ROOT\CLIP`).
2. Přeskočí vše, co už v knihovně je (porovnává jen názvy souborů, z OneDrive nic nestahuje).
3. Ukáže časovou osu po dnech. Nová akce se navrhne po ≥ 2 dnech bez focení. Číslem dne řez přidáš nebo zrušíš.
4. Zeptá se na název každé akce a vytvoří `_Foto\2026\260703-18_Norsko\` + `_upraveno\` (+ `video\`).
5. Kopíruje s ověřením kontrolního součtu. Karta zůstane beze změny.

Soubory se přejmenují na `260703_143502_DSC01234.ARW` (čas pořízení + původní název), takže RAW+JPG drží spolu, řadí se chronologicky a nevadí přetočení počítadla Sony.

Nastavení (cesta ke knihovně, mezera mezi akcemi, podsložky) je v `fotosort/config.py`.

Po importu se appka zeptá, jestli nové akce rovnou roztřídit.

## Třídění akce

```
python -m fotosort cull "C:\...\_Foto\2026\260703-18_Norsko" --dry-run
python -m fotosort cull "C:\...\_Foto\2026\260703-18_Norsko" --kategorie
python -m fotosort cull "C:\...\_Foto\2026\260703-18_Norsko" --undo
```

Prochází jen fotky přímo ve složce akce (ne `_upraveno` apod.).

**1. Technická kontrola** → `_ke_smazani\<důvod>\`
- `serie` – snímky rychle za sebou nebo skoro stejné; ponechá nejostřejší bez zavřených očí,
- `neostre` – ostrost hluboko pod mediánem focení (měří se nejostřejší místo, bokeh nevadí),
- `zavrene_oci` – výrazný obličej (ne lidi v pozadí) má zavřené obě oči,
- `expozice` – jen samotné JPG s extrémně přepálenou/černou plochou,
- `chyba` – soubor nejde načíst.

**2. AI hodnocení** zbytku (CLIP + LAION aesthetic), relativně v rámci focení:
- horních 40 % → `_vyber\` (s `--kategorie` → `_vyber\detail\`, `landscape_hory`, `lidi`, `street_architektura`, `zvirata`, `ostatni`),
- spodních 20 % → `_ke_smazani\slabe\` (jen když je fotek aspoň 10),
- zbytek → `_nejiste\`.

`--bez-ai` udělá jen technickou kontrolu bez očí. RAW+JPG se přesouvají spolu, nic se nemaže,
`--undo` vrátí vše zpět (log je v `_ke_smazani\_fotosort_log.csv`).
Prahy, procenta a kategorie jsou v `config.py`.

### Instalace AI (jednou)

```
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130
pip install -r requirements-ai.txt
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

Poslední řádek musí vypsat `True` a název grafiky. Když vypíše `False`, aktualizuj ovladač NVIDIA,
případně zvol jinou verzi CUDA na https://pytorch.org/get-started/locally/.

Při prvním třídění se stáhnou modely (~900 MB CLIP, pár MB ostatní) do `%LOCALAPPDATA%\fotosort\models`
a do cache Hugging Face.

## Testy

```
pip install pytest
python -m pytest            # test se skutečným CLIP modelem je pomalý (~1 min)
```
