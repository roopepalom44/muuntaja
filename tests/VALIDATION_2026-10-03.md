# Muuntaja 1.5.3: kansiot ja karttaryhmät — testiraportti 3.10.2026

Pohjana on GitHubin uusin `main`, `fb4841a76280e4652dea7d5427e3276af05aee7b`,
ja julkaisu `v1.5.2.21`. Alkuperäisen `muuntaja`-hakemiston paikalliset
muutokset säilytettiin; työ tehtiin erillisessä työpuussa haaralla
`feature/folder-layer-groups`.

**142 automaattista testiä läpäisi ilman ohituksia. 93 oikean ArcGIS Pro
3.7 Advanced -ympäristön testitapausta läpäisi.** Kooste, ajokohtaiset
tulokset ja lähdekoodin sekä paketin SHA-256-tunnisteet ovat tiedostossa
[validation-2026-10-03.json](validation-2026-10-03.json).

## Toteutettu toiminta

- Kansiotuonti säilyttää kaikkien alikansioiden nimet ja sisäkkäisyyden
  kartan ryhmätasoina. Vektorit ja rasterit käyttävät samaa rakennetta.
  Valittu yläkansio itse ei lisää ylimääräistä ryhmää; sen juuressa olevat
  aineistot jäävät kartan juureen.
- Saman nimiset aliryhmät eri vanhempien alla ovat erillisiä. Rasterien
  mosaiikit eivät sekoitu eri ryhmien välillä.
- Vienti kirjoittaa valitut karttatasot kartan ryhmähierarkiaa vastaaviin
  alikansioihin. Ryhmättömät tasot ja erikseen selatut aineistopolut
  kirjoitetaan vientikansion juureen.
- Yhteinen GPKG/DWG/DXF tehdään kullekin ryhmälle erikseen. Tasokohtainen
  paketointi toimii samoissa ryhmäkansioissa.
- Karttatasojen valinnat, määrityskyselyt ja tyylit säilyvät viennissä.
  Windowsin varatut nimet ja kelpaamattomat kansiomerkit käsitellään;
  nimien siivouksen aiheuttamat törmäykset erotetaan nimipäätteellä.

## Aidot ArcGIS-testit

| Testistö | Läpäisseet |
| --- | ---: |
| Kansioryhmät ja ryhmäviennit | 16 |
| Aiempi tuonti-/vientimatriisi | 65 |
| Reunatapaukset, rasterimosaiikki ja CAD-projisointi | 11 |
| Rekisteröidyn GP-työkalun tuonti ja vienti avoimessa Prossa | 1 |
| Yhteensä | 93 |

Ryhmätestit käyttivät Shapefile-, GPKG-, GeoJSON- ja TIFF-lähteitä,
Unicode-kansionimiä, juuressa olevia tiedostoja sekä saman nimisiä
sisäkkäisiä ryhmiä. Vienti tarkistettiin kaikissa seitsemässä muodossa:
GPKG, DWG, DXF, Shapefile, GeoJSON, KML ja KMZ. GPKG/DWG/DXF tarkistettiin
sekä yhteisellä että tasokohtaisella paketoinnilla. Tiedostojen
kansiosijainnit, lukumäärät, kohdemäärät ja GPKG/Shapefile-tyylitiedostot
tarkistettiin. Ryhmitelty GPKG-vienti tuotiin takaisin karttaan ja
alkuperäinen ryhmärakenne sekä kohdemäärät palautuivat.

Lisäksi testattiin GDB- ja kansiokohteet, rasterien yksittäinen tuonti ja
mosaiikit, rasterien uudelleentuonti ilman duplikaatteja, karttavalitsimen
koko ryhmäpolku, samannimiset tasot, määrityskyselyt sekä erikoisnimet.

Käyttöliittymätestissä avattiin koneen ArcGIS Pro Computer Use -työkalulla
ja luotiin erillinen projekti `Muuntaja_kansioryhmat_20261003`. Testi
rekisteröi työkalulaatikon `arcpy.ImportToolbox`-kutsulla ja ajoi sen
`UniversalImportTool`-geoprocessointityökaluna kartassa `Muuntaja native GP`.
Tässä ajossa `CURRENT` oli oikea avoin projekti; karttarajapintoja tai
muunnoksia ei korvattu testikaksoisilla. Viisi vektoritasoa ja kaksi
rasteria tuotiin, minkä jälkeen vektorit vietiin Shapefileiksi neljään
ryhmäpolkuun. Kaikkien vektoritasojen kaksi kohdetta säilyivät.

Komentorivin ryhmätesteissä vain `CURRENT`-projektin haku ohjattiin
erilliseen oikeaan ArcGIS-projektiin. Kaikki muunnokset, geodatabaset,
mosaiikit, ryhmät ja karttatasot käyttivät koneen aitoa ArcPy-rajapintaa.

## Testeissä korjattu

Ryhmän sisällä olevan tason `SaveToLayerFile`-tulos sisältää vanhempien
CIM-rakenteen, jota `ApplySymbologyFromLayer` ei hyväksynyt. Vienti siirtää
nyt tyylin suoraan lähdekarttatasosta, ja GPKG/Shapefile-tyylitiedostot
syntyvät oikein.

Testiskripteistä korjattiin rasterimosaiikin Boundary-/Footprint-alitasojen
rajaus ja CAD-geometrialaskenta. ArcGIS näyttää suljetut CAD-entiteetit sekä
Polygon- että Polyline-luokassa, joten samoja entiteettejä ei lasketa
kahdesti. Neljä CAD-ryhmävientitestiä ajettiin tämän korjauksen jälkeen
uudelleen tallennetusta oikeasta testiprojektista; kaikki läpäisivät.
Alkuperäiset ajolokit säilyvät paikallisissa tuloskansioissa.

## Toistaminen

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
& 'C:\Program Files\QGIS 3.44.14\bin\python-qgis-ltr.bat' -m unittest discover -s tests -q
uvx ruff check --select F,E9 --extension pyt:python Toolboxes qgis_plugin tests
& 'C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe' tests\arcgis_folder_groups_smoke.py --output-dir <uusi-kansio>
& 'C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe' tests\arcgis_matrix_smoke.py --output-dir <uusi-kansio>
& 'C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe' tests\arcgis_edge_smoke.py --output-dir <uusi-kansio>
```

Käyttöliittymätestin `run_current`-funktiota voi kutsua ArcGIS Pron
Python-ikkunassa. Aktiivisen kartan tulee olla erillinen tyhjä testikartta.

Paketti käännettiin virallisella ArcGIS Pro 3.5 SDK:lla ja .NET 8:lla.
Paketin Python-työkalulaatikon tavut verrattiin testattuun lähdekoodiin.
Ajot tehtiin koneen Pro 3.7:llä; Pro 3.5:llä ei tehty ajonaikaista testiä.
