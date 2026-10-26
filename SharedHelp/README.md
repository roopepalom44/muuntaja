# Yhteinen Avaa ohje

Tämä kokonaisuus toimitetaan Suomenväylien, Muuntajan, Liikenneselvityksen ja
Saavutettavuuskarttojen mukana. Ohje on yksi HTML-tiedosto, jonka kuvat ovat
upotettuja: se toimii ilman verkkoyhteyttä eikä tarvitse HTML-palvelinta.

## Ylläpito ja sama ohje kaikissa julkaisuissa

Ohjeen ensisijainen lähde on `roopepalom44/suomenvaylat`, `SharedHelp/`.
Muokkaa siellä `manual.html`-tiedostoa ja kuvia. Nosta `build_manual.py`:n
revision- ja version-arvoa sekä HTML:n näkyvää päiväystä/versionumeroa.
Aja `python SharedHelp/build_manual.py` ja `python SharedHelp/sync.py`.
Älä muuta saman revision sisältöä: uusi sisältö tarvitsee uuden revision.

Vie lähde samalla muihin paikallisiin repoihin:

```powershell
python MUU_REPO/SharedHelp/sync.py --source SUOMENVAYLAT_REPO/SharedHelp
python MUU_REPO/SharedHelp/sync.py --check
```

Muuntajan CI-julkaisu hakee pakettiin tämän ensisijaisen lähteen uusimman valmiin
`index.html`-tiedoston ja `manifest.json`:n ennen käännöstä ja paketointia
(`python SharedHelp/sync.py --fetch`). Liikenneselvityksen ja Saavutettavuuskarttojen
paikalliset julkaisuskriptit tarkistavat lähteen verkosta `--verify-canonical`-valinnalla;
jos sisältö poikkeaa, aja `--fetch`, synkronoi ja commitoi päivitys ennen julkaisua.
Verkkovirhe pysäyttää julkaisun, jotta mukaan ei vahingossa tule eri ohjetta. Suomenväylien
oma julkaisu käyttää oman commitin ohjetta. Julkaise ohjeen lähdemuutos ensin
Suomenväylien main-haaraan, sitten muiden työkalujen julkaisut.

Tavallinen paikallinen rakentaminen toimii ilman verkkoa. Kaikki paketointireitit
tarkistavat ohjeen tiivisteen sekä QGIS-kopioiden yhtenäisyyden. Kun tarvitset
uusimman julkaistun ohjeen paikalliseen pakettiin, aja `--fetch` ensin.
Repojen lähdekopiot pidetään samoina `--source`-komennolla; julkaisuhetken
haku varmistaa pakettien saman HTML-sisällön myös eri julkaisuajankohtina.

## Yksi painike ja version valinta

QGIS: jokainen plugin rekisteröi oman QActioninsa yhteiseen manageriin.
Manageri säilytetään Python-tulkin yhteisessä `sys.modules`-rekisterissä ja
ikkuna tunnistetaan C++-osoitteella, koska SIP voi palauttaa samasta ikkunasta
eri Python-kääreet. Rekisteri säilyttää myös painikkeen avauskäsittelijän elossa.
Sama ohjepainike säilyy, kun yksi lisäosa poistetaan käytöstä;
viimeisen poistuessa myös ohjepainike poistuu. Työkalujen järjestys on Suomenväylät,
Muuntaja, Liikenneselvitys, Saavutettavuuskartat, Avaa ohje. Muut QActionit säilyvät.

ArcGIS Pro: erilliset DAML-tunnisteet estävät lisäosien tunnistetörmäykset.
Jokainen päivitetty moduuli rekisteröi itsensä AppDomainin yhteiseen BCL-rekisteriin.
DAML-painikkeiden luokat ovat kunkin lisäosan omassa oletusnimiavaruudessa
(`SharedHelpButtons.cs`). ArcGIS lisää oletusnimiavaruuden `className`-arvon
eteen: jaettua apukoodin nimiavaruutta ei saa käyttää DAML:n luokkaviittauksena.
Yhden moduulin vakioryhmät näkyvät kerrallaan. Rekisteröidyt työkalut käyttävät
alkuperäisiä komentojaan, ohjepainike on viimeinen. Muutosten jälkeen käynnistys
uudelleen tarvitaan. Kaikki neljä lisäosaa kannattaa päivittää, jotta myös vanhojen
versioiden alkuperäiset työkaluryhmät korvautuvat yhteisellä järjestyksellä.
Käyttäjän omat ribbon-muokkaukset voivat muuttaa oletusjärjestystä.

Molemmat ohjelmat valitsevat käytössä olevista ohjeista suurimman `revision`-arvon,
eivät tiedoston aikaleimaa tai lisäosan omaa versionumeroa. HTML:n SHA-256 tarkistetaan
ennen avaamista. Rikkinäinen kopio ohitetaan; jos ehjää kopiota ei ole, näytetään virhe.
Asentaminen ei hae verkosta mitään ajon aikana. Uudempi jo asennettu ohje säilyy
valittuna myös vanhemman toisen työkalupaketin asentamisen jälkeen.

## Virhekorjauksen tarkistus 26.10.2026

Paketointi lukee DLL:n CLR-metatiedot `TypeCheck`-aputyökalulla lataamatta
ArcGIS SDK:ta ja vertaa jokaista DAML-luokkaa nimiavaruuksineen oikeaan
tyyppimäärittelyyn. Puuttuva luokka estää paketin valmistamisen; pelkkä luokan
nimen löytyminen DLL:n tekstimerkkijonoista ei riitä.

`test_qgis_help.py` käyttää saman C++-ikkunan eri SIP-kääreitä, pakottaa
roskienkeruun ja napsauttaa ohjepainiketta kaikissa 24 latausjärjestyksessä.
Se tarkistaa oikean HTML-tiedoston, toteuttaneen moduulin poiston ja viimeisen
lisäosan siivouksen. Aiempi toteutus tuotti tässä neljä toimimatonta painiketta.

`test_native_qgis.py` suoritetaan oikean QGIS Desktopin `--code`-parametrilla
erillisessä profiilissa. Se käyttää oikeaa `QgisInterface`-/`QgisApp`-ikkunaa,
lataa saatavilla olevat lisäosat, avaa työkaludialogit ja tarkistaa
ohjepainikkeen avauskutsun. Oletusselaimen käynnistys korvataan vain tässä
testissä tallentavalla tarkistuksella; testattava Qt-painike ja sen käsittelijä
ovat lisäosan oikeita toteutuksia. Kun neljä repoa ovat rinnakkain, testi
käyttää kaikkia neljää. Suomenväylien CI suorittaa myös tämän testin.

## Kuvat ja videot

Kuvien lähteet ja ajankohdat on kerrottu HTML:n lopussa. Uudet QGIS-kuvat
on renderöity oikeista lisäosadialogeista. ArcGIS-esimerkkikuvat ovat aiemmista
kuvallisista ohjeista; käyttöliittymän pieniä eroja on merkitty.

Video voidaan lisätä HTML:n `video controls preload="none"` -elementtinä.
Jotta ohje säilyy yhtenä tiedostona ja toimii offline, MP4/WebM täytyy upottaa
data-URLina samoin kuin kuvat. Suosi lyhyttä, pakattua videota; se kasvattaa jokaisen
asennuspaketin kokoa. Tässä versiossa mukana ovat kuvalliset ohjeet, ei videoita.
