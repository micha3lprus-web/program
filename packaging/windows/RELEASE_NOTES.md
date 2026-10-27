StadoVet 0.1.0 — pierwsza wersja dla jednego lokalnego stanowiska.

Pobierz `StadoVet-Setup-0.1.0-win64.exe`, uruchom instalator, a potem skrót StadoVet na pulpicie. Alternatywnie pobierz ZIP z instalatorem i instrukcją. Wymagany Windows 10/11, 64-bit. Python i wszystkie biblioteki są dołączone; nie potrzebujesz ich osobnej instalacji, internetu podczas instalacji ani uprawnień administratora.

Program obsługuje kartoteki gospodarstw i bydła, wizyty, leczenie, karencje na mleko i mięso, eksport CSV, asystenta oraz materiały regionalne z publicznych źródeł. Bez klucza API działa oznaczony pomocnik lokalny; pełny AI wymaga własnego klucza i dostępu do dostawcy. Pobieranie materiałów wymaga internetu i jest zależne od dostępności źródeł oraz robots.txt. Nie zebrano ani nie dołączono aktualnych doniesień chorobowych.

Dane: `%LOCALAPPDATA%\StadoVet`. Aktualizacja i odinstalowanie zachowują bazę. Przed aktualizacją zapisz formularze. Zatrzymywanie: Start → StadoVet → Zatrzymaj StadoVet.

Instalator nie zawiera danych gospodarstw ani kluczy API i nie ma podpisu cyfrowego wydawcy. Suma SHA-256 jest dostępna w osobnym pliku. Testy: 27 testów aplikacji, w tym Chromium; instalacja, dołączony interpreter Windows, SQLite, API, pojedyncza instancja, aktualizacja i zachowanie bazy po deinstalacji sprawdzone pod Wine. Nie przeprowadzono jeszcze testu na fizycznym Windows.

To wersja lokalna bez logowania i ról — nie wystawiaj serwera publicznie. Program nie zastępuje decyzji lekarza, nie dobiera dawek i nie ma integracji z IRZplus. Pełna instrukcja znajduje się w instalacji oraz w repozytorium.
