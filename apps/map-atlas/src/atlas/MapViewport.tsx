import { useEffect, useId, useMemo, useRef } from "react";
import ImageLayer from "ol/layer/Image";
import Map from "ol/Map";
import Projection from "ol/proj/Projection";
import ImageStatic from "ol/source/ImageStatic";
import View from "ol/View";
import "ol/ol.css";
import type { CatalogMap, MapCatalog } from "./catalog";
import { atlasExtent, solveGeography, toOpenLayersExtent, visibleSurfaceMaps } from "./geography";
import { mapImageUrl } from "./urls";

interface MapViewportProps {
  readonly catalog: MapCatalog;
  readonly maps: readonly CatalogMap[];
}

export function MapViewport({ catalog, maps }: MapViewportProps) {
  const host = useRef<HTMLDivElement>(null);
  const keyboardInstructionsId = useId();
  const mapRef = useRef<Map | null>(null);
  const visibleMaps = useMemo(() => visibleSurfaceMaps(maps), [maps]);
  const geography = useMemo(() => solveGeography(visibleMaps), [visibleMaps]);
  const extent = useMemo(
    () => atlasExtent(geography.placements, catalog.pixelsPerMetatile),
    [catalog.pixelsPerMetatile, geography.placements],
  );

  useEffect(() => {
    if (!host.current || !extent) {
      return undefined;
    }
    const projection = new Projection({
      code: "pokemon-openworld-atlas-pixels",
      units: "pixels",
      extent,
    });
    const layers = visibleMaps.map((catalogMap) => {
      const placement = geography.placements[catalogMap.name];
      return new ImageLayer({
        source: new ImageStatic({
          url: mapImageUrl(catalogMap.image.path),
          imageExtent: toOpenLayersExtent(placement, catalog.pixelsPerMetatile),
          projection,
          interpolate: false,
        }),
      });
    });
    const view = new View({ projection, center: [(extent[0] + extent[2]) / 2, (extent[1] + extent[3]) / 2], zoom: 0 });
    const map = new Map({ target: host.current, controls: [], layers, view });
    mapRef.current = map;
    view.fit(extent, { padding: [40, 40, 40, 40], maxZoom: 3 });

    return () => {
      map.setTarget(undefined);
      mapRef.current = null;
    };
  }, [catalog.pixelsPerMetatile, extent, geography.placements, visibleMaps]);

  const zoom = (amount: number) => {
    const view = mapRef.current?.getView();
    if (view) {
      view.setZoom((view.getZoom() ?? 0) + amount);
    }
  };

  const reset = () => {
    const view = mapRef.current?.getView();
    if (view && extent) {
      view.setRotation(0);
      view.fit(extent, { padding: [40, 40, 40, 40], maxZoom: 3 });
    }
  };

  if (!extent) {
    return <p className="empty-state">This region has no default-visible surface maps.</p>;
  }

  return (
    <section className="atlas-panel" aria-label="Interactive map atlas">
      <div className="atlas-toolbar">
        <span>{visibleMaps.length} surface maps, {geography.components.length} components</span>
        {geography.residuals.length > 0 && <span className="warning">{geography.residuals.length} topology conflicts retained</span>}
        <div className="atlas-actions" aria-label="Map controls">
          <button type="button" onClick={() => zoom(-1)} aria-label="Zoom out">−</button>
          <button type="button" onClick={() => zoom(1)} aria-label="Zoom in">+</button>
          <button type="button" onClick={reset}>Fit / reset</button>
        </div>
      </div>
      <div
        className="atlas-map"
        ref={host}
        tabIndex={0}
        aria-label="Interactive regional map"
        aria-describedby={keyboardInstructionsId}
      />
      <p className="map-keyboard-help" id={keyboardInstructionsId}>
        Keyboard: focus the map, then use arrow keys to pan and plus or minus to zoom.
      </p>
      {geography.residuals.length > 0 && (
        <p className="residual-note">Conflicting cycle links remain visible as their first deterministic placement.</p>
      )}
    </section>
  );
}
