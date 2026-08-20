# Exterior map renderer

`tools.map_render` renders the project's exterior maps without building or running the
ROM. It reads the pokeemerald map, layout, and tileset sources directly and writes a
frontend-ready catalog beside the PNG files.

## Usage

List the configured regions and their map counts:

```sh
python3 -m tools.map_render regions
```

Render every exterior map into the ignored build directory:

```sh
make map-catalog
```

The catalog is written to `build/map-catalog/` by default. Set
`MAP_CATALOG_OUTPUT` to write it elsewhere.

Render one or more regions into another directory:

```sh
python3 -m tools.map_render render \
  --region kanto \
  --region johto \
  --output build/kanto-johto-maps
```

Use `--source-revision` in CI when the catalog must record a revision other than the
checked-out `HEAD`.

## Output

The command writes individual images under `maps/<region>/<category>/`, plus
`catalog.json` and its JSON Schema. The catalog is the public contract. Folder names
alone do not define map identity or topology.

Each map record contains:

- Its source name, map ID, region, category, map type, map section, and map group
- Its image path, SHA-256 digest, and pixel dimensions
- Its layout ID, format, metatile dimensions, and tilesets
- Its surface, underwater, or generated layer, default visibility, and variant identity
- Music, weather, map-name behavior, and Flash requirements
- Direct outdoor connections with direction and metatile offset
- Warp coordinates and destinations, including exits to maps outside the catalog

The catalog does not contain atlas coordinates. A frontend can derive connected
components from `connections`, then choose how to arrange warp-only components.
`world.variantGroup` prevents alternate states and technical proxies from appearing at
the same time. `schemaVersion` changes whenever that contract changes
incompatibly.

`regions.json` owns regional classification. The tool refuses to run when an exterior
map is unassigned or assigned to more than one region. Town, city, route, ocean-route,
and underwater map types are exterior. Prototypes, technical connection maps,
underwater maps, and generated surfaces remain visible through explicit categories.
Generated surfaces have no fixed world position and are hidden by default.

The renderer includes terrain only. It does not draw object events, NPCs, weather,
animations, or story state.
