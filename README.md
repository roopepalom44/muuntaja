# Muuntaja

**QGIS-versio (esijulkaisu):** [asennus ja nykyinen toiminnallisuus](qgis_plugin/README.md). Uusimmat asennuspaketit: [Muuntaja-QGIS-Windows.zip](https://github.com/roopepalom44/muuntaja/releases/latest/download/Muuntaja-QGIS-Windows.zip) ja [Muuntaja-QGIS.zip](https://github.com/roopepalom44/muuntaja/releases/latest/download/Muuntaja-QGIS.zip).

**Muuntaja** on ArcGIS Pro Add-In -laajennus, joka on suunniteltu helpottamaan erilaisten tiedostomuotojen (kuten CAD, GPX, KML jne.) tuomista ja viemistä ArcGIS Pro -ympäristössä. Se tarjoaa käyttäjäystävällisen käyttöliittymän aineistojen nopeaan kääntämiseen ja siirtämiseen.

## Ominaisuudet
- **Tiedostojen muuntaminen:** Tuo CAD-, GPKG-, Shapefile-, GeoJSON-, GPX-, KML/KMZ- ja DFSU-aineistoja suoraan projektiin.
- **Kansiotuonti:** Anna tuonnissa yhden kansion polku. Muuntaja käy kansion ja sen alikansiot läpi, tunnistaa kaikki tuetut tiedostomuodot ja lisää muunnetut tasot työtilaan.
- **Rasterituonti ryhmiteltynä:** Tuonti tunnistaa myös rasterit (TIFF, JP2, IMG sekä PNG/JPG, joiden vieressä on world-tiedosto kuten `.pgw`). Rasterit lisätään työtilaan ryhmätasoihin lähimmän `taustakartta_`-alkuisen kansion mukaan, joten MML:n latauskansion voi antaa sellaisenaan (ks. alla).
- **Tasovalinta viennissä:** Vientitilassa tasot valitaan ArcGIS Pron omalla monitasovalitsimella aktiivisesta kartasta tai selaamalla. Vienti noudattaa tason valintaa ja määrityskyselyä (definition query) kuten ArcGISin omat työkalut: vain kartalla näkyvät tai valitut kohteet viedään, ja loki kertoo rajauksesta.
- **Kohdekoordinaatisto viennissä:** Vientiin voi valita koordinaatiston, johon aineisto muunnetaan: ETRS-TM35FIN, ETRS-GK19–GK31 (esim. EUREF-FIN / ETRS-GK23), KKJ-kaistat, WGS 84 tai Web Mercator. Muunnos koskee GPKG-, Shapefile-, GeoJSON-, DWG- ja DXF-vientiä; KML/KMZ on standardin mukaan aina WGS84. Oletus on **Tason oma**, ja GeoJSON viedään ilman valintaa WGS84:ään kuten ennenkin. Usean tason viennissä jokainen taso säilyttää oman koordinaatistonsa ("Tason oma"), eikä tasoja projisoida ensimmäisen tason koordinaatistoon. Yhteen DWG/DXF-tiedostoon mahtuu vain yksi koordinaatisto, joten eri koordinaatistoissa olevat tasot vaativat joko kohdekoordinaatiston tai oman tiedoston jokaiselle tasolle; muuten vienti pysähtyy ja kertoo tämän.
- **Tyyli mukaan:** Valinta **Pakkaa tasojen tyylit mukaan** (oletuksena päällä). GeoPackage- ja Shapefile-viennin viereen kirjoitetaan tason symbologia `.lyrx`-tasotiedostona (GeoPackagessa `<tiedosto>_<taso>.lyrx`), joka viittaa viedyn tiedoston dataan suhteellisella polulla. KML/KMZ saa tyylin ArcGISin KML-viennistä. GeoJSONille ei ole tyylistandardia, eikä DWG/DXF-vienti kirjoita symbologiaa.
- **Tyyli tuonnissa:** Kun tuotavan Shapefilen tai GeoPackagen vieressä on sen tyylitiedosto (`<tiedosto>.lyrx` tai GeoPackagessa `<gpkg>_<taso>.lyrx`, kuten Muuntajan vienti ne nimeää), tuotu taso saa kartalle saman symbologian automaattisesti. ArcGIS Pro ei itse etsi tyylitiedostoa aineiston vierestä; ilman Muuntajaa lisää kartalle `.lyrx`-tiedosto, joka tuo aineiston tyyleineen.
- **Monitasoviennin paketointi:** Shapefile-, GeoJSON- ja KML/KMZ-viennit tehdään aina omiksi tiedostoiksi tasoittain. GPKG-, DWG- ja DXF-vienneissä voi valita yhden yhteisen tiedoston tai oman tiedoston jokaiselle tasolle.
- **Selkeä CAD-vienti:** DWG/DXF-vientiin kirjoitetaan vain valittujen tasojen geometriat. Labeltekstejä tai erillisiä attribuuttitaulukoita ei muodosteta.
- **Hallittu karttasisältö:** Vienti kirjoittaa vain tiedostot eikä lisää vientituloksia aktiiviselle kartalle. Tuonti lisää muunnetut aineistot normaalisti työtilaan.
- **Integrointi ArcGIS Prohon:** Laajennus lisää ArcGIS Pron käyttöliittymään oman välilehden / painikkeen (Muuntaja), josta työkalun saa nopeasti auki.
- **Python-työkalulaatikko:** Sisältää `Muuntaja.pyt`-työkalulaatikon geokäsittelytehtäviä varten.

## Asennus
1. Varmista, että sinulla on ArcGIS Pro (vähintään versio 3.5) asennettuna.
2. Lataa uusin [Muuntaja.esriAddInX](https://github.com/roopepalom44/muuntaja/releases/latest/download/Muuntaja.esriAddInX) ([kaikki julkaisut](https://github.com/roopepalom44/muuntaja/releases)).
3. Sulje ArcGIS Pro ja asenna `.esriAddInX`-tiedosto kaksoisklikkaamalla sitä, jolloin se asentuu ArcGIS Pron Add-In -kansioon.

### Automaattiset GitHub-julkaisut

Julkaisut tehdään ainoastaan GitHub Actionsilla. Työnkulku
`.github/workflows/addin-release.yml` ajaa jokaisessa pull requestissa ja
`main`-pushissa ensin yksikkötestit (myös QGIS-lisäosan testit QGISin
Python-kirjastoilla) ja lint-tarkistuksen. Vasta kun ne menevät läpi,
`main`-push kääntää ja paketoi AddInX:n ja QGIS-lisäosan sekä luo
GitHub-releasen, jonka liitteinä ovat `Muuntaja.esriAddInX`, versioidut
QGIS-ZIPit sekä vakionimiset `Muuntaja-QGIS.zip` ja `Muuntaja-QGIS-Windows.zip`.
Paketin versio muodostuu `Config.daml`-version ja GitHub-ajon numeron
perusteella, joten jokaisella pushilla on yksilöllinen versio.

Työnkulku kääntää virallisilla ArcGIS Pro 3.5 SDK -viitteillä
`Esri.ArcGISPro.Extensions30` NuGet-paketista `3.5.0.57366`; Pro 3.5 on myös
AddInX:n vähimmäisversio. Runnerille ei tarvitse asentaa ArcGIS Prota.
GitHub Actionsin pitää sallia työnkulun `GITHUB_TOKEN`-oikeus `contents: write`,
jotta se voi luoda releasen.

Uusin AddInX on saatavilla suoraan osoitteesta
<https://github.com/roopepalom44/muuntaja/releases/latest/download/Muuntaja.esriAddInX>.

### Paikallinen käännös ja testit (kehittäjille)

AddInX:n voi kääntää ja paketoida paikallisesti ilman julkaisua:

```powershell
powershell -ExecutionPolicy Bypass -File .\build-addin.ps1 -Configuration Release
```

Skripti käyttää .NET 8 SDK:ta, täyttä MSBuildia ja virallista Pro 3.5 NuGet
-pakettia. Testit ajetaan komennolla `python -m unittest discover -s tests`;
QGIS-testit ajetaan, kun Python löytää QGISin kirjastot (muuten ne ohitetaan).

## Käyttö
1. Käynnistä ArcGIS Pro.
2. Siirry Add-In (tai Muuntaja) -välilehdelle.
3. Klikkaa **Muuntaja**-painiketta avataksesi työkalun.
4. Valitse tuonnissa joko tiedostoja tai kansio. Kansiota käytettäessä kansioon voi kerätä eri muotoja sekaisin; Muuntaja skannaa myös alikansiot, ohittaa Shapefilen sivutiedostot (DBF/SHX/PRJ) ja tuo jokaisen varsinaisen aineiston erikseen.
5. Valitse viennissä tasot ArcGIS Pron monitasovalitsimella ja määritä vientiformaatti, vientikansio ja tarvittaessa kohdekoordinaatisto. Usean tason GPKG-, DWG- tai DXF-viennissä valitse lisäksi yhteinen tai tasokohtainen tiedosto.
6. CAD-vienti vie valitut tasot DWG/DXF-tiedostoon geometrioina ilman labeltekstejä tai erillisiä attribuuttitaulukoita.

## Rasterit (esim. MML:n taustakarttasarja)

MML:n tiedostopalvelusta ladatut karttalehdet tulevat syvään kansiorakenteeseen,
esim. `Maanmittauslaitos_Tiedostopalvelu_REST-…/taustakarttasarja_jhs180/taustakartta_20k/4m/etrs89/png/R4/R43/R4324.png`.
Anna tuonnissa pelkkä yläkansio (esim. `Downloads\rasterit`), niin Muuntaja:

- etsii kaikki rasterit alikansioineen; PNG/JPG otetaan mukaan vain, jos
  vieressä on world-tiedosto (`.pgw`, `.jgw`, `.wld`) tai `.aux.xml`
- luo aktiiviseen karttaan ryhmätason jokaiselle `taustakartta_`-kansiolle
  (`taustakartta_20k`, `taustakartta_5k` …). GDB-kohteella ja ArcGIS Pro
  Standard/Advanced -lisenssillä kaikki ryhmän karttalehdet lisätään yhdellä
  eräoperaatiolla mosaiikkiaineistoon ja kartalle tulee vain yksi taso ryhmää
  kohti. Basic-lisenssillä tai kansiokohteella karttalehdet lisätään ryhmään
  yksittäisinä tasoina. Eri latauksista tulevat saman nimiset ryhmät
  yhdistetään, ja tarkin mittakaava jää sisällysluettelossa ylimmäksi
- määrittää koordinaatiston rasterille, jolta se puuttuu (MML:n PNG:t):
  ensisijaisesti world-tiedoston koordinaateista (TM35FIN, GK-kaistat, KKJ),
  sitten kansiopolusta (`etrs89` → ETRS-TM35FIN). Lähtökoordinaatisto-valinnalla
  voi pakottaa koordinaatiston. Mosaiikkituonnissa CRS annetaan koko erälle;
  yksittäistuonnissa määritys kirjoittaa `.aux.xml`-tiedoston rasterin viereen
- ohittaa karttalehdet, jotka ovat jo samassa ryhmässä, joten uudelleenajo ei tuplaa niitä

Jos rasterit eivät ole `taustakartta_`-kansiossa, ryhmä nimetään syötekansion
ensimmäisen alikansion mukaan (MML:n latauskohtainen kansio ohitetaan).
Rasterit lisätään **viittauksina alkuperäisiin tiedostoihin** eikä niitä
kopioida tallennuspaikkaan, joten latauskansio kannattaa siirtää pysyvään
paikkaan ennen tuontia.

## Suorituskyky ja virheensieto

- **Eräajo ei enää kaadu ensimmäiseen virheeseen.** Aiemmin yksi rikkinäinen
  tiedosto keskeytti koko kansiotuonnin, jolloin sen jälkeiset tiedostot jäivät
  käsittelemättä. Nyt virhe kirjataan varoituksena, käsittely jatkuu seuraavaan
  tiedostoon, ja ajon lopussa kerrotaan `n/m onnistui` sekä luettelo
  epäonnistuneista. Ajo merkitään virheelliseksi vain jos yksikään kohde ei
  onnistunut. Sama koskee monitasovientiä.
- **DFSU-geometria kirjoitetaan WKB-tavuina.** Aiemmin jokaiselle elementille
  rakennettiin `arcpy.Array` ja erilliset `arcpy.Point`-oliot; miljoonan
  elementin meshissä se tarkoitti miljoonia COM-rajapinnan yli meneviä olioita.
  `SHAPE@WKB` ohittaa koko olioketjun. Yksittäinen viallinen elementti
  ohitetaan varoituksella sen sijaan että se kaataisi tuonnin.
- **DFSU kirjoitetaan kerran, ei kahdesti.** Kun kohde on file geodatabase eikä
  projisointia tarvita, taso kirjoitetaan suoraan lopulliseen sijaintiin
  välikopion sijaan. Keskeytynyt ajo ei jätä puolikasta tasoa kohteeseen.
- **DFSU-attribuutit poimitaan listoina.** numpy-taulukon indeksointi palauttaa
  boksatun skalaarin joka kutsulla; `.tolist()` kerran ennen silmukkaa on
  selvästi halvempaa kuin miljoona indeksointia.
- **DFSU-insertti käyttää samoja GP-asetuksia kuin CAD-polku**
  (`autoCommit`, `maintainSpatialIndex=False`, `buildStats=NONE`,
  `parallelProcessingFactor`). Asetukset palautetaan ajon jälkeen, joten tila ei
  vuoda seuraavaan tiedostoon.
- **Monitasoviennin GeoJSON-, Shapefile- ja KML/KMZ-haarat on yhdistetty**
  yhdeksi kierrokseksi formaattikohtaisella dispatchilla kolmen identtisen
  silmukan sijaan.
- **Tyhjä tuonti on virhe.** Jos tiedostosta ei saada yhtään kohdetta (tyhjä
  GeoJSON/GPKG/KML/GPX/CAD tai DFSU-suodatin ilman osumia) tai tason
  tallennus epäonnistuu, tiedosto näkyy yhteenvedossa epäonnistuneena eikä
  onnistuneena.
- **Kansioskannaus ohittaa muut kuin paikkatieto-JSONit** (esim. asetus- ja
  metatietotiedostot), ja kansiopuu käydään läpi vain kerran validointia ja
  ajoa kohden.
- **CAD-tuonnin tunnistettu koordinaatisto tallentuu tulokseen** myös silloin,
  kun kohde-CRS puuttuu tai on sama kuin lähde.
- **CAD-tuonti kohde-CRS:llä projisoi jokaisen tason suoraan.** Tunnistettu
  lähtökoordinaatisto annetaan jo CAD-muunnokselle, joten ArcGIS ei enää hylkää
  projisointia (ERROR 000289/000599) eikä tuonti kierrä hitaan varaketjun kautta.
  Aiemmin varaketju kirjoitti tulokset nimellä `<taso>_proj`, ja DWG:n toinen
  saman geometriatyypin taso ylikirjoitti ensimmäisen.

## mikeio ja DFSU-tuki

DFSU-tuonti vaatii `mikeio`-kirjaston ArcGIS Pron Python-ympäristöön. Suositeltu
asennustapa on kerran kloonattuun ympäristöön:

```
conda install -c conda-forge mikeio
```

Työkalu **ei asenna kirjastoa ajon aikana.** Ajonaikainen `pip install`
muuttaisi ArcGIS Pron jaettua Python-ympäristöä huomaamatta, kestäisi minuutteja
ja epäonnistuisi lukitulla työasemalla. Jos `mikeio` puuttuu, vain
DFSU-tiedostot epäonnistuvat asennusohjeen kanssa; eräajon muut tiedostot
tuodaan normaalisti.

DFSU:n lähtökoordinaatisto luetaan tiedoston projektiosta (`LONG/LAT` =
WGS84) tai päätellään Suomen koordinaateista. Jos sitä ei tunnisteta
(esim. `NON-UTM`), valitse **Lähtökoordinaatisto**; kohde-CRS:ää ei koskaan
käytetä arvauksena lähteen koordinaatistoksi.

Jos `mikeio` puuttuu, DFSU-suodattimen sarakelista on tyhjä ja dialogi kertoo
syyn. Aiemmin lista täytettiin binääriheaderista arvatuilla nimillä ja viime
kädessä keksityillä kentillä (`Element ID`, `X`, `Y`, `Z`), joista valittu
suodatin ei osunut koskaan mihinkään.

## Tekninen kuvaus
- **Kehitysympäristö:** .NET 8.0 (WPF), C#
- **ArcGIS Pro SDK:** 3.5.0
- **Kehittäjä:** Roope Palomaa

Katso tarkemmat käyttöohjeet projektin mukana tulevasta manuaalista:
- `Muuntaja_User_Manual.pdf` tai `.docx`
