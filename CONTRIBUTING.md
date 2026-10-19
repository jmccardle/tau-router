# Contributing

## Checks

```sh
pip install -e '.[dev]'
pytest                          # the extensions against a fake Tau; no model is called
ruff check src tests && mypy
python -I tests/check_loader.py # Tau's real loader on the installed package, run outside the checkout
```

CI (`.github/workflows/publish.yml`) runs all four on Python 3.11 to 3.14.

## Branches and remotes

- All work continues from `master`. Merge to it often; a version tag, not
  `master`, marks a release.
- `master` lives on two remotes, and every push goes to both:
  - `origin`: dev.ffwf.net/forgejo/john/tau-router
  - `github`: github.com/jmccardle/tau-router

  ```sh
  git push origin master && git push github master
  ```
- No other branch goes to GitHub. Feature branches may be pushed to `origin`.

## Releases

- Pushing a `v*` tag to GitHub publishes to PyPI (ffwf-tau-router), after
  the maintainer approves the `pypi` environment. Push a tag only for an
  agreed release.
- The release commit bumps `tau_router.__version__`. Tag that commit, so the
  tag contains the workflow and its version matches the tag (CI checks).
  Push the tag to both remotes:

  ```sh
  git tag v0.X.0 && git push origin v0.X.0 && git push github v0.X.0
  ```
- To rehearse, run the workflow by hand with `target: testpypi`.
