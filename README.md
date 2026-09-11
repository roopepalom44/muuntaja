# Muuntaja

**Muuntaja** on ArcGIS Pro Add-In -laajennus, joka on suunniteltu helpottamaan erilaisten tiedostomuotojen (kuten CAD, GPX, KML jne.) tuomista ja viemistä ArcGIS Pro -ympäristössä. Se tarjoaa käyttäjäystävällisen käyttöliittymän aineistojen nopeaan kääntämiseen ja siirtämiseen.

## Ominaisuudet
- **Tiedostojen muuntaminen:** Tuo CAD-, GPKG-, Shapefile-, GeoJSON-, GPX-, KML/KMZ- ja DFSU-aineistoja suoraan projektiin.
- **Kansiotuonti:** Anna tuonnissa yhden kansion polku. Muuntaja käy kansion ja sen alikansiot läpi, tunnistaa kaikki tuetut tiedostomuodot ja lisää muunnetut tasot työtilaan.
- **Tasovalinta viennissä:** Vientitilassa tasot valitaan ArcGIS Pron omalla monitasovalitsimella aktiivisesta kartasta tai selaamalla.
- **Monitasoviennin paketointi:** Shapefile-, GeoJSON- ja KML/KMZ-viennit tehdään aina omiksi tiedostoiksi tasoittain. GPKG-, DWG- ja DXF-vienneissä voi valita yhden yhteisen tiedoston tai oman tiedoston jokaiselle tasolle.
- **Tasokohtaiset CAD-taulukot:** DWG/DXF-viennissä attribuuttitaulukko kytketään päälle erikseen halutuille tasoille. Taulukkoon otetaan kaikki tulostuskelpoiset kentät, jokaiselle tasolle muodostuu oma nimetty taulukko ja saman CAD-tiedoston taulukot sijoitetaan vierekkäin.
- **Tasokohtaiset CAD-tekstit:** Jokaiselle DWG/DXF-vientitasolle voi kytkeä tekstiviennin erikseen ja valita juuri kyseisen tason labelkentän.
- **Hallittu karttasisältö:** Vienti kirjoittaa vain tiedostot eikä lisää vientituloksia aktiiviselle kartalle. Tuonti lisää muunnetut aineistot normaalisti työtilaan.
- **Integrointi ArcGIS Prohon:** Laajennus lisää ArcGIS Pron käyttöliittymään oman välilehden / painikkeen (Muuntaja), josta työkalun saa nopeasti auki.
- **Python-työkalulaatikko:** Sisältää `Muuntaja.pyt`-työkalulaatikon geokäsittelytehtäviä varten.

## Asennus
1. Varmista, että sinulla on ArcGIS Pro (vähintään versio 3.5) asennettuna.
2. Käännä projekti Visual Studiossa (esim. `Muuntaja.sln`).
3. Asenna `.esriAddinX`-tiedosto kaksoisklikkaamalla sitä, jolloin se asentuu ArcGIS Pron Add-In -kansioon.

## Käyttö
1. Käynnistä ArcGIS Pro.
2. Siirry Add-In (tai Muuntaja) -välilehdelle.
3. Klikkaa **Muuntaja**-painiketta avataksesi työkalun.
4. Valitse tuonnissa joko tiedostoja tai kansio. Kansiota käytettäessä kansioon voi kerätä eri muotoja sekaisin; Muuntaja skannaa myös alikansiot, ohittaa Shapefilen sivutiedostot (DBF/SHX/PRJ) ja tuo jokaisen varsinaisen aineiston erikseen.
5. Valitse viennissä tasot ArcGIS Pron monitasovalitsimella ja määritä vientiformaatti sekä vientikansio. Usean tason GPKG-, DWG- tai DXF-viennissä valitse lisäksi yhteinen tai tasokohtainen tiedosto.
6. CAD-viennin tekstit valitaan tasokohtaisilta riveiltä: kytke **Vie tekstit** halutuille tasoille ja valitse niiden omat labelkentät. Attribuuttitaulukoissa riittää tasokohtainen **Luo attribuuttitaulu** -valinta; kaikki käyttökelpoiset kentät otetaan mukaan automaattisesti.

## Tekninen kuvaus
- **Kehitysympäristö:** .NET 8.0 (WPF), C#
- **ArcGIS Pro SDK:** 3.5.0
- **Kehittäjä:** Roope Palomaa

Katso tarkemmat käyttöohjeet projektin mukana tulevasta manuaalista:
- `Muuntaja_User_Manual.pdf` tai `.docx`
