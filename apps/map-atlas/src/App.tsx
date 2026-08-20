import { useEffect, useMemo, useState } from "react";
import { CatalogValidationError, loadCatalog, type MapCatalog } from "./atlas/catalog";
import { MapViewport } from "./atlas/MapViewport";

type LoadState =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly catalog: MapCatalog }
  | { readonly kind: "error"; readonly message: string; readonly details: readonly string[] };

export function App() {
  const [loadState, setLoadState] = useState<LoadState>({ kind: "loading" });
  const [selectedRegion, setSelectedRegion] = useState<string | null>(null);

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
  const activeRegion = useMemo(
    () => catalog?.regions.find((region) => region.id === selectedRegion) ?? catalog?.regions[0] ?? null,
    [catalog, selectedRegion],
  );
  const maps = useMemo(
    () => (catalog && activeRegion ? catalog.maps.filter((map) => map.region === activeRegion.id) : []),
    [activeRegion, catalog],
  );

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
        <nav className="region-picker" aria-label="Regions">
          <h2>Regions</h2>
          {catalog.regions.map((region) => (
            <button
              key={region.id}
              type="button"
              className={region.id === activeRegion.id ? "selected" : ""}
              onClick={() => setSelectedRegion(region.id)}
            >
              <span>{region.label}</span>
              <small>{region.mapCount} catalog maps</small>
            </button>
          ))}
        </nav>
        <div className="atlas-content">
          <div className="region-heading">
            <h2>{activeRegion.label}</h2>
            <p>Only default-visible surface maps are shown. Pan, scroll or pinch to explore.</p>
          </div>
          <MapViewport catalog={catalog} maps={maps} />
        </div>
      </div>
    </main>
  );
}
