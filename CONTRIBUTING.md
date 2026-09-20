# Contributing

Imagescope is a Linux-only, stateless image-analysis library and CLI.

## Local development

```sh
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m build
```

### Managed-tool installation smoke check

With `uv` already installed, build a wheel and run the opt-in lifecycle check:

```sh
.venv/bin/python -m build --outdir .tmp/tool-dist
.venv/bin/python tests/smoke_uv_tool.py .tmp/tool-dist/imagescope-0.1.0rc1-py3-none-any.whl
```

Use the actual wheel filename after a version change. The check installs into
unique `.tmp/uv-tool-smoke-*` tool/bin/cache directories, runs installed-package
and PATH-based CLI checks, replaces the installation using `--force`, and
uninstalls it. It verifies removal of the managed command/environment while
preserving test image/user files. It does not edit shell configuration, use
sudo, download Python/models, or touch the user's real tool installation.
Dependency downloads may require network access; command logs are retained in
that ignored directory. This is separate from the offline-model unittest suite.
Replacing the same wheel verifies reinstall mechanics, not a cross-version
migration guarantee. CI's wheel/source checks remain independent of uv.

Keep the core free of GUI, catalog, queue, and persistence dependencies. Tests
must run without downloading models or requiring a real inference service.
Use synthetic images rather than personal photos or copyrighted fixture sets.

Preserve decoder resource limits, input/response size limits, explicit endpoint
selection, strict JSON validation, and machine-output stdout discipline. Keep
behavior changes covered by tests, including structured failures.

Protocol changes must follow `PROTOCOL.md`. Update the package version in both
`pyproject.toml` and `imagescope/__init__.py` for releases. Profile/prompt and
measurement revisions have their own versions and must not change silently.

## Release checklist

See `RELEASE_PLAN.md` for the scoped 0.1.0 release gates and verification record.

- Confirm package-name availability before public release.
- Preserve the MIT license and copyright notice in release distributions.
- Run the complete Linux test matrix and installed-package smoke test.
- Build and inspect both the wheel and source archive.
- Test live inference separately when changing prompts or the Ollama backend;
  automated tests use a fake server and do not establish model quality.
- Update `CHANGELOG.md` and explicitly document consumer migration requirements.
- Publishing, tagging, and pushing require a separate deliberate release step.
