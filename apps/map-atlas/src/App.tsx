import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CatalogValidationError, loadCatalog, type CatalogMap, type MapCatalog } from "./atlas/catalog";
import { searchMaps, type WarpSelection } from "./atlas/interactions";
import { MapViewport } from "./atlas/MapViewport";
import { visibleSurfaceMaps } from "./atlas/geography";
import { atlasUrlWithState, parseAtlasUrlState, type AtlasUrlState, type AtlasViewState } from "./atlas/urls";

type LoadState =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly catalog: MapCatalog }
  | { readonly kind: "error"; readonly message: string; readonly details: readonly string[] };

interface FocusRequest {
  readonly mapName: string;
  readonly token: number;
}

const emptyUrlState: AtlasUrlState = { region: null, selectedMap: null, view: null };

function initialUrlState(): AtlasUrlState {
  return typeof window === "undefined" ? emptyUrlState : parseAtlasUrlState(window.location.href);
}

function destinationForWarp(catalog: MapCatalog, warp: CatalogMap["warps"][number]): CatalogMap | null {
  return catalog.maps.find((map) => map.name === warp.destinationMap || map.id === warp.destinationMapId) ?? null;
}

function MapDetails({
  catalog,
  selectedMap,
  selectedWarp,
  renderedMapNames,
  onSelectWarp,
  onFocusDestination,
}: {
  readonly catalog: MapCatalog;
  readonly selectedMap: CatalogMap | null;
  readonly selectedWarp: WarpSelection | null;
  readonly renderedMapNames: ReadonlySet<string>;
  readonly onSelectWarp: (selection: WarpSelection) => void;
  readonly onFocusDestination: (destination: CatalogMap) => void;
}) {
  if (!selectedMap) {
    return (
      <aside className="map-details" aria-live="polite">
        <h3>Map details</h3>
        <p>Select a map polygon or choose a search result to inspect it and its exits.</p>
      </aside>
    );
  }
  const warp = selectedWarp?.sourceMapName === selectedMap.name
    ? selectedMap.warps.find((candidate) => candidate.warpId === selectedWarp.warpId) ?? null
    : null;
  const destination = warp ? destinationForWarp(catalog, warp) : null;
  const isRendered = renderedMapNames.has(selectedMap.name);

  return (
    <aside className="map-details" aria-live="polite">
      <p className="eyebrow">Selected map</p>
      <h3>{selectedMap.name}</h3>
      <dl className="map-facts">
        <div><dt>Source ID</dt><dd><code>{selectedMap.id}</code></dd></div>
        <div><dt>Map section</dt><dd>{selectedMap.mapSection ?? "Not assigned"}</dd></div>
        <div><dt>Layout</dt><dd>{selectedMap.layout.widthMetatiles} × {selectedMap.layout.heightMetatiles} metatiles</dd></div>
        <div><dt>Atlas state</dt><dd>{isRendered ? "Rendered default-visible surface map" : "Not rendered in the default-visible surface atlas"}</dd></div>
      </dl>

      <section className="exit-details" aria-labelledby="selected-map-exits">
        <h4 id="selected-map-exits">Exits ({selectedMap.warps.length})</h4>
        {selectedMap.warps.length === 0 ? (
          <p>This map has no catalogued warp exits.</p>
        ) : (
          <ul className="exit-list">
            {selectedMap.warps.map((candidate) => {
              const candidateDestination = destinationForWarp(catalog, candidate);
              const selected = warp?.warpId === candidate.warpId;
              return (
                <li key={candidate.warpId}>
                  <button
                    type="button"
                    className={selected ? "selected" : ""}
                    aria-pressed={selected}
                    onClick={() => onSelectWarp({ sourceMapName: selectedMap.name, warpId: candidate.warpId })}
                  >
                    <span>Warp {candidate.warpId} · ({candidate.xMetatiles}, {candidate.yMetatiles})</span>
                    <small>{candidateDestination?.name ?? candidate.destinationMap ?? candidate.destinationMapId}</small>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {warp && (
        <section className="exit-popup" aria-labelledby="exit-detail-title">
          <h4 id="exit-detail-title">Warp {warp.warpId} details</h4>
          <dl className="map-facts">
            <div><dt>Source coordinates</dt><dd>{selectedMap.name} · x {warp.xMetatiles}, y {warp.yMetatiles} metatiles</dd></div>
            <div><dt>Destination</dt><dd>{destination?.name ?? warp.destinationMap ?? "Unresolved destination"}</dd></div>
            <div><dt>Destination ID</dt><dd><code>{warp.destinationMapId}</code></dd></div>
            <div><dt>Destination warp</dt><dd><code>{warp.destinationWarpId}</code></dd></div>
          </dl>
          {destination && renderedMapNames.has(destination.name) ? (
            <button type="button" className="focus-destination" onClick={() => onFocusDestination(destination)}>
              Focus {destination.name}
            </button>
          ) : (
            <p className="unresolved-note">The destination is not a rendered exterior map, so it cannot be focused here.</p>
          )}
        </section>
      )}
    </aside>
  );
}

export function App() {
  const urlState = useRef(initialUrlState());
  const currentView = useRef<AtlasViewState | null>(urlState.current.view);
  const [loadState, setLoadState] = useState<LoadState>({ kind: "loading" });
  const [requestedRegion, setRequestedRegion] = useState(urlState.current.region);
  const [requestedMap, setRequestedMap] = useState(urlState.current.selectedMap);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedWarp, setSelectedWarp] = useState<WarpSelection | null>(null);
  const [showExits, setShowExits] = useState(false);
  const [focusRequest, setFocusRequest] = useState<FocusRequest | null>(null);
  const [initialViewAvailable, setInitialViewAvailable] = useState(urlState.current.view !== null);

  useEffect(() => {
    const controller = new AbortController();
    void loadCatalog(controller.signal)
      .then((catalog) => setLoadState({ kind: "ready", catalog }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        const details = error instanceof CatalogValidationError ? error.details : [];
        setLoadState({
          kind: "error",
          message: error instanceof Error ? error.message : "The map catalog could not be read.",
          details,
        });
      });
    return () => controller.abort();
  }, []);

  const catalog = loadState.kind === "ready" ? loadState.catalog : null;
  const requestedCatalogMap = useMemo(
    () => catalog?.maps.find((map) => map.name === requestedMap || map.id === requestedMap) ?? null,
    [catalog, requestedMap],
  );
  const activeRegion = useMemo(() => {
    if (!catalog) {
      return null;
    }
    if (requestedCatalogMap) {
      return catalog.regions.find((region) => region.id === requestedCatalogMap.region) ?? catalog.regions[0] ?? null;
    }
    return catalog.regions.find((region) => region.id === requestedRegion) ?? catalog.regions[0] ?? null;
  }, [catalog, requestedCatalogMap, requestedRegion]);
  const maps = useMemo(
    () => (catalog && activeRegion ? catalog.maps.filter((map) => map.region === activeRegion.id) : []),
    [activeRegion, catalog],
  );
  const selectedMap = requestedCatalogMap?.region === activeRegion?.id ? requestedCatalogMap : null;
  const renderedMapNames = useMemo(
    () => new Set(visibleSurfaceMaps(catalog?.maps ?? []).map((map) => map.name)),
    [catalog],
  );
  const searchResults = useMemo(() => searchMaps(catalog?.maps ?? [], searchQuery), [catalog, searchQuery]);

  const replaceUrl = useCallback((state: AtlasUrlState) => {
    if (typeof window === "undefined") {
      return;
    }
    const next = atlasUrlWithState(window.location.href, state);
    const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (next !== current) {
      window.history.replaceState(window.history.state, "", next);
    }
  }, []);

  const selectMap = useCallback((mapName: string, focus = false) => {
    const candidate = catalog?.maps.find((map) => map.name === mapName) ?? null;
    if (!candidate) {
      return;
    }
    const changingRegion = candidate.region !== activeRegion?.id;
    if (changingRegion) {
      currentView.current = null;
    }
    setRequestedRegion(candidate.region);
    setRequestedMap(candidate.name);
    setSelectedWarp(null);
    replaceUrl({ region: candidate.region, selectedMap: candidate.name, view: currentView.current });
    if (focus && renderedMapNames.has(candidate.name)) {
      setFocusRequest((previous) => ({ mapName: candidate.name, token: (previous?.token ?? 0) + 1 }));
    }
  }, [activeRegion?.id, catalog, renderedMapNames, replaceUrl]);

  const selectRegion = useCallback((region: string) => {
    currentView.current = null;
    setRequestedRegion(region);
    setRequestedMap(null);
    setSelectedWarp(null);
    setFocusRequest(null);
    replaceUrl({ region, selectedMap: null, view: null });
  }, [replaceUrl]);

  const selectExit = useCallback((selection: WarpSelection) => {
    selectMap(selection.sourceMapName);
    setSelectedWarp(selection);
    setShowExits(true);
  }, [selectMap]);

  const focusDestination = useCallback((destination: CatalogMap) => {
    setSelectedWarp(null);
    selectMap(destination.name, true);
  }, [selectMap]);

  const cameraChanged = useCallback((view: AtlasViewState) => {
    currentView.current = view;
    if (activeRegion) {
      replaceUrl({ region: activeRegion.id, selectedMap: selectedMap?.name ?? null, view });
    }
  }, [activeRegion, replaceUrl, selectedMap?.name]);

  if (loadState.kind === "loading") {
    return <main className="status-page"><p>Loading the map catalog…</p></main>;
  }
  if (loadState.kind === "error") {
    return (
      <main className="status-page error-page">
        <h1>Map atlas unavailable</h1>
        <p>{loadState.message}</p>
        {loadState.details.length > 0 && <ul>{loadState.details.map((detail) => <li key={detail}>{detail}</li>)}</ul>}
      </main>
    );
  }
  if (!catalog || !activeRegion) {
    return <main className="status-page"><p>The catalog has no regions.</p></main>;
  }

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">Pokemon OpenWorld</p>
          <h1>Map atlas</h1>
        </div>
        <p className="source-state">
          Source {catalog.source.revision.slice(0, 12)}
          <span className={catalog.source.workingTreeDirty ? "dirty" : "clean"}>
            {catalog.source.workingTreeDirty ? "dirty" : "clean"}
          </span>
        </p>
      </header>
      <div className="atlas-layout">
        <aside className="atlas-sidebar">
          <nav className="region-picker" aria-label="Regions">
            <h2>Regions</h2>
            {catalog.regions.map((region) => (
              <button
                key={region.id}
                type="button"
                className={region.id === activeRegion.id ? "selected" : ""}
                onClick={() => selectRegion(region.id)}
              >
                <span>{region.label}</span>
                <small>{region.mapCount} catalog maps</small>
              </button>
            ))}
          </nav>
          <section className="map-search" aria-label="Map search">
            <h2>Find a map</h2>
            <label htmlFor="map-search-input">Source name or map section</label>
            <input
              id="map-search-input"
              type="search"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="e.g. Route101 or MAPSEC…"
            />
            {searchQuery.trim() && (
              <ul className="search-results" aria-label="Matching maps">
                {searchResults.length > 0 ? searchResults.map((map) => (
                  <li key={map.id}>
                    <button type="button" onClick={() => selectMap(map.name, true)}>
                      <span>{map.name}</span>
                      <small>{map.mapSection ?? "No map section"}</small>
                    </button>
                  </li>
                )) : <li className="no-search-results">No source maps or map sections match.</li>}
              </ul>
            )}
          </section>
        </aside>
        <div className="atlas-content">
          <div className="region-heading">
            <h2>{activeRegion.label}</h2>
            <p>Only default-visible surface maps are drawn. Pan, scroll or pinch to explore.</p>
          </div>
          <MapViewport
            key={activeRegion.id}
            catalog={catalog}
            maps={maps}
            selectedMapName={selectedMap?.name ?? null}
            selectedWarp={selectedWarp}
            initialView={initialViewAvailable ? urlState.current.view : null}
            focusRequest={focusRequest}
            showExits={showExits}
            onSelectMap={selectMap}
            onSelectWarp={selectExit}
            onCameraChange={cameraChanged}
            onToggleExits={setShowExits}
            onInitialViewApplied={() => setInitialViewAvailable(false)}
          />
          <MapDetails
            catalog={catalog}
            selectedMap={selectedMap}
            selectedWarp={selectedWarp}
            renderedMapNames={renderedMapNames}
            onSelectWarp={selectExit}
            onFocusDestination={focusDestination}
          />
        </div>
      </div>
    </main>
  );
}
