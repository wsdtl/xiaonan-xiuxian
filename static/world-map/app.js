(function () {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const MAP_SIZE = 1000;
  const MIN_VIEW_SIZE = 155;
  const MAX_VERTICAL_OVERSCROLL = 0.5;
  const CATEGORY_STYLE_COUNT = 6;
  const ROAD_STYLE_COUNT = 7;
  const NUMBER_FORMATTER = new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 1,
  });
  const RELIEF_LIGHT_LENGTH = Math.sqrt(
    (-0.58) ** 2 + (-0.62) ** 2 + 0.53 ** 2,
  );
  const CATEGORY_TINT_COLORS = Object.freeze([
    "#39745e",
    "#95573d",
    "#41697a",
    "#75643f",
    "#5f557c",
    "#447276",
  ]);
  const root = document.getElementById("atlasRoot");
  const state = {
    data: null,
    view: { x: 0, y: 0, size: MAP_SIZE },
    drag: null,
    selectedLocation: "",
    labelLayoutFrame: 0,
    labelLayoutTimer: 0,
    viewFrame: 0,
    cameraFrame: 0,
    wheelFrame: 0,
    wheelEndTimer: 0,
    wheelLastFrameAt: 0,
    wheelTarget: null,
    pendingLabelLayout: false,
    interacting: false,
    zoomMode: "",
    cameraViewport: { side: 0, left: 0, top: 0, width: 0, height: 0 },
    visibleLabels: [],
    paintLabels: [],
    visibleMarkers: [],
    labelPaintStyles: new WeakMap(),
    markerPaintStyles: new WeakMap(),
    locationIndex: null,
    presentationLabels: null,
    locationHitRadius: 0,
    regionByName: new Map(),
    terrainZoneByName: new Map(),
    locationByName: new Map(),
    categoryStyleByName: new Map(),
  };

  let nodes = null;

  async function init() {
    try {
      const data = await loadMap();
      validateMap(data);
      state.data = data;
      state.regionByName = new Map(
        data.regions.map((region) => [region.name, region]),
      );
      state.terrainZoneByName = new Map(
        data.terrain_zones.map((zone) => [zone.name, zone]),
      );
      state.locationByName = new Map(
        data.locations.map((location) => [location.name, location]),
      );
      state.categoryStyleByName = new Map(
        unique(data.regions.map((region) => region.category)).map(
          (category, index) => [category, index % CATEGORY_STYLE_COUNT],
        ),
      );
      renderShell();
      nodes = collectNodes();
      bindControls();
      renderMap();
      showWorld(false);
      nodes.mapLoading.hidden = true;
    } catch (error) {
      renderError(error instanceof Error ? error.message : String(error));
    }
  }

  async function loadMap() {
    const response = await fetch(`${mapBasePath()}/data`, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error(`地图数据读取失败 (${response.status})`);
    return response.json();
  }

  function mapBasePath() {
    const path = window.location.pathname.replace(/\/$/, "");
    if (path !== "/world-map") throw new Error("地图展示地址无效");
    return path;
  }

  function validateMap(data) {
    const requiredArrays = [
      "bounds",
      "altitude_range",
      "surface",
      "regions",
      "terrain_zones",
      "locations",
      "roads",
    ];
    if (!data || typeof data !== "object") throw new Error("地图数据格式无效");
    if (data.schema !== "game.world_map.presentation" || data.version !== 2) {
      throw new Error("地图展示协议暂不支持");
    }
    requiredArrays.forEach((field) => {
      if (!Array.isArray(data[field])) throw new Error(`地图数据缺少 ${field}`);
    });
    if (data.bounds.length !== 4 || data.altitude_range.length !== 2) {
      throw new Error("地图坐标或海拔边界无效");
    }
    const width = data.bounds[1] - data.bounds[0] + 1;
    const height = data.bounds[3] - data.bounds[2] + 1;
    if (width < 1 || height < 1 || data.surface.length !== height) {
      throw new Error("地图高度场尺寸无效");
    }
    if (
      data.surface.some((row) => !Array.isArray(row) || row.length !== width)
    ) {
      throw new Error("地图高度场行宽不一致");
    }
    [...data.regions, ...data.terrain_zones].forEach((domain) => {
      if (
        !Array.isArray(domain.bounds) ||
        domain.bounds.length !== 4 ||
        !Array.isArray(domain.label_xy) ||
        domain.label_xy.length !== 2 ||
        !Array.isArray(domain.coordinate_bands) ||
        domain.coordinate_bands.length === 0
      ) {
        throw new Error(`地图坐标域无效：${domain.name || "未命名"}`);
      }
    });
  }

  function renderError(message) {
    root.replaceChildren();
    const error = document.createElement("section");
    error.className = "map-loading is-error";
    error.setAttribute("role", "alert");
    error.textContent = message || "全境舆图暂时无法展开";
    root.appendChild(error);
  }

  function renderShell() {
    root.innerHTML = `
      <section class="map-stage" aria-label="全境地图">
        <div class="map-frame" id="mapFrame">
          <div class="map-camera" id="mapCamera">
            <canvas id="terrainCanvas" class="terrain-canvas" width="1000" height="1000" aria-hidden="true"></canvas>
            <svg id="worldMap" class="world-map" viewBox="0 0 1000 1000" role="img" aria-labelledby="mapTitle mapDescription">
              <title id="mapTitle"></title>
              <desc id="mapDescription"></desc>
              <g id="mapContent">
              <g id="terrainLabels" class="terrain-labels"></g>
              <g id="regionLabels" class="region-labels"></g>
              <g id="locations" class="locations"></g>
              </g>
            </svg>
          </div>
          <svg id="roadMap" class="road-map" viewBox="0 0 1000 1000" aria-hidden="true">
            <g id="roads" class="roads"></g>
          </svg>
          <canvas id="presentationCanvas" class="presentation-canvas" aria-hidden="true"></canvas>

          <div class="map-atmosphere" aria-hidden="true">
            <span class="mist-layer mist-layer-a"></span>
            <span class="mist-layer mist-layer-b"></span>
            <span class="celestial-sheen"></span>
          </div>

          <div class="map-loading" id="mapLoading" role="status">正在绘制全境地势</div>

          <header class="atlas-header">
            <div class="atlas-title">
              <span>全境舆图</span>
              <h1 id="worldName"></h1>
            </div>
            <div class="atlas-facts" aria-label="地图尺度">
              <span id="mapScale"></span>
              <span id="mapExtent"></span>
              <span id="altitudeExtent"></span>
            </div>
          </header>

          <div class="atlas-controls" aria-label="地图检索与图层">
            <label class="search-control" for="locationSearch">
              <span>地点</span>
              <input id="locationSearch" type="search" list="locationOptions" placeholder="查找地点" autocomplete="off">
              <datalist id="locationOptions"></datalist>
            </label>
            <label class="select-control" for="regionSelect">
              <span>区域</span>
              <select id="regionSelect"><option value="">全境</option></select>
            </label>
            <div class="layer-controls" aria-label="地图图层">
              <label class="switch-control" for="roadToggle">
                <input id="roadToggle" type="checkbox" checked>
                <span>道路</span>
              </label>
              <label class="switch-control" for="terrainToggle">
                <input id="terrainToggle" type="checkbox" checked>
                <span>地形名</span>
              </label>
            </div>
          </div>

          <div class="zoom-controls" aria-label="地图缩放">
            <button type="button" id="zoomIn" aria-label="放大地图">+</button>
            <button type="button" id="zoomOut" aria-label="缩小地图">−</button>
            <button type="button" id="resetView" aria-label="回到全境">⌂</button>
          </div>

          <div class="compass" aria-label="北方在上"><span>北</span><i aria-hidden="true"></i></div>

          <div class="map-key" aria-label="地图图例">
            <div class="category-key" id="categoryKey"></div>
            <div class="altitude-key">
              <span id="altitudeMin"></span>
              <i aria-hidden="true"></i>
              <span id="altitudeMax"></span>
            </div>
          </div>

          <aside class="place-detail" id="placeDetail" aria-live="polite" hidden>
            <button class="detail-close" type="button" id="closeDetail" aria-label="关闭地点详情">×</button>
            <div class="detail-heading">
              <span id="detailRegion"></span>
              <h2 id="detailName"></h2>
              <p id="detailType"></p>
            </div>
            <p class="detail-description" id="detailDescription"></p>
            <dl class="detail-facts">
              <div><dt>坐标</dt><dd id="detailCoordinate"></dd></div>
              <div><dt>海拔</dt><dd id="detailAltitude"></dd></div>
              <div><dt>地形</dt><dd id="detailTerrain"></dd></div>
            </dl>
            <section class="detail-functions" aria-labelledby="featureTitle">
              <h3 id="featureTitle"></h3>
              <div id="detailFunctions"></div>
            </section>
          </aside>
        </div>
      </section>
    `;
  }

  function collectNodes() {
    return {
      atlasShell: root,
      atlasHeader: root.querySelector(".atlas-header"),
      atlasControls: root.querySelector(".atlas-controls"),
      worldName: document.getElementById("worldName"),
      mapTitle: document.getElementById("mapTitle"),
      mapDescription: document.getElementById("mapDescription"),
      mapScale: document.getElementById("mapScale"),
      mapExtent: document.getElementById("mapExtent"),
      altitudeExtent: document.getElementById("altitudeExtent"),
      locationSearch: document.getElementById("locationSearch"),
      locationOptions: document.getElementById("locationOptions"),
      regionSelect: document.getElementById("regionSelect"),
      roadToggle: document.getElementById("roadToggle"),
      terrainToggle: document.getElementById("terrainToggle"),
      mapFrame: document.getElementById("mapFrame"),
      map: document.getElementById("worldMap"),
      mapCamera: document.getElementById("mapCamera"),
      terrainCanvas: document.getElementById("terrainCanvas"),
      roadMap: document.getElementById("roadMap"),
      presentationCanvas: document.getElementById("presentationCanvas"),
      roads: document.getElementById("roads"),
      terrainLabels: document.getElementById("terrainLabels"),
      regionLabels: document.getElementById("regionLabels"),
      locations: document.getElementById("locations"),
      mapLoading: document.getElementById("mapLoading"),
      zoomIn: document.getElementById("zoomIn"),
      zoomOut: document.getElementById("zoomOut"),
      resetView: document.getElementById("resetView"),
      zoomControls: root.querySelector(".zoom-controls"),
      compass: root.querySelector(".compass"),
      mapKey: root.querySelector(".map-key"),
      categoryKey: document.getElementById("categoryKey"),
      closeDetail: document.getElementById("closeDetail"),
      altitudeMin: document.getElementById("altitudeMin"),
      altitudeMax: document.getElementById("altitudeMax"),
      detailRegion: document.getElementById("detailRegion"),
      detailName: document.getElementById("detailName"),
      detailType: document.getElementById("detailType"),
      detailDescription: document.getElementById("detailDescription"),
      detailCoordinate: document.getElementById("detailCoordinate"),
      detailAltitude: document.getElementById("detailAltitude"),
      detailTerrain: document.getElementById("detailTerrain"),
      detailTitle: document.getElementById("featureTitle"),
      detailFunctions: document.getElementById("detailFunctions"),
      placeDetail: document.getElementById("placeDetail"),
    };
  }

  function bindControls() {
    nodes.roadToggle.addEventListener("change", () => {
      nodes.roads.classList.toggle("is-hidden", !nodes.roadToggle.checked);
    });
    nodes.terrainToggle.addEventListener("change", () => {
      nodes.terrainLabels.classList.toggle(
        "is-hidden",
        !nodes.terrainToggle.checked,
      );
      scheduleLabelLayout();
    });
    nodes.regionSelect.addEventListener("change", () => {
      const region = state.regionByName.get(nodes.regionSelect.value);
      if (!region) {
        resetMap();
        return;
      }
      state.selectedLocation = "";
      updateSelectedMarker();
      nodes.locationSearch.value = "";
      focusBounds(region.bounds, 32);
      showRegion(region);
    });
    nodes.locationSearch.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        findLocation();
      }
    });
    nodes.zoomIn.addEventListener("click", () => zoomAt(0.72));
    nodes.zoomOut.addEventListener("click", () => zoomAt(1.38));
    nodes.resetView.addEventListener("click", resetMap);
    nodes.closeDetail.addEventListener("click", () => {
      closeDetail();
    });
    nodes.map.addEventListener("wheel", handleWheel, { passive: false });
    nodes.map.addEventListener("dblclick", (event) => {
      const point = screenToMap(event.clientX, event.clientY);
      zoomAt(0.55, point.x, point.y);
    });
    nodes.map.addEventListener("pointerdown", beginDrag);
    nodes.map.addEventListener("pointermove", continueDrag);
    nodes.map.addEventListener("pointerup", endDrag);
    nodes.map.addEventListener("pointercancel", endDrag);
    window.addEventListener(
      "resize",
      () => {
        syncCameraViewport();
        scheduleLabelLayout(120);
      },
      { passive: true },
    );
  }

  function renderMap() {
    const data = state.data;
    const [xMin, xMax, yMin, yMax] = data.bounds;
    const width = xMax - xMin + 1;
    const height = yMax - yMin + 1;
    const kilometers = data.cell_size_meters / 1000;
    nodes.worldName.textContent = data.name;
    nodes.mapScale.textContent = `每格 ${formatNumber(kilometers)} 公里`;
    nodes.mapExtent.textContent = `全境 ${width} × ${height}`;
    nodes.altitudeExtent.textContent = `海拔 ${formatMeters(data.altitude_range[0])} 至 ${formatMeters(data.altitude_range[1])}`;
    nodes.altitudeMin.textContent = formatMeters(data.altitude_range[0]);
    nodes.altitudeMax.textContent = formatMeters(data.altitude_range[1]);
    nodes.mapTitle.textContent = `${data.name}全境地图`;
    nodes.mapDescription.textContent = data.description;
    document.title = `${data.name} · 全境舆图`;

    drawRelief(data);
    renderTerrainLabels();
    renderCategoryKey();
    renderRegions();
    renderRoads();
    renderLocations();
    indexPresentationElements();
    renderSelectors();
    renderCamera(state.view);
    commitZoomMode(zoomMode(state.view.size, state.zoomMode));
    refreshLabelLayout(false);
    paintPresentationLayer();
  }

  function drawRelief(data) {
    const sourceHeight = data.surface.length;
    const sourceWidth = data.surface[0].length;
    const source = document.createElement("canvas");
    const sourceScale = 8;
    source.width = sourceWidth * sourceScale;
    source.height = sourceHeight * sourceScale;
    const sourceContext = source.getContext("2d", { alpha: false });
    const pixels = sourceContext.createImageData(source.width, source.height);
    const sampledSurface = new Float32Array(source.width * source.height);
    const [minimum, maximum] = data.altitude_range;
    const slopeDivisor = Math.max(1, data.cell_size_meters * 2);
    const reliefDivisor = Math.max(1, data.cell_size_meters * 0.08);
    const colorStops = [
      [minimum, [22, 57, 74]],
      [-12000, [35, 84, 103]],
      [-4200, [49, 119, 139]],
      [-1800, [58, 129, 145]],
      [-500, [76, 142, 149]],
      [0, [88, 149, 148]],
      [700, [96, 152, 138]],
      [1800, [106, 154, 125]],
      [3500, [130, 157, 113]],
      [6500, [169, 160, 115]],
      [10000, [162, 146, 127]],
      [15000, [139, 143, 142]],
      [21000, [190, 198, 196]],
      [maximum, [231, 235, 232]],
    ];

    for (let screenY = 0; screenY < source.height; screenY += 1) {
      const sourceY = screenY / sourceScale;
      const dataY = sourceHeight - 1 - sourceY;
      for (let screenX = 0; screenX < source.width; screenX += 1) {
        const sourceX = screenX / sourceScale;
        sampledSurface[screenY * source.width + screenX] = sampleSurface(
          data.surface,
          sourceX,
          dataY,
        );
      }
    }
    const renderedSurface = blurHeightField(
      sampledSurface,
      source.width,
      source.height,
      Math.round(sourceScale * 1.35),
    );

    for (let screenY = 0; screenY < source.height; screenY += 1) {
      const southY = Math.min(source.height - 1, screenY + sourceScale);
      const northY = Math.max(0, screenY - sourceScale);
      for (let screenX = 0; screenX < source.width; screenX += 1) {
        const westX = Math.max(0, screenX - sourceScale);
        const eastX = Math.min(source.width - 1, screenX + sourceScale);
        const sampleIndex = screenY * source.width + screenX;
        const altitude = renderedSurface[sampleIndex];
        const left = renderedSurface[screenY * source.width + westX];
        const right = renderedSurface[screenY * source.width + eastX];
        const south = renderedSurface[southY * source.width + screenX];
        const north = renderedSurface[northY * source.width + screenX];
        const slopeX = (right - left) / slopeDivisor;
        const slopeY = (north - south) / slopeDivisor;
        const localRelief = clamp(
          (altitude - (left + right + south + north) / 4) / reliefDivisor,
          -1,
          1,
        );
        const coastRatio = clamp(Math.abs(altitude) / 2800, 0, 1);
        const coastEase = coastRatio * coastRatio * (3 - 2 * coastRatio);
        const coastalRelief = 0.24 + 0.76 * coastEase;
        const shade = hillshade(
          slopeX * coastalRelief,
          slopeY * coastalRelief,
          localRelief * coastalRelief,
        );
        const color = shadeReliefColor(
          reliefColor(altitude, colorStops),
          shade,
          localRelief,
        );
        const offset = sampleIndex * 4;
        pixels.data[offset] = color[0];
        pixels.data[offset + 1] = color[1];
        pixels.data[offset + 2] = color[2];
        pixels.data[offset + 3] = 255;
      }
    }

    sourceContext.putImageData(pixels, 0, 0);
    const context = nodes.terrainCanvas.getContext("2d", { alpha: false });
    context.clearRect(0, 0, MAP_SIZE, MAP_SIZE);
    context.imageSmoothingEnabled = true;
    context.imageSmoothingQuality = "high";
    context.filter = "blur(0.55px)";
    context.drawImage(source, 0, 0, MAP_SIZE, MAP_SIZE);
    context.filter = "none";
    drawSoftGeographyTints(context, data);
    syncCameraViewport();
  }

  function drawSoftGeographyTints(context, data) {
    const categoryLayer = createTintLayer();
    const categoryContext = categoryLayer.getContext("2d");
    data.regions.forEach((region) => {
      categoryContext.fillStyle =
        CATEGORY_TINT_COLORS[categoryStyleIndex(region.category)];
      fillCoordinateBands(categoryContext, region.coordinate_bands);
    });
    blendTintLayer(context, categoryLayer, 54, 0.055);
  }

  function fillCoordinateBands(context, bands) {
    bands.forEach((band) => {
      band.x_ranges.forEach((xRange) => {
        const rect = rangeRect(xRange, [band.y, band.y]);
        context.fillRect(rect.x, rect.y, rect.width, rect.height);
      });
    });
  }

  function createTintLayer() {
    const canvas = document.createElement("canvas");
    canvas.width = MAP_SIZE;
    canvas.height = MAP_SIZE;
    return canvas;
  }

  function blendTintLayer(context, layer, blur, opacity) {
    context.save();
    context.globalAlpha = opacity;
    context.filter = `blur(${blur}px)`;
    context.drawImage(layer, 0, 0);
    context.restore();
  }

  function reliefColor(altitude, stops) {
    if (altitude <= stops[0][0]) return stops[0][1];
    for (let index = 1; index < stops.length; index += 1) {
      const previous = stops[index - 1];
      const current = stops[index];
      if (altitude <= current[0]) {
        const ratio =
          (altitude - previous[0]) / Math.max(1, current[0] - previous[0]);
        return [
          previous[1][0] + (current[1][0] - previous[1][0]) * ratio,
          previous[1][1] + (current[1][1] - previous[1][1]) * ratio,
          previous[1][2] + (current[1][2] - previous[1][2]) * ratio,
        ];
      }
    }
    return stops[stops.length - 1][1];
  }

  function sampleSurface(surface, x, y) {
    const maxY = surface.length - 1;
    const maxX = surface[0].length - 1;
    const clampedX = clamp(x, 0, maxX);
    const clampedY = clamp(y, 0, maxY);
    const baseX = Math.floor(clampedX);
    const baseY = Math.floor(clampedY);
    const tx = clampedX - baseX;
    const ty = clampedY - baseY;
    const first = sampleSurfaceRow(
      surface[clamp(baseY - 1, 0, maxY)],
      baseX,
      maxX,
      tx,
    );
    const start = sampleSurfaceRow(surface[baseY], baseX, maxX, tx);
    const end = sampleSurfaceRow(
      surface[clamp(baseY + 1, 0, maxY)],
      baseX,
      maxX,
      tx,
    );
    const last = sampleSurfaceRow(
      surface[clamp(baseY + 2, 0, maxY)],
      baseX,
      maxX,
      tx,
    );
    return monotoneCubic(first, start, end, last, ty);
  }

  function blurHeightField(source, width, height, radius) {
    const horizontal = new Float32Array(source.length);
    const output = new Float32Array(source.length);
    for (let y = 0; y < height; y += 1) {
      const rowOffset = y * width;
      let sum = 0;
      for (let x = 0; x <= radius; x += 1) sum += source[rowOffset + x];
      for (let x = 0; x < width; x += 1) {
        const left = Math.max(0, x - radius);
        const right = Math.min(width - 1, x + radius);
        horizontal[rowOffset + x] = sum / (right - left + 1);
        if (x - radius >= 0) sum -= source[rowOffset + x - radius];
        if (x + radius + 1 < width) sum += source[rowOffset + x + radius + 1];
      }
    }
    for (let x = 0; x < width; x += 1) {
      let sum = 0;
      for (let y = 0; y <= radius; y += 1) sum += horizontal[y * width + x];
      for (let y = 0; y < height; y += 1) {
        const top = Math.max(0, y - radius);
        const bottom = Math.min(height - 1, y + radius);
        output[y * width + x] = sum / (bottom - top + 1);
        if (y - radius >= 0) sum -= horizontal[(y - radius) * width + x];
        if (y + radius + 1 < height) {
          sum += horizontal[(y + radius + 1) * width + x];
        }
      }
    }
    return output;
  }

  function sampleSurfaceRow(row, baseX, maxX, ratio) {
    return monotoneCubic(
      row[clamp(baseX - 1, 0, maxX)],
      row[baseX],
      row[clamp(baseX + 1, 0, maxX)],
      row[clamp(baseX + 2, 0, maxX)],
      ratio,
    );
  }

  function monotoneCubic(first, start, end, last, ratio) {
    const squared = ratio * ratio;
    const cubed = squared * ratio;
    const value =
      0.5 *
      (2 * start +
        (-first + end) * ratio +
        (2 * first - 5 * start + 4 * end - last) * squared +
        (-first + 3 * start - 3 * end + last) * cubed);
    return clamp(value, Math.min(start, end), Math.max(start, end));
  }

  function hillshade(slopeX, slopeY, localRelief) {
    const exaggeration = 9;
    const normalX = -slopeX * exaggeration;
    const normalY = slopeY * exaggeration;
    const normalZ = 1;
    const length = Math.sqrt(normalX ** 2 + normalY ** 2 + normalZ ** 2);
    const lightX = -0.58;
    const lightY = -0.62;
    const lightZ = 0.53;
    const dot =
      (normalX * lightX + normalY * lightY + normalZ * lightZ) /
      (length * RELIEF_LIGHT_LENGTH);
    return clamp(0.94 + dot * 0.11 + localRelief * 0.018, 0.84, 1.055);
  }

  function shadeReliefColor(base, light, localRelief) {
    const ridge = Math.max(0, localRelief) * 1.2;
    const valley = Math.max(0, -localRelief) * 0.8;
    const tonal = clamp(0.96 + (light - 0.94) * 0.46, 0.9, 1.04);
    return [
      Math.round(clamp(base[0] * tonal + ridge, 0, 255)),
      Math.round(clamp(base[1] * tonal + ridge * 0.7, 0, 255)),
      Math.round(clamp(base[2] * tonal - valley, 0, 255)),
    ];
  }

  function renderTerrainLabels() {
    clear(nodes.terrainLabels);
    state.data.terrain_zones.forEach((zone) => {
      const rect = boundsRect(zone.bounds);
      const [x, y] = mapPoint(zone.label_xy);
      const prominence = zone.cell_count >= 150 ? "major" : "local";
      const label = svg("text", {
        class: "terrain-label",
        x,
        y: y + 3,
        "data-zone": zone.name,
        "data-prominence": prominence,
        "data-box-x": rect.x,
        "data-box-y": rect.y,
        "data-box-width": rect.width,
        "data-box-height": rect.height,
        "data-collision-hidden": "true",
      });
      label.textContent = zone.name;
      nodes.terrainLabels.appendChild(label);
    });
  }

  function renderCategoryKey() {
    clear(nodes.categoryKey);
    categoryGroups().forEach((group) => {
      const item = document.createElement("span");
      const swatch = document.createElement("i");
      swatch.dataset.categoryStyle = String(group.styleIndex);
      item.append(swatch, document.createTextNode(group.category));
      nodes.categoryKey.appendChild(item);
    });
  }

  function categoryGroups() {
    return Array.from(state.categoryStyleByName, ([category, styleIndex]) => ({
      category,
      styleIndex,
      regions: state.data.regions.filter(
        (region) => region.category === category,
      ),
    }));
  }

  function renderRegions() {
    clear(nodes.regionLabels);
    state.data.regions.forEach((region) => {
      const rect = boundsRect(region.bounds);
      const [x, y] = mapPoint(region.label_xy);
      const label = svg("text", {
        class: "region-label",
        x,
        y: y + 7,
        "data-region": region.name,
        "data-box-x": rect.x,
        "data-box-y": rect.y,
        "data-box-width": rect.width,
        "data-box-height": rect.height,
        "data-collision-hidden": "true",
      });
      label.textContent = region.name;
      nodes.regionLabels.appendChild(label);
    });
  }

  function renderRoads() {
    clear(nodes.roads);
    const roadTypes = unique(state.data.roads.map((road) => road.road_type));
    const paths = roadTypes.map((roadType, index) => ({
      styleIndex: index % ROAD_STYLE_COUNT,
      pathData: state.data.roads
        .filter((road) => road.road_type === roadType)
        .map((road) => roadPath(road.coordinates))
        .join(" "),
    }));
    [
      ["road-casing-layer", "road-casing"],
      ["road-base-layer", "road-base"],
      ["road-effect-layer", "road-effect"],
    ].forEach(([layerClass, roadClass]) => {
      paths.forEach(({ styleIndex, pathData }) => {
        const layer = svg("g", {
          class: `road-layer ${layerClass}`,
          "data-road-style": styleIndex,
          "aria-hidden": "true",
        });
        layer.appendChild(
          svg("path", {
            class: `road ${roadClass}`,
            d: pathData,
          }),
        );
        nodes.roads.appendChild(layer);
      });
    });
  }

  function roadPath(coordinates) {
    const points = simplifyRoadCoordinates(coordinates).map(mapPoint);
    if (points.length <= 2) {
      return points
        .map(([x, y], index) => `${index === 0 ? "M" : "L"}${x},${y}`)
        .join(" ");
    }
    const commands = [`M${points[0][0]},${points[0][1]}`];
    for (let index = 1; index < points.length - 1; index += 1) {
      const [x, y] = points[index];
      const [nextX, nextY] = points[index + 1];
      commands.push(`Q${x},${y} ${(x + nextX) / 2},${(y + nextY) / 2}`);
    }
    const last = points[points.length - 1];
    commands.push(`L${last[0]},${last[1]}`);
    return commands.join(" ");
  }

  function simplifyRoadCoordinates(coordinates) {
    if (coordinates.length <= 2) return coordinates;
    const result = [coordinates[0]];
    for (let index = 1; index < coordinates.length - 1; index += 1) {
      const previous = coordinates[index - 1];
      const current = coordinates[index];
      const next = coordinates[index + 1];
      const first = [current[0] - previous[0], current[1] - previous[1]];
      const second = [next[0] - current[0], next[1] - current[1]];
      const collinear =
        first[0] * second[1] === first[1] * second[0] &&
        first[0] * second[0] + first[1] * second[1] > 0;
      if (!collinear) result.push(current);
    }
    result.push(coordinates[coordinates.length - 1]);
    return result;
  }

  function renderLocations() {
    clear(nodes.locations);
    const birthplace = state.data.birthplace;
    const all = [];
    const hits = [];
    const byName = new Map();
    const labelsByName = new Map();
    state.data.locations.forEach((location) => {
      const [x, y] = mapPoint(location.xy);
      const region = state.regionByName.get(location.region);
      const group = svg("g", {
        class: "location",
        "data-location": location.name,
        "data-category-style": categoryStyleIndex(region?.category),
        "data-birthplace": String(location.name === birthplace),
        "data-map-x": x,
        "data-map-y": y,
        role: "button",
        tabindex: "0",
        "aria-label": `${location.name}，${location.region}${location.terrain}，海拔${formatMeters(location.altitude)}`,
        transform: `translate(${x} ${y})`,
      });
      group.appendChild(
        svg("circle", {
          class: "marker-ring",
          cx: 0,
          cy: 0,
          r: 1,
        }),
      );
      group.appendChild(
        svg("circle", {
          class: "marker-core",
          cx: 0,
          cy: 0,
          r: 1,
        }),
      );
      const hit = svg("circle", {
        class: "location-hit",
        cx: 0,
        cy: 0,
        r: 1,
      });
      group.appendChild(hit);
      const label = svg("text", {
        class: "location-label",
        x: 0,
        y: 0,
        "data-collision-hidden": "true",
      });
      label.textContent = location.name;
      group.appendChild(label);
      const title = svg("title");
      title.textContent = `${location.name} · ${formatMeters(location.altitude)}`;
      group.appendChild(title);
      group.addEventListener("click", () => selectLocation(location, false));
      group.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectLocation(location, false);
        }
      });
      group.addEventListener("focus", () => scheduleLabelLayout());
      group.addEventListener("blur", () => scheduleLabelLayout());
      nodes.locations.appendChild(group);
      all.push(group);
      hits.push(hit);
      byName.set(location.name, group);
      labelsByName.set(location.name, label);
    });
    state.locationIndex = {
      all,
      hits,
      byName,
      labelsByName,
    };
  }

  function indexPresentationElements() {
    const terrain = Array.from(nodes.terrainLabels.children);
    const regions = Array.from(nodes.regionLabels.children);
    const locations = state.locationIndex.all
      .map((element) =>
        state.locationIndex.labelsByName.get(element.dataset.location),
      )
      .filter(Boolean);
    state.presentationLabels = {
      all: [...terrain, ...regions, ...locations],
      terrain,
      terrainMajor: terrain.filter(
        (element) => element.dataset.prominence === "major",
      ),
      regions,
      locations,
    };
  }

  function renderSelectors() {
    state.data.regions.forEach((region) => {
      const option = document.createElement("option");
      option.value = region.name;
      option.textContent = region.name;
      nodes.regionSelect.appendChild(option);
    });
    state.data.locations.forEach((location) => {
      const option = document.createElement("option");
      option.value = location.name;
      option.label = location.region;
      nodes.locationOptions.appendChild(option);
    });
  }

  function findLocation() {
    if (!state.data) return;
    const query = nodes.locationSearch.value.trim();
    if (!query) return;
    let location = state.locationByName.get(query);
    if (!location) {
      const matches = state.data.locations.filter((item) =>
        item.name.includes(query),
      );
      if (matches.length === 1) location = matches[0];
    }
    if (!location) {
      nodes.locationSearch.setCustomValidity("没有找到这个地点");
      nodes.locationSearch.reportValidity();
      return;
    }
    nodes.locationSearch.setCustomValidity("");
    nodes.locationSearch.value = location.name;
    selectLocation(location, true);
  }

  function selectLocation(location, focus) {
    state.selectedLocation = location.name;
    updateSelectedMarker();
    nodes.regionSelect.value = location.region;
    if (focus) {
      const [x, y] = mapPoint(location.xy);
      animateViewTo(x - 105, y - 105, 210);
    }
    showLocation(location);
  }

  function updateSelectedMarker() {
    state.locationIndex.all.forEach((element) => {
      element.classList.toggle(
        "is-selected",
        element.dataset.location === state.selectedLocation,
      );
    });
    scheduleLabelLayout();
  }

  function scheduleLabelLayout(delay = 0) {
    if (state.interacting) return;
    if (state.labelLayoutTimer) {
      clearTimeout(state.labelLayoutTimer);
      state.labelLayoutTimer = 0;
    }
    if (state.labelLayoutFrame) cancelAnimationFrame(state.labelLayoutFrame);
    const requestLayout = () => {
      state.labelLayoutTimer = 0;
      state.labelLayoutFrame = requestAnimationFrame(() => {
        state.labelLayoutFrame = 0;
        refreshLabelLayout();
      });
    };
    if (delay > 0) {
      state.labelLayoutTimer = window.setTimeout(requestLayout, delay);
      return;
    }
    requestLayout();
  }

  function refreshLabelLayout(paint = true) {
    syncAnnotationMetrics();
    const visible = activeLabelCandidates();
    state.visibleMarkers = visibleLocationMarkers();
    visible.forEach((element) => {
      if (element.dataset.collisionHidden === "true") {
        element.dataset.collisionHidden = "false";
      }
    });
    const collisionDecisions = new Map();
    const occupied = [
      nodes.atlasHeader,
      nodes.atlasControls,
      nodes.zoomControls,
      nodes.compass,
      nodes.mapKey,
      nodes.placeDetail.hidden ? null : nodes.placeDetail,
    ]
      .filter(Boolean)
      .map((element) => element.getBoundingClientRect());
    const mapRect = mapViewportRect();
    const visibleRect = nodes.mapFrame.getBoundingClientRect();
    const markerRects = state.visibleMarkers.map((element) => {
      const point = locationScreenPoint(element, mapRect);
      const radius = locationScreenRadius(element);
      return expandRect(
        {
          left: point.x - radius,
          right: point.x + radius,
          top: point.y - radius,
          bottom: point.y + radius,
        },
        3,
      );
    });
    const accepted = [];
    visible
      .sort((first, second) => labelPriority(second) - labelPriority(first))
      .forEach((element) => {
        const placements = labelPlacements(element);
        const lockedIndex = Number(element.dataset.placementIndex);
        // Once a label has a valid slot it may fade out, but never jumps to
        // another slot merely because the camera moved.
        const candidates =
          Number.isInteger(lockedIndex) && placements[lockedIndex]
            ? [[lockedIndex, placements[lockedIndex]]]
            : placements.map((placement, index) => [index, placement]);
        let chosen = null;
        for (const [index, placement] of candidates) {
          applyLabelPlacement(element, placement);
          const rect = element.getBoundingClientRect();
          if (!rect.width || !rect.height) continue;
          const padded = expandRect(rect, 3);
          const outsideMap =
            padded.left < visibleRect.left + 2 ||
            padded.right > visibleRect.right - 2 ||
            padded.top < visibleRect.top + 2 ||
            padded.bottom > visibleRect.bottom - 2;
          const blocked = occupied.some((other) => intersects(padded, other));
          const overlaps = accepted.some((other) => intersects(padded, other));
          const onMarker = markerRects.some((other) =>
            intersects(padded, other),
          );
          if (!outsideMap && !blocked && !overlaps && !onMarker) {
            chosen = padded;
            element.dataset.placementIndex = String(index);
            break;
          }
        }
        if (chosen) {
          accepted.push(chosen);
          collisionDecisions.set(element, false);
          return;
        }
        if (isSelectedLabel(element)) {
          const fallbackIndex =
            Number.isInteger(lockedIndex) && placements[lockedIndex]
              ? lockedIndex
              : 0;
          const fallback = placements[fallbackIndex];
          if (fallback) {
            applyLabelPlacement(element, fallback);
            element.dataset.placementIndex = String(fallbackIndex);
            collisionDecisions.set(element, false);
            accepted.push(expandRect(element.getBoundingClientRect(), 2));
            return;
          }
        }
        // Keep the map readable: a marker or a colored area remains useful
        // even when there is no safe place for its text label.
        collisionDecisions.set(element, true);
      });
    collisionDecisions.forEach((hidden, element) => {
      element.dataset.collisionHidden = String(hidden);
    });
    state.visibleLabels = visible.filter(
      (element) => collisionDecisions.get(element) === false,
    );
    state.paintLabels = state.visibleLabels
      .slice()
      .sort((first, second) => labelPriority(first) - labelPriority(second));
    if (paint) paintPresentationLayer();
  }

  function paintPresentationLayer() {
    cachePresentationStyles();
    paintPresentationFrame(state.view);
  }

  function cachePresentationStyles() {
    state.visibleLabels.forEach((element) => {
      const style = getComputedStyle(element);
      const metrics = annotationScreenMetrics(element);
      state.labelPaintStyles.set(element, {
        fill: style.fill,
        stroke: style.stroke,
        fontFamily: style.fontFamily,
        fontWeight: style.fontWeight || "400",
        fontSize: metrics.fontSize,
        strokeWidth: metrics.strokeWidth,
      });
    });
    state.visibleMarkers.forEach((element) => {
      const ring = element.querySelector(".marker-ring");
      const core = element.querySelector(".marker-core");
      if (!ring || !core) return;
      const ringStyle = getComputedStyle(ring);
      const coreStyle = getComputedStyle(core);
      state.markerPaintStyles.set(element, {
        ringFill: ringStyle.fill,
        ringStroke: ringStyle.stroke,
        ringStrokeWidth: Math.max(
          1,
          Number.parseFloat(ringStyle.strokeWidth) || 1,
        ),
        coreFill: coreStyle.fill,
        coreStroke: coreStyle.stroke,
        coreStrokeWidth: Math.max(
          1,
          Number.parseFloat(coreStyle.strokeWidth) || 1,
        ),
      });
    });
  }

  function paintPresentationFrame(view) {
    const { width, height, left, top, side } = state.cameraViewport;
    if (!width || !height || !side) return;
    const pixelRatio = Math.max(1, window.devicePixelRatio || 1);
    const pixelWidth = Math.max(1, Math.round(width * pixelRatio));
    const pixelHeight = Math.max(1, Math.round(height * pixelRatio));
    const output = nodes.presentationCanvas;
    if (output.width !== pixelWidth) output.width = pixelWidth;
    if (output.height !== pixelHeight) output.height = pixelHeight;
    const context = output.getContext("2d");
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    context.clearRect(0, 0, width, height);
    const viewport = { left, top, width: side, height: side };
    state.visibleMarkers.forEach((element) => {
      drawLocationMarker(context, element, viewport, view);
    });
    state.paintLabels.forEach((element) => {
      drawMapLabel(context, element, viewport, view);
    });
  }

  function drawLocationMarker(context, element, viewport, view) {
    const style = state.markerPaintStyles.get(element);
    if (!style) return;
    const point = locationScreenPoint(element, viewport, view);
    const ringRadius = locationScreenRadius(element);
    const coreRadius = ringRadius * 0.55;

    context.save();
    if (element.classList.contains("is-selected")) {
      context.shadowColor = "rgba(255, 230, 156, 0.82)";
      context.shadowBlur = 7;
    }
    context.beginPath();
    context.arc(point.x, point.y, ringRadius, 0, Math.PI * 2);
    context.fillStyle = style.ringFill;
    context.fill();
    context.shadowColor = "transparent";
    context.lineWidth = style.ringStrokeWidth;
    context.strokeStyle = style.ringStroke;
    context.stroke();

    context.beginPath();
    context.arc(point.x, point.y, coreRadius, 0, Math.PI * 2);
    context.fillStyle = style.coreFill;
    context.fill();
    context.lineWidth = style.coreStrokeWidth;
    context.strokeStyle = style.coreStroke;
    context.stroke();
    context.restore();
  }

  function locationScreenPoint(
    element,
    viewport = mapViewportRect(),
    view = state.view,
  ) {
    const x = Number(element.dataset.mapX);
    const y = Number(element.dataset.mapY);
    return {
      x: viewport.left + ((x - view.x) / view.size) * viewport.width,
      y: viewport.top + ((y - view.y) / view.size) * viewport.height,
    };
  }

  function locationScreenRadius(element) {
    if (element.classList.contains("is-selected")) return 7.5;
    return 5.8;
  }

  function mapUnitsForScreenPixels(pixels) {
    const screenScale = state.cameraViewport.side / state.view.size;
    return screenScale > 0 ? pixels / screenScale : pixels;
  }

  function syncAnnotationMetrics() {
    const screenScale = state.cameraViewport.side / state.view.size;
    if (!screenScale) return;
    state.presentationLabels.all.forEach((element) => {
      const metrics = annotationScreenMetrics(element);
      element.style.fontSize = `${(metrics.fontSize / screenScale).toFixed(3)}px`;
      element.style.strokeWidth = `${(metrics.strokeWidth / screenScale).toFixed(3)}px`;
    });
  }

  function annotationScreenMetrics(element) {
    if (element.classList.contains("location-label")) {
      const location = element.parentElement;
      const fontSize = location?.classList.contains("is-selected") ? 13.5 : 12;
      return { fontSize, strokeWidth: 3 };
    }
    if (element.classList.contains("terrain-label")) {
      return { fontSize: 11, strokeWidth: 2.2 };
    }
    if (element.classList.contains("region-label")) {
      return { fontSize: 18, strokeWidth: 3.6 };
    }
    return { fontSize: 22, strokeWidth: 4.4 };
  }

  function drawMapLabel(context, element, viewport, view) {
    const style = state.labelPaintStyles.get(element);
    if (!style) return;
    const placement = labelScreenPlacement(element, viewport, view);

    context.save();
    context.font = `${style.fontWeight} ${style.fontSize}px ${style.fontFamily}`;
    context.textAlign = placement.align;
    context.textBaseline = placement.baseline;
    context.lineJoin = "round";
    if (style.strokeWidth > 0 && style.stroke !== "none") {
      context.lineWidth = style.strokeWidth;
      context.strokeStyle = style.stroke;
      context.strokeText(element.textContent || "", placement.x, placement.y);
    }
    context.fillStyle = style.fill;
    context.fillText(element.textContent || "", placement.x, placement.y);
    context.restore();
  }

  function labelScreenPlacement(element, viewport, view) {
    if (element.classList.contains("location-label")) {
      const location = element.parentElement;
      const point = locationScreenPoint(location, viewport, view);
      const offset = locationScreenRadius(location) + 8;
      const index = Number(element.dataset.placementIndex) || 0;
      const placements = [
        { dx: 0, dy: -offset, align: "center", baseline: "bottom" },
        { dx: 0, dy: offset + 4, align: "center", baseline: "top" },
        { dx: offset, dy: 0, align: "left", baseline: "middle" },
        { dx: -offset, dy: 0, align: "right", baseline: "middle" },
        { dx: offset, dy: -offset, align: "left", baseline: "bottom" },
        { dx: -offset, dy: -offset, align: "right", baseline: "bottom" },
        { dx: offset, dy: offset, align: "left", baseline: "top" },
        { dx: -offset, dy: offset, align: "right", baseline: "top" },
      ];
      const placement = placements[index] || placements[0];
      return {
        x: point.x + placement.dx,
        y: point.y + placement.dy,
        align: placement.align,
        baseline: placement.baseline,
      };
    }
    const x = Number(element.getAttribute("x"));
    const y = Number(element.getAttribute("y"));
    const anchor = element.getAttribute("text-anchor");
    const baseline = element.getAttribute("dominant-baseline");
    return {
      x: viewport.left + ((x - view.x) / view.size) * viewport.width,
      y: viewport.top + ((y - view.y) / view.size) * viewport.height,
      align:
        anchor === "start" ? "left" : anchor === "end" ? "right" : "center",
      baseline:
        baseline === "hanging"
          ? "top"
          : baseline === "middle"
            ? "middle"
            : "bottom",
    };
  }

  function activeLabelCandidates() {
    const labels = state.presentationLabels;
    const visible = [];
    if (state.zoomMode === "overview") visible.push(...labels.regions);
    if (state.zoomMode === "region") {
      visible.push(...labels.regions, ...labels.locations);
      if (nodes.terrainToggle.checked) visible.push(...labels.terrainMajor);
    }
    if (state.zoomMode === "local") {
      visible.push(...labels.locations);
      if (nodes.terrainToggle.checked) visible.push(...labels.terrain);
    }
    if (state.zoomMode === "detail") visible.push(...labels.locations);
    const selected = state.locationIndex.labelsByName.get(
      state.selectedLocation,
    );
    if (selected) visible.push(selected);
    return unique(visible);
  }

  function visibleLocationMarkers() {
    const locations = state.locationIndex;
    const selected = locations.byName.get(state.selectedLocation);
    if (state.zoomMode === "overview") {
      return selected ? [selected] : [];
    }
    return locations.all;
  }

  function labelPlacements(element) {
    if (element.classList.contains("location-label")) {
      const location = element.parentElement;
      const size = mapUnitsForScreenPixels(locationScreenRadius(location));
      const gap = mapUnitsForScreenPixels(8);
      const baselineGap = mapUnitsForScreenPixels(4);
      return [
        { x: 0, y: -size - gap, anchor: "middle", baseline: "auto" },
        {
          x: 0,
          y: size + gap + baselineGap,
          anchor: "middle",
          baseline: "hanging",
        },
        { x: size + gap, y: 0, anchor: "start", baseline: "middle" },
        { x: -size - gap, y: 0, anchor: "end", baseline: "middle" },
        { x: size + gap, y: -size - gap, anchor: "start", baseline: "auto" },
        { x: -size - gap, y: -size - gap, anchor: "end", baseline: "auto" },
        { x: size + gap, y: size + gap, anchor: "start", baseline: "hanging" },
        { x: -size - gap, y: size + gap, anchor: "end", baseline: "hanging" },
      ];
    }

    const x = Number(element.dataset.boxX);
    const y = Number(element.dataset.boxY);
    const width = Number(element.dataset.boxWidth);
    const height = Number(element.dataset.boxHeight);
    if (![x, y, width, height].every(Number.isFinite)) return [];
    const centerX = x + width / 2;
    const centerY = y + height / 2;
    const inset = Math.min(18, Math.max(7, Math.min(width, height) * 0.16));
    return [
      { x: centerX, y: centerY, anchor: "middle", baseline: "middle" },
      { x: centerX, y: y + inset, anchor: "middle", baseline: "hanging" },
      { x: centerX, y: y + height - inset, anchor: "middle", baseline: "auto" },
      { x: x + inset, y: centerY, anchor: "start", baseline: "middle" },
      { x: x + width - inset, y: centerY, anchor: "end", baseline: "middle" },
      { x: x + inset, y: y + inset, anchor: "start", baseline: "hanging" },
      {
        x: x + width - inset,
        y: y + inset,
        anchor: "end",
        baseline: "hanging",
      },
      {
        x: x + inset,
        y: y + height - inset,
        anchor: "start",
        baseline: "auto",
      },
      {
        x: x + width - inset,
        y: y + height - inset,
        anchor: "end",
        baseline: "auto",
      },
    ];
  }

  function applyLabelPlacement(element, placement) {
    element.setAttribute("x", placement.x);
    element.setAttribute("y", placement.y);
    element.setAttribute("text-anchor", placement.anchor || "middle");
    if (placement.baseline) {
      element.setAttribute("dominant-baseline", placement.baseline);
    } else {
      element.removeAttribute("dominant-baseline");
    }
  }

  function labelPriority(element) {
    if (isSelectedLabel(element)) return 1000;
    if (element.classList.contains("location-label")) return 280;
    if (element.classList.contains("terrain-label")) return 200;
    if (element.classList.contains("region-label")) return 120;
    return 10;
  }

  function isSelectedLabel(element) {
    return element.parentElement?.classList.contains("is-selected");
  }

  function expandRect(rect, padding) {
    return {
      left: rect.left - padding,
      right: rect.right + padding,
      top: rect.top - padding,
      bottom: rect.bottom + padding,
    };
  }

  function intersects(first, second) {
    return (
      first.left < second.right &&
      first.right > second.left &&
      first.top < second.bottom &&
      first.bottom > second.top
    );
  }

  function showWorld(open = false) {
    const data = state.data;
    setDetail({
      region: "全境",
      name: data.name,
      type: "世界",
      description: data.description,
      coordinate: `${data.bounds[0]}–${data.bounds[1]}，${data.bounds[2]}–${data.bounds[3]}`,
      altitude: `${formatMeters(data.altitude_range[0])} 至 ${formatMeters(data.altitude_range[1])}`,
      terrain: `${data.regions.length} 个区域`,
      sectionTitle: "区域构成",
      functions: data.regions.map((region) => region.name),
      boundary: true,
    });
    setDetailVisibility(open);
  }

  function showRegion(region) {
    const terrainZones = region.terrain_zones
      .map((name) => state.terrainZoneByName.get(name))
      .filter(Boolean);
    setDetail({
      region: region.category,
      name: region.name,
      type: `${terrainZones.length} 片地形分区`,
      description: region.description,
      coordinate: `${region.bounds[0]}–${region.bounds[1]}，${region.bounds[2]}–${region.bounds[3]}（${region.cell_count} 格）`,
      altitude: `${formatMeters(region.altitude_range[0])} 至 ${formatMeters(region.altitude_range[1])}`,
      terrain: unique(terrainZones.map((zone) => zone.terrain)).join("、"),
      sectionTitle: "地形分区",
      functions: terrainZones.map((zone) => zone.name),
      boundary: true,
    });
    setDetailVisibility(true);
  }

  function showLocation(location) {
    setDetail({
      region: location.region,
      name: location.name,
      type: "地点",
      description: location.description,
      coordinate: `${location.xy[0]}，${location.xy[1]}`,
      altitude: formatMeters(location.altitude),
      terrain: location.terrain,
      sectionTitle: "可见功能",
      functions: location.available_functions,
      boundary: false,
    });
    setDetailVisibility(true);
  }

  function closeDetail() {
    setDetailVisibility(false);
  }

  function setDetailVisibility(visible) {
    nodes.placeDetail.toggleAttribute("hidden", !visible);
    nodes.atlasShell.classList.toggle("has-detail", visible);
    scheduleLabelLayout();
  }

  function setDetail(detail) {
    nodes.detailRegion.textContent = detail.region;
    nodes.detailName.textContent = detail.name;
    nodes.detailType.textContent = detail.type;
    nodes.detailDescription.textContent = detail.description;
    nodes.detailCoordinate.textContent = detail.coordinate;
    nodes.detailAltitude.textContent = detail.altitude;
    nodes.detailTerrain.textContent = detail.terrain;
    nodes.detailTitle.textContent = detail.sectionTitle;
    clear(nodes.detailFunctions);
    detail.functions.forEach((value) => {
      const item = document.createElement("span");
      item.textContent = value;
      if (detail.boundary) item.dataset.kind = "boundary";
      nodes.detailFunctions.appendChild(item);
    });
  }

  function resetMap() {
    if (!state.data) return;
    state.selectedLocation = "";
    nodes.locationSearch.value = "";
    nodes.regionSelect.value = "";
    updateSelectedMarker();
    animateViewTo(0, 0, MAP_SIZE);
    showWorld(false);
  }

  function focusBounds(bounds, padding) {
    const rect = boundsRect(bounds);
    const size = Math.min(
      MAP_SIZE,
      Math.max(rect.width, rect.height) + padding * 2,
    );
    animateViewTo(
      rect.x + rect.width / 2 - size / 2,
      rect.y + rect.height / 2 - size / 2,
      size,
    );
  }

  function handleWheel(event) {
    event.preventDefault();
    cancelViewAnimation();
    if (!state.interacting) beginInteraction();
    if (state.wheelEndTimer) clearTimeout(state.wheelEndTimer);
    const factor = Math.exp(clamp(event.deltaY, -160, 160) * 0.00155);
    queueWheelZoom(factor, event.clientX, event.clientY);
    state.wheelEndTimer = window.setTimeout(() => {
      state.wheelEndTimer = 0;
      ensureWheelFrame();
    }, 120);
  }

  function queueWheelZoom(factor, clientX, clientY) {
    const ratio = screenRatio(clientX, clientY);
    const base = state.wheelTarget || state.view;
    const targetX = base.x + ratio.x * base.size;
    const targetY = base.y + ratio.y * base.size;
    const nextSize = clamp(base.size * factor, MIN_VIEW_SIZE, MAP_SIZE);
    state.wheelTarget = normalizedView(
      targetX - ratio.x * nextSize,
      targetY - ratio.y * nextSize,
      nextSize,
      isVerticallyOverscrolled(base),
    );
    if (reducedMotion()) {
      state.view = state.wheelTarget;
      renderCamera(state.view);
      return;
    }
    ensureWheelFrame();
  }

  function ensureWheelFrame() {
    if (state.wheelFrame) return;
    if (reducedMotion()) {
      if (!state.wheelEndTimer) finishWheelZoom();
      return;
    }
    state.wheelFrame = requestAnimationFrame(renderWheelZoom);
  }

  function renderWheelZoom(now) {
    state.wheelFrame = 0;
    const target = state.wheelTarget;
    if (!target) return;
    const elapsed = state.wheelLastFrameAt
      ? clamp(now - state.wheelLastFrameAt, 1, 40)
      : 16.67;
    state.wheelLastFrameAt = now;
    const blend = 1 - Math.exp(-elapsed / 42);
    const view = state.view;
    const size =
      view.size * Math.exp(Math.log(target.size / view.size) * blend);
    state.view = normalizedView(
      view.x + (target.x - view.x) * blend,
      view.y + (target.y - view.y) * blend,
      size,
      isVerticallyOverscrolled(target),
    );
    renderCamera(state.view);

    const scaleError = Math.abs(Math.log(target.size / state.view.size));
    const panError = Math.hypot(
      target.x - state.view.x,
      target.y - state.view.y,
    );
    if (!state.wheelEndTimer && scaleError < 0.00025 && panError < 0.08) {
      finishWheelZoom();
      return;
    }
    state.wheelFrame = requestAnimationFrame(renderWheelZoom);
  }

  function finishWheelZoom() {
    if (state.wheelFrame) {
      cancelAnimationFrame(state.wheelFrame);
      state.wheelFrame = 0;
    }
    if (state.wheelTarget) {
      state.view = state.wheelTarget;
      updateCamera(false);
    }
    state.wheelEndTimer = 0;
    state.wheelLastFrameAt = 0;
    state.wheelTarget = null;
    finishInteraction();
  }

  function cancelWheelZoom() {
    if (state.wheelFrame) {
      cancelAnimationFrame(state.wheelFrame);
      state.wheelFrame = 0;
    }
    if (state.wheelEndTimer) {
      clearTimeout(state.wheelEndTimer);
      state.wheelEndTimer = 0;
    }
    state.wheelLastFrameAt = 0;
    state.wheelTarget = null;
  }

  function zoomAt(factor, centerX, centerY) {
    const view = state.view;
    const targetX = Number.isFinite(centerX) ? centerX : view.x + view.size / 2;
    const targetY = Number.isFinite(centerY) ? centerY : view.y + view.size / 2;
    const nextSize = clamp(view.size * factor, MIN_VIEW_SIZE, MAP_SIZE);
    const ratioX = (targetX - view.x) / view.size;
    const ratioY = (targetY - view.y) / view.size;
    const x = targetX - nextSize * ratioX;
    const y = targetY - nextSize * ratioY;
    animateViewTo(x, y, nextSize, isVerticallyOverscrolled(view));
  }

  function beginDrag(event) {
    if (event.button !== 0 || event.target.closest(".location")) return;
    cancelViewAnimation();
    cancelWheelZoom();
    const rect = mapViewportRect();
    state.drag = {
      pointerId: event.pointerId,
      clientX: event.clientX,
      clientY: event.clientY,
      viewX: state.view.x,
      viewY: state.view.y,
      scale: state.view.size / rect.width,
    };
    nodes.map.setPointerCapture(event.pointerId);
    nodes.map.classList.add("is-dragging");
    beginInteraction();
  }

  function continueDrag(event) {
    if (!state.drag || state.drag.pointerId !== event.pointerId) return;
    setView(
      state.drag.viewX -
        (event.clientX - state.drag.clientX) * state.drag.scale,
      state.drag.viewY -
        (event.clientY - state.drag.clientY) * state.drag.scale,
      state.view.size,
    );
  }

  function endDrag(event) {
    if (!state.drag || state.drag.pointerId !== event.pointerId) return;
    if (nodes.map.hasPointerCapture(event.pointerId))
      nodes.map.releasePointerCapture(event.pointerId);
    state.drag = null;
    nodes.map.classList.remove("is-dragging");
    finishInteraction();
  }

  function beginInteraction() {
    state.interacting = true;
    if (state.labelLayoutFrame) {
      cancelAnimationFrame(state.labelLayoutFrame);
      state.labelLayoutFrame = 0;
    }
    if (state.labelLayoutTimer) {
      clearTimeout(state.labelLayoutTimer);
      state.labelLayoutTimer = 0;
    }
  }

  function finishInteraction() {
    state.interacting = false;
    const modeChanged = commitZoomMode(
      zoomMode(state.view.size, state.zoomMode),
    );
    if (modeChanged) {
      refreshLabelLayout();
    } else {
      scheduleLabelLayout(48);
    }
  }

  function setView(x, y, size) {
    state.view = normalizedView(x, y, size, true);
    updateCamera(false);
  }

  function normalizedView(x, y, size, allowVerticalOverscroll = false) {
    const nextSize = clamp(size, MIN_VIEW_SIZE, MAP_SIZE);
    const horizontalBounds = horizontalViewBounds(nextSize);
    const verticalMargin = allowVerticalOverscroll
      ? nextSize * MAX_VERTICAL_OVERSCROLL
      : 0;
    return {
      x: clamp(x, horizontalBounds.minimum, horizontalBounds.maximum),
      y: clamp(y, -verticalMargin, MAP_SIZE - nextSize + verticalMargin),
      size: nextSize,
    };
  }

  function horizontalViewBounds(size) {
    const { width, side } = state.cameraViewport;
    if (!width || !side) {
      return { minimum: 0, maximum: MAP_SIZE - size };
    }
    const visibleWidth = (size * width) / side;
    if (visibleWidth >= MAP_SIZE) {
      const center = (MAP_SIZE - size) / 2;
      return { minimum: center, maximum: center };
    }
    const margin = Math.max(0, (visibleWidth - size) / 2);
    return {
      minimum: margin,
      maximum: MAP_SIZE - size - margin,
    };
  }

  function isVerticallyOverscrolled(view) {
    return view.y < 0 || view.y > MAP_SIZE - view.size;
  }

  function animateViewTo(x, y, size, allowVerticalOverscroll = false) {
    cancelWheelZoom();
    cancelViewAnimation();
    const start = { ...state.view };
    const target = normalizedView(x, y, size, allowVerticalOverscroll);
    if (reducedMotion()) {
      state.view = target;
      updateCamera(true);
      return;
    }
    beginInteraction();
    const scaleDistance = Math.abs(
      Math.log(target.size / Math.max(1, start.size)),
    );
    const panDistance =
      Math.hypot(target.x - start.x, target.y - start.y) /
      Math.max(1, start.size);
    const duration = clamp(340 + (scaleDistance + panDistance) * 190, 360, 640);
    const startedAt = performance.now();

    const moveCamera = (now) => {
      state.cameraFrame = 0;
      const progress = clamp((now - startedAt) / duration, 0, 1);
      const eased = 1 - (1 - progress) ** 4;
      state.view = {
        x: start.x + (target.x - start.x) * eased,
        y: start.y + (target.y - start.y) * eased,
        size: start.size + (target.size - start.size) * eased,
      };
      renderCamera(state.view);
      if (progress < 1) {
        state.cameraFrame = requestAnimationFrame(moveCamera);
        return;
      }
      state.view = target;
      renderCamera(state.view);
      finishInteraction();
    };
    state.cameraFrame = requestAnimationFrame(moveCamera);
  }

  function cancelViewAnimation() {
    if (!state.cameraFrame) return;
    cancelAnimationFrame(state.cameraFrame);
    state.cameraFrame = 0;
  }

  function reducedMotion() {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function updateCamera(layout = true) {
    state.pendingLabelLayout = state.pendingLabelLayout || layout;
    if (state.viewFrame) return;
    state.viewFrame = requestAnimationFrame(() => {
      state.viewFrame = 0;
      const view = state.view;
      renderCamera(view);
      if (!state.interacting) {
        const changed = commitZoomMode(zoomMode(view.size, state.zoomMode));
        state.pendingLabelLayout = state.pendingLabelLayout || changed;
      }
      const shouldLayout = state.pendingLabelLayout;
      state.pendingLabelLayout = false;
      if (shouldLayout && !state.interacting) scheduleLabelLayout();
    });
  }

  function renderCamera(view) {
    const { side, left, top, width, height } = state.cameraViewport;
    if (!side) return;
    const scale = MAP_SIZE / view.size;
    const translateX = -(view.x / view.size) * side;
    const translateY = -(view.y / view.size) * side;
    const unitsPerPixel = view.size / side;
    const roadX = view.x - left * unitsPerPixel;
    const roadY = view.y - top * unitsPerPixel;
    const roadWidth = width * unitsPerPixel;
    const roadHeight = height * unitsPerPixel;
    nodes.mapCamera.style.transform = `translate3d(${translateX.toFixed(3)}px, ${translateY.toFixed(3)}px, 0) scale3d(${scale.toFixed(5)}, ${scale.toFixed(5)}, 1)`;
    nodes.roadMap.setAttribute(
      "viewBox",
      `${roadX.toFixed(3)} ${roadY.toFixed(3)} ${roadWidth.toFixed(3)} ${roadHeight.toFixed(3)}`,
    );
    paintPresentationFrame(view);
    syncLocationHitRadius(view);
  }

  function syncLocationHitRadius(view) {
    const hits = state.locationIndex?.hits || [];
    if (!hits.length || !state.cameraViewport.side) {
      state.locationHitRadius = 0;
      return;
    }
    const radius = (15 * view.size) / state.cameraViewport.side;
    const tolerance = Math.max(0.08, state.locationHitRadius * 0.025);
    if (
      state.locationHitRadius &&
      Math.abs(radius - state.locationHitRadius) < tolerance
    ) {
      return;
    }
    state.locationHitRadius = radius;
    const value = radius.toFixed(3);
    hits.forEach((hit) => hit.setAttribute("r", value));
  }

  function syncCameraViewport() {
    const rect = nodes.mapFrame.getBoundingClientRect();
    const side = Math.max(1, Math.min(rect.width, rect.height));
    const left = (rect.width - side) / 2;
    const top = (rect.height - side) / 2;
    state.cameraViewport = {
      side,
      left,
      top,
      width: rect.width,
      height: rect.height,
    };
    state.view = normalizedView(
      state.view.x,
      state.view.y,
      state.view.size,
      isVerticallyOverscrolled(state.view),
    );
    nodes.mapCamera.style.width = `${side}px`;
    nodes.mapCamera.style.height = `${side}px`;
    nodes.mapCamera.style.left = `${left}px`;
    nodes.mapCamera.style.top = `${top}px`;
    nodes.roadMap.style.width = `${rect.width}px`;
    nodes.roadMap.style.height = `${rect.height}px`;
    nodes.roadMap.style.left = "0";
    nodes.roadMap.style.top = "0";
    renderCamera(state.view);
  }

  function commitZoomMode(mode) {
    if (!mode || mode === state.zoomMode) return false;
    ["overview", "region", "local", "detail"].forEach((name) => {
      [nodes.map, nodes.roadMap].forEach((element) => {
        element.classList.toggle(`zoom-${name}`, name === mode);
      });
    });
    state.zoomMode = mode;
    return true;
  }

  function zoomMode(size, current = "") {
    if (current === "overview" && size >= 720) return current;
    if (current === "region" && size >= 400 && size < 800) return current;
    if (current === "local" && size >= 250 && size < 480) return current;
    if (current === "detail" && size < 320) return current;
    if (size >= 760) return "overview";
    if (size >= 440) return "region";
    if (size >= 280) return "local";
    return "detail";
  }

  function screenRatio(clientX, clientY) {
    const rect = mapViewportRect();
    return {
      x: (clientX - rect.left) / rect.width,
      y: (clientY - rect.top) / rect.height,
    };
  }

  function mapViewportRect() {
    const frame = nodes.mapFrame.getBoundingClientRect();
    const side = Math.max(1, Math.min(frame.width, frame.height));
    const left = frame.left + (frame.width - side) / 2;
    const top = frame.top + (frame.height - side) / 2;
    return {
      left,
      right: left + side,
      top,
      bottom: top + side,
      width: side,
      height: side,
    };
  }

  function screenToMap(clientX, clientY) {
    const ratio = screenRatio(clientX, clientY);
    return {
      x: state.view.x + ratio.x * state.view.size,
      y: state.view.y + ratio.y * state.view.size,
    };
  }

  function rangeRect(xRange, yRange) {
    const [xMin, xMax, , yMax] = state.data.bounds;
    const width = xMax - xMin + 1;
    const scale = MAP_SIZE / width;
    return {
      x: (xRange[0] - xMin) * scale,
      y: (yMax - yRange[1]) * scale,
      width: (xRange[1] - xRange[0] + 1) * scale,
      height: (yRange[1] - yRange[0] + 1) * scale,
    };
  }

  function boundsRect(bounds) {
    return rangeRect([bounds[0], bounds[1]], [bounds[2], bounds[3]]);
  }

  function mapPoint(coordinate) {
    const [xMin, xMax, , yMax] = state.data.bounds;
    const scale = MAP_SIZE / (xMax - xMin + 1);
    return [
      (coordinate[0] - xMin + 0.5) * scale,
      (yMax - coordinate[1] + 0.5) * scale,
    ];
  }

  function categoryStyleIndex(category) {
    return state.categoryStyleByName.get(category) ?? 0;
  }

  function svg(tag, attributes = {}) {
    const element = document.createElementNS(SVG_NS, tag);
    Object.entries(attributes).forEach(([name, value]) => {
      element.setAttribute(name, String(value));
    });
    return element;
  }

  function clear(element) {
    element.replaceChildren();
  }

  function unique(values) {
    return Array.from(new Set(values));
  }

  function formatMeters(value) {
    return `${formatNumber(value)} 米`;
  }

  function formatNumber(value) {
    return NUMBER_FORMATTER.format(value);
  }

  function clamp(value, minimum, maximum) {
    return Math.min(maximum, Math.max(minimum, value));
  }

  init();
})();
