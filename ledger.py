"""Journal public des prédictions : chaîne de hachages en ajout seul (bibliothèque standard uniquement).

Chaque ligne du fichier est un objet JSON canonique :
    {"seq": N, "prev": "<hash de la ligne précédente>", "type": ..., "published_at": ..., "data": {...}, "hash": "..."}
`hash` = SHA-256 du même objet sans le champ `hash`. Modifier, supprimer ou réordonner une ligne casse
la chaîne à partir de ce point : `python ledger.py ledger.jsonl` le détecte.

Le format est strict : une ligne doit être écrite sous sa forme canonique octet pour octet (pas de clé dupliquée,
pas de NaN, pas de réindentation), sinon deux lecteurs JSON pourraient comprendre deux contenus différents sous
le même hash. Le vérificateur de référence est celui-ci (Python) : les nombres sont sérialisés comme Python le fait.

    python ledger.py ledger.jsonl                       chaîne intacte ?
    python ledger.py nouveau.jsonl --base ancien.jsonl  ... et nouveau = ancien + des ajouts ? (aucune réécriture)

Limite honnête : le propriétaire du dépôt peut réécrire tout le fichier ET recalculer toute la chaîne. La preuve
vient de ce que le dernier hash a été publié ailleurs (historique GitHub, miroirs, horodatage externe) avant
les résultats des matchs. La chaîne rend la falsification détectable, elle ne l'empêche pas toute seule.
"""
from __future__ import annotations

import hashlib
import json
import sys

GENESIS_PREV = "0" * 64
SCHEMA_VERSION = 1
KNOWN_TYPES = ("genesis", "prediction", "result")
ENTRY_KEYS = {"seq", "prev", "type", "published_at", "data", "hash"}
RESULT_KEYS = ("prediction_id", "real_result", "real_home_goals", "real_away_goals")


class LedgerFormatError(ValueError):
    """Le fichier n'est pas un journal au format strict."""


def canonical(obj) -> str:
    """JSON déterministe : clés triées, sans espaces, caractères non ASCII conservés, NaN refusé."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def entry_hash(body: dict) -> str:
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def make_entry(seq: int, prev: str, kind: str, published_at: str, data: dict) -> dict:
    body = {"seq": seq, "prev": prev, "type": kind, "published_at": published_at, "data": data}
    return {**body, "hash": entry_hash(body)}


def _no_duplicate_keys(pairs):
    obj: dict = {}
    for key, value in pairs:
        if key in obj:
            raise LedgerFormatError(f"clé dupliquée {key!r}")
        obj[key] = value
    return obj


def _reject_constant(name: str):
    raise LedgerFormatError(f"valeur {name} : ce n'est pas du JSON")


def read_ledger(path: str) -> list[dict]:
    """Lit le journal en format strict ; lève LedgerFormatError au moindre écart. Fichier absent = journal vide."""
    try:
        with open(path, encoding="utf-8", newline="") as f:
            text = f.read()
    except FileNotFoundError:
        return []
    except UnicodeDecodeError as exc:
        raise LedgerFormatError(f"le fichier n'est pas de l'UTF-8 ({exc.reason})") from None
    if not text:
        return []
    if not text.endswith("\n"):
        raise LedgerFormatError("le fichier doit se terminer par un saut de ligne")
    entries = []
    for n, line in enumerate(text.split("\n")[:-1], 1):
        try:
            obj = json.loads(line, object_pairs_hook=_no_duplicate_keys, parse_constant=_reject_constant)
            canonical_form = canonical(obj)
        except LedgerFormatError as exc:
            raise LedgerFormatError(f"ligne {n} : {exc}") from None
        except (ValueError, RecursionError) as exc:  # JSON invalide, NaN, imbrication démesurée...
            raise LedgerFormatError(f"ligne {n} : JSON invalide ({exc})") from None
        if not isinstance(obj, dict):
            raise LedgerFormatError(f"ligne {n} : ce n'est pas un objet JSON")
        if canonical_form != line:
            raise LedgerFormatError(f"ligne {n} : pas écrite sous forme canonique")
        entries.append(obj)
    return entries


def _entry_problem(e) -> str | None:
    """Défaut de forme d'une entrée (None = bien formée). Évite qu'un fichier piégé fasse planter la suite."""
    if not isinstance(e, dict) or set(e) != ENTRY_KEYS:
        return "champs inattendus ou manquants"
    if type(e["seq"]) is not int:
        return "seq doit être un entier"
    if e["type"] not in KNOWN_TYPES:
        return f"type inconnu {e['type']!r}"
    if not all(isinstance(e[k], str) for k in ("prev", "published_at", "hash")):
        return "prev, published_at et hash doivent être du texte"
    data = e["data"]
    if not isinstance(data, dict):
        return "data doit être un objet"
    if e["type"] == "prediction" and type(data.get("id")) is not int:
        return "une prédiction doit avoir un id entier"
    if e["type"] == "result" and (type(data.get("prediction_id")) is not int
                                  or any(k not in data for k in RESULT_KEYS)):
        return "un résultat doit référencer prediction_id et porter son score"
    return None


def verify(entries: list[dict]) -> list[str]:
    """Liste des anomalies (vide = chaîne intacte)."""
    errors: list[str] = []
    prev = GENESIS_PREV
    for i, e in enumerate(entries):
        where = f"ligne {i + 1}"
        problem = _entry_problem(e)
        if problem:
            errors.append(f"{where} : {problem}")
            prev = e.get("hash", "") if isinstance(e, dict) else ""
            continue
        if e["seq"] != i:
            errors.append(f"{where} : seq {e['seq']} au lieu de {i}")
        if e["prev"] != prev:
            errors.append(f"{where} : prev ne correspond pas au hash de la ligne précédente")
        body = {k: v for k, v in e.items() if k != "hash"}
        try:
            expected = entry_hash(body)
        except ValueError:  # texte non encodable (substitut isolé), NaN...
            expected = None
        if e["hash"] != expected:
            errors.append(f"{where} : hash incorrect (contenu modifié)")
        if i == 0 and e["type"] != "genesis":
            errors.append(f"{where} : la première entrée doit être de type genesis")
        prev = e["hash"]
    return errors


def is_extension(old: list[dict], new: list[dict]) -> bool:
    """Vrai si `new` ne fait qu'ajouter des lignes à la suite de `old` (aucune réécriture, aucune troncature)."""
    return len(new) >= len(old) and new[:len(old)] == old


class LedgerState:
    """Ce que le journal contient déjà : dernier hash, prochain numéro, prédictions et résultats publiés.

    À utiliser sur un journal déjà vérifié (`verify` renvoie []).
    """

    def __init__(self, entries: list[dict]):
        self.last_hash = entries[-1]["hash"] if entries else GENESIS_PREV
        self.next_seq = len(entries)
        self.empty = not entries
        self.predictions: set[int] = set()
        self.results: dict[int, tuple] = {}
        for e in entries:
            d = e.get("data", {})
            if e["type"] == "prediction":
                self.predictions.add(d["id"])
            elif e["type"] == "result":
                self.results[d["prediction_id"]] = (d["real_result"], d["real_home_goals"], d["real_away_goals"])


def _load_checked(path: str) -> tuple[list[dict] | None, list[str]]:
    try:
        entries = read_ledger(path)
    except LedgerFormatError as exc:
        return None, [f"{path} : format invalide, {exc}"]
    return entries, [f"{path} : {err}" for err in verify(entries)]


def main(argv: list[str]) -> int:
    args = argv[1:]
    base_path = None
    if len(args) == 3 and args[1] == "--base":
        args, base_path = [args[0]], args[2]
    if len(args) != 1:
        print("usage : python ledger.py ledger.jsonl [--base ancien.jsonl]", file=sys.stderr)
        return 2

    entries, errors = _load_checked(args[0])
    if not errors and base_path is not None:
        base, base_errors = _load_checked(base_path)
        errors += base_errors
        if not base_errors and not is_extension(base, entries):
            errors.append(f"{args[0]} ne prolonge pas {base_path} : une partie du passé a été modifiée ou supprimée")
    if errors:
        print(f"JOURNAL INVALIDE ({len(errors)} anomalie(s)) :")
        for err in errors[:20]:
            print("  -", err)
        return 1

    kinds: dict[str, int] = {}
    for e in entries:
        kinds[e["type"]] = kinds.get(e["type"], 0) + 1
    head = entries[-1]["hash"] if entries else "(vide)"
    print(f"Chaîne valide : {len(entries)} entrées {kinds}\nDernier hash : {head}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
