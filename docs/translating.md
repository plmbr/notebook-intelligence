# Translating Notebook Intelligence

Notebook Intelligence (NBI) follows the language you pick for JupyterLab under **Settings → Language**. It ships a translation for every language JupyterLab publishes a language pack for on PyPI: Arabic, Armenian, Catalan, Chinese (Simplified and Traditional), Czech, Danish, Dutch, Estonian, Finnish, French, German, Greek, Hebrew, Hungarian, Indonesian, Italian, Japanese, Korean, Lithuanian, Norwegian, Polish, Portuguese (Brazil), Romanian, Russian, Spanish, Turkish, Ukrainian and Vietnamese.

**These translations were drafted with AI and have not yet been reviewed by native speakers.** Each catalog's header says whether it has been. If a word reads wrong in your language, a fix is one line in a text file, and a pull request with it is very welcome.

## Seeing NBI in your language

1. Install JupyterLab's language pack for your language, for example `pip install jupyterlab-language-pack-fr-FR`, and restart JupyterLab.
2. Choose the language under **Settings → Language**.

NBI's sidebar, settings, panels, Chatbook, tour, and the messages its server writes (the readiness report, approval cards) then appear in that language. A string that has no translation yet appears in English.

To also have the AI reply in your language, turn on **NBI Settings → General → Language → Reply in my JupyterLab language**.

## Fixing or improving a translation

Each language is one file: `notebook_intelligence/locale/<locale>/LC_MESSAGES/notebook_intelligence.po` (for example `fr_FR`). It is a standard gettext catalog, so any `.po` editor works ([Poedit](https://poedit.net/) is a good free one), as does a text editor. An entry looks like this:

```po
#: src/components/settings-panel.tsx
msgctxt "settings section"
msgid "Language"
msgstr "Langue"
```

- `msgid` is the English text. Never change it; change only `msgstr`.
- `msgctxt`, when present, says what kind of text it is ("approval button", "permission mode", "first-run tour"), so the same English word can be translated differently in different places.
- The `#:` line names the source file, a hint to where the text appears.

Keep these exactly as they are in `msgid`, in whatever order your language needs:

- **Placeholders**: `%1`, `%2` (values filled in at run time), `%%` (a percent sign) and `{launchers}`. `"Saved %1"` might become `"%1 gespeichert"`.
- **Product and feature names**: Notebook Intelligence, NBI, JupyterLab, Claude, Claude Code, GitHub Copilot, Codex, opencode, Pi, MCP, ACP, Chatbook, and "Coding Agent" (the name of a Launcher section).
- **Code**: commands, file names, setting names, environment variables (`NBI_*`), keyboard shortcuts.
- **Markdown markers**: `**bold**` and `` `code` ``.

Plurals have one `msgstr[n]` per form your language has, in the order its `Plural-Forms` header defines (for Russian: one, few, many):

```po
msgid "%1 file"
msgid_plural "%1 files"
msgstr[0] "%1 файл"
msgstr[1] "%1 файла"
msgstr[2] "%1 файлов"
```

Use the words JupyterLab's own translation uses for its concepts (notebook, cell, kernel, Launcher, command palette), so NBI reads as part of JupyterLab.

When you have reviewed a catalog, add your name to its header's `Last-Translator` line and change the review note at the top, so others know.

## Trying your change

From a clone of the repository:

```bash
pip install -e ".[i18n]"
jlpm i18n:compile         # also checks placeholders, plural forms and headers
```

`jlpm i18n:compile` refuses a catalog whose placeholders do not match the English, or whose plural forms are malformed, and says which entry. Then restart JupyterLab with your language selected.

## Adding a language

JupyterLab only shows a language it has a language pack for, so a new NBI language needs one too ([JupyterLab language packs](https://github.com/jupyterlab/language-packs)). Then start the catalog with `jlpm i18n:update -l <locale>` (for example `sk_SK`), translate it, and open a pull request.

## For developers

How strings are marked for translation in the code, and how the catalogs are extracted, updated and built, is in [CONTRIBUTING.md](../CONTRIBUTING.md#translations).
