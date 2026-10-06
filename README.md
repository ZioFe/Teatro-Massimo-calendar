# Teatro Massimo – Calendario Turno Prime

Calendario iCalendar automatico del **Turno Prime – Opere e Balletti 2026/27** del Teatro Massimo di Palermo.

## Abbonamento al calendario

URL stabile:

https://raw.githubusercontent.com/ZioFe/Teatro-Massimo-calendar/main/teatro-massimo.ics

Su iPhone: Calendario → Calendari → Aggiungi calendario → Aggiungi calendario in abbonamento, quindi incolla l'URL.

## Aggiornamento

GitHub Actions esegue `update_calendar.py` ogni 6 ore e manualmente su richiesta. Lo script legge la pagina ufficiale del Turno Prime e aggiorna il file solo quando i dati cambiano.

Fonte principale: https://www.teatromassimo.it/biglietteria/turno-prime/

Per ogni evento include, quando disponibile sul sito ufficiale: data, ora, tipologia, struttura/atti, durata, luogo e link ufficiale. La durata non viene stimata.

### Sicurezza

Se l'estrazione dal sito ufficiale risulta incompleta, lo script termina con errore e non sovrascrive il calendario esistente. Gli UID non dipendono da data e ora, così una variazione aggiorna l'evento già presente invece di crearne un duplicato.

Progetto indipendente da `Palermo-calendar`.
