# Map atlas

The atlas is a small React application for browsing the exterior-map catalog. It places default-visible surface maps from their cardinal connections, then packs disconnected components without storing hand-authored atlas coordinates.

From the repository root:

```sh
npm --prefix apps/map-atlas ci
make map-atlas-catalog
make map-atlas-build
```

The generated catalog and rendered site stay under `build/map-atlas/`. To run the development server after generating the catalog:

```sh
npm --prefix apps/map-atlas run dev
```

Run the geography tests with `make map-atlas-test`.

The default build uses relative asset URLs, so the static site can be mounted below any path. Set `MAP_ATLAS_BASE` when the deployment has a fixed public prefix:

```sh
MAP_ATLAS_BASE=/atlas/ npm --prefix apps/map-atlas run build
```

## GitHub Pages and pull request previews

The dedicated `Map Atlas` workflow runs the catalog, unit, and Chromium browser
checks for `main` and every pull request. A successful `main` run uploads the
production `map-atlas-site` artifact. A successful pull request from this
repository uploads the same artifact built with its preview base path.

The trusted `Publish Map Atlas previews` workflow runs only from `main`. It
downloads the latest successful artifact for the current `main` commit and for
each open same-repository pull request whose artifact matches that pull
request's current head SHA. The build checks out that exact source SHA and adds
source metadata that the publisher verifies against the Actions run before it
uses the artifact. It publishes one static Pages tree:

- Production atlas: the Pages root
- Pull request atlas: `previews/pr-<number>/`

Each eligible pull request gets one bot-owned marker comment with its preview
link. If its current atlas build fails, expires, or is unavailable, the next
publication removes its stale directory and updates that comment. Closing the
pull request removes the directory and marks the comment as removed. A merge
can close before its new `main` artifact exists, so that close event waits for
the next successful exact-main publication instead of deploying an older main
site. A weekly `main` build refreshes the production artifact before its
90-day retention window expires, and a same-repository close event builds the
current default branch as a fallback for otherwise dormant repositories.

Fork pull requests still receive all atlas checks, but they never upload a site
artifact and never receive a Pages preview. The publisher does not check out
pull request refs or run downloaded artifact files. It validates ZIP paths,
symlinks, member and directory counts, path depth, sizes, source identity, and
the static tree before copying files into the composed deployment.

Before the first deployment, enable GitHub Pages for the repository and select
GitHub Actions as its build source. Run the focused trusted-publisher tests with:

```sh
make map-atlas-preview-test
```
