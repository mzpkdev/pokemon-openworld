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

## GitHub Pages

CI deploys the `main` build to GitHub Pages and keeps pull request builds as the downloadable `map-atlas-site` artifact. Before the first deployment, enable GitHub Pages for the repository and select GitHub Actions as its build source.
