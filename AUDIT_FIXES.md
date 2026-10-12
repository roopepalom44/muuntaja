# Auditointikorjaukset 11.10.2026

Korjaukset on yhdistetty GitHubin `main`-version `4f05439` päälle. Auditoinnin lähtökopio oli 28 commitia jäljessä: uudemman version CAD-lukija, tasotyylit, ryhmät, ohjeet ja testit on säilytetty. Alkuperäinen `AUDIT_REPORT.md` jää vertailuaineistoksi; tämä tiedosto kuvaa toimitettavan toteutuksen.

| Löydös | Toteutettu korjaus / tarkennus |
|---|---|
| CRIT-01 | CAD-työprosessi on mukana lähteissä ja AddInX-paketissa. Puuttuvan työprosessin tapauksessa käytetään sisäistä lukijaa. Natiivi DXF-tuonti on testattu. |
| CRIT-02 | Lähtö- ja kohde-CRS kulkevat kaikkien vektorituontien läpi. Kohdemuunnos käyttää tiedoston omaa CRS:ää, kun käyttäjä ei pakota lähtö-CRS:ää. Tuntematon lähtö-CRS pysäyttää muunnoksen. |
| CRIT-03 | Uudemman main-version DXF-vienti käyttää QGISin omaa vientiä ja yhteistä kohde-CRS:ää. Eri CRS:t vaativat käyttäjältä kohdevalinnan. Julkaistun main-version päätös jättää DWG-vienti pois säilyy: pelkkä LibreDWG ei kirjoita kaikkia tarvittavia entiteettejä. |
| CRIT-04 | Numerolla alkavat FileGDB-nimet normalisoidaan ennen kirjoitusta. DFSU avaa ajurin palauttaman todellisen tasonimen. |
| CRIT-05 | Probet, lähdetasot ja tilapäiset vientitasot vapautetaan. OGR-yhteysvarasto mitätöidään providerin `reloadData()`-kutsulla ennen `sip.delete()`-poistoa. Pelkkä poisto ei riittänyt tämän Windowsin QGIS-versiossa. |
| CRIT-06 | Rasterit validoidaan yksitellen. Kelvolliset tiilet päätyvät mosaiikkiin, ja yhteenveto ilmoittaa vain todelliset epäonnistumiset. |
| CRIT-07 | Vanhentuneet parametri-, allekirjoitus- ja ryhmäoletukset on sovitettu nykyisiin rajapintoihin. Testit vaativat nyt tekstisarakkeiden säilymistä. |
| CRIT-08 | CI ajaa pytestin sekä tavallisella Windows-Pythonilla että Ubuntu/QGIS-ympäristössä ja lintin. Julkaisu riippuu molemmista testitöistä. |
| CRIT-09 | Rajattu QGIS-mock-fixture sekä oikealla QGISillä ajettavat integraatiotestit ovat mukana pytest-/CI-ajossa. |
| HIGH-01 | ArcGISin rasteritasot luodaan `.lyrx`-tiedostoiksi kartan ulkopuolella ja lisätään ryhmään yhdellä kutsulla erää kohti. Näkyvät nimet säilyttävät rasterien tiedostonimet. |
| HIGH-02 | DFSU-suodatinsarake ratkaistaan kerran. NumPy-maskit valitsevat rivit ja OGR kirjoittaa 1 000 kohteen transaktioita. Käyttämättömiä elementtien keskipisteitä ei lasketa. |
| HIGH-03 | Dialogin tuonti/vienti ja CAD-pudotus käyttävät `QgsTask`-tehtäviä. Työ käyttää omaa projektia ja vientilähteen/tyylin tilannekuvaa. Valmiit tasot ja CRS-valitsin käsitellään pääsäikeessä. Tuotantokoodista on poistettu `processEvents()`-kutsut. |
| HIGH-04 | 400 000–600 000 itäkoordinaatin alue on epäselvä automaattisessa tunnistuksessa. Prefiksitöntä GK:ta ei nimetä hiljaa TM35FINiksi. Aineiston oma CRS tai käyttäjän valinta ratkaisee tilanteen. |
| HIGH-05 | Shapefile-sarakkeita säilytetään lyhentämällä tekstileveyksiä. Lyhentämisestä ilmoitetaan. Jos rakenne ei mahdu, vienti pysähtyy ja ohjaa GeoPackageen sarakkeiden poistamisen sijaan. |
| HIGH-06 | Suomen sijaintiin perustuva ristiriitatarkistus koskee vain yleisiä EPSG:4326-/3857-oletuksia. Voimassa olevia ulkomaisia projektioita ei hylätä numerovälien perusteella. |
| HIGH-07 | CAD-tunnistus äänestää paikkatietonäytteistä; origon apukohteet eivät vie enemmistöä. |
| HIGH-08 | Riskialttiit tuontipolut, CRS-välitys ja kaikki ArcGISin raportissa mainitut vektoriformaatit on lisätty regressio-/natiivitesteihin. Tämä ei tarkoita jokaisen metodin 100 % kattavuutta. |
| HIGH-09 | Virheelliset GeoJSON-/GPX-/KMZ-/CAD-tiedostot ja puuttuvat Shapefile-sivutiedostot on testattu. JSON/XML/ZIP tarkistetaan ennen QGISin avausta. |
| HIGH-10 | Sekä ArcGISin eräajo että QGISin oikea tuonti on testattu erällä, jossa onnistuneiden ja rikkinäisten tiedostojen käsittely jatkuu toisistaan riippumatta. |
| MED-01 | World-sivutiedostot tarkistetaan hakemistolistasta; ArcGISin world-koordinaatit välimuistitetaan tuontiajon ajaksi. |
| MED-02 | CAD-pisteiden `CadType` asetetaan `CalculateField`-kutsulla rivikohtaisen UpdateCursorin sijaan. |
| MED-03 | ArcGIS säilyttää alkuperäiset NumPy-puskurit: ei koko sarakkeiden `tolist()`-muunnosta, tarpeetonta float64-kopiota, toista mesh-lukua tai koko aikasarjan varalukua. |
| MED-04 | Vektorierä lukee kohteen tasonimet kerran ja päivittää nimiavaruutta muistissa. Probet suljetaan. |
| MED-05 | Rasterien tarkastus pitää auki yhden tilapäisen rasteritason kerrallaan, eikä tuhansien tasojen listaa. |
| MED-06 | QGISin kansioskannaus käyttää `scandir`-lukua, sivutiedostojen nimijoukkoa ja ohittaa piilohakemistot/välimuistit. Paikallista tiedostoa ei `resolve()`-avata jokaisella kierroksella. |
| MED-07 | Lukittu projisoimaton välitaso siirretään jälkisiivousjonoon. Siivous vapauttaa ArcGISin workspace-välimuistin ja säilyttää epäonnistuneet poistot seuraavaan yritykseen. |
| MED-08 | GeoJSONin syntaksivirhe välittyy tiedoston nimellä. Native-muuntimen virhe kirjataan geometriatyypin kanssa. |
| MED-09 | Kenttänimien ä/ö/å translitteroidaan, ja tyhjälle nimelle annetaan kelvollinen varanimi. |
| MED-10 | ArcGISin `.kml` on KMZ:stä erotettua XML:ää, `.kmz` pysyy arkistona. Vienti käyttää aktiivisen karttanäkymän mittakaavaa tai työkalun oletusta. |
| MED-11 | Julkaistun CAD-lukijan kenttähaku ja Defpoints/0-suodatus käsittelevät kirjainkoon. Natiivi lowercase-Defpoints-testi on mukana. |
| MED-12 | 50 000 vektorikohteen, 1 000 rasterin, 219 Mt:n DFSU:n, Windows-lukkojen ja tilapäishakemistojen siivouksen testit on toteutettu. |
| LOW-01 | Polkutestit kattavat välilyönnit, suomalaiset merkit, eri erottimet ja UNC-polun komponentit. Oikeaa verkkopalvelimen saavutettavuutta ei simuloida paikallisella polkutestillä. |
| INF-01 | Jokainen VRT-uudelleenrakennus saa uuden tiedostonimen. Vanhaan VRT:hen avoin ulkopuolinen kahva ei estä uuden mosaiikin julkaisemista. |
| INF-02 | QGISin DBF-kenttänimet tehdään yksilöllisiksi 10 merkissä. Leveydet ja UTF-8-tavumäärä rajataan; mahdoton rivirakenne hylätään selvästi. |
| INF-03 | Yksi dialogi säilytetään istunnon ajan. Lisäosan poisto keskeyttää taustatehtävät ja vapauttaa dialogin tehtävän päätyttyä. |

## Tarkistukset

- Tavallinen Python 3.14: `python -m pytest tests --tb=short` — **146 läpäisi**. 62 natiivi-/opt-in-testiä ohitetaan tässä ympäristössä tarkoituksella.
- QGIS 3.44.14: `python-qgis-ltr.bat -m unittest discover -s tests -p "test_qgis*.py" -v` — **62 läpäisi**, yksi suuren DFSU:n opt-in-testi ohitettiin; se ajettiin erikseen alla.
- ArcGIS Pro 3.7: `propy.bat -m unittest discover -s tests -p test_arcgis_integration.py -v` — **9 läpäisi**, mukaan lukien oikea CAD-työprosessi, viisi vektoriformaattia, rasterien LayerFile-erä ja NumPy/NaN-DFSU-kirjoitus.
- Windowsin GitHub-runnerin 8.3-polkujen testivertailu käyttää molempien polkujen kanonista muotoa.
- Ruff: `ruff check --select F,E9 --extension pyt:python Toolboxes qgis_plugin tests` — läpäisi.
- 50 000 kohteen QGIS-vienti: **0,53 s** viimeisessä koko testisarjan ajossa; tiedoston kohdemäärä ja tiedostolukkojen vapautuminen tarkistetaan.
- 1 000 rasterin VRT: **24,38 s** viimeisessä koko testisarjan ajossa; yksi karttataso ja kaikki lähdepolut tarkistetaan.
- Todellinen DFSU: **219,5 Mt, 2 952 452 kohdetta, 115,39 s, RSS-kasvu 1 696,2 Mt**. Opt-in-testin raja on 2 GiB tämän näytemeshin RSS-kasvulle. Mittaus sisältää mikeio/mikecore-kirjaston mesh-allokaatiot; suuremmille mesheille ei väitetä samaa absoluuttista rajaa.
- MSBuild Release ja AddInX-rakenteen tarkistus sekä QGISin normaalin/Windows-ZIPin luonti läpäisivät.

DFSU-muistitestin uusiminen: asenna `mikeio` ja `psutil` erilliseen testikäyttöiseen Python-ympäristöön ja aseta `MUUNTAJA_DFSU_STRESS_FILE` aineiston poluksi. `MUUNTAJA_AUDIT_DEPENDENCIES` voi osoittaa erilliseen testikirjastohakemistoon. Testi ei sisälly CI:n vakiopakettiin, koska suuri paikallinen aineisto ei ole Gitissä.

Algoritmi käyttää QGISin [taustatehtävien säierajoja](https://docs.qgis.org/3.44/en/docs/pyqgis_developer_cookbook/tasks.html) ja GDALin [OpenFileGDB-transaktioita](https://gdal.org/en/stable/drivers/vector/openfilegdb.html#transaction-support). GitHubin CI:n toteutunut tulos on erillinen paikallisista testituloksista.

## CAD-viennin jatkokorjaus 2026-10-12 (ArcGIS 1.5.5)

`Polut_viivat`-aineiston DWG-vienti epäonnistui ArcGIS Pro 3.7:ssä virheeseen
`000520: Unexpected TopoEngine Error`. Virhe toistettiin alkuperäisen aineiston
scratch-kopiolla. Check Geometry ei löytänyt ongelmia; Repair Geometry,
2D-kopio ja pienempi kohdevalinta eivät auttaneet. Virhe rajattiin OSM:n
`layer`-attribuuttiin, joka tulkittiin CADin varatuksi `Layer`-kentäksi.
Myös etuliitteellä nimetty `osm_layer` toisti virheen; `layer_value` toimi.

Muuntaja yrittää kenttätörmäyksestä palautumista vain virheen 000520 jälkeen.
Uuden scratch-kopion Layer/Level-nimille ja aliaksille annetaan yksilöllinen
`_value`-pääte. Kaikki attribuutit ja geometria säilytetään, lähteeseen ei
kirjoiteta, ja käyttäjälle kerrotaan kenttänimien muutoksesta. Jos vienti
onnistuu alun perin, CAD-ohjauskenttiä ei muuteta. Muut virheet ja
epäonnistunut uusinta välitetään eräajon tavalliseen virheraportointiin.

Todellisella 27 019 kohteen aineistolla sekä DWG että DXF onnistuivat.
Vientikopion kaikkien ominaisuuksien ja WKB-geometrian SHA-256 vastasi
lähdettä; myös lähteen muuttumattomuus, Z-ulottuvuus ja EPSG:3067 tarkistettiin.
Molempien CAD-tiedostojen Polyline-kohdemäärä oli 27 019. Tarkistus tehtiin
myös `overwriteOutput=False`-asetuksella: epäonnistuneen ensimmäisen yrityksen
CAD-runko poistetaan ennen uusintaa, jotta ArcGISin validointi ei pysäytä sitä.

Paikalliset testit: 153 Python-testiä läpäisi (63 ympäristökohtaista testiä
ohitettiin), 10 natiivia ArcGIS-testiä läpäisi. Natiivi regressio varmistaa
valinnan ja määrityskyselyn, attribuuttien ja kenttänimitörmäysten säilymisen,
suomalaiset merkit, emoji-tekstin, Z-arvot sekä oikean DWG/DXF-tuloksen.
