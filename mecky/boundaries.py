"""Keep this venue assistant on topic before retrieval or model calls."""
import re

OFF_TOPIC = re.compile(
    r"\b(politik\w*|politisch\w*|bundestag\w*|bundeskanzler\w*|bundespräsident\w*|wahlkampf\w*|"
    r"afd|cdu|spd|fdp|trump|putin|biden|israel|palästina|gaza|ukrainekrieg|"
    r"bitcoin|kryptowährung\w*|aktienkurs\w*|quantenphysik|hausaufgaben|"
    r"bundesliga|champions league|porn\w*|sexchat|bombenbau|malware|ransomware|"
    r"hauptstadt|matheaufgabe|horoskop|witz|wettervorhersage)\b|"
    r"welche\s+partei|wen\s+soll\s+ich\s+wählen|"
    r"(schreib|programmier|erstell|erklär)\w*.*\b(python|javascript|code|sql|aufsatz)\b|"
    r"(ignorier\w*|vergiss|ignore|forget).*\b(regeln|anweisungen|instructions|prompt)\b|"
    r"(zeig|verrat|gib|show|reveal)\w*.*\b(systemprompt|system.prompt|api.key|api.schlüssel|admin.secret|passwort)\b",
    re.I,
)


def is_off_topic(message):
    return bool(OFF_TOPIC.search(message))


def friendly_boundary(message):
    if re.search(r"politik|politisch|partei|wählen|trump|putin|bundestag|\b(afd|cdu|spd|fdp)\b", message, re.I):
        return "Bei politischen Themen halte ich mich freundlich raus. Ich bin Mecky, dein digitaler Gastgeber für die Heuchelberger Warte. Wenn du etwas zu eurem Besuch, Essen oder Feiern wissen möchtest, helfe ich dir gern."
    return "Dabei kann ich dir hier leider nicht helfen. Ich bin für Fragen rund um die Heuchelberger Warte da – zum Beispiel zu eurem Besuch, zur Speisekarte oder zur Reservierung. Was möchtest du dazu wissen?"
