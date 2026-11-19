#!/usr/bin/env python3
import hashlib
import html
import re
import sys
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo

PRIME_URL = "https://www.teatromassimo.it/en/biglietteria/turno-prime/"
SEASON_URL = "https://www.teatromassimo.it/la-stagione-2026-27/"
UNDER35_URL = "https://www.teatromassimo.it/en/biglietteria/under-35-turni-prime-e-concerti/"
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
    last_error=None
    for attempt in range(3):
        try:
            r=requests.get(url,headers={"User-Agent":UA},timeout=30)
            r.raise_for_status()
            return r.text
        except requests.RequestException as exc:
            last_error=exc
            if attempt<2:
                print(f"Accesso temporaneamente fallito ({url}): {exc}. Riprovo.",file=sys.stderr)
                time.sleep(3*(attempt+1))
    raise last_error

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

def prime_from_summary(title, url):
    soup=BeautifulSoup(get(url),"html.parser")
    text=norm(soup.get_text(" | ",strip=True))
    def canon(v):
        return re.sub(r"[–—-]+"," ",v.casefold())
    flat=canon(text)
    needle=canon(title)
    pos=flat.find(needle)
    if pos < 0:
        return None
    chunk=text[pos+len(title):pos+len(title)+180]
    m=re.search(r"(?:lunedì|martedì|mercoledì|giovedì|venerdì|sabato|domenica)\s+(\d{1,2})\s+([A-Za-zÀ-ÿ]+)(?:\s+(20\d{2}))?(?:\s+ore\s+(\d{1,2})[.:](\d{2}))?",chunk,re.I)
    if not m:
        return None
    day,month,year,hh,mm=m.groups()
    month_n=MONTHS.get(month.casefold())
    if not month_n:
        return None
    y=int(year) if year else 2027
    hour=int(hh) if hh else 20
    minute=int(mm) if mm else 0
    return {"title":title,"start":datetime(y,month_n,int(day),hour,minute,tzinfo=TZ)}

def parse_prime_from_events(links):
    events=[]
    for title in FORMS:
        url=links.get(title)
        event=prime_from_event_page(title,url) if url else None
        if not event:
            event=prime_from_summary(title,UNDER35_URL)
            if event and not url:
                links[title]=PRIME_URL
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

def intervals_from_page(url):
    if not url or url == PRIME_URL:
        return None
    try:
        text=norm(BeautifulSoup(get(url),"html.parser").get_text(" ",strip=True))
    except requests.RequestException:
        return None
    for occurrence in list(re.finditer(r"\bdurata\b",text,re.I))[:5]:
        segment=text[occurrence.start():occurrence.start()+240]
        segment=re.split(r"\b(?:Cast|Date|Biglietti|Acquista)\b",segment,maxsplit=1)[0]
        if re.search(r"\bsenza\s+intervall[oi]\b",segment,re.I):
            return (0,None)
        if not re.search(r"\bintervall[oi]\b",segment,re.I):
            continue
        count=None
        for word,n in (("un",1),("uno",1),("1",1),("due",2),("2",2),("tre",3),("3",3)):
            if re.search(r"\b"+word+r"\s+intervall[oi]\b",segment,re.I):
                count=n
                break
        if count is None and re.search(r"\bintervallo\b",segment,re.I):
            count=1
        length=None
        d=re.search(r"\bintervall[oi]\b.{0,55}?\b(?:di|da)\s*(\d{1,3})\s*(?:minuti|min)\b",segment,re.I)
        if not d:
            d=re.search(r"\b(\d{1,3})\s*(?:minuti|min)\s+(?:di\s+)?intervallo\b",segment,re.I)
        if d:
            length=int(d.group(1))
        return (count,length)
    return None

def argomento_from_page(url):
    """Trova il collegamento ufficiale 'Scarica l'argomento' dello spettacolo."""
    if not url or url == PRIME_URL:
        return None
    try:
        soup=BeautifulSoup(get(url),"html.parser")
    except requests.RequestException:
        return None
    for a in soup.find_all("a",href=True):
        label=norm(a.get_text(" ",strip=True))
        title=norm(a.get("title",""))
        aria=norm(a.get("aria-label",""))
        if "argomento" not in " ".join((label,title,aria)).casefold():
            continue
        href=urljoin(url,a["href"].strip())
        if href.startswith(("https://","http://")) and href != url:
            return href
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

def old_event_meta(old):
    meta={}
    for block in old.split("BEGIN:VEVENT")[1:]:
        uid_m=re.search(r"(?m)^UID:([^\\r\\n]+)",block)
        if not uid_m:
            continue
        seq_m=re.search(r"(?m)^SEQUENCE:(\\d+)",block)
        stamp_m=re.search(r"(?m)^DTSTAMP:([^\\r\\n]+)",block)
        hash_m=re.search(r"(?m)^X-CONTENT-HASH:([^\\r\\n]+)",block)
        meta[uid_m.group(1)]={
            "sequence":int(seq_m.group(1)) if seq_m else 0,
            "dtstamp":stamp_m.group(1) if stamp_m else None,
            "hash":hash_m.group(1) if hash_m else None,
        }
    return meta

def build(events,links,old=""):
    lines=["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//ZioFe//Teatro Massimo Turno Prime//IT",
           "CALSCALE:GREGORIAN","METHOD:PUBLISH","X-WR-CALNAME:Teatro Massimo - Turno Prime",
           "X-WR-TIMEZONE:Europe/Rome","X-PUBLISHED-TTL:PT6H"]
    previous=old_event_meta(old)
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
        else:
            desc.append("Durata: non ancora pubblicata")
        intervals=intervals_from_page(link)
        # Durata intervallo confermata dalla comunicazione ufficiale del Teatro.
        if title == "Samson et Dalila" and intervals is not None and intervals[0] == 1 and intervals[1] is None:
            intervals=(1,20)
        if intervals is None:
            desc.append("Intervalli: informazioni non ancora pubblicate")
        else:
            count,length=intervals
            if count == 0:
                desc.append("Intervalli: nessuno (confermato)")
            else:
                desc.append("Intervalli: "+(str(count) if count is not None else "numero non specificato"))
                desc.append("Durata intervalli: "+(str(length)+" min ciascuno" if length is not None else "non specificata"))
        argomento=argomento_from_page(link)
        if argomento:
            desc.append("Argomento: "+argomento)
        else:
            desc.append("Argomento: non ancora disponibile")
        desc += ["Turno Prime", "Fonte ufficiale: "+link]
        event_uid=uid(title)
        content_key="|".join([
            "🎭 "+title,start.isoformat(),kind,form or "",str(mins or ""),
            str(intervals),argomento or "non ancora disponibile",link
        ])
        content_hash=hashlib.sha256(content_key.encode("utf-8")).hexdigest()[:16]
        prev=previous.get(event_uid,{})
        changed=prev.get("hash") != content_hash
        sequence=prev.get("sequence",0)+(1 if changed else 0)
        dtstamp=(datetime.now(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")
                 if changed or not prev.get("dtstamp") else prev["dtstamp"])
        lines += ["BEGIN:VEVENT",f"UID:{event_uid}",
                  f"DTSTAMP:{dtstamp}",f"SEQUENCE:{sequence}",
                  f"X-CONTENT-HASH:{content_hash}",
                  f"DTSTART;TZID=Europe/Rome:{start.strftime('%Y%m%dT%H%M%S')}"]
        if mins:
            end=start+timedelta(minutes=mins)
            lines.append(f"DTEND;TZID=Europe/Rome:{end.strftime('%Y%m%dT%H%M%S')}")
        lines += [f"SUMMARY:{esc('🎭 '+title)}",
                  "LOCATION:"+esc("Teatro Massimo, Piazza Verdi, Palermo"),
                  "CATEGORIES:"+esc(kind),
                  "DESCRIPTION:"+esc("\n".join(desc)),
                  "URL:"+link,
                  "STATUS:CONFIRMED","END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(x) for x in lines)+"\r\n"

def main():
    try:
        season=get(SEASON_URL)
        links=event_links(season)
    except requests.RequestException as exc:
        print(f"Fonte ufficiale temporaneamente non raggiungibile: {exc}. Calendario precedente conservato.",file=sys.stderr)
        return 0 if OUT.exists() and "BEGIN:VEVENT" in OUT.read_text(encoding="utf-8") else 2
    events=parse_prime_from_events(links)
    expected=set(FORMS)
    found={e["title"] for e in events}
    if len(events)<12 or not expected.issubset(found):
        print(f"ERRORE: estrazione PRIME incompleta ({len(events)} eventi). File esistente non modificato.",file=sys.stderr)
        print("Link trovati:",sorted(links),file=sys.stderr)
        print("Mancanti:",sorted(expected-found),file=sys.stderr)
        return 2
    old=OUT.read_text(encoding="utf-8") if OUT.exists() else ""
    data=build(events,links,old)
    if old.replace("\\n","\\r\\n").replace("\\r\\r\\n","\\r\\n") == data:
        print("Calendario invariato.")
        return 0
    OUT.write_bytes(data.encode("utf-8"))
    print(f"Calendario aggiornato: {len(events)} eventi PRIME.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
