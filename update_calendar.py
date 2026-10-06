#!/usr/bin/env python3
import hashlib
import html
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo

PRIME_URL = "https://www.teatromassimo.it/biglietteria/turno-prime/"
SEASON_URL = "https://www.teatromassimo.it/la-stagione-2026-27/"
OUT = Path("teatro-massimo.ics")
TZ = ZoneInfo("Europe/Rome")
UA = "Teatro-Massimo-calendar/1.0 (+https://github.com/ZioFe/Teatro-Massimo-calendar)"

MONTHS = {
    "gennaio":1,"febbraio":2,"marzo":3,"aprile":4,"maggio":5,"giugno":6,
    "luglio":7,"agosto":8,"settembre":9,"ottobre":10,"novembre":11,"dicembre":12
}
FORMS = {
    "Samson et Dalila": ("Opera", "Opéra in tre atti e quattro quadri"),
    "Biancaneve": ("Balletto", "Balletto in tre atti"),
    "Non dirmi che hai paura": ("Spettacolo", None),
    "Macbeth": ("Opera", "Melodramma in quattro atti"),
    "Lucia di Lammermoor": ("Opera", "Dramma tragico in tre atti"),
    "Il grande Gatsby": ("Balletto", "Balletto"),
    "Tosca": ("Opera", "Melodramma in tre atti"),
    "Falstaff": ("Opera", "Commedia lirica in tre atti"),
    "Sylvia": ("Balletto", "Balletto in tre atti"),
    "Die Zauberflöte": ("Opera", "Singspiel in due atti"),
    "Balanchine – Čajkovskij": ("Danza", "Spettacolo di danza"),
    "Ernani": ("Opera", "Dramma lirico in quattro parti"),
    "Carmen": ("Opera", "Opéra-comique in quattro atti"),
    "Lo schiaccianoci": ("Balletto", "Balletto in due atti"),
}

def get(url):
    r=requests.get(url,headers={"User-Agent":UA},timeout=30)
    r.raise_for_status()
    return r.text

def norm(s):
    return re.sub(r"\s+"," ",html.unescape(s or "")).strip()

def parse_prime(page):
    soup=BeautifulSoup(page,"html.parser")
    events=[]
    rx=re.compile(
        r"(?:lunedì|martedì|mercoledì|giovedì|venerdì|sabato|domenica)\s+"
        r"(\d{1,2})\s+([a-zà]+)(?:\s+(20\d{2}))?\s+ore\s+(\d{1,2})[.:](\d{2})",
        re.I,
    )
    for tr in soup.find_all("tr"):
        cells=[norm(x.get_text(" ",strip=True)) for x in tr.find_all(["th","td"])]
        if len(cells)<2: continue
        title, value=cells[0],cells[1]
        m=rx.search(value)
        if not m: continue
        day,month,year,hh,mm=m.groups()
        month_n=MONTHS.get(month.lower())
        if not month_n: continue
        year=int(year) if year else (2027 if month_n <= 12 else 2027)
        events.append({"title":title,"start":datetime(year,month_n,int(day),int(hh),int(mm),tzinfo=TZ)})
    return events

def event_links(season_page):
    soup=BeautifulSoup(season_page,"html.parser")
    links={}
    for a in soup.find_all("a",href=True):
        label=norm(a.get_text(" ",strip=True))
        for title in FORMS:
            if title.casefold() in label.casefold():
                links.setdefault(title,urljoin(SEASON_URL,a["href"]))
    return links

def duration_from_page(url):
    if not url: return None
    try:
        text=norm(BeautifulSoup(get(url),"html.parser").get_text(" ",strip=True))
    except Exception:
        return None
    patterns=[
        r"durata\s*(?:dello spettacolo)?\s*[:\-]?\s*(\d+)\s*(?:h|ore)(?:\s*(?:e|:)?\s*(\d{1,2})\s*(?:min|minuti)?)?",
        r"durata\s*[:\-]?\s*(\d+)\s*(?:min|minuti)"
    ]
    m=re.search(patterns[0],text,re.I)
    if m: return int(m.group(1))*60 + int(m.group(2) or 0)
    m=re.search(patterns[1],text,re.I)
    if m: return int(m.group(1))
    return None

def esc(s):
    return str(s).replace("\\","\\\\").replace(";","\\;").replace(",","\\,").replace("\n","\\n")

def fold(line):
    raw=line.encode("utf-8")
    if len(raw)<=75: return line
    parts=[]; cur=""
    for ch in line:
        test=cur+ch
        if len(test.encode("utf-8"))>73:
            parts.append(cur); cur=ch
        else: cur=test
    parts.append(cur)
    return "\r\n ".join(parts)

def uid(title):
    key=("2026-27|prime|"+title.casefold()).encode()
    return hashlib.sha256(key).hexdigest()[:24]+"@teatro-massimo-calendar"

def build(events,links):
    lines=["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//ZioFe//Teatro Massimo Turno Prime//IT",
           "CALSCALE:GREGORIAN","METHOD:PUBLISH","X-WR-CALNAME:Teatro Massimo - Turno Prime",
           "X-WR-TIMEZONE:Europe/Rome","X-PUBLISHED-TTL:PT6H"]
    for e in events:
        title=e["title"]; start=e["start"]
        kind,form=FORMS.get(title,("Spettacolo",None))
        link=links.get(title,PRIME_URL)
        mins=duration_from_page(link)
        desc=[kind]
        if form and form != kind: desc.append(form)
        if mins:
            h,m=divmod(mins,60)
            desc.append("Durata: "+((f"{h} h {m} min") if m else f"{h} h"))
        desc += ["Turno Prime", "Fonte ufficiale: "+link]
        lines += ["BEGIN:VEVENT",f"UID:{uid(title)}",
                  f"DTSTART;TZID=Europe/Rome:{start.strftime('%Y%m%dT%H%M%S')}"]
        if mins:
            end=start+timedelta(minutes=mins)
            lines.append(f"DTEND;TZID=Europe/Rome:{end.strftime('%Y%m%dT%H%M%S')}")
        lines += [f"SUMMARY:{esc(title)}",
                  "LOCATION:"+esc("Teatro Massimo, Piazza Verdi, Palermo"),
                  "CATEGORIES:"+esc(kind),
                  "DESCRIPTION:"+esc("\n".join(desc)),
                  "URL:"+link,
                  "STATUS:CONFIRMED","END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(x) for x in lines)+"\r\n"

def main():
    prime=get(PRIME_URL)
    events=parse_prime(prime)
    expected=set(FORMS)
    found={e["title"] for e in events}
    if len(events)<12 or not expected.issubset(found):
        print(f"ERRORE: estrazione PRIME incompleta ({len(events)} eventi). File esistente non modificato.",file=sys.stderr)
        print("Mancanti:",sorted(expected-found),file=sys.stderr)
        return 2
    season=get(SEASON_URL)
    links=event_links(season)
    data=build(events,links)
    old=OUT.read_text(encoding="utf-8") if OUT.exists() else ""
    if old.replace("\n","\r\n").replace("\r\r\n","\r\n") == data:
        print("Calendario invariato.")
        return 0
    OUT.write_bytes(data.encode("utf-8"))
    print(f"Calendario aggiornato: {len(events)} eventi PRIME.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
