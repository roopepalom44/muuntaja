# Muuntaja 1.5.2: testiraportti 30.9.2026

134 automaattista testiä läpäisi QGIS 3.44.14 -ympäristössä ilman ohituksia.
83 oikean ArcGIS Pro 3.7:n testitapausta läpäisi korjausten ja tarvittavien
uusinta-ajojen jälkeen. Koneellinen kooste on tiedostossa
[`validation-2026-09-30.json`](validation-2026-09-30.json).
Release-paketti käännettiin Pro 3.5 SDK:lla; Python-integraatiotestit ajettiin
Pro 3.7:llä, joten koko toiminnallisuutta Pro 3.5:llä ei tässä ajossa testattu.

## Testattu toiminnallisuus

- Pisteet, viivat ja alueet: vienti GPKG-, Shapefile-, GeoJSON-, DWG-, DXF-,
  KML- ja KMZ-muotoihin sekä takaisinluenta. GPKG/Shapefile-tyylitiedostot,
  GeoJSONin rakenne, KML/XML ja KMZ-arkisto tarkistettiin.
- Monitasoviennit: yhteinen tiedosto ja tasokohtaiset tiedostot niitä
  tukevissa formaateissa, sekä rivimäärät GPKG/Shapefile/GeoJSON-tuloksista.
- ETRS-TM35FIN → ETRS-GK23, CADin koordinaatiston valinta ja kenttäsuodatus,
  määrityskyselyllä rajattu tason vienti ja tunnisteiden tarkkuus.
- Tyhjät vientitasot, null-geometria, tuntematon lähtö-CRS, Unicode,
  1 000 merkin tekstikentät, leveä taulu, BigInteger ja uudet aikatyypit.
- Tuonti geodatabaseen ja kansioon, nimiristiriita, avoin syötekursori,
  sisäkkäiset kansiot, rikkinäinen ja tyhjä GeoJSON sekä rikkinäinen DFSU
  yhdessä onnistuvan aineiston kanssa.
- CAD: oikea DWG, DXF, uudempi DWG ja vanha DWG-testitiedosto, joka kaataa
  ArcGISin native-lukijan. Viimeinen hylättiin hallitusti erillisessä
  prosessissa, ja erän seuraava GeoJSON tuotiin onnistuneesti.
- TIFF-rasteista muodostettu mosaiikki: upotettu koordinaatisto, kaksi
  karttalehteä, uudelleentuonti ilman duplikaatteja ja rikkinäinen rasteri
  yhdessä onnistuvan rasterin kanssa. Karttalisäykset tehtiin erilliseen
  muistissa olevaan testikarttaan, eivät käyttäjän avoimeen projektiin.

## Oikeat aineistot

| Aineisto | Tulos |
| --- | --- |
| Väylän aidat, GPKG | 6 098 kohdetta; myös kansiotuonti onnistui |
| Väylän aidat, vienti GK23-Shapefileksi | 6 098 kohdetta ja tyyli; kahdeksan BigInteger-kentän kaikki arvot säilyivät |
| Tilastokeskuksen postialueet 2026 | 3 018 aluetta |
| GPX-reitti | 341 pistettä ja yksi reittiviiva |
| Oikea DWG-piirustus | Ei-tyhjät tasot tuotiin |
| DFSU-tulva-aineisto | 2 952 452 elementtiä |
| Tyhjä GPKG-taso | Hallittu hylkäys; ei virheellistä onnistumisilmoitusta |

DFSU:n `mikeio 3.3.0` ja `mikecore 0.2.2` asennettiin erilliseen
testiriippuvuuksien kansioon. ArcGIS Pron oletusympäristöä ei muutettu.
Shapefilen dBASE-rajoitukset säilyvät: aita-aineistosta jätetään pois
34 kenttää rivipituusrajan vuoksi, ja tästä annetaan varoitus.

## Testien suorittaminen

Automaattiset testit QGISin Pythonilla:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
& 'C:\Program Files\QGIS 3.44.14\bin\python-qgis-ltr.bat' -m unittest discover -s tests -q
uvx ruff check --select F,E9 --extension pyt:python Toolboxes qgis_plugin tests
```

ArcGIS-integraatiotestit ArcGIS Pron Pythonilla; anna jokaiselle ajolle uusi
tuloskansio. `--downloads`, `--dfsu`, `--source` ja `--cad` ovat valinnaisia
omien aineistojen polkuja:

```text
python tests/arcgis_matrix_smoke.py --output-dir <uusi-kansio> [--downloads <aineistokansio>] [--dfsu <tiedosto>]
python tests/arcgis_edge_smoke.py --output-dir <uusi-kansio> [--cad <tiedosto>]
python tests/arcgis_shapefile_smoke.py [--source <feature-class>]
```

Tulokset osoittavat näiden tapausten toimivan testatuissa ympäristöissä.
Ne eivät takaa, ettei jokin muu aineisto, ArcGIS-versio tai native-kirjasto
voisi epäonnistua. CAD-lukijan kaatuminen on eristetty; kaikkia ArcGISin
native-toimintoja ei ajeta erillisessä prosessissa.
