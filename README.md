# Fortune’s Weave Recruitment Planner

Choose who to recruit on each of the four Part I routes in *Fire Emblem: Fortune’s Weave*. Compare recruitment conditions, collect all 50 companions across your playthroughs, or recruit them again on another route.

**[中文](https://guchengwei.github.io/fortunes-weave-recruitment/) · [日本語](https://guchengwei.github.io/fortunes-weave-recruitment/ja.html) · [English](https://guchengwei.github.io/fortunes-weave-recruitment/en.html)**

## Using the planner

1. Choose whether to recruit everyone once, add companions on other routes, or recruit as many as possible twice.
2. Choose your priorities: earlier recruitment, less support training, or a more even split between routes.
3. Check each route’s members. Open a character’s information for required renown, support level, quests and items.

Your selections are saved in your browser. Use **Copy plan link** to share them or open them on another device. No account is needed.

The character list includes all 62 characters, with names in Chinese, Japanese and English. The planner covers the 50 available in Part I. Of those, 43 can join on two different routes; seven are limited to one route.

Renown is a requirement to meet, not a resource you spend. Support starts at level 1, so the planner counts only the levels you need to gain. See [Calculation methods and sources](en/methods.html) for details.

## Offline use

Download an edition and open it in your browser. Portraits and recruitment data are included.

- [中文](artifacts/offline/recruitment-planner.html)
- [日本語](artifacts/offline/recruitment-planner-ja.html)
- [English](artifacts/offline/recruitment-planner-en.html)

## Sources

Recruitment conditions are based on the recruitment tables dated September 22, 2026, with supplementary details from [RPG Site](https://www.rpgsite.net/guide/21391-fire-emblem-fortunes-weave-recruitment-guide-all-characters-in-game-how-to-recruit-them). Japanese names were checked against [AppMedia](https://appmedia.jp/fe_banshisenkou). Differences between sources are noted with the relevant character.

This is an unofficial fan tool. Game names and character artwork belong to their respective rights holders. The decorative four-faction seal is an AI-generated interpretation of the coaster artwork.

## License

Original code and documentation are available under the [MIT License](LICENSE).

Game character images, names, logos and other third-party materials are excluded from this license and remain the property of their respective rights holders. This also applies to third-party material embedded in the generated HTML and offline editions. No rights to those materials are granted by this project.

<details>
<summary>Build and test the site</summary>

The repository contains the complete source, data, images and published pages. Normal builds require Python 3 and Node.js, with no package installation.

```sh
python3 scripts/build.py --out-dir dist --offline-dir artifacts/offline
python3 scripts/verify.py --site-dir dist --offline-dir artifacts/offline
python3 tests/check_expansion.py
node --test tests/*.test.mjs
python3 -m http.server 8765 --bind 127.0.0.1 --directory dist
```

Open `http://127.0.0.1:8765/`. To update the pages served by GitHub Pages from the repository root:

```sh
python3 scripts/sync_root.py --site-dir dist
```

After changing recruitment data, regenerate the calculated results before building. This optional step requires the packages in `requirements-solver.txt`:

```sh
python3 -m pip install -r requirements-solver.txt
python3 scripts/solvers/base.py
python3 scripts/solvers/balanced.py
python3 scripts/solvers/twice.py
python3 tests/check_expansion.py --write-fixtures
```

Review the new results and update the expected values in `scripts/verify.py` before running all checks. Continuous integration also verifies that the published pages match the source.

</details>
