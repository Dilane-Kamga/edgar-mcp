# EDGAR MCP — Engineering guide for Claude Code

This repo is a Model Context Protocol server that wraps the SEC EDGAR API for use by LLM agents doing financial research. Anyone reading this file is about to write or modify code in the repo — read it completely before your first edit.

## What this MCP is (and isn't)

This is a tool provider, not an analyst. Every tool returns structured data an LLM can reason over. The LLM does the analysis — we do the fetching, parsing, normalization, and diffing.

**In scope:** filing discovery, filing retrieval, semantic section extraction, XBRL financial time series, Form 4 insider aggregation, filing-to-filing diffs.

**Out of scope:** sentiment analysis, valuation models, ratios the user can compute from the primitives, any non-EDGAR data source, any "buy/sell" output. If a user request would need data we don't have, the tool returns what it has and lets the model explain the gap.

## Design principles

**Tools are designed for LLMs, not for API parity.** Don't mirror EDGAR's taxonomy. A tool like `find_filings(company="Apple", kind="annual report")` accepts what a model will naturally pass — ticker, name, or CIK for `company`, and either EDGAR's form type (`"10-K"`) or a plain description (`"annual report"`) for `kind`. The client normalizes internally.

**Outputs are typed Pydantic models, not raw JSON.** Every return value has an explicit schema in `src/edgar_mcp/models.py`. No tool returns `dict[str, Any]`.

**Tool docstrings are the product.** The model decides when to call a tool by reading its docstring. A bad docstring is a bug. Every docstring includes: a one-sentence summary, when to use this tool vs. a related one, parameter semantics, and a brief example of the return shape.

**Bounded payloads.** No tool returns more than ~10KB in the default response. Longer content (full filings, large insider histories) is paginated with a `cursor` parameter. The model should never have its context blown by a single tool call.

**Immutable data is cached aggressively.** Filings don't change after they're filed. Use the `diskcache.Cache` wrapper on every URL fetch with effectively infinite TTL. The only non-cacheable endpoints are the ticker map and "recent filings" queries.

## Tech stack

- **Python 3.12**, managed with `uv`. No Poetry, no pip-tools, no Conda.
- **`mcp[cli]`** SDK with the FastMCP decorators.
- **`httpx`** for async HTTP. Sync fallback only where the MCP SDK requires it.
- **`pydantic` v2** for all models.
- **`selectolax`** for HTML parsing (faster than BeautifulSoup, enough API for our needs).
- **`xmltodict`** for Form 4 XML.
- **`diskcache`** for response caching.
- **`pytest`**, **`pytest-asyncio`**, **`ruff`**, **`mypy --strict`** for dev.

Do not add dependencies without updating this list. If you reach for `pandas`, `requests`, or `beautifulsoup4` — stop. We don't use them.

## SEC compliance (non-negotiable)

The SEC enforces fair access. Violating this gets the IP banned, which kills the MCP for every user.

- Every request MUST include a `User-Agent` header of the form `EDGAR-MCP/{version} {contact_email}`. The contact email is read from the `dilanekamga777@gmail.com` env var at startup. If unset, the server refuses to start.
- Hard rate limit: 10 requests/second, implemented in the client with a token bucket. Do not bypass this.
- Respect `Retry-After` headers on 429 responses. Exponential backoff on 5xx.

These requirements live in `src/edgar_mcp/client.py`. Do not replicate request logic anywhere else in the codebase.

## Workflow

For every new tool, work in this order:

1. Update `README.md` with the tool's signature, docstring, and an example return. This is the spec.
2. Add the Pydantic return model to `src/edgar_mcp/models.py`.
3. Add a pytest with a real-filing fixture to `tests/test_tools.py`. The test should fail.
4. Implement the tool in `src/edgar_mcp/server.py` until the test passes.
5. Run `uv run ruff check --fix && uv run mypy src && uv run pytest`. All three must be clean.
6. Commit with a conventional commit message (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`).

Do not open a pull request without running the full check suite. CI runs the same commands and will reject the PR if any step fails.

Fixtures go in `tests/fixtures/` as real EDGAR responses captured at a specific date. Do not hand-craft mock responses — replay captures. New fixtures are added with `scripts/capture_fixture.py`.

## Directory layout

```
edgar-mcp/
├── CLAUDE.md              ← you are here
├── README.md              ← public spec; authoritative tool surface
├── pyproject.toml
├── src/edgar_mcp/
│   ├── __init__.py
│   ├── server.py          ← FastMCP server, @tool decorators
│   ├── client.py          ← HTTP + rate limiting + User-Agent
│   ├── models.py          ← Pydantic return types
│   ├── parsers/
│   │   ├── sections.py    ← semantic section extraction
│   │   ├── xbrl.py        ← XBRL fact normalization
│   │   ├── form4.py       ← Form 4 aggregation
│   │   └── diff.py        ← filing diffs
│   └── cache.py           ← diskcache wrapper
├── tests/
│   ├── fixtures/
│   ├── test_client.py
│   └── test_tools.py
└── scripts/
    └── capture_fixture.py
```

New modules need a reason. If your PR adds a file outside this layout, justify it in the PR description.

## Things that will fail review

- A tool that returns `dict` or `list` without a Pydantic model.
- A tool whose docstring doesn't include an example return.
- A tool that makes HTTP requests outside the client.
- Any mention of "trading signals," "buy/sell," or valuation recommendations in code, docs, or commit messages. This is a data tool.
- Pandas.
- Silent failure. Every error path returns a typed error or raises a named exception. No bare `except:` blocks.
- A README that documents behavior the code doesn't implement, or vice versa.

## Release checklist (v0.1.0 and beyond)

1. All tests pass (`uv run pytest`).
2. `uv run ruff check` clean.
3. `uv run mypy src` clean.
4. Every README example prompt executed live against the current build.
5. Version bumped in `pyproject.toml`.
6. Git tag pushed.
7. `uv build && uv publish`.
8. GitHub release notes from the tag.