# Muuntaja

**QGIS-versio (esijulkaisu):** [asennus ja nykyinen toiminnallisuus](qgis_plugin/README.md). Ladattava ZIP on [GitHub-julkaisussa](https://github.com/roopepalom44/muuntaja/releases/tag/qgis-v0.2.0).

**Muuntaja** on ArcGIS Pro Add-In -laajennus, joka on suunniteltu helpottamaan erilaisten tiedostomuotojen (kuten CAD, GPX, KML jne.) tuomista ja viemistä ArcGIS Pro -ympäristössä. Se tarjoaa käyttäjäystävällisen käyttöliittymän aineistojen nopeaan kääntämiseen ja siirtämiseen.

## Ominaisuudet
- **Tiedostojen muuntaminen:** Tuo CAD-, GPKG-, Shapefile-, GeoJSON-, GPX-, KML/KMZ- ja DFSU-aineistoja suoraan projektiin.
- **Kansiotuonti:** Anna tuonnissa yhden kansion polku. Muuntaja käy kansion ja sen alikansiot läpi, tunnistaa kaikki tuetut tiedostomuodot ja lisää muunnetut tasot työtilaan.
- **Rasterituonti ryhmiteltynä:** Tuonti tunnistaa myös rasterit (TIFF, JP2, IMG sekä PNG/JPG, joiden vieressä on world-tiedosto kuten `.pgw`). Rasterit lisätään työtilaan ryhmätasoihin lähimmän `taustakartta_`-alkuisen kansion mukaan, joten MML:n latauskansion voi antaa sellaisenaan (ks. alla).
- **Tasovalinta viennissä:** Vientitilassa tasot valitaan ArcGIS Pron omalla monitasovalitsimella aktiivisesta kartasta tai selaamalla.
- **Monitasoviennin paketointi:** Shapefile-, GeoJSON- ja KML/KMZ-viennit tehdään aina omiksi tiedostoiksi tasoittain. GPKG-, DWG- ja DXF-vienneissä voi valita yhden yhteisen tiedoston tai oman tiedoston jokaiselle tasolle.
- **Selkeä CAD-vienti:** DWG/DXF-vientiin kirjoitetaan vain valittujen tasojen geometriat. Labeltekstejä tai erillisiä attribuuttitaulukoita ei muodosteta.
- **Hallittu karttasisältö:** Vienti kirjoittaa vain tiedostot eikä lisää vientituloksia aktiiviselle kartalle. Tuonti lisää muunnetut aineistot normaalisti työtilaan.
- **Integrointi ArcGIS Prohon:** Laajennus lisää ArcGIS Pron käyttöliittymään oman välilehden / painikkeen (Muuntaja), josta työkalun saa nopeasti auki.
- **Python-työkalulaatikko:** Sisältää `Muuntaja.pyt`-työkalulaatikon geokäsittelytehtäviä varten.

## Asennus
1. Varmista, että sinulla on ArcGIS Pro (vähintään versio 3.5) asennettuna.
2. Lataa uusin [Muuntaja.esriAddInX](https://github.com/roopepalom44/muuntaja/releases/latest/download/Muuntaja.esriAddInX) ([kaikki julkaisut](https://github.com/roopepalom44/muuntaja/releases)).
3. Sulje ArcGIS Pro ja asenna `.esriAddInX`-tiedosto kaksoisklikkaamalla sitä, jolloin se asentuu ArcGIS Pron Add-In -kansioon.

### Julkaisun tekeminen (kehittäjille)
Nosta versio `Config.daml`-tiedostossa, commitoi ja pushaa, ja aja sitten:

```powershell
powershell -ExecutionPolicy Bypass -File .\release.ps1
```

Skripti rakentaa Release-version, paketoi sen ja luo GitHub-releasen `v<versio>` (vaatii ArcGIS Pron ja `gh auth login`).

## Käyttö
1. Käynnistä ArcGIS Pro.
2. Siirry Add-In (tai Muuntaja) -välilehdelle.
3. Klikkaa **Muuntaja**-painiketta avataksesi työkalun.
4. Valitse tuonnissa joko tiedostoja tai kansio. Kansiota käytettäessä kansioon voi kerätä eri muotoja sekaisin; Muuntaja skannaa myös alikansiot, ohittaa Shapefilen sivutiedostot (DBF/SHX/PRJ) ja tuo jokaisen varsinaisen aineiston erikseen.
5. Valitse viennissä tasot ArcGIS Pron monitasovalitsimella ja määritä vientiformaatti sekä vientikansio. Usean tason GPKG-, DWG- tai DXF-viennissä valitse lisäksi yhteinen tai tasokohtainen tiedosto.
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

## mikeio ja DFSU-tuki

DFSU-tuonti vaatii `mikeio`-kirjaston ArcGIS Pron Python-ympäristöön. Suositeltu
asennustapa on kerran kloonattuun ympäristöön:

```
conda install -c conda-forge mikeio
```

Työkalu **ei enää asenna kirjastoa automaattisesti oletuksena.** Ajonaikainen
`pip install` muuttaa ArcGIS Pron jaettua Python-ympäristöä, kestää minuutteja
ja epäonnistuu lukitulla työasemalla kesken kaiken. Automaattiasennuksen voi
ottaa käyttöön kertaluonteisesti valinnalla **DFSU: asenna puuttuva
mikeio-kirjasto automaattisesti**, joka näkyy vain kun tuonnissa on
DFSU-tiedostoja.

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
