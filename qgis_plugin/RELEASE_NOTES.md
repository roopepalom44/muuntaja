## Muuntaja QGIS 0.5.1 — 13.10.2026

- **DXF- ja DWG-viivat eivät enää levene kilometrien levyisiksi.** QGIS kirjoittaa viivan leveyden karttayksiköissä symbologiamittakaavassa, joten koko Suomen näkymästä (n. 1:5 000 000) viety 1,6 mm tieviiva oli DXF:ssä ja DWG:ssä 8 km leveä. Viivat kirjoitetaan nyt nollaleveyksinä ja leveys tallennetaan CAD-viivapaksuudeksi (lähin vakiopaksuus, esim. 1,58 mm). Pistesymbolien sisältö säilyy ennallaan.
- DXF:n ja DWG:n piirustusyksikkö on metri metrisissä koordinaatistoissa (aiemmin "Unitless"). DWG:hen tallennetaan piirustuksen laajuus ja jokainen CAD-taso saa kohteidensa värin (QGIS kirjoittaa kaikki tasot punaisina).
- **Yhteiseen tiedostoon viedyt tasot nimetään sisällön mukaan** `muuntaja_vienti`-nimen sijaan: saman ryhmän tasot saavat ryhmän nimen (esim. tuodun `suunnitelma.dgn`:n tasot → `suunnitelma.dwg`), muuten käytetään tasonimien yhteistä alkua, tallennetun projektin nimeä tai ensimmäisen tason nimeä (`Eurooppatienumero_Digiroad_ja_2_muuta.dwg`). Koskee DWG-, DXF-, DGN- ja GeoPackage-vientiä.
- Vientisivulta poistettiin CAD-muotojen ohjeteksti.

## Muuntaja QGIS 0.5.0 — 13.10.2026

- **DWG-vienti.** Tasot voi viedä DWG-muotoon (AutoCAD 2018, 2013, 2010, 2004 tai 2000) ilman ODA File Converteria tai muita asennuksia. DWG kirjoitetaan QGISin omasta DXF-viennistä lisäosan mukana tulevalla ACadSharp-ohjelmalla, joten symbologia, nimiöt, pistesymbolit, viivatyypit ja CAD-tasonimet säilyvät. Kirjoitettu tiedosto luetaan takaisin ja kohdemäärät verrataan ennen hyväksyntää, ja koordinaatisto tallennetaan viereen `.prj`-tiedostoon ArcGIS Pron luettavaksi. Valikkoon tuli **Projekti → Tuo/Vie → Vie tasot DWG-muotoon (Muuntaja)**.
- AutoCAD 2000 -DWG:n MTEXT-tekstit tuodaan ilman muotoilukoodeja (aiemmin esim. `\fArial|b0;\H2.5;Kauppakatu`).

## Muuntaja QGIS 0.4.4 — 13.10.2026

- **DGN-mitoitukset ja kartiot tuodaan geometriana.** MicroStationin mitoitus- ja nimiöviivat (elementtityyppi 33) tulevat viivoina ja niiden tekstit (esim. korot ja putkimerkinnät kuten "Sv 160 PVC") nimiöinä; kartiot ja sylinterit (tyyppi 23, esim. kaivot) tulevat pohja-alueina kannen korkeudella. Aiemmin ne jäivät pois ilmoituksella "kept as Unknown entities". Muut tunnistamattomat graafiset elementit säilyvät vähintään pisteenä omalla paikallaan, ja tulosikkuna kertoo mitä purettiin.
- **Monitasoiset tiedostot ryhmitellään tiedostonimen mukaan.** GeoPackage, KML, GPX ja muut useita tasoja tuottavat tiedostot lisätään CAD-tuonnin tapaan omaan ryhmäänsä (esim. `kohteet.gpkg`). Uudet ryhmät tulevat sisällysluettelon ylimmäksi.

## Muuntaja QGIS 0.4.2 — 11.10.2026

- Tuonnit, viennit ja CAD-tiedostojen pudotus suoritetaan QgsTask-taustatehtävinä. Projektin tasot ja käyttöliittymä päivitetään pääsäikeessä; vienti käyttää aineiston ja tyylin tilannekuvaa.
- Numerolla alkavat FileGDB-nimet, lähdetiedostojen Windows-lukot, tekstikenttien DBF-rajat ja rasterierän yksittäiset virheet käsitellään hallitusti.
- DFSU-suodatus käyttää NumPy-maskeja ja kohteet kirjoitetaan 1 000 kohteen transaktioissa. Tarpeettomia elementtien keskipisteitä ei lasketa.
- Kansioiden skannaus käyttää scandir-lukua ja world-tiedostot tarkistetaan hakemistolistasta.
- Koordinaateista epäselvä prefiksitön GK ei enää muutu automaattisesti TM35FIN-järjestelmäksi. Voimassa olevat ulkomaiset koordinaatistot säilyvät.
- Julkaisua estävät Python- ja QGIS-regressiotestit. Tarkempi löydöskohtainen kooste on juuren AUDIT_FIXES.md-tiedostossa.

## Muuntaja QGIS 0.2.2

- Jäsensi tuonnin tallennustavat erillisiksi GeoPackage-tiedostoiksi, yhdeksi GeoPackageksi tai File Geodatabaseksi. Tiedostonvalitsin ja kentän ohjeteksti vaihtuvat tallennustavan mukaan.
- Siirsi CRS-, CAD- ja DFSU-valinnat lisäasetuksiin ja ottaa tiedostokohtaiset asetukset käyttöön vain, kun syöte voi sisältää kyseistä aineistoa.
- Selkeytti vientiasetuksia: yhdistetty tiedosto on tarjolla vain GPKG-, DXF- ja DWG-muodoille, ja ODA-muunnin näkyy vain DWG-viennissä.

## Muuntaja QGIS 0.2.1 — esijulkaisu

Uusi Windows-asennus: lataa `Muuntaja-QGIS-0.2.1-Windows.zip`, pura se ja suorita `install_windows.bat` QGISin ollessa suljettu. Asennin kopioi lisäosan QGIS-profiileihin ja aktivoi sen. Vaihtoehtoisesti asenna `Muuntaja-QGIS-0.2.1.zip` QGISin **Lisäosat → Hallitse ja asenna lisäosia → Asenna ZIP-tiedostosta** -toiminnolla. Vaatii QGIS 3.44:n.

Tässä versiossa toimivat kansio- ja tiedostotuonti, FileGDB/GPKG-kohteet, rasterien VRT-mosaiikki ryhmittäin, DFSU-tuonti `mikeio`-kirjastolla sekä GPKG-, GeoJSON-, Shapefile-, KML-, KMZ- ja DXF-vienti. Valinnainen DWG-vienti muuntaa DXF:n DWG:ksi ODA File Converterilla. QGIS 3.44:ssä on testattu näiden formaattien vienti, yhdistetty GPKG/DXF-vienti, CAD-tuonti, rasterimosaiikin uudelleenajo ja jäljitelty DFSU-suodatus. DWG-työnkulku on testattu jäljitellyllä ODA-muuntimella, ei oikealla asennuksella.

**Tämä ei vielä ole toiminnallisesti identtinen ArcGIS Pro -version kanssa.** DWG-vienti tarvitsee erillisen ODA File Converter -asennuksen. QGISin VRT-mosaiikki käyttää eri tallennusmuotoa kuin ArcGIS Pron FileGDB-mosaiikki. Tarkempi tilanne: [QGIS-ohje](https://github.com/roopepalom44/muuntaja/blob/main/qgis_plugin/README.md).
## Muuntaja QGIS 0.2.3

- Julkaistaan samassa GitHub-releasessa ArcGIS Pro AddInX:n kanssa sekä QGISin omana asennus-ZIPinä että Windows-asennus-ZIPinä.
- GeoJSON-vienti muuntaa koordinaatit WGS84:ään ja hylkää puuttuvan lähtökoordinaatiston. Tarkistettu QGIS 3.44:llä.
## Muuntaja QGIS 0.2.4

- Tallennetun QGIS-projektin kansio täyttyy oletuksena tuonnin ja viennin tallennuspaikaksi. GeoPackage- ja FileGDB-tallennustavat saavat tiedostonimen samasta kansiosta.

## Muuntaja QGIS 0.2.5

- Uudemman DWG:n tuonti käyttää ODA File Converteria varapolkuna, kun QGISin CAD-ajuri ei avaa tiedostoa. Virhe ilmoittaa DWG-version ja tarvittavan toimenpiteen.
- Lähtö-CRS voidaan pakottaa myös aineistolle, jolla on virheellinen CRS-merkintä. Puuttuva tai Suomen koordinaattiarvojen kanssa ristiriitainen CRS pysäyttää tuonnin selkeään virheeseen.

## Muuntaja QGIS 0.2.6

- Virheellinen CRS-merkintä tunnistetaan myös muista koordinaatistoista kuin EPSG:3857 ja EPSG:4326, kun aineiston koordinaatit osoittavat Suomeen mutta merkitty järjestelmä vie ne muualle.
- Suomen alueen EPSG:3857-koordinaatit tunnistetaan myös aineistoista, joilla CRS-merkintä puuttuu.

## Muuntaja QGIS 0.2.7

- Jos QGIS-projektilta puuttuu koordinaattijärjestelmä, tuonti asettaa sen ensimmäisen tuodun tason mukaan ennen tason lisäämistä. Tämä koskee vektori-, rasteri- ja DFSU-tasoja.
- Tuonnin valmistumisviesti kertoo, kun projektin CRS asetettiin automaattisesti.

## Muuntaja QGIS 0.3.0

- **DWG ja DXF natiivisti QGISissä.** Piirustus tuodaan ryhmäksi, jossa ovat tekstit, pisteet, viivat ja alueet omina tasoinaan. CAD-värit säilyvät, CAD-tasot näkyvät sisällysluettelossa päälle/pois kytkettävinä sääntöinä ja tekstit nimiöinä CAD-korkeudella, -kulmalla ja -ankkurilla. Paperitilan kohteet ohitetaan.
- DWG:n voi raahata suoraan QGIS-ikkunaan tai lisätä valikosta **Taso → Lisää taso → Lisää DWG/DXF-taso (Muuntaja)**. Jos koordinaatistoa ei voi päätellä, QGIS kysyy sen tavalliseen tapaan.
- **DWG avautuu Windowsissa ilman asennuksia:** lisäosan mukana tulee LibreDWG 0.14 (GPL-3), joka lukee AutoCAD 2000–2018 -DWG:t. Testattu DWG-versioilla 2000, 2004, 2007, 2010, 2013 ja 2018. ODA File Converter -tuki poistettiin: sitä ei saa jakaa lisäosan mukana, ja erillinen asennus ja .exe-polun valinta oli kömpelö.
- **DXF-vienti käyttää QGISin omaa DXF-vientiä:** symbologia, nimiöt ja tuotujen CAD-tasojen nimet säilyvät, ja eri koordinaatistoissa olevat tasot muunnetaan samaan koordinaatistoon (aiemmin yhdistetty vienti sekoitti ne). DWG-vienti löytyy myös valikosta **Projekti → Tuo/Vie**.
- DWG-vienti on kokeellinen: DWG tehdään LibreDWG:llä ja kirjoitetaan uudelleen dwgrewrite:llä, jolloin ArcGIS Pro avaa sen (aiemmin Pro kaatui LibreDWG:n DWG-tiedostoihin). Tulos luetaan takaisin ja verrataan kohdetyypeittäin: aluetaso hyväksytään varoituksella, jos vain reunaviivat puuttuvat; muut puutteet pysäyttävät viennin ja virhe kertoo mitä puuttuu. Viivat, pisteet ja tekstit kannattaa viedä DXF-muotoon.
- Korjattu: DFSU-taso avattiin väärällä nimellä GeoPackageen, jossa oli jo muita tasoja; rasterituonti poisti käyttäjän omia tasoja samannimisestä ryhmästä; GeoPackage-tasonimet vertaillaan kirjainkoosta riippumatta; projektista poistettu taso kaatoi viennin; kansioskannaus otti mukaan muitakin kuin paikkatieto-JSONeja.
- Muuntimen aikakatkaisu ja puuttuva muunnin näytetään selkeänä suomenkielisenä virheenä, eikä Windows avaa konsoli-ikkunaa muunnoksen ajaksi. Muuntimen muu kuin UTF-8-tuloste (esim. ääkköset polussa) ei enää kaada muunnosta.
- Tunnettu rajoitus: Linuxissa ja macOS:ssä ilman järjestelmän LibreDWG:tä avautuu vain AutoCAD 2000 -DWG, ja silloin GDAL:n CAD-ajuri ei lue täyttöjä (HATCH) eikä lohkoviittauksia (INSERT). LibreDWG 0.14 ei kirjoita DWG:hen viivoja, pistesymboleita eikä tekstejä.

## Muuntaja QGIS 0.3.1

- **DWG-vienti poistettu.** LibreDWG ei kirjoita DWG:hen viivoja, pistesymboleita eikä tekstejä, joten CAD-vienti tehdään DXF-muotoon, jonka AutoCAD, ArcGIS ja QGIS avaavat sellaisenaan. Valikon toiminto on nyt **Projekti → Tuo/Vie → Vie tasot DXF-muotoon (Muuntaja)**.
- Lisäosan mukana tulee enää LibreDWG:n DWG-lukija (`dwg2dxf`), joten asennuspaketti pieneni. DWG-tuonti toimii ennallaan (AutoCAD 2000–2018).

## Muuntaja QGIS 0.4.0

- **Kohdekoordinaatisto viennissä.** Vientiin voi valita koordinaatiston, johon aineisto muunnetaan (ETRS-TM35FIN, ETRS-GK19–GK31 kuten EUREF-FIN / ETRS-GK23, KKJ-kaistat, WGS 84, Web Mercator tai mikä tahansa QGISin valitsimesta). Oletus on **Tason oma**. Koskee GPKG-, Shapefile-, GeoJSON- ja DXF-vientiä; KML/KMZ on aina WGS84. Usean tason viennissä jokainen taso säilyttää oman koordinaatistonsa; tasokohtaiset DXF:t eivät enää saa projektin koordinaatistoa, ja eri koordinaatistojen tasojen yhdistäminen yhteen DXF:ään vaatii kohdekoordinaatiston.
- **Tyyli kulkee viennin mukana** (valinta *Pakkaa tasojen tyylit mukaan*, oletuksena päällä). GeoPackageen tyyli tallennetaan sisäisesti, Shapefilen ja GeoJSONin viereen kirjoitetaan `.qml` ja KML/KMZ saa tyylit. Tulosikkuna kertoo, minne tyyli tallennettiin.

## Muuntaja QGIS 0.4.1

- **Tyyli kulkee myös tuonnissa.** Kun tuotavalla Shapefilellä tai GeoJSONilla on vieressään samanniminen `.qml` tai GeoPackagessa on tasolle tallennettu tyyli, tuotu taso saa saman tyylin ja se tallennetaan tuonnin GeoPackageen oletustyyliksi. Tulosikkuna kertoo, mille tasoille tyyli otettiin käyttöön.
