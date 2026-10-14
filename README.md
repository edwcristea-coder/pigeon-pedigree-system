# EDW Pigeons – aplicație web

## Railway
1. Publică aceste fișiere în rădăcina repository-ului GitHub `pigeon-pedigree-system`.
2. Conectează repository-ul la serviciul Railway și atașează baza PostgreSQL.
3. În Railway > serviciul web > Variables configurează:
   - `DATABASE_URL` = referință la variabila `DATABASE_URL` a serviciului Postgres (de exemplu `${{Postgres.DATABASE_URL}}` în interfața Railway).
   - `SECRET_KEY` = șir aleatoriu lung (cel puțin 32 de caractere).
   - `APP_USERNAME` = `edwcristea`.
   - `APP_PASSWORD_HASH` = hash PBKDF2 obținut local, vezi mai jos.
4. Build automat din `requirements.txt`, start din `Procfile`; generează domeniul public din Networking.

## Generare hash parolă (pe calculatorul personal)
Rulează Python și execută:
```
import hashlib, secrets, getpass
salt=secrets.token_bytes(16)
pw=getpass.getpass('Parola: ')
print(salt.hex()+'$'+hashlib.pbkdf2_hmac('sha256',pw.encode(),salt,260000).hex())
```
Copiază doar rezultatul în `APP_PASSWORD_HASH`. Nu pune parola sau cheia secretă în GitHub.

## Date și backup
Tabele PostgreSQL: `pigeons` și `revisions`. La fiecare adăugare/editare se salvează în aceeași tranzacție o revizie JSON. Aceasta este istoric intern, **nu backup independent**. Butonul Export backup descarcă datele și reviziile în JSON. Pentru copii independente automate trebuie configurat separat un job cu destinație externă, de exemplu object storage; nu este încă implementat. Restaurarea automată nu este implementată.

## Limitări
PDF se obține cu Print > Save as PDF, nu printr-un generator PDF dedicat. Pedigree-ul afișează patru niveluri (subiect și trei generații de strămoși). Nu sunt încă implementate sigla și setările crescătoriei. Protecție login de bază; înainte de utilizare publică de lungă durată sunt recomandate limitarea încercărilor de login, protecție CSRF și gestionarea securizată a sesiunilor.
