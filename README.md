# Muuntaja

**Muuntaja** on ArcGIS Pro Add-In -laajennus, joka on suunniteltu helpottamaan erilaisten tiedostomuotojen (kuten CAD, GPX, KML jne.) tuomista ja viemistä ArcGIS Pro -ympäristössä. Se tarjoaa käyttäjäystävällisen käyttöliittymän aineistojen nopeaan kääntämiseen ja siirtämiseen.

## Ominaisuudet
- **Tiedostojen muuntaminen:** Tuo CAD-, GPKG-, Shapefile-, GeoJSON-, GPX-, KML/KMZ- ja DFSU-aineistoja suoraan projektiin.
- **Kansiotuonti:** Anna tuonnissa yhden kansion polku. Muuntaja käy kansion ja sen alikansiot läpi, tunnistaa kaikki tuetut tiedostomuodot ja lisää muunnetut tasot työtilaan.
- **Tasovalinta viennissä:** Vientitilassa aktiivisen kartan feature-tasot näkyvät valintaruutulistana, josta vietävät tasot voi rastittaa.
- **Monitasoviennin paketointi:** Shapefile-, GeoJSON- ja KML/KMZ-viennit tehdään aina omiksi tiedostoiksi tasoittain. GPKG-, DWG- ja DXF-vienneissä voi valita yhden yhteisen tiedoston tai oman tiedoston jokaiselle tasolle.
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
5. Valitse viennissä aktiivisen kartan tasot valintaruuduista ja määritä vientiformaatti sekä vientikansio. Usean tason GPKG-, DWG- tai DXF-viennissä valitse lisäksi yhteinen tai tasokohtainen tiedosto.

## Tekninen kuvaus
- **Kehitysympäristö:** .NET 8.0 (WPF), C#
- **ArcGIS Pro SDK:** 3.5.0
- **Kehittäjä:** Roope Palomaa

Katso tarkemmat käyttöohjeet projektin mukana tulevasta manuaalista:
- `Muuntaja_User_Manual.pdf` tai `.docx`
