import json
from pathlib import Path

groups={
"OPENING_HOURS":["Habt ihr heute offen?","Habt ihr morgen geöffnet?","Wie lange habt ihr Sonntag offen?","Ist am Samstag geöffnet?","Öffnet ihr am 24. Dezember?","Habt ihr am 21. November offen?","Wie sind die Öffnungszeiten im Oktober?","Kann ich Montag einfach vorbeikommen?","Ist am 6. Januar geöffnet?","Habt ihr nächstes Wochenende offen?"],
"KITCHEN_HOURS":["Bis wann hat die Küche heute offen?","Wann schließt die Küche im September?","Hat die Küche am Freitag länger offen?","Gibt es nach Küchenschluss noch Essen?","Wie lange kocht ihr bei Hitze?","Schließt die Küche bei Regen früher?","Ist die Küche nächsten Sonntag offen?","Bis wann kann ich im Oktober essen?","Habt ihr morgen Abend Küche?","Gibt es um 22 Uhr noch warme Gerichte?"],
"RESERVATION":["Wo kann ich reservieren?","Kann ich mit 8 Leuten Sonntag reservieren?","Sind morgen noch Plätze frei?","Kann ich einen bestimmten Tisch buchen?","Wie weit im Voraus kann ich reservieren?","Kann ich spontan Samstag kommen?","Brauche ich für den Biergarten eine Reservierung?","Kann ich für 20 Personen online buchen?","Kann ich mit Kinderwagen am Tisch reservieren?","Wie storniere ich meinen Tisch?"],
"MENU":["Zeig mir die Speisekarte.","Was gibt es aktuell zu essen?","Habt ihr vegetarische Gerichte?","Gibt es glutenfreie Optionen?","Was kostet der Burger genau?","Wo ist die Mittagstischkarte?","Habt ihr veganes Essen?","Sind eure Suppen glutenfrei?","Gibt es Kindergerichte?","Kann ich Allergene in der Karte nachlesen?"],
"PARKING":["Wo kann ich parken?","Darf ich direkt hochfahren?","Was kostet das Parken?","Wie weit ist es vom Hauptparkplatz?","Gibt es einen Parkplatz für Rollstuhlfahrer?","Kann ich mit dem Auto bis zum Restaurant fahren?","Wo ist die Hupferhaltestelle?","Gibt es einen E-Ladeplatz?","Welche Parkregeln gelten?","Wird der Parkplatz nachts abgeschlossen?"],
"DIRECTIONS":["Wie lautet eure Adresse?","Wie komme ich mit der Bahn?","Wie lange laufe ich vom Bahnhof?","Wo finde ich den Weg zur Warte?","Kann ich mit dem Hupfer hochfahren?","Was kostet der Shuttle?","Wie lange dauert die Shuttlefahrt?","Wo ist der Parkplatz Alte Burg?","Ist der Weg von Alte Burg flach?","Kann ich mit einem Reisebus direkt hoch?"],
"WEDDING":["Kann man bei euch heiraten?","Wir wollen nächstes Jahr heiraten.","Was kostet eine Hochzeit?","Wie viele Hochzeitsgäste passen hinein?","Gibt es Hochzeitsinfoabende?","Kann man draußen feiern?","Wie frage ich ein Hochzeitsangebot an?","Gibt es einen Festsaal?","Ist mein Wunschtermin im Juni frei?","Kann man eine Trauung vor Ort machen?"],
"CORPORATE_EVENT":["Wir planen eine Firmenfeier.","Kann man mit 100 Kollegen feiern?","Gibt es Weihnachtsfeiern?","Was kostet ein Teamabend?","Gibt es ein Ausflugs-Special?","Kann ich ein Firmenevent buchen?","Macht ihr Tagungen?","Kann man im Winter feiern?","Welche Räume eignen sich für Firmen?","Ist der 14. Oktober für uns frei?"],
"CHILDREN":["Gibt es Ponyreiten?","Gibt es Sonntag Ponyreiten um 10?","Sind Kinder willkommen?","Gibt es einen Spielplatz?","Kann ich Kindergeburtstag feiern?","Ist ein Kinderwagen am Tisch möglich?","Gibt es Aktivitäten für Kinder?","Wie alt muss mein Kind zum Ponyreiten sein?","Brauche ich Tickets für Ponyreiten?","Gibt es eine Wickelmöglichkeit?"],
"ACCESSIBILITY":["Kann mein Vater hochfahren, wenn er schlecht läuft?","Ist der Weg rollstuhlgerecht?","Wie komme ich ohne Steigung hoch?","Kann man mit Rollstuhl vom Parkplatz Alte Burg kommen?","Ist das Restaurant komplett barrierefrei?","Gibt es ein barrierefreies WC?","Nimmt der Shuttle einen Rollstuhl mit?","Kann ich mit Kinderwagen hoch?","Gibt es Behindertenparkplätze?","Ist die Gartenküche stufenlos erreichbar?"],
"GARDEN":["Kann ich draußen sitzen?","Ist der Garten bei Regen offen?","Muss ich mich im Biergarten selbst bedienen?","Gibt es draußen die gleiche Karte?","Kann ich den Biergarten reservieren?","Sind Hunde draußen erlaubt?","Ist die Terrasse im Oktober offen?","Gibt es einen überdachten Außenbereich?","Bis wann ist der Garten geöffnet?","Kann man im Winter draußen sitzen?"],
"CONTACT":["Wie lautet eure E-Mail?","Habt ihr eine Telefonnummer?","Wie kann ich euch erreichen?","Wo melde ich eine Beschwerde?","Wie frage ich ein Angebot an?","Gibt es ein Kontaktformular?","Ist das Büro Sonntag erreichbar?","Wem schreibe ich wegen einer Trauerfeier?","Wie erreiche ich das Reservierungsbüro?","Kann ich per WhatsApp schreiben?"],
"OTHER":["Darf mein Hund mit?","Muss der Hund an die Leine?","Kann ich mit Kreditkarte zahlen?","Darf ich rauchen?","Gibt es Übernachtung vor Ort?","Kann man frühstücken?","Gibt es Berg-Brunch?","Hallo!","Hoffentlich wird das Wetter schön 😅","Gibt es morgen eine geheime Weinprobe für 5 Euro?"]
}

links={"OPENING_HOURS":"https://heuchelberg.com/","KITCHEN_HOURS":"https://heuchelberg.com/","RESERVATION":"https://www.sevenrooms.com/","MENU":".pdf","PARKING":"https://heuchelberg.com/","DIRECTIONS":"https://heuchelberg.com/","WEDDING":"/hochzeit","CORPORATE_EVENT":"/firmen-events","CHILDREN":"/kinderaktivitaeten","ACCESSIBILITY":"https://heuchelberg.com/","GARDEN":"https://heuchelberg.com/","CONTACT":"/kontakt/","OTHER":""}
traps=("kostet","frei?","e-lade","nachts","komplett","rollstuhl mit","tickets","wickel","geheime","was kostet","wunschtermin")
def expected_link(group,question):
    q=question.lower()
    if "20 personen online" in q: return "typeform.com"
    if "biergarten" in q and "reserv" in q: return "https://heuchelberg.com/"
    if "kinderwagen" in q and "tisch" in q: return "sevenrooms.com"
    if "kindergeburtstag" in q: return "/kontakt/"
    if "pony" in q and "sonntag" in q: return "https://heuchelberg.com/"
    if "draußen feiern" in q or "winter feiern" in q: return "/feine-feste-"
    if "hochzeitsangebot" in q: return "/kontakt/"
    if "wunschtermin" in q or ("frei" in q and "oktober" in q): return "/kontakt/"
    return links[group]
cases=[]
for group,questions in groups.items():
    for question in questions:
        cases.append({"question":question,"expected_category":group.lower(),"expected_relevant_url":expected_link(group,question),"expected_facts":[],"must_not_claim":["gebucht","garantiert verfügbar"],"confidence_expectation":"unknown_or_partial" if any(x in question.lower() for x in traps) else "sourced_or_partial"})
path=Path("eval/questions.jsonl");path.parent.mkdir(exist_ok=True)
path.write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in cases),encoding="utf-8")
print(f"Wrote {len(cases)} evaluation questions")
