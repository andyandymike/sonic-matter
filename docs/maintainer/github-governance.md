# GitHub governance

SonicMatter keeps repository administration small enough for one maintainer
while preserving a predictable contribution path.

## Main branch policy

Two repository rulesets apply to `main`:

1. **Main branch safety** applies to everyone, including administrators. It
   blocks branch deletion and non-fast-forward updates and requires linear
   history.
2. **Main contribution policy** requires contributors to use a pull request,
   pass the `Gate A` status check, receive one code-owner approval, resolve all
   review conversations, and obtain approval for the latest push. Repository
   administrators have an `always` bypass for this quality ruleset so the sole
   maintainer can still make an intentional direct push.

The administrator bypass does not override the separate safety ruleset. A
direct maintainer push is therefore possible, while force-pushing or deleting
`main` remains blocked.

The workflow now also emits an aggregate `Release Gate` covering Gate A,
Material Lab, content-pack rights, and Windows export/package evidence. After
that check has completed successfully on the remote once, the maintainer must
replace the ruleset's required `Gate A` context with `Release Gate` through the
GitHub API while preserving the administrator bypass. Until that remote update
is recorded, `Gate A` remains the currently enforced context.

## Automation

- `CI` runs the Gate A/runtime compatibility suite, offline Material Lab and
  UI Foley tests, content-pack rights checks, Windows export/package evidence,
  and a single aggregate `Release Gate`.
- `Docs` builds this site with a pinned MkDocs Material version and deploys it
  through GitHub Pages using OpenID Connect.
- Dependabot checks GitHub Actions and the documentation dependency weekly.
- Workflow dependencies are pinned to immutable commit SHAs; the adjacent
  comments record the corresponding release tags.

## Private material

The CI workflow fails if Git ever tracks `spec/`, `planning-private/`, or
`.local/`. Those directories are also ignored locally. Private specifications
are working inputs, not public project contracts.

## Administration boundary

Pages, repository settings, labels, security features, and rulesets are managed
through the GitHub API. Browser-only configuration is not part of the
maintainer procedure. Current state can be inspected with `gh api` against the
repository endpoints; secrets and authentication material must never be added
to the repository.
