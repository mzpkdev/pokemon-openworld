import { useEffect, useId, useMemo, useRef } from "react";
import Feature, { type FeatureLike } from "ol/Feature";
import Point from "ol/geom/Point";
import { fromExtent as polygonFromExtent } from "ol/geom/Polygon";
import ImageLayer from "ol/layer/Image";
import VectorLayer from "ol/layer/Vector";
import Map from "ol/Map";
import Projection from "ol/proj/Projection";
import ImageStatic from "ol/source/ImageStatic";
import VectorSource from "ol/source/Vector";
import Fill from "ol/style/Fill";
import CircleStyle from "ol/style/Circle";
import Stroke from "ol/style/Stroke";
import Style from "ol/style/Style";
import View from "ol/View";
import "ol/ol.css";
import type { CatalogMap, MapCatalog } from "./catalog";
import { focusExtent, recordAtlasClickHit, shouldShowExitMarkers, type AtlasClickHit, type WarpSelection, warpCoordinate } from "./interactions";
import { atlasExtent, solveGeography, toOpenLayersExtent, visibleSurfaceMaps } from "./geography";
import { mapImageUrl, type AtlasViewState } from "./urls";

interface FocusRequest {
  readonly mapName: string;
  readonly token: number;
}

interface MapViewportProps {
  readonly catalog: MapCatalog;
  readonly maps: readonly CatalogMap[];
  readonly selectedMapName?: string | null;
  readonly selectedWarp?: WarpSelection | null;
  readonly initialView?: AtlasViewState | null;
  readonly focusRequest?: FocusRequest | null;
  readonly showExits?: boolean;
  readonly onSelectMap?: (mapName: string) => void;
  readonly onSelectWarp?: (selection: WarpSelection) => void;
  readonly onCameraChange?: (view: AtlasViewState) => void;
  readonly onToggleExits?: (showExits: boolean) => void;
  readonly onInitialViewApplied?: () => void;
}

interface AtlasMapInstance {
  readonly map: Map;
  readonly view: View;
  readonly mapInteractionLayer: VectorLayer<VectorSource>;
  readonly exitLayer: VectorLayer<VectorSource>;
  readonly updateExitVisibility: () => void;
}

const mapBaseStyle = new Style({
  fill: new Fill({ color: "rgba(0, 0, 0, 0)" }),
  stroke: new Stroke({ color: "rgba(0, 0, 0, 0)", width: 1 }),
});
const mapHoverStyle = new Style({
  fill: new Fill({ color: "rgba(229, 238, 123, 0.22)" }),
  stroke: new Stroke({ color: "#d8ee78", width: 2 }),
  zIndex: 2,
});
const mapSelectedStyle = new Style({
  fill: new Fill({ color: "rgba(255, 211, 95, 0.12)" }),
  stroke: new Stroke({ color: "#ffb703", width: 3 }),
  zIndex: 3,
});
const mapSelectedHoverStyle = new Style({
  fill: new Fill({ color: "rgba(255, 211, 95, 0.22)" }),
  stroke: new Stroke({ color: "#f77f00", width: 3 }),
  zIndex: 4,
});
const exitMarkerStyle = new Style({
  image: new CircleStyle({
    radius: 12,
    fill: new Fill({ color: "#ee6c4d" }),
    stroke: new Stroke({ color: "#fffdf7", width: 3 }),
  }),
  zIndex: 10,
});
const exitMarkerSelectedStyle = new Style({
  image: new CircleStyle({
    radius: 14,
    fill: new Fill({ color: "#f77f00" }),
    stroke: new Stroke({ color: "#432818", width: 3 }),
  }),
  zIndex: 11,
});

function featureProperty(feature: FeatureLike, name: string): unknown {
  return feature.get(name);
}

export function MapViewport({
  catalog,
  maps,
  selectedMapName = null,
  selectedWarp = null,
  initialView = null,
  focusRequest = null,
  showExits = false,
  onSelectMap,
  onSelectWarp,
  onCameraChange,
  onToggleExits,
  onInitialViewApplied,
}: MapViewportProps) {
  const host = useRef<HTMLDivElement>(null);
  const keyboardInstructionsId = useId();
  const mapRef = useRef<AtlasMapInstance | null>(null);
  const selectedMapRef = useRef(selectedMapName);
  const selectedWarpRef = useRef<WarpSelection | null>(selectedWarp);
  const hoveredMapRef = useRef<string | null>(null);
  const showExitsRef = useRef(showExits);
  const initialViewRef = useRef(initialView);
  const selectMapRef = useRef(onSelectMap);
  const selectWarpRef = useRef(onSelectWarp);
  const cameraChangeRef = useRef(onCameraChange);
  const initialViewAppliedRef = useRef(onInitialViewApplied);
  const visibleMaps = useMemo(() => visibleSurfaceMaps(maps), [maps]);
  const geography = useMemo(() => solveGeography(visibleMaps), [visibleMaps]);
  const extent = useMemo(
    () => atlasExtent(geography.placements, catalog.pixelsPerMetatile),
    [catalog.pixelsPerMetatile, geography.placements],
  );

  useEffect(() => {
    selectedMapRef.current = selectedMapName;
    mapRef.current?.map.render();
  }, [selectedMapName]);

  useEffect(() => {
    selectedWarpRef.current = selectedWarp;
    mapRef.current?.map.render();
  }, [selectedWarp]);

  useEffect(() => {
    showExitsRef.current = showExits;
    mapRef.current?.updateExitVisibility();
  }, [showExits]);

  useEffect(() => {
    selectMapRef.current = onSelectMap;
    selectWarpRef.current = onSelectWarp;
    cameraChangeRef.current = onCameraChange;
    initialViewAppliedRef.current = onInitialViewApplied;
  }, [onCameraChange, onInitialViewApplied, onSelectMap, onSelectWarp]);

  useEffect(() => {
    if (!host.current || !extent) {
      return undefined;
    }
    const projection = new Projection({
      code: "pokemon-openworld-atlas-pixels",
      units: "pixels",
      extent,
    });
    const imageLayers = visibleMaps.map((catalogMap) => {
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
    const mapInteractionSource = new VectorSource();
    const exitSource = new VectorSource();
    for (const catalogMap of visibleMaps) {
      const placement = geography.placements[catalogMap.name];
      if (!placement) {
        continue;
      }
      mapInteractionSource.addFeature(new Feature({
        geometry: polygonFromExtent(toOpenLayersExtent(placement, catalog.pixelsPerMetatile)),
        mapName: catalogMap.name,
      }));
      for (const warp of catalogMap.warps) {
        exitSource.addFeature(new Feature({
          geometry: new Point(warpCoordinate(placement, warp, catalog.pixelsPerMetatile)),
          mapName: catalogMap.name,
          warpId: warp.warpId,
        }));
      }
    }
    const mapInteractionLayer = new VectorLayer({
      source: mapInteractionSource,
      style: (feature) => {
        const mapName = featureProperty(feature, "mapName");
        const selected = selectedMapRef.current === mapName;
        const hovered = hoveredMapRef.current === mapName;
        if (selected && hovered) {
          return mapSelectedHoverStyle;
        }
        return selected ? mapSelectedStyle : hovered ? mapHoverStyle : mapBaseStyle;
      },
    });
    const exitLayer = new VectorLayer({
      source: exitSource,
      style: (feature) => {
        const selectedWarp = selectedWarpRef.current;
        return selectedWarp?.sourceMapName === featureProperty(feature, "mapName")
          && selectedWarp?.warpId === featureProperty(feature, "warpId")
          ? exitMarkerSelectedStyle
          : exitMarkerStyle;
      },
    });
    const view = new View({
      projection,
      center: [(extent[0] + extent[2]) / 2, (extent[1] + extent[3]) / 2],
      zoom: 0,
    });
    const map = new Map({ target: host.current, controls: [], layers: [...imageLayers, mapInteractionLayer, exitLayer], view });
    const updateExitVisibility = () => exitLayer.setVisible(shouldShowExitMarkers(showExitsRef.current, view.getResolution()));
    const reportCamera = () => {
      updateExitVisibility();
      const center = view.getCenter();
      const zoom = view.getZoom();
      if (center && zoom !== undefined) {
        cameraChangeRef.current?.({ center: [center[0], center[1]], zoom });
      }
    };
    const updateHover = (event: { pixel: number[]; dragging: boolean }) => {
      if (event.dragging) {
        return;
      }
      let hoveredMap: string | null = null;
      let overInteractiveFeature = false;
      map.forEachFeatureAtPixel(event.pixel, (feature) => {
        if (typeof featureProperty(feature, "warpId") === "string") {
          overInteractiveFeature = true;
        } else if (typeof featureProperty(feature, "mapName") === "string") {
          hoveredMap = featureProperty(feature, "mapName") as string;
          overInteractiveFeature = true;
        }
        return undefined;
      }, { hitTolerance: 12, layerFilter: (layer) => layer === mapInteractionLayer || layer === exitLayer });
      if (hoveredMapRef.current !== hoveredMap) {
        hoveredMapRef.current = hoveredMap;
        map.render();
      }
      host.current!.style.cursor = overInteractiveFeature ? "pointer" : "";
    };
    const handleClick = (event: { pixel: number[] }) => {
      const accumulated = { hit: null as AtlasClickHit | null };
      const stoppedHit = map.forEachFeatureAtPixel<AtlasClickHit | null>(event.pixel, (feature) => {
        const mapName = featureProperty(feature, "mapName");
        if (typeof mapName !== "string") {
          return null;
        }
        const warpId = featureProperty(feature, "warpId");
        const candidate: AtlasClickHit = typeof warpId === "string"
          ? { kind: "warp", selection: { sourceMapName: mapName, warpId } }
          : { kind: "map", mapName };
        const outcome = recordAtlasClickHit(accumulated.hit, candidate);
        accumulated.hit = outcome.hit;
        return outcome.stop ? outcome.hit : null;
      }, { hitTolerance: 12, layerFilter: (layer) => layer === mapInteractionLayer || layer === exitLayer });
      const selectedHit = stoppedHit ?? accumulated.hit;
      if (selectedHit?.kind === "warp") {
        selectedWarpRef.current = selectedHit.selection;
        selectMapRef.current?.(selectedHit.selection.sourceMapName);
        selectWarpRef.current?.(selectedHit.selection);
        map.render();
      } else if (selectedHit?.kind === "map") {
        selectedWarpRef.current = null;
        selectMapRef.current?.(selectedHit.mapName);
        map.render();
      }
    };

    mapRef.current = { map, view, mapInteractionLayer, exitLayer, updateExitVisibility };
    view.fit(extent, { padding: [40, 40, 40, 40], maxZoom: 3 });
    if (initialViewRef.current) {
      view.setCenter([...initialViewRef.current.center]);
      view.setZoom(initialViewRef.current.zoom);
      initialViewAppliedRef.current?.();
    }
    updateExitVisibility();
    map.on("moveend", reportCamera);
    map.on("pointermove", updateHover);
    map.on("singleclick", handleClick);
    reportCamera();

    return () => {
      map.un("moveend", reportCamera);
      map.un("pointermove", updateHover);
      map.un("singleclick", handleClick);
      map.setTarget(undefined);
      mapRef.current = null;
    };
  }, [catalog.pixelsPerMetatile, extent, geography.placements, visibleMaps]);

  useEffect(() => {
    if (!focusRequest) {
      return;
    }
    const instance = mapRef.current;
    const placement = geography.placements[focusRequest.mapName];
    if (instance && placement) {
      instance.view.fit(focusExtent(placement, catalog.pixelsPerMetatile), { padding: [72, 72, 72, 72], maxZoom: 3 });
    }
  }, [catalog.pixelsPerMetatile, focusRequest, geography.placements]);

  const zoom = (amount: number) => {
    const view = mapRef.current?.view;
    if (view) {
      view.setZoom((view.getZoom() ?? 0) + amount);
    }
  };

  const reset = () => {
    const view = mapRef.current?.view;
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
        <label className="exit-toggle">
          <input type="checkbox" checked={showExits} onChange={(event) => onToggleExits?.(event.target.checked)} />
          Exits
        </label>
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
        Keyboard: focus the map, then use arrow keys to pan and plus or minus to zoom. Click a map for details; exits appear when zoomed in or when Exits is enabled.
      </p>
      {geography.residuals.length > 0 && (
        <p className="residual-note">Conflicting cycle links remain visible as their first deterministic placement.</p>
      )}
    </section>
  );
}
