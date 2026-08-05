# Muuntaja

**Muuntaja** on ArcGIS Pro Add-In -laajennus, joka on suunniteltu helpottamaan erilaisten tiedostomuotojen (kuten CAD, GPX, KML jne.) tuomista ja viemistä ArcGIS Pro -ympäristössä. Se tarjoaa käyttäjäystävällisen käyttöliittymän aineistojen nopeaan kääntämiseen ja siirtämiseen.

## Ominaisuudet
- **Tiedostojen muuntaminen:** Tuo CAD-, GPX- ja KML-aineistoja suoraan projektiin.
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
4. Työkalu mahdollistaa tiedostojen (esim. CAD ja KML) lukemisen ja viemisen.

## Tekninen kuvaus
- **Kehitysympäristö:** .NET 8.0 (WPF), C#
- **ArcGIS Pro SDK:** 3.5.0
- **Kehittäjä:** Roope Palomaa, Ramboll

Katso tarkemmat käyttöohjeet projektin mukana tulevasta manuaalista:
- `Muuntaja_User_Manual.pdf` tai `.docx`
