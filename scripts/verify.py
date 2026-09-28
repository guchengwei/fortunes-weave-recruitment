#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import posixpath
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://guchengwei.github.io/fortunes-weave-recruitment/"
BASE_PATH = "/fortunes-weave-recruitment/"
LANG_FILES = {"zh": "index.html", "ja": "ja.html", "en": "en.html"}
HTML_LANG = {"zh": "zh-CN", "ja": "ja", "en": "en"}
ROUTES = ("cai", "dietrich", "theodora", "leda")
OUTPUT_MARKER = ".fw-generated-output"
UPGRADE_COPY = json.loads((ROOT / "src/upgrade-copy.json").read_text())


class InventoryParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = []
        self.hrefs = []
        self.img_sources = []
        self.script_sources = []
        self.stylesheet_hrefs = []
        self.h1_count = 0
        self.tr_count = 0
        self.html_lang = None
        self.canonicals = []
        self.alternates = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids.append(values["id"])
        if tag == "html":
            self.html_lang = values.get("lang")
        if tag == "h1":
            self.h1_count += 1
        if tag == "tr":
            self.tr_count += 1
        if tag == "a" and values.get("href"):
            self.hrefs.append(values["href"])
        if tag == "img" and values.get("src"):
            self.img_sources.append(values["src"])
        if tag == "script" and values.get("src"):
            self.script_sources.append(values["src"])
        if tag == "link":
            rel = set((values.get("rel") or "").split())
            if "canonical" in rel:
                self.canonicals.append(values.get("href"))
            if "alternate" in rel:
                self.alternates.append((values.get("hreflang"), values.get("href")))
            if "stylesheet" in rel:
                self.stylesheet_hrefs.append(values.get("href"))


def parse(path: Path):
    parser = InventoryParser()
    parser.feed(path.read_text())
    return parser


def expected_pages():
    pages = set(LANG_FILES.values())
    pages |= {"methods.html", "ja/methods.html", "en/methods.html"}
    pages |= {f"routes/{route}.html" for route in ROUTES}
    pages |= {f"ja/routes/{route}.html" for route in ROUTES}
    pages |= {f"en/routes/{route}.html" for route in ROUTES}
    return pages


def canonical_for(relative: str):
    return BASE_URL if relative == "index.html" else BASE_URL + relative


def canonical_url(lang: str, kind: str, route_id: str | None = None):
    prefix = "" if lang == "zh" else f"{lang}/"
    relative = f"{prefix}methods.html" if kind == "methods" else f"{prefix}routes/{route_id}.html"
    return BASE_URL + relative


def page_path(lang: str, kind: str = "planner", route_id: str | None = None):
    if kind == "planner":
        return LANG_FILES[lang]
    prefix = "" if lang == "zh" else f"{lang}/"
    return f"{prefix}methods.html" if kind == "methods" else f"{prefix}routes/{route_id}.html"


def locale_href(source_lang: str, target_lang: str, kind: str = "planner", route_id: str | None = None):
    source = page_path(source_lang, kind, route_id)
    target = page_path(target_lang, kind, route_id)
    return posixpath.relpath(target, posixpath.dirname(source) or ".")


def extract_json_scripts(text: str, script_type: str):
    return [json.loads(match) for match in re.findall(
        rf'<script type="{re.escape(script_type)}"(?: id="[^"]+")?>([\s\S]*?)</script>', text
    )]


def extract_json_script_by_id(text: str, identifier: str):
    matches = re.findall(
        rf'<script type="application/json" id="{re.escape(identifier)}">([\s\S]*?)</script>', text
    )
    assert len(matches) == 1, identifier
    return json.loads(matches[0])


def verify_planners(site_dir: Path):
    for lang, relative in LANG_FILES.items():
        path = site_dir / relative
        text = path.read_text()
        parser = parse(path)
        assert parser.html_lang == HTML_LANG[lang], (relative, parser.html_lang)
        assert parser.h1_count == 1, relative
        assert parser.canonicals == [canonical_for(relative)], (relative, parser.canonicals)
        assert {key for key, _ in parser.alternates} == {"zh-Hans", "ja", "en", "x-default"}
        character_ids = {identifier for identifier in parser.ids if identifier.startswith("character-")}
        assert len(character_ids) == 62, (relative, len(character_ids))
        assert {f"character-c-{index:03d}" for index in range(50)} <= character_ids
        assert {f"character-l-{index:03d}" for index in range(12)} <= character_ids
        assert all(source.startswith("data:image/") for source in parser.img_sources), relative
        model = extract_json_script_by_id(text, "planner-data")
        assert len(model["characters"]) == 62 and len(model["rows"]) == 200
        assert model["dataVersion"] == "d1fb224e6b4e5be80f8b9f6d3b27a32b4d8ea6105610db44a140b5b3f83fc43a"
        assert model["defaultBasePlanId"] == "p-c58caacbfac49668" and model["upper"] == 93
        assert sum(row["status"] == "story" for row in model["rows"]) == 18
        plans = {plan["id"]: plan for plan in model["plans"]}
        once = [plans[identifier] for identifier in model["selectors"]["once"]["all"]]
        twice = [plans[identifier] for identifier in model["selectors"]["twice"]["all"]]
        assert all(plan["metrics"]["coverage"] == 50 and plan["metrics"]["total"] == 50 for plan in once)
        assert all(plan["metrics"]["coverage"] == 50 and plan["metrics"]["total"] == 93 for plan in twice)
        assert min(plan["r"] for plan in once) == 171 and min(plan["s"] for plan in once) == 30
        assert min(plan["r"] for plan in twice) == 453 and min(plan["s"] for plan in twice) == 91
        default = plans[model["defaultBasePlanId"]]
        assert (default["r"], default["s"]) == (173, 34)
        assert any(plan["metrics"]["recruitCounts"] == [18, 19, 19, 19] for plan in twice)
        for scope in ("once", "twice"):
            for identifier in model["selectors"][scope]["threshold"]:
                plan = plans[identifier]
                objective = plan["objectives"]["threshold"]
                assert objective["r"] == sum(plan["metrics"]["gates"])
                assert objective["caps"] == plan["metrics"]["gates"]
        json_ld = extract_json_scripts(text, "application/ld+json")
        assert len(json_ld) == 1 and len(json_ld[0]["@graph"]) == 3
        assert "RPG Site" in text and "AppMedia" in text
        assert "routes/cai.html" in text and "methods.html" in text
        assert {locale_href(lang, target) for target in LANG_FILES} <= set(parser.hrefs)
        assert "<title>Fire Emblem: Fortune’s Weave · Recruitment Planner</title>" not in text


def verify_content_pages(site_dir: Path):
    for relative in sorted(expected_pages() - set(LANG_FILES.values())):
        path = site_dir / relative
        text = path.read_text()
        parser = parse(path)
        lang = "en" if relative.startswith("en/") else "ja" if relative.startswith("ja/") else "zh"
        assert parser.h1_count == 1, relative
        assert parser.canonicals == [canonical_for(relative)], (relative, parser.canonicals)
        assert {key for key, _ in parser.alternates} == {"zh-Hans", "ja", "en", "x-default"}
        assert len(extract_json_scripts(text, "application/ld+json")) == 1
        if "/routes/" in f"/{relative}" or relative.startswith("routes/"):
            assert parser.tr_count == 51, (relative, parser.tr_count)
            assert "RPG Site" in text and "AppMedia" in text
            route_id = Path(relative).stem
            assert {locale_href(lang, target, "route", route_id) for target in LANG_FILES} <= set(parser.hrefs)
        else:
            assert "R / S / Δ" in text
            assert {locale_href(lang, target, "methods") for target in LANG_FILES} <= set(parser.hrefs)
            for key in ("methodExpansionCap", "methodExpansionCutoff", "methodExpansionBaseline",
                        "methodExpansionSelection", "methodExpansionGateRemoval"):
                assert UPGRADE_COPY[lang][key] in text, (relative, key)


def verify_sitemap(site_dir: Path):
    root = ET.parse(site_dir / "sitemap.xml").getroot()
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = [element.text for element in root.findall("sm:url/sm:loc", namespace)]
    expected = {canonical_for(relative) for relative in expected_pages()}
    assert len(urls) == len(set(urls)) == 18
    assert set(urls) == expected
    assert all("?" not in url and "#" not in url and not url.endswith("index.html") for url in urls)


def resolve_internal(site_dir: Path, current_relative: str, href: str):
    parsed = urlparse(href)
    if parsed.scheme not in ("", "https"):
        return None
    if parsed.netloc and parsed.netloc != "guchengwei.github.io":
        return None
    if parsed.netloc:
        if not parsed.path.startswith(BASE_PATH):
            return None
        relative = parsed.path[len(BASE_PATH):]
    else:
        relative = current_relative if not parsed.path else posixpath.normpath(
            posixpath.join(posixpath.dirname(current_relative), parsed.path)
        )
        if relative == ".." or relative.startswith("../"):
            return None
    if relative == "":
        relative = "index.html"
    target = site_dir / relative
    return target, parsed.fragment


def verify_links(site_dir: Path):
    cache = {}
    for relative in expected_pages():
        parser = parse(site_dir / relative)
        for href in parser.hrefs:
            assert not href.startswith(BASE_URL), (relative, "navigation must stay on the current site", href)
            resolved = resolve_internal(site_dir, relative, href)
            if not resolved:
                continue
            target, fragment = resolved
            assert target.is_file(), (relative, href)
            if fragment:
                if target not in cache:
                    cache[target] = set(parse(target).ids)
                assert fragment in cache[target], (relative, href)


def verify_offline(offline_dir: Path):
    expected = {"recruitment-planner.html", "recruitment-planner-ja.html", "recruitment-planner-en.html"}
    found = {path.name for path in offline_dir.glob("*.html")}
    assert found == expected
    for filename in expected:
        path = offline_dir / filename
        text = path.read_text()
        parser = parse(path)
        assert all(source.startswith("data:image/") for source in parser.img_sources), filename
        assert not parser.script_sources and not parser.stylesheet_hrefs
        assert len({identifier for identifier in parser.ids if identifier.startswith("character-")}) == 62
        assert len(extract_json_script_by_id(text, "planner-data")["characters"]) == 62
        locale_pack = extract_json_script_by_id(text, "offline-locales")
        assert set(locale_pack) == {"zh", "ja", "en"}
        assert all(set(item["model"]) == {"language", "htmlLanguage", "copy"} for item in locale_pack.values())
        assert sum(bool(item["content"]) for item in locale_pack.values()) == 2
        assert "recruitment-planner-ja.html" not in text and "recruitment-planner-en.html" not in text


def verify_inline_script(site_dir: Path):
    text = (site_dir / "index.html").read_text()
    scripts = re.findall(r'<script type="module">([\s\S]*?)</script>', text)
    assert len(scripts) == 1
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as handle:
        handle.write(scripts[0])
        temp = Path(handle.name)
    try:
        subprocess.run(["node", "--check", str(temp)], check=True)
    finally:
        temp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Verify generated recruitment site.")
    parser.add_argument("--site-dir", type=Path, required=True)
    parser.add_argument("--offline-dir", type=Path, required=True)
    args = parser.parse_args()
    site_dir = args.site_dir if args.site_dir.is_absolute() else ROOT / args.site_dir
    offline_dir = args.offline_dir if args.offline_dir.is_absolute() else ROOT / args.offline_dir
    manifest = json.loads((site_dir / "build-manifest.json").read_text())
    assert set(manifest["siteFiles"]) == {
        str(path.relative_to(site_dir)) for path in site_dir.rglob("*")
        if path.is_file() and path.name != OUTPUT_MARKER
    }
    verify_planners(site_dir)
    verify_content_pages(site_dir)
    verify_sitemap(site_dir)
    verify_links(site_dir)
    verify_offline(offline_dir)
    verify_inline_script(site_dir)
    print("PASS: 18 canonical pages, static localized content, structured data, internal links, sitemap, and three offline editions.")


if __name__ == "__main__":
    main()
