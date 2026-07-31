# Authors

Moon Downloader is created and maintained by:

- **LeyckerS** — [github.com/LeyckerS](https://github.com/LeyckerS)

## Contributors

Twenty-two people other than the maintainer have shipped changes to this
project. Naming them here is the point of this file — the auto-updated list on
the [contributors graph](https://github.com/LeyckerS/moondownloader/graphs/contributors)
is useful, but it is not a thank-you.

In order of first contribution:

| Contributor | What they did |
|:--|:--|
| [@donghyun-5](https://github.com/donghyun-5) | `SECURITY.md` and the vulnerability reporting policy (#1) |
| [@danielblake638](https://github.com/danielblake638) | the first CI workflow — the syntax check that still runs on every PR (#2) |
| [@arjun-cole](https://github.com/arjun-cole) | Dependabot for pip and GitHub Actions (#3) |
| [@rafael-33](https://github.com/rafael-33) | macOS and Windows artifact entries in `.gitignore` (#4) |
| [@daiki-1944](https://github.com/daiki-1944) | English alongside Italian in the launcher error (#5) |
| [@xxjaemin68](https://github.com/xxjaemin68) | upper version bounds for the dependencies (#12) |
| [@emilio18275](https://github.com/emilio18275) | `docs/FAQ.md` (#13) |
| [@sven-25](https://github.com/sven-25) | the pull request template (#14) |
| [@marenace380](https://github.com/marenace380) | `CHANGELOG.md`, in Keep a Changelog format (#15) |
| [@xxchloe61](https://github.com/xxchloe61) | `.editorconfig` (#16) |
| [@ethanlars637](https://github.com/ethanlars637) | the coding style conventions in `CONTRIBUTING.md` (#17) |
| [@lisa-felix](https://github.com/lisa-felix) | issue template contact links, blank issues disabled (#18) |
| [@paolohajinz75](https://github.com/paolohajinz75) | `docs/TROUBLESHOOTING.md` (#19) |
| [@snapandres2012](https://github.com/snapandres2012) | this file (#20) |
| [@xxwyatt57](https://github.com/xxwyatt57) | `docs/PROVIDERS.md` (#21) |
| [@tayloralessia207](https://github.com/tayloralessia207) | `docs/QUICKSTART.md` (#22) |
| [@sunwoo-miguel](https://github.com/sunwoo-miguel) | the Contributor Covenant `CODE_OF_CONDUCT.md` (#23) |
| [@maren61513](https://github.com/maren61513) | caught a wrong line count in the README architecture section (#24) |
| [@kushin25](https://github.com/kushin25) | `docs/CLI.md`, the CLI reference (#37) |
| [@pollychen-lab](https://github.com/pollychen-lab) | the pytest suite (#38) **and the shared download engine (#41)** |
| [@NanoRisk6](https://github.com/NanoRisk6) | pointed the documented verification commands at `pytest tests/` after the test move (#43) |
| [@AdvaitVarhade](https://github.com/AdvaitVarhade) | narrowed `native_dialog`'s exception handling and documented four deliberate swallows (#54) |

Dependabot handles the dependency and action bumps.

**@pollychen-lab's #41 is the largest single contribution to the project so far.**
`download_file`, `Telemetry` and `ProxyPool` existed as two copies, one in
`moon_engine.py` and one in `moon_cli.py`, so every fix in the download path was
a two-file change and the two copies were free to drift. They now live once in
`moon_download.py`.

If you have contributed and want your entry to say something different — a
different description, a link, a bio — open a PR editing this file. If you have
contributed and are missing from this list, that is a mistake worth reporting in
an issue.
