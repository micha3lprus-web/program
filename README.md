# StadoVet

Polska aplikacja do pracy lekarza weterynarii z gospodarstwami utrzymującymi bydło. Pierwsza wersja dla jednego stanowiska: FastAPI, SQLite i interfejs przeglądarkowy bez zewnętrznych skryptów, fontów i usług frontendowych.

## Instalator Windows bez instalowania Pythona

Gotowy plik: `dist/StadoVet-Setup-0.1.0-win64.exe` — Windows 10/11, x64. Instalator zawiera prywatny runtime Pythona 3.13.17 i wszystkie biblioteki, działa offline i nie wymaga administratora. Nie zmienia systemowego Pythona ani PATH. Po instalacji uruchom skrót **StadoVet** na pulpicie. Program otworzy domyślną przeglądarkę; serwer pozostaje lokalny. Zamknięcie karty nie zatrzymuje serwera — służy do tego **Start → StadoVet → Zatrzymaj StadoVet**. Nie ma automatycznego startu przy logowaniu.

Pliki programu: `%LOCALAPPDATA%\Programs\StadoVet`. Baza, logi i stan procesu: `%LOCALAPPDATA%\StadoVet`. Aktualizacja zatrzymuje działający serwer, a aktualizacja i odinstalowanie zachowują bazę. Zapisz formularze przed aktualizacją. Do przeniesienia danych zatrzymaj program i skopiuj cały folder danych. Instalator nie zawiera danych z chmury, fikcyjnej bazy ani kluczy API. Ograniczenia funkcji AI, źródeł i wdrożenia opisane poniżej obowiązują także w wersji Windows.

Instalator nie jest podpisany certyfikatem wydawcy. Plik `.exe.sha256` obok instalatora podaje jego sumę kontrolną. Test zgodności pod Wine obejmuje instalację, dołączony interpreter Windows, SQLite, API, pojedynczą instancję, aktualizację, zatrzymywanie oraz zachowanie bazy po deinstalacji; nie zastępuje testu na fizycznym Windows.

Odtwarzalny proces budowania: `packaging/windows/build.py` (Python z httpx, pip i NSIS 3.11 z obsługą `amd64-unicode`). Przykład: `.venv/bin/python packaging/windows/build.py --makensis /ścieżka/do/makensis`. Dla NSIS rozpakowanego poza systemem ustaw `NSISDIR` na katalog zasobów NSIS. Skrypt weryfikuje oficjalny runtime PSF z NuGet przez przypięty SHA-512 i każdą bibliotekę przez SHA-256 z metadanych PyPI, następnie buduje instalator offline. Manifest składników i ich sum jest dołączony do instalacji. Dane, `.venv`, testy i sekrety nie są kopiowane do pakietu. Kod aplikacji i licencje bibliotek pozostają w instalacji.

## Uruchomienie

Wymagany Python 3.12 i dostęp do PyPI podczas instalacji.

```bash
cd /workspace/program
bash scripts/install.sh
bash scripts/start.sh
```

Serwer słucha lokalnie na porcie **8000**. Test gotowości: `curl --fail http://127.0.0.1:8000/api/health`. Port zmienisz przez `VET_PORT`. Dokumentacja API znajduje się pod ścieżką `/docs`. Do kolejnych zadań używaj istniejącego checkoutu; środowisko jest już izolowane i nie potrzebuje dodatkowego worktree.

## Funkcje

- Gospodarstwa z kierunkiem hodowli, województwem, miejscowością i kontaktami; edycja kartoteki.
- Bydło: unikalny, normalizowany numer kolczyka, imię, rasa, płeć, data urodzenia, status, notatki oraz karta historii leczenia i wizyt. Rejestr można przeszukiwać i filtrować.
- Wizyty dla całego gospodarstwa lub konkretnego zwierzęcia: planowanie, edycja i zakończenie. Backend sprawdza przynależność zwierzęcia do gospodarstwa.
- Faktyczne podania leków z rozpoznaniem lekarza, dawką, drogą podania, lekarzem i odrębną karencją na mleko i mięso. Karencja trwa wpisaną liczbę pełnych 24-godzinnych dni od czasu podania. Nie ma automatycznego doboru leków ani dawek. Przy kuracji wielodniowej dodawaj wpis dla każdego podania; program zachowuje najdłuższą aktywną karencję ze wszystkich wpisów zwierzęcia. Dla okresów wyrażonych w godzinach lub udojach ta wersja nie oblicza terminu — nie zastępuj ich zaokrągleniem bez decyzji lekarza.
- Sygnały regionalne: pomorskie, warmińsko-mazurskie i podlaskie. Ręczne dodawanie publicznych odnośników, opis problemu, kategoria i udokumentowana ocena materiału. Status „Oceniono” nie jest potwierdzeniem ogniska choroby.
- Eksport CSV z ochroną przed formułami w arkuszach. Eksport nie jest kopią zapasową całej aplikacji.
- Opcjonalne fikcyjne dane pokazowe. Ładują się tylko do pustej bazy gospodarstw i są oznaczone `[DEMO]`. Usunięcie danych pokazowych usuwa również wszystkie później dopisane zwierzęta, wizyty i leczenie w tych gospodarstwach. Nie dodawaj prawdziwych danych do gospodarstw demonstracyjnych.

Program nie wysyła zgłoszeń do IRZplus, nie realizuje recept, faktur ani urzędowego potwierdzania chorób. Nie prowadzi jeszcze rejestru przemieszczeń; gospodarstwo zwierzęcia jest niezmienne. Wpisy leczenia są dopisywane i nie mają edycji/usuwania w interfejsie tej wersji.

## Agent AI

Bez klucza działa wyraźnie oznaczony **pomocnik lokalny**: odpowiedzi regułowe o obsłudze programu i faktycznych liczbach/wizytach z bazy. Nie jest to model językowy.

Pełny agent korzysta z OpenAI Chat Completions i narzędzia `read_records` do odczytu gospodarstw, zwierząt, wizyt, podsumowania i sygnałów. Wyniki narzędzi zawierają wybrane rekordy, bez pól właściciela i telefonu. Agent nie zapisuje zmian; wskazuje formularze. Nie przegląda internetu poza materiałami zgromadzonymi przez kolektor. Odpowiedzi modelu wymagają oceny użytkownika.

Ustaw bezpiecznie **`VET_AI_API_KEY`** w ustawieniach środowiska, z docelową domeną `api.openai.com`, następnie zastosuj ustawienia i uruchom ponownie proces. Nie wpisuj sekretu do repozytorium, formularza ani czatu. Opcjonalne **`VET_AI_MODEL`** zmienia model (domyślnie `gpt-4.1-mini`). W środowisku bez proxy zmienna musi zawierać rzeczywisty klucz API.

Przy włączonym AI wiadomości, ograniczona historia rozmowy i dane odczytane narzędziami są wysyłane do OpenAI. Parametr `store` jest ustawiony na `false`; nie oznacza to braku przetwarzania danych przez dostawcę. Nie podawaj zbędnych danych osobowych. Awaria lub brak autoryzacji modelu jest jawnie oznaczany przejściem na pomocnika lokalnego. Historia rozmowy pozostaje w pamięci karty przeglądarki i znika po odświeżeniu.

## Publiczne źródła i monitoring

Kolektor obsługuje publiczne strony:

| Źródło | Adres | Typ |
|---|---|---|
| GIW | `https://www.wetgiw.gov.pl/main/komunikaty` | urzędowy |
| Agrofoto | `https://www.agrofoto.pl/forum/` | forum hodowców |
| Farmer | `https://www.farmer.pl/produkcja-zwierzeca/bydlo-i-mleko/` | portal branżowy |

Zbiera maksymalnie 40 pasujących **tytułów i odnośników z jednej strony źródłowej**, bez pobierania treści wątków, profili, autorów, logowania, formularzy czy wysyłania wiadomości. To ograniczony przegląd, nie pełne badanie forów ani statystyka zachorowalności. Nowe lub głębiej ukryte wątki mogą nie pojawić się na stronie źródłowej. Parser HTML może wymagać dostosowania przy zmianie portalu.

Każdy odczyt sprawdza `robots.txt`; odmowa lub niepewny wynik blokuje pobranie. Brak pliku (404) dopuszcza odczyt. Nie obchodzimy blokad, CAPTCHA ani ograniczeń dostępu. Limity: 2 MB na odpowiedź, maks. 3 przekierowania, tylko ustalone hosty HTTPS, co najmniej 15 minut między ręcznymi seriami. `Crawl-delay` powyżej 30 sekund powoduje pominięcie źródła. Podstawowa redakcja telefonów i adresów e-mail w tytułach nie jest pełnym systemem anonimizacji; nie dodawaj danych osobowych do opisów.

Region rozpoznawany jest po wzmiance w tytule (województwo lub wybrane miasta/powiaty), z jawnym zastrzeżeniem konieczności sprawdzenia. Materiały bez rozpoznanego regionu pozostają w oddzielnym kontekście „ogólnopolskie / nieustalone”. Data „odczyt” jest czasem zebrania, nie datą publikacji. Każdy materiał, również urzędowy, początkowo wymaga oceny. Pusta lista nie dowodzi braku chorób.

`scripts/start.sh` włącza monitoring przy starcie i co 6 godzin. **`VET_AUTO_COLLECT=0`** go wyłącza. Uruchamiaj jeden proces Uvicorn (bez wielu workerów), aby nie dublować harmonogramu. Przycisk „Sprawdź źródła” uruchamia tę samą procedurę. Wyniki prób, w tym błędy, są widoczne w „Źródła i ustawienia”. Przy braku dostępu można dodawać odnośniki ręcznie.

W chmurze potrzebne są domeny `www.wetgiw.gov.pl`, `www.agrofoto.pl`, `www.farmer.pl` i opcjonalnie `api.openai.com`. Nie musisz nadawać nieograniczonego dostępu do internetu. Początkowa weryfikacja tego środowiska wykazała odmowę proxy dla źródeł; domeny zapisano w szkicu konfiguracji, ale rzeczywisty odczyt trzeba ponowić po zastosowaniu ustawień. Nie zgromadzono ani nie wymyślono aktualnych doniesień o chorobach.

## Dane i ograniczenia wdrożenia

Baza jest trwale zapisywana w `data/vet.db` (opcjonalnie **`VET_DATABASE`**), poza repozytorium Git. Transakcje SQLite, klucze obce i dziennik zmian chronią spójność. Zapisane dane są danymi jednego stanowiska, bez separacji użytkowników.

**Ta wersja działa lokalnie i nie ma logowania, uprawnień, szyfrowania bazy ani mechanizmu odzyskiwania hasła.** Serwer domyślnie słucha tylko na `127.0.0.1`, ma kontrolę hosta i pochodzenia zapisów oraz politykę CSP. Nie wystawiaj go publicznie ani nie wprowadzaj danych osobowych do publicznego wdrożenia. Przed wdrożeniem dla gabinetu potrzebne są uwierzytelnianie, role, HTTPS, kopie, procedury ochrony danych, historia korekt dokumentacji i przegląd kliniczny. `VET_ALLOWED_HOST` służy wyłącznie do jawnego skonfigurowania zaufanego hosta lokalnego środowiska; samo jego ustawienie nie zapewnia bezpieczeństwa wdrożenia.

Przykład spójnej kopii podczas pracy (SQLite Backup API):

```bash
mkdir -p /workspace/backups
.venv/bin/python - <<'PY'
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import os
name = datetime.now(timezone.utc).strftime('stadovet-%Y%m%dT%H%M%S%fZ.sqlite3')
with sqlite3.connect(os.environ.get('VET_DATABASE', 'data/vet.db')) as source:
    with sqlite3.connect(Path('/workspace/backups') / name) as target:
        source.backup(target)
print('Utworzono kopię bazy.')
PY
```

Kopia zawiera dane gospodarstw; przechowuj ją prywatnie. Odtwarzanie wykonuj przy zatrzymanym serwerze, po zachowaniu kopii bieżących plików bazy. Kopie w tej samej maszynie nie zastępują kopii poza środowiskiem.

## Testy

```bash
.venv/bin/python -m pytest -q
node --check vetapp/static/app.js
```

Testy API używają oddzielnej bazy tymczasowej, obejmują powiązania stada, daty, karencje, historię, eksport, usuwanie tylko danych demonstracyjnych i ochronę pochodzenia zapisów. Testy kolektora i dostawcy AI używają kontrolowanych odpowiedzi HTTP; nie dowodzą działającego dostępu do zewnętrznych serwisów.

Test przeglądarkowy uruchamia własny serwer i Chromium (`chromium`, `google-chrome` lub `CHROMIUM_PATH`), przechodzi przez rzeczywiste formularze, leczenie, wizytę, ocenę sygnału, pomocnika i ekran mobilny. Jeżeli Chromium nie jest zainstalowany, zainstaluj przeglądarkę Playwright przez `.venv/bin/python -m playwright install chromium` (może wymagać bibliotek systemowych). Zrzuty z fikcyjnymi danymi trafiają do ignorowanego `test-results/`.
