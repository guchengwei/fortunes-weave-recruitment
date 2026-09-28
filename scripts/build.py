#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import posixpath
import re
import shutil
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
BASE_URL = "https://guchengwei.github.io/fortunes-weave-recruitment/"
LASTMOD = "2026-09-26"
LANGS = ("zh", "ja", "en")
HTML_LANG = {"zh": "zh-CN", "ja": "ja", "en": "en"}
HREFLANG = {"zh": "zh-Hans", "ja": "ja", "en": "en"}
ROUTE_COLORS = ("#4176a8", "#8869af", "#9b7e28", "#b64d6b")
RPG_SOURCE = "https://www.rpgsite.net/guide/21391-fire-emblem-fortunes-weave-recruitment-guide-all-characters-in-game-how-to-recruit-them"
APPMEDIA_SOURCE = "https://appmedia.jp/fe_banshisenkou"
OUTPUT_MARKER = ".fw-generated-output"


def read_json(path: Path):
    return json.loads(path.read_text())


def json_compact(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=False).replace("</", "<\\/")


def data_uri(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = {".png": "image/png", ".webp": "image/webp", ".svg": "image/svg+xml"}[suffix]
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def plan_id(pair_ids: list[str]) -> str:
    normalized = "\n".join(sorted(pair_ids))
    return "p-" + hashlib.sha256(normalized.encode()).hexdigest()[:16]


def validate_output(path: Path, role: str):
    resolved = path.resolve()
    if resolved == ROOT or ROOT not in resolved.parents:
        raise ValueError(f"output must be a child of repository root: {resolved}")
    protected = (ROOT / ".git", SRC, ROOT / "scripts", ROOT / "tests", ROOT / "reference")
    if any(resolved == item or item in resolved.parents or resolved in item.parents for item in protected):
        raise ValueError(f"output overlaps protected repository content: {resolved}")
    if resolved.exists():
        if not resolved.is_dir():
            raise ValueError(f"output must be a directory: {resolved}")
        marker = resolved / OUTPUT_MARKER
        legacy_site = role == "site" and resolved == ROOT / "dist" and (resolved / "build-manifest.json").is_file()
        legacy_offline = role == "offline" and resolved == ROOT / "artifacts/offline" and {
            "recruitment-planner.html", "recruitment-planner-ja.html", "recruitment-planner-en.html"
        } <= {item.name for item in resolved.iterdir() if item.is_file()}
        if not marker.is_file() and not legacy_site and not legacy_offline:
            raise ValueError(f"refusing to clear unmarked output directory: {resolved}")
        if marker.is_file() and marker.read_text().strip() != role:
            raise ValueError(f"output marker role mismatch: {resolved}")
    return resolved


def prepare_output(resolved: Path, role: str):
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True)
    (resolved / OUTPUT_MARKER).write_text(role + "\n")
    return resolved


class SiteData:
    def __init__(self):
        self.data = read_json(SRC / "assets/recruitment-data.json")
        self.results = read_json(SRC / "assets/optimization-results.json")
        self.names = read_json(SRC / "character-names.json")
        self.i18n = read_json(SRC / "i18n.json")
        self.upgrade = read_json(SRC / "upgrade-copy.json")
        self.extras = read_json(SRC / "recruitment-extras.json")
        self.reader_notes = read_json(SRC / "reader-notes.json")
        self.later = read_json(SRC / "later-characters.json")
        self.identities = read_json(SRC / "identities.json")
        self.icon_manifest = read_json(SRC / "assets/character-icons.json")
        version_inputs = {
            name: read_json(SRC / name)
            for name in (
                "assets/recruitment-data.json",
                "assets/optimization-results.json",
                "recruitment-extras.json",
                "later-characters.json",
            )
        }
        version_inputs["identities.json"] = self.identities
        canonical = json.dumps(version_inputs, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.data_version = hashlib.sha256(canonical.encode()).hexdigest()
        self.character_identity = {item["sourceName"]: item for item in self.identities["characters"]}
        self.route_identity = {item["sourceName"]: item for item in self.identities["routes"]}
        self.route_ids = [item["id"] for item in self.identities["routes"]]
        self.rows = self._make_rows()
        self.row_by_id = {row["id"]: row for row in self.rows}
        self.story_ids = {row["id"] for row in self.rows if row["status"] == "story"}
        self.characters = self._make_characters()
        self.routes = self._make_routes()
        self.plans, self.selectors = self._make_plans()
        self.plan_by_id = {plan["id"]: plan for plan in self.plans}
        self.valid_once_plan_ids = [
            plan["id"] for plan in self.plans
            if plan["scope"] == "once" and plan["metrics"]["coverage"] == 50
            and plan["metrics"]["total"] == 50 and self.story_ids <= set(plan["pairIds"])
        ]
        self.upper = sum(min(2, sum(row["characterId"] == character["id"] and row["status"] != "no" for row in self.rows))
                         for character in self.characters if character["scope"] == "part1")
        self.default_base_plan_id = self._default_base()
        fixtures = read_json(ROOT / "tests/fixtures/expansion.json")
        assert self.data_version == fixtures["dataVersion"]
        assert self.default_base_plan_id == fixtures["defaultBasePlanId"]
        assert self.upper == 93

    def _make_rows(self):
        rows = []
        for source in self.data["rows"]:
            character = self.character_identity[source["name"]]
            route = self.route_identity[source["route"]]
            rows.append({
                "id": f'{character["id"]}@{route["id"]}',
                "characterId": character["id"],
                "routeId": route["id"],
                "sourceName": source["name"],
                "routeSourceName": source["route"],
                "rank": character["rank"],
                "status": source["status"],
                "renown": source["renown"] or 0,
                "support": source["support"] or 0,
                "details": {lang: self.reader_notes[lang].get(text, text) for lang, text in self.extras.get(source["name"], {}).get(source["route"], {}).items()},
            })
        assert len(rows) == len({row["id"] for row in rows}) == 200
        return rows

    def _make_characters(self):
        later_by_source = {item["zh"]: item for item in self.later}
        characters = []
        for identity in self.identities["characters"]:
            source = identity["sourceName"]
            if identity["scope"] == "part1":
                names = {lang: self.names[source][lang] for lang in LANGS}
                icon = self.icon_manifest[source]
                portrait = data_uri(SRC / "assets" / icon["file"])
                portrait_source = icon.get("source", "")
                group = self.names[source].get("group")
                notes = None
            else:
                item = later_by_source[source]
                names = {lang: item[lang] for lang in LANGS}
                portrait = data_uri(SRC / "assets" / item["portrait_file"])
                portrait_source = item.get("portrait_source", "")
                group = None
                notes = {lang: self.reader_notes[lang].get(text, text) for lang, text in item["notes"].items()}
            characters.append({
                **identity,
                "names": names,
                "group": group,
                "portrait": portrait,
                "portraitSource": portrait_source,
                "notes": notes,
            })
        assert len(characters) == 62
        return characters

    def _make_routes(self):
        return [{
            **identity,
            "names": {lang: self.names[identity["sourceName"]][lang] for lang in LANGS},
            "color": ROUTE_COLORS[index],
        } for index, identity in enumerate(self.identities["routes"])]

    def normalize_assignment(self, assignment):
        ids = []
        for source in assignment:
            character_id = self.character_identity[source["name"]]["id"]
            route_id = self.route_identity[source["route"]]["id"]
            ids.append(f"{character_id}@{route_id}")
        for row in self.rows:
            if row["status"] == "story" and row["sourceName"] not in self.data["targets"]:
                ids.append(row["id"])
        unique = sorted(set(ids))
        if len(unique) != len(ids):
            raise ValueError("assignment normalization produced a duplicate pair")
        return unique

    def metrics(self, pair_ids):
        selected = [self.row_by_id[pair_id] for pair_id in pair_ids]
        people = Counter(row["characterId"] for row in selected)
        counts = [sum(row["routeId"] == route_id and row["status"] != "story" for row in selected)
                  for route_id in self.route_ids]
        gates = [max([2] + [row["renown"] for row in selected if row["routeId"] == route_id])
                 for route_id in self.route_ids]
        frequency = Counter(people.values())
        return {
            "coverage": len(people),
            "total": len(selected),
            "frequency": {str(key): value for key, value in sorted(frequency.items())},
            "r": sum(row["renown"] for row in selected),
            "s": sum(max(0, row["support"] - 1) for row in selected if row["status"] == "recruit"),
            "recruitCounts": counts,
            "gates": gates,
            "delta": max(counts) - min(counts),
        }

    def _make_plans(self):
        catalog = {}
        selectors = {}
        for result_key, scope in (("inclusive", "once"), ("twice", "twice")):
            raw = self.results[result_key]
            selector = {"frontier": [], "threshold": [], "additive": [], "product": None,
                        "minDelta": raw.get("min_delta", 0)}
            for family, source_plans in (
                ("frontier", raw["balanced_frontier"]),
                ("threshold", raw["threshold"]),
                ("additive", raw["additive"]),
                ("product", [raw["product"]]),
            ):
                ids = []
                for source_plan in source_plans:
                    pair_ids = self.normalize_assignment(source_plan["assignment"])
                    identifier = plan_id(pair_ids)
                    metrics = self.metrics(pair_ids)
                    expected_total = 50 if scope == "once" else 93
                    assert metrics["coverage"] == 50 and metrics["total"] == expected_total
                    assert self.story_ids <= set(pair_ids)
                    objective = {
                        "r": source_plan.get("r", metrics["r"]),
                        "value": source_plan.get("value"),
                        "caps": source_plan.get("caps"),
                    }
                    record = {
                        "id": identifier,
                        "scope": scope,
                        "pairIds": pair_ids,
                        "r": metrics["r"],
                        "s": metrics["s"],
                        "objectives": {family: objective},
                        "families": [family],
                        "metrics": metrics,
                    }
                    if identifier in catalog:
                        if catalog[identifier]["pairIds"] != pair_ids:
                            raise ValueError(f"plan ID collision: {identifier}")
                        if family not in catalog[identifier]["families"]:
                            catalog[identifier]["families"].append(family)
                        prior = catalog[identifier]["objectives"].get(family)
                        if prior is not None and prior != objective:
                            raise ValueError(f"conflicting {family} provenance for {identifier}")
                        catalog[identifier]["objectives"][family] = objective
                    else:
                        catalog[identifier] = record
                    ids.append(identifier)
                if family == "product":
                    selector[family] = ids[0]
                else:
                    selector[family] = list(dict.fromkeys(ids))
            selector["all"] = list(dict.fromkeys(
                selector["frontier"] + selector["threshold"] + selector["additive"] + [selector["product"]]
            ))
            selectors[scope] = selector
        return list(catalog.values()), selectors

    def _default_base(self):
        plans = [self.plan_by_id[identifier] for identifier in self.selectors["once"]["frontier"]]
        plans.sort(key=lambda plan: (4 * plan["r"] + 4 * plan["s"], plan["metrics"]["delta"], plan["s"], plan["r"]))
        return plans[0]["id"]

    def model(self, lang):
        copy = {**self.i18n[lang], **self.upgrade[lang]}
        return {
            "language": lang,
            "htmlLanguage": HTML_LANG[lang],
            "dataVersion": self.data_version,
            "defaultBasePlanId": self.default_base_plan_id,
            "upper": self.upper,
            "routeIds": self.route_ids,
            "routes": self.routes,
            "characters": self.characters,
            "rows": self.rows,
            "plans": self.plans,
            "selectors": self.selectors,
            "validOncePlanIds": self.valid_once_plan_ids,
            "copy": copy,
            "seal": data_uri(SRC / "assets/coaster-style-c-atlas.webp"),
            "links": {
                "base": BASE_URL,
                "rpg": RPG_SOURCE,
                "appmedia": APPMEDIA_SOURCE,
            },
        }


def e(value) -> str:
    return html.escape(str(value), quote=True)


def localized_name(item, lang):
    return item["names"][lang]


def status_text(row, copy, lang):
    if row["status"] == "story":
        return copy["story"]
    if row["status"] == "free":
        return f'{copy["renown"]} {row["renown"]} · {copy["free"]}'
    if row["status"] == "recruit":
        return f'{copy["renown"]} {row["renown"]} · {copy["supportLevel"]} {row["support"]}'
    return copy["no"]


def condition_details(row, copy, lang):
    return row["details"].get(lang, "")


def locale_path(lang, kind="planner", route_id=None):
    if kind == "planner":
        return {"zh": "", "ja": "ja.html", "en": "en.html"}[lang]
    prefix = "" if lang == "zh" else f"{lang}/"
    if kind == "methods":
        return f"{prefix}methods.html"
    return f"{prefix}routes/{route_id}.html"


def canonical_url(lang, kind="planner", route_id=None):
    return BASE_URL + locale_path(lang, kind, route_id)


def output_path(lang, kind="planner", route_id=None):
    path = locale_path(lang, kind, route_id)
    return path or "index.html"


def locale_href(source_lang, target_lang, kind="planner", route_id=None):
    source = output_path(source_lang, kind, route_id)
    target = output_path(target_lang, kind, route_id)
    return posixpath.relpath(target, posixpath.dirname(source) or ".")


def local_navigation(content, current_path, offline=False):
    def replace(match):
        target = html.unescape(match.group(1))[len(BASE_URL):]
        path, sep, fragment = target.partition("#")
        if offline:
            return 'href="' + ("#methods" if "methods.html" in path else "#original") + '"'
        path, query_sep, query = path.partition("?")
        relative = posixpath.relpath(path or "index.html", posixpath.dirname(current_path) or ".")
        return 'href="' + e(relative + (query_sep + query if query_sep else "") + (sep + fragment if sep else "")) + '"'
    return re.sub(r'href="(' + re.escape(BASE_URL) + r'[^"<>]*)"', replace, content)


def head_markup(lang, title, description, canonical, kind="planner", route_id=None, json_ld=None, offline=False):
    links = []
    for target in LANGS:
        links.append(f'<link rel="alternate" hreflang="{HREFLANG[target]}" href="{e(canonical_url(target, kind, route_id))}">')
    links.append(f'<link rel="alternate" hreflang="x-default" href="{e(canonical_url("zh", kind, route_id))}">')
    structured = f'<script type="application/ld+json">{json_compact(json_ld)}</script>' if json_ld else ""
    icon = data_uri(SRC / "assets/coaster-style-c-atlas.webp") if offline else posixpath.relpath("assets/site-icon.webp", posixpath.dirname(output_path(lang, kind, route_id)) or ".")
    share = BASE_URL + "assets/share-card.svg"
    return f'''<title>{e(title)}</title>
  <link rel="icon" type="image/webp" href="{e(icon)}">
  <meta name="description" content="{e(description)}">
  <link rel="canonical" href="{e(canonical)}">
  {''.join(links)}
  <meta property="og:title" content="{e(title)}">
  <meta property="og:description" content="{e(description)}">
  <meta property="og:url" content="{e(canonical)}">
  <meta property="og:type" content="website">
  <meta property="og:image" content="{e(share)}">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:image:alt" content="{e(title)}">
  {structured}'''


def language_nav(lang, kind="planner", route_id=None, offline=False):
    names = {"zh": "中文", "ja": "日本語", "en": "English"}
    if offline:
        return '<nav class="language-nav" aria-label="Language">' + "".join(
            f'<button type="button" data-switch-language="{target}"'
            + (' aria-current="page"' if target == lang else '') + f'>{names[target]}</button>'
            for target in LANGS
        ) + "</nav>"
    targets = {key: locale_href(lang, key, kind, route_id) for key in LANGS}
    return '<nav class="language-nav" aria-label="Language">' + "".join(
        f'<a data-locale="{target}" href="{e(targets[target])}"' + (' aria-current="page"' if target == lang else '') + f'>{names[target]}</a>'
        for target in LANGS
    ) + "</nav>"


def static_summary(site: SiteData, model, plan):
    copy = model["copy"]
    metrics = plan["metrics"]
    return f'<p class="plan-summary">{e(copy["coverageMetric"])} <strong>{metrics["coverage"]}</strong> · {e(copy["totalJoins"])} <strong>{metrics["total"]}</strong></p>'


def static_routes(site: SiteData, model, plan):
    lang, copy = model["language"], model["copy"]
    selected = set(plan["pairIds"])
    character_by_id = {character["id"]: character for character in model["characters"]}
    cards = []
    for route in model["routes"]:
        route_rows = [row for row in model["rows"] if row["routeId"] == route["id"] and row["id"] in selected]
        route_rows.sort(key=lambda row: ({"story": 0, "free": 1, "recruit": 2}[row["status"]], row["renown"], row["support"], row["rank"]))
        items = []
        for row in route_rows:
            person = character_by_id[row["characterId"]]
            detail = row["details"].get(lang, "")
            note_id = "condition-route-" + row["id"].replace("@", "-")
            note_title = f'{localized_name(person, lang)} · {localized_name(route, lang)}'
            aliases = " · ".join(person["names"][key] for key in LANGS if key != lang)
            note = f'<button type="button" class="condition-trigger" popovertarget="{note_id}" aria-label="{e(copy["openCharacter"] + ": " + note_title)}"><span aria-hidden="true">ⓘ</span></button><div id="{note_id}" class="condition-popover" popover><header><strong>{e(note_title)}</strong><button type="button" popovertarget="{note_id}" popovertargetaction="hide" aria-label="{e(copy["close"])}">×</button></header><p class="name-translations">{e(aliases)}</p><p class="condition-note">{e(detail)}</p></div>'
            items.append(f'''<li class="route-row">
              <img class="portrait" src="{person['portrait']}" width="48" height="48" alt="">
              <div><div class="row-title"><strong>{e(localized_name(person, lang))}</strong></div>
              <div class="row-facts"><span class="row-copy">{e(status_text(row, copy, lang))}</span>{note}</div></div>
            </li>''')
        cards.append(f'''<article class="route-card" data-route-card="{route['id']}" style="--route-color:{route['color']}">
          <header><div><h3>{e(localized_name(route, lang))}</h3><p>{e(copy['routeCounts'])}: {plan['metrics']['recruitCounts'][route['index']]}</p>
          <p><a href="{e(canonical_url(lang, 'route', route['id']))}">{e(copy['routeGuide'])}</a></p></div>
          <span class="tag">{e(copy['maxGate'])} {plan['metrics']['gates'][route['index']]}</span></header>
          <ul class="route-rows">{''.join(items)}</ul></article>''')
    return "".join(cards)


def static_roster(site: SiteData, model):
    lang, copy = model["language"], model["copy"]
    rows_by_character = {character["id"]: [row for row in model["rows"] if row["characterId"] == character["id"]]
                         for character in model["characters"]}
    cards = []
    for person in model["characters"]:
        aliases = " · ".join(person["names"][key] for key in LANGS if key != lang)
        if person["scope"] == "part1":
            conditions = []
            for route in model["routes"]:
                row = next(row for row in rows_by_character[person["id"]] if row["routeId"] == route["id"])
                conditions.append(f'''<div class="condition" style="--route-color:{route['color']}">
                  <strong>{e(localized_name(route, lang))} · {e(status_text(row, copy, lang))}</strong>
                  {f'<p>{e(condition_details(row, copy, lang))}</p>' if condition_details(row, copy, lang) else ''}</div>''')
            body = f'<div class="condition-grid">{"".join(conditions)}</div>'
            badge = "1×"
        else:
            body = f'<p>{e(person["notes"][lang])}</p><p><a href="{e(person["portraitSource"])}">{e(copy["viewSource"])}</a></p>'
            badge = copy["referenceOnly"]
        cards.append(f'''<details class="person-card" id="character-{person['id']}" data-character-card="{person['id']}">
          <summary><img class="portrait" src="{person['portrait']}" width="48" height="48" alt=""><span><strong>{e(localized_name(person, lang))}</strong>
          <span class="aliases">{e(aliases)}</span></span><span class="tag">{e(badge)}</span></summary>
          <div class="person-body">{body}</div></details>''')
    return "".join(cards)


def planner_json_ld(model, canonical):
    copy = model["copy"]
    return {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "WebSite", "@id": BASE_URL + "#website", "url": BASE_URL,
             "name": copy["title"], "inLanguage": ["zh-CN", "ja", "en"]},
            {"@type": "WebPage", "@id": canonical + "#webpage", "url": canonical,
             "name": copy["metaTitle"], "description": copy["metaDescription"],
             "inLanguage": HTML_LANG[model["language"]], "isPartOf": {"@id": BASE_URL + "#website"}},
            {"@type": "WebApplication", "@id": canonical + "#planner", "url": canonical,
             "name": copy["metaTitle"], "description": copy["metaDescription"],
             "applicationCategory": "GameApplication", "operatingSystem": "Any",
             "isAccessibleForFree": True, "inLanguage": HTML_LANG[model["language"]]},
        ],
    }


def planner_main(site: SiteData, model, offline=False):
    lang, copy = model["language"], model["copy"]
    plan = site.plan_by_id[site.default_base_plan_id]
    mode_cards = "".join(
        f'''<button class="choice-card" type="button" data-mode="{mode}" aria-pressed="{'true' if mode == 'once' else 'false'}" data-focus-key="mode-{mode}">
        <strong>{e(copy['mode' + title])}</strong><span>{e(copy['mode' + title + 'Description'])}</span></button>'''
        for mode, title in (("once", "Once"), ("expand", "Expand"), ("twice", "Twice"))
    )
    route_tabs = '<div class="route-tabs" role="tablist" aria-label="Routes">' + \
        f'<button type="button" role="tab" data-route="all" aria-selected="true">{e(copy["allRoutes"])}</button>' + "".join(
            f'<button type="button" role="tab" data-route="{route["id"]}" aria-selected="false">{e(localized_name(route, lang))}</button>'
            for route in model["routes"]
        ) + "</div>"
    offline_note = f'<p class="notice">{e(copy["offlineNotice"])}</p>' if offline else ""
    return f'''<header class="hero"><div class="shell hero-grid"><div class="hero-copy">
      <div class="eyebrow">{e(copy['eyebrow'])}</div><h1>{e(copy['metaTitle'])}</h1>
      <p class="lede">{e(copy['intro'])}</p><p class="scope-line">{e(copy['scopeLine'])}</p>
      {language_nav(lang, offline=offline)}</div><img class="seal" src="{model['seal']}" width="220" height="200" alt=""></div></header>
      <nav class="primary-nav" aria-label="Primary"><div class="shell"><a href="#optimizer">{e(copy['plan'])}</a>
      <a href="#allocation">{e(copy['allocation'])}</a><a href="#original">{e(copy['roster'])}</a><a href="#methods">{e(copy['methodsSources'])}</a></div></nav>
      <main class="shell"><noscript><p class="notice">{e(copy['interactiveNeedsJs'])}</p></noscript>{offline_note}
      <section id="optimizer" class="panel"><div class="section-heading"><div><h2>{e(copy['modeHeading'])}</h2><p>{e(copy['partOneScope'])}</p></div></div>
      <div class="mode-grid" id="mode-controls">{mode_cards}</div>
      <div id="planner-controls" class="controls-stack"><h3>{e(copy['goalHeading'])}</h3>
      <div class="goal-grid">{''.join(f'<button type="button" class="choice-card" data-goal="{goal}" aria-pressed="{str(goal == "compromise").lower()}"><strong>{e(copy[goal])}</strong></button>' for goal in ('early','support','compromise'))}</div>
      <details class="advanced"><summary>{e(copy['advanced'])}</summary><p>{e(copy['weightHelp'])}</p></details></div>
      <div class="planner-footer"><div id="summary">{static_summary(site, model, plan)}</div><div class="control-row toolbar-actions"><button type="button" class="button" data-action="share">{e(copy['share'])}</button>
      <button type="button" class="button quiet" data-action="reset">{e(copy['reset'])}</button></div>
      </div><div id="planner-notice" class="notice" role="status"></div>
      <div id="live-region" class="visually-hidden" aria-live="polite"></div></section>
      <section id="allocation"><div class="section-heading"><div><h2>{e(copy['allocation'])}</h2><p>{e(copy['routeNote'])}</p></div></div>
      <div id="route-tabs">{route_tabs}</div><div class="route-grid" id="routes">{static_routes(site, model, plan)}</div>
      </section>
      <section id="original"><span id="matrix"></span><div class="section-heading"><div><h2>{e(copy['roster'])}</h2><p>{e(copy['rosterNote'])}</p></div></div>
      <div id="roster-tools" class="toolbar"><label class="field search-field"><span>{e(copy['searchLabel'])}</span><input type="search" data-search placeholder="{e(copy['searchPlaceholder'])}"></label>
      <button type="button" class="button quiet" data-action="clear-search">{e(copy['clearSearch'])}</button></div>
      <p id="roster-count" class="roster-count">{e(copy['showing'])} 62 {e(copy['of'])} 62</p><div id="roster-content" class="roster-grid">{static_roster(site, model)}</div></section>
      <section id="methods"><details class="methods-disclosure panel"><summary><h2>{e(copy['methodsSources'])}</h2></summary><p>{e(copy['checkedDate'])} · {e(copy['unofficial'])}</p>
      <div class="method-grid"><article class="method-card"><h3>{e(copy['modeOnce'])}</h3><p>{e(copy['rulesBody'])}</p></article>
      <article class="method-card"><h3>{e(copy['modeExpand'])}</h3><p>{e(copy['proxyWarning'])}</p></article>
      <article class="method-card"><h3>{e(copy['modeTwice'])}</h3><p>{e(copy['twiceExceptions'])}</p></article></div>
      <details class="advanced"><summary>{e(copy['rules'])}</summary><p>{e(copy['paretoMethod'])}</p><p>{e(copy['paretoExample'])}</p><p>{e(copy['methods'])}</p><p>{e(copy['supportTip'])}</p></details>
      <ul class="source-list"><li><a href="{RPG_SOURCE}">RPG Site · recruitment guide</a></li><li><a href="{APPMEDIA_SOURCE}">AppMedia · Japanese reference</a></li>
      <li>{e(copy['sourceInfo'])}</li></ul><p><a href="{e(canonical_url(lang, 'methods'))}">{e(copy['methodsPage'])}</a></p></details></section>
      <footer class="footer">{e(copy['footer'])} · {e(copy['unofficial'])}</footer></main>'''


def build_planner(site: SiteData, out: Path, offline_out: Path):
    template = (SRC / "page.html").read_text()
    style = (SRC / "styles.css").read_text()
    core = (SRC / "planner-core.mjs").read_text()
    core = re.sub(r"\bexport\s+(?=(?:const|function)\b)", "", core)
    script = core + "\n" + (SRC / "app.js").read_text()
    models = {lang: site.model(lang) for lang in LANGS}
    offline_content = {
        lang: f'<a class="skip-link" href="#optimizer">{e(models[lang]["copy"]["plan"])}</a>'
              + local_navigation(planner_main(site, models[lang], True), output_path(lang), True)
        for lang in LANGS
    }
    for lang in LANGS:
        model = models[lang]
        canonical = canonical_url(lang)
        head = head_markup(lang, model["copy"]["metaTitle"], model["copy"]["metaDescription"], canonical,
                           json_ld=planner_json_ld(model, canonical))
        online = template.replace("__HTML_LANG__", HTML_LANG[lang]).replace("__HEAD__", head)
        online = online.replace("__STYLE__", style).replace("__LANG__", lang).replace("__OFFLINE__", "false")
        online = online.replace("__SKIP__", e(model["copy"]["plan"])).replace("__MAIN__", local_navigation(planner_main(site, model), output_path(lang)))
        online = online.replace("__DATA__", json_compact(model)).replace("__OFFLINE_LOCALES__", "{}")
        online = online.replace("__SCRIPT__", script)
        target = out / ({"zh": "index.html", "ja": "ja.html", "en": "en.html"}[lang])
        target.write_text(online.rstrip() + "\n")
        offline_head = head_markup(lang, model["copy"]["metaTitle"], model["copy"]["metaDescription"], canonical,
                                   json_ld=planner_json_ld(model, canonical), offline=True)
        offline = template.replace("__HTML_LANG__", HTML_LANG[lang]).replace("__HEAD__", offline_head)
        offline = offline.replace("__STYLE__", style).replace("__LANG__", lang).replace("__OFFLINE__", "true")
        offline = offline.replace("__SKIP__", e(model["copy"]["plan"])).replace("__MAIN__", local_navigation(planner_main(site, model, True), output_path(lang), True))
        locale_pack = {
            target: {
                "model": {
                    "language": target,
                    "htmlLanguage": HTML_LANG[target],
                    "copy": models[target]["copy"],
                },
                "title": models[target]["copy"]["metaTitle"],
                "description": models[target]["copy"]["metaDescription"],
                "content": "" if target == lang else offline_content[target],
            }
            for target in LANGS
        }
        offline = offline.replace("__DATA__", json_compact(model)).replace("__OFFLINE_LOCALES__", json_compact(locale_pack))
        offline = offline.replace("__SCRIPT__", script)
        offline_name = {"zh": "recruitment-planner.html", "ja": "recruitment-planner-ja.html", "en": "recruitment-planner-en.html"}[lang]
        (offline_out / offline_name).write_text(offline.rstrip() + "\n")


def static_page_shell(lang, title, description, canonical, body, kind, route_id=None, json_ld=None):
    body = local_navigation(body, output_path(lang, kind, route_id))
    head = head_markup(lang, title, description, canonical, kind, route_id, json_ld)
    return f'''<!doctype html><html lang="{HTML_LANG[lang]}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">{head}<style>{(SRC / 'styles.css').read_text()}</style></head><body>{body}</body></html>'''


def breadcrumb_json(lang, current_name, current_url):
    copy = {**read_json(SRC / "i18n.json")[lang], **read_json(SRC / "upgrade-copy.json")[lang]}
    return {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "WebSite", "@id": BASE_URL + "#website", "url": BASE_URL,
             "name": copy["title"], "inLanguage": ["zh-CN", "ja", "en"]},
            {"@type": "WebPage", "@id": current_url + "#webpage", "url": current_url,
             "name": current_name, "inLanguage": HTML_LANG[lang], "isPartOf": {"@id": BASE_URL + "#website"}},
            {"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": copy["breadcrumbsHome"], "item": canonical_url(lang)},
                {"@type": "ListItem", "position": 2, "name": current_name, "item": current_url},
            ]},
        ],
    }


def guide_header(model, title, intro, kind, route_id=None):
    copy, lang = model["copy"], model["language"]
    return f'''<header class="hero"><div class="shell"><div class="eyebrow">{e(copy['eyebrow'])}</div><h1>{e(title)}</h1><p class="lede">{e(intro)}</p>
    {language_nav(lang, kind, route_id)}</div></header><main class="shell">'''


def build_route_pages(site: SiteData, out: Path):
    character_by_id = {character["id"]: character for character in site.characters}
    for route in site.routes:
        for lang in LANGS:
            model, copy = site.model(lang), site.model(lang)["copy"]
            route_name = localized_name(route, lang)
            title = f'{route_name} · {copy["routeGuideTitle"]}'
            description = f'{route_name}: {copy["routeFactsIntro"]}'
            canonical = canonical_url(lang, "route", route["id"])
            rows = [row for row in site.rows if row["routeId"] == route["id"]]
            rows.sort(key=lambda row: row["rank"])
            table_rows = []
            for row in rows:
                person = character_by_id[row["characterId"]]
                planner_link = canonical_url(lang) + f'#character-{person["id"]}'
                table_rows.append(f'''<tr><th scope="row"><a href="{e(planner_link)}">{e(localized_name(person, lang))}</a></th>
                <td>{e(status_text(row, copy, lang))}</td><td>{e(condition_details(row, copy, lang))}</td></tr>''')
            body = guide_header(model, title, copy["routeFactsIntro"], "route", route["id"]) + f'''
            <nav class="breadcrumb" aria-label="Breadcrumb"><a href="{e(canonical_url(lang))}">{e(copy['breadcrumbsHome'])}</a><span aria-hidden="true">/</span><span>{e(route_name)}</span></nav>
            <div class="matrix-wrap"><table class="guide-table"><thead><tr><th>{e(copy['character'])}</th><th>{e(copy['joinMethod'])}</th><th>{e(copy['additionalConditions'])}</th></tr></thead>
            <tbody>{''.join(table_rows)}</tbody></table></div>
            <p>{e(copy['laterLinkNote'])} <a href="{e(canonical_url(lang) + '#original')}">{e(copy['roster'])}</a></p>
            <p><a class="button" href="{e(canonical_url(lang) + '?route=' + route['id'] + '#allocation')}">{e(copy['backPlanner'])}</a></p>
            <section id="sources" class="panel"><h2>{e(copy['methodsSources'])}</h2><p>{e(copy['checkedDate'])}</p><ul class="source-list"><li><a href="{RPG_SOURCE}">RPG Site</a></li><li><a href="{APPMEDIA_SOURCE}">AppMedia</a></li></ul></section>
            <footer class="footer">{e(copy['unofficial'])}</footer></main>'''
            page = static_page_shell(lang, title, description, canonical, body, "route", route["id"], breadcrumb_json(lang, title, canonical))
            target = out / locale_path(lang, "route", route["id"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(page)


def method_sections(copy):
    return f'''<div class="method-grid"><article class="method-card"><h2>{e(copy['modeOnce'])}</h2><p>{e(copy['rulesBody'])}</p></article>
      <article class="method-card"><h2>{e(copy['modeExpand'])}</h2><p>{e(copy['methodExpansionCap'])}</p><p>{e(copy['methodExpansionCutoff'])}</p></article>
      <article class="method-card"><h2>{e(copy['modeTwice'])}</h2><p>{e(copy['twiceExceptions'])}</p></article></div>
      <section class="panel"><h2>R / S / Δ</h2><p>{e(copy['paretoMethod'])}</p><p>{e(copy['paretoExample'])}</p><p>{e(copy['methods'])}</p></section>
      <section class="panel"><h2>{e(copy['baseVsResult'])}</h2><p>{e(copy['methodExpansionBaseline'])}</p><p>{e(copy['baselineLimitNote'])}</p>
      <p>{e(copy['methodExpansionSelection'])}</p><p>{e(copy['methodExpansionGateRemoval'])}</p><p>{e(copy['proxyWarning'])}</p></section>'''


def build_method_pages(site: SiteData, out: Path):
    for lang in LANGS:
        model, copy = site.model(lang), site.model(lang)["copy"]
        title = f'{copy["methodsPage"]} · {copy["title"]}'
        description = copy["rulesBody"] + " " + copy["proxyWarning"]
        canonical = canonical_url(lang, "methods")
        body = guide_header(model, title, copy["sourceInfo"], "methods") + f'''
        <nav class="breadcrumb" aria-label="Breadcrumb"><a href="{e(canonical_url(lang))}">{e(copy['breadcrumbsHome'])}</a><span aria-hidden="true">/</span><span>{e(copy['methodsPage'])}</span></nav>
        <p class="direct-answer">{e(copy['rulesBody'])}</p>{method_sections(copy)}
        <section class="panel"><h2>{e(copy['methodsSources'])}</h2><p>{e(copy['sourceInfo'])}</p><p>{e(copy['checkedDate'])}</p>
        <ul class="source-list"><li><a href="{RPG_SOURCE}">RPG Site · recruitment guide</a></li><li><a href="{APPMEDIA_SOURCE}">AppMedia</a></li></ul></section>
        <p><a class="button" href="{e(canonical_url(lang))}">{e(copy['backPlanner'])}</a></p><footer class="footer">{e(copy['unofficial'])}</footer></main>'''
        page = static_page_shell(lang, title, description, canonical, body, "methods", json_ld=breadcrumb_json(lang, title, canonical))
        target = out / locale_path(lang, "methods")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page)


def build_share_card(site: SiteData, out: Path):
    seal = data_uri(SRC / "assets/coaster-style-c-atlas.webp")
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
    <rect width="1200" height="630" fill="#f6f0e3"/><rect x="60" y="56" width="1080" height="518" fill="#fffdf7" stroke="#c9cfbf" stroke-width="2"/>
    <rect x="60" y="56" width="18" height="518" fill="#1e5a43"/><image href="{seal}" x="800" y="110" width="300" height="310" opacity=".16" preserveAspectRatio="xMidYMid meet"/>
    <text x="120" y="150" fill="#947329" font-family="Arial, sans-serif" font-size="24" font-weight="700" letter-spacing="5">FORTUNE'S WEAVE</text>
    <text x="120" y="245" fill="#18362d" font-family="Georgia, serif" font-size="62" font-weight="700">Recruitment Atlas</text>
    <text x="120" y="315" fill="#18362d" font-family="Arial, sans-serif" font-size="30">Part I · four routes · 62-character reference</text>
    <line x1="120" y1="380" x2="720" y2="380" stroke="#c9cfbf" stroke-width="2"/>
    <text x="120" y="445" fill="#4f675f" font-family="Arial, sans-serif" font-size="26">Everyone once · Once + easy extras · As close to twice as possible</text>
    <text x="120" y="515" fill="#1e5a43" font-family="Arial, sans-serif" font-size="23" font-weight="700">guchengwei.github.io/fortunes-weave-recruitment/</text></svg>'''
    assets = out / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "share-card.svg").write_text(svg)


def build_sitemap(site: SiteData, out: Path):
    urls = [canonical_url(lang) for lang in LANGS]
    urls += [canonical_url(lang, "methods") for lang in LANGS]
    urls += [canonical_url(lang, "route", route_id) for lang in LANGS for route_id in site.route_ids]
    assert len(urls) == len(set(urls)) == 18
    body = "".join(f"<url><loc>{e(url)}</loc><lastmod>{LASTMOD}</lastmod></url>" for url in urls)
    (out / "sitemap.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>')


def main():
    parser = argparse.ArgumentParser(description="Build the Fortune's Weave recruitment site.")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--offline-dir", type=Path, required=True)
    args = parser.parse_args()
    out_candidate = (args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir).resolve()
    offline_candidate = (args.offline_dir if args.offline_dir.is_absolute() else ROOT / args.offline_dir).resolve()
    if out_candidate == offline_candidate or out_candidate in offline_candidate.parents or offline_candidate in out_candidate.parents:
        raise ValueError("site and offline outputs must not overlap")
    out = validate_output(out_candidate, "site")
    offline = validate_output(offline_candidate, "offline")
    out = prepare_output(out, "site")
    offline = prepare_output(offline, "offline")
    site = SiteData()
    build_planner(site, out, offline)
    build_route_pages(site, out)
    build_method_pages(site, out)
    build_share_card(site, out)
    shutil.copyfile(SRC / "assets/coaster-style-c-atlas.webp", out / "assets/site-icon.webp")
    build_sitemap(site, out)
    (out / ".nojekyll").write_text("")
    site_files = sorted(
        str(path.relative_to(out)) for path in out.rglob("*")
        if path.is_file() and path.name != OUTPUT_MARKER
    )
    manifest = {
        "dataVersion": site.data_version,
        "defaultBasePlanId": site.default_base_plan_id,
        "siteFiles": site_files + ["build-manifest.json"],
        "offlineFiles": sorted(
            str(path.relative_to(offline)) for path in offline.rglob("*")
            if path.is_file() and path.name != OUTPUT_MARKER
        ),
    }
    (out / "build-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"Built {len(manifest['siteFiles'])} site files and {len(manifest['offlineFiles'])} offline editions.")
    print(f"dataVersion: {site.data_version}")
    print(f"defaultBasePlanId: {site.default_base_plan_id}")


if __name__ == "__main__":
    main()
