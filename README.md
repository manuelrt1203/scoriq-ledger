# ScorIQ — journal public des prédictions

Copie publique et autonome du journal de [ScorIQ](https://pronostics-frontend.vercel.app), un suivi de prédictions de
football transparent et vérifiable. Ce dépôt ne contient que le journal (`ledger.jsonl`), son vérificateur
(`ledger.py`) et cette explication. Le code de ScorIQ n'y est pas : le pipeline y **ajoute** des lignes chaque jour
et ne réécrit jamais l'existant.

> **Ce que ce journal n'est pas.** ScorIQ ne bat pas les bookmakers et ne promet aucun gain. Ce journal prouve
> *quand* et *quoi* a été prédit, rien d'autre.

`ledger.jsonl` liste, dans l'ordre, chaque prédiction de ScorIQ **publiée avant le match**, puis son résultat.
Les lignes ne sont jamais modifiées : on ajoute, on ne remplace pas.

## Ce que contient le journal

| Type | Contenu |
|---|---|
| `genesis` | première ligne, décrit le format |
| `prediction` | match, pronostic 1/X/2, probabilités, confiance, probabilités du modèle seul, buts attendus, Over/BTTS |
| `result` | score réel, ajouté après le match. Un résultat corrigé est ajouté avec `"correction": true`, jamais écrasé |

Sont publiés aussi les matchs **sans pronostic** (`INSUFFICIENT_HISTORY`, historique insuffisant) et les prédictions
dont le coup d'envoi n'a pas pu être retrouvé (`provenance: "unknown"`, `kickoff: null`) : on ne montre pas
seulement les réussites.

N'est **pas** publié : les cotes des bookmakers (données d'un fournisseur tiers). Les probabilités publiées
intègrent toutefois une part de marché (le modèle `+mkt` en tient compte) : on ne peut pas exclure qu'on en retrouve
une approximation en comparant `proba_*` et `model_pure_*`.

## Quel modèle a produit la prédiction : `model_version` et `dc_params_date`

- `model_version` : empreinte de 12 caractères des fichiers de modèles réellement chargés (LightGBM, modèles de
  buts, calibrateurs) et des poids du mélange. Si les modèles changent un jour, la valeur change : les prédictions
  d'avant et d'après restent distinguables, sans réécrire le passé. Elle ne couvre pas le code lui-même.
- `dc_params_date` : date d'entraînement des paramètres Dixon-Coles utilisés. Ces paramètres sont ré-entraînés
  chaque nuit sur les résultats connus, donc cette date change chaque jour sans que `model_version` change.

Pour juger la performance d'un modèle précis, filtrez sur une valeur de `model_version`.

## Publication tardive : le champ `late`

`kickoff` est l'heure de début du match (UTC). `late` vaut `true` si la prédiction a été publiée **après** le coup
d'envoi ou si son résultat était déjà connu au moment de la publication (un passage du pipeline a échoué et a été
rattrapé plus tard). Une ligne `late: true` ne prouve pas une prédiction faite avant le match : il faut l'ignorer
pour juger la performance. `late: null` signifie que le coup d'envoi est inconnu.

## Quand commence-t-il ?

Au premier passage du pipeline après la mise en place de l'horodatage par la base de données (17 novembre 2026).
Seules les prédictions horodatées par l'horloge de la **base** (`created_at`, que le script ne peut pas fausser) y entrent.

Les prédictions antérieures n'y sont pas : leur heure venait du script, et celles de mars à août 2026 sont un
rattrapage fait avec les modèles d'aujourd'hui (un backtest, pas une preuve).

## Vérifier le journal

```bash
python ledger.py ledger.jsonl
```

Le script (bibliothèque standard uniquement) recalcule la chaîne de hachages. Il signale toute ligne modifiée,
supprimée ou déplacée, et affiche le dernier hash. Le format est strict : chaque ligne doit être écrite sous sa forme
canonique octet pour octet (pas de clé dupliquée, pas de `NaN`, pas de réindentation), sinon deux lecteurs JSON
pourraient lire deux contenus différents sous le même hash. **Le vérificateur de référence est ce script Python** :
les nombres y sont sérialisés comme Python le fait.

Pour comparer deux versions (par exemple la vôtre, copiée un jour donné, et la version actuelle) :

```bash
python ledger.py ledger.jsonl --base ma-copie-ancienne.jsonl
```

Il échoue si l'actuel ne se contente pas d'ajouter des lignes à la suite de l'ancien. Une réécriture complète avec
tous les hachages recalculés passe la première commande, mais pas celle-ci : c'est pourquoi une copie ancienne
est précieuse. Le workflow `Verify` de ce dépôt fait ces deux contrôles automatiquement à chaque push et chaque pull request.

Pour vérifier *quand* une ligne a été publiée, regardez l'historique git du fichier : chaque ajout est un commit
du pipeline, daté par GitHub au moment du push (`git log --format='%h %cI %s' -- ledger.jsonl`).

## Limites

- La chaîne rend une falsification **détectable**, elle ne l'empêche pas : le propriétaire du dépôt pourrait réécrire
  le fichier entier et recalculer tous les hachages. Ce qui compte, c'est que les versions déjà publiées existent
  ailleurs (clones, miroirs). **Conservez une copie ou notez le dernier hash** : si le journal change dans
  le passé, les copies divergent.
- Un horodatage indépendant (par exemple OpenTimestamps) renforcerait la preuve. Il n'est pas encore en place.
- Les probabilités sont celles de l'instant de la prédiction. Les résultats viennent de TheSportsDB et peuvent
  être corrigés (voir `correction`).
- Ce journal prouve *quand* et *quoi* a été prédit. Il ne dit pas que le modèle bat les bookmakers.
