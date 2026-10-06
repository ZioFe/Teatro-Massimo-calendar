#!/usr/bin/env python3
import hashlib
import html
import re
import sys
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo

PRIME_URL = "https://www.teatromassimo.it/en/biglietteria/turno-prime/"
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

def get_rendered(url):
    """Renderizza le pagine che popolano il contenuto via JavaScript."""
    cmd=[
        "google-chrome","--headless","--no-sandbox","--disable-gpu",
        "--disable-dev-shm-usage","--virtual-time-budget=8000",
        "--dump-dom",url,
    ]
    p=subprocess.run(cmd,capture_output=True,text=True,timeout=45)
    if p.returncode != 0 or len(p.stdout) < 1000:
        raise RuntimeError("Chrome headless non ha restituito una pagina valida")
    return p.stdout

def norm(s):
    return re.sub(r"\s+"," ",html.unescape(s or "")).strip()

def prime_from_event_page(title, url):
    page=get(url)
    soup=BeautifulSoup(page,"html.parser")
    text=norm(soup.get_text(" | ",strip=True))
    positions=[m.start() for m in re.finditer(r"Turno\s+Prime",text,re.I)]
    rx=re.compile(r"(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\s*\|?\s*(\d{1,2})[.:](\d{2})",re.I)
    for pos in positions:
        chunk=text[max(0,pos-180):pos]
        matches=list(rx.finditer(chunk))
        if not matches:
            continue
        day,month,hh,mm=matches[-1].groups()
        month_n=MONTHS.get(month.casefold())
        if not month_n:
            continue
        year=2026 if month_n in (11,12) and title in ("Samson et Dalila","Biancaneve") else 2027
        return {"title":title,"start":datetime(year,month_n,int(day),int(hh),int(mm),tzinfo=TZ)}
    return None

def parse_prime_from_events(links):
    events=[]
    for title in FORMS:
        url=links.get(title)
        if not url:
            continue
        event=prime_from_event_page(title,url)
        if event:
            events.append(event)
    return events

def event_links(season_page):
    soup=BeautifulSoup(season_page,"html.parser")
    links={}
    def key(value):
        value=norm(value).casefold()
        value=re.sub(r"[–—-]+"," ",value)
        return re.sub(r"\s+"," ",value).strip()
    for a in soup.find_all("a",href=True):
        label=norm(a.get_text(" ",strip=True))
        label_key=key(label)
        for title in FORMS:
            if key(title) in label_key:
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
    season=get(SEASON_URL)
    links=event_links(season)
    events=parse_prime_from_events(links)
    expected=set(FORMS)
    found={e["title"] for e in events}
    if len(events)<12 or not expected.issubset(found):
        print(f"ERRORE: estrazione PRIME incompleta ({len(events)} eventi). File esistente non modificato.",file=sys.stderr)
        print("Link trovati:",sorted(links),file=sys.stderr)
        print("Mancanti:",sorted(expected-found),file=sys.stderr)
        return 2
    data=build(events,links)
    old=OUT.read_text(encoding="utf-8") if OUT.exists() else ""
    if old.replace("\\n","\\r\\n").replace("\\r\\r\\n","\\r\\n") == data:
        print("Calendario invariato.")
        return 0
    OUT.write_bytes(data.encode("utf-8"))
    print(f"Calendario aggiornato: {len(events)} eventi PRIME.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
