/** World coordinates stay stable as neighborhoods are added around the viewport. */
const MIN_ZOOM = 0.08;
const MAX_ZOOM = 1.35;
const FIT_PADDING = 32;

const finite = value => typeof value === 'number' && Number.isFinite(value);
const clamp = (value, minimum, maximum) => Math.min(maximum, Math.max(minimum, value));

function checkedBounds(bounds) {
  if (!bounds || !['minX', 'minY', 'maxX', 'maxY', 'width', 'height']
    .every(key => finite(bounds[key]))) throw new TypeError('Invalid world bounds.');
  const {minX, minY, maxX, maxY, width, height} = bounds;
  if (width <= 0 || height <= 0 || maxX <= minX || maxY <= minY
    || width !== maxX - minX || height !== maxY - minY
    || !finite(width * MAX_ZOOM) || !finite(height * MAX_ZOOM)) {
    throw new TypeError('Invalid world bounds.');
  }
  return Object.freeze({minX, minY, maxX, maxY, width, height});
}

export class WorldCamera {
  constructor(bounds, width = 800, height = 520) {
    this.bounds = checkedBounds(bounds);
    this.viewportWidth = 800;
    this.viewportHeight = 520;
    this.x = 0;
    this.y = 0;
    this.zoom = 0.8;
    this.setViewport(width, height);
    this._clampCenter();
  }

  setBounds(bounds) {
    this.bounds = checkedBounds(bounds);
    this._clampCenter();
  }

  setViewport(width, height) {
    if (!finite(width) || !finite(height) || width <= 0 || height <= 0) return;
    this.viewportWidth = width;
    this.viewportHeight = height;
    this._clampCenter();
  }

  moveTo(x, y, zoom = this.zoom) {
    if (!finite(x) || !finite(y) || !finite(zoom)) return;
    this.x = x;
    this.y = y;
    this.zoom = clamp(zoom, MIN_ZOOM, MAX_ZOOM);
    this._clampCenter();
  }

  /** Pointer drag distance in screen pixels; the map follows the pointer. */
  pan(dx, dy) {
    if (!finite(dx) || !finite(dy)) return;
    this.moveTo(this.x - dx / this.zoom, this.y - dy / this.zoom);
  }

  setZoom(value) {
    this.moveTo(this.x, this.y, value);
  }

  fit() {
    const {minX, minY, width, height} = this.bounds;
    const zoom = Math.min(0.9,
      Math.max(1, this.viewportWidth - FIT_PADDING * 2) / width,
      Math.max(1, this.viewportHeight - FIT_PADDING * 2) / height);
    this.moveTo(minX + width / 2, minY + height / 2, zoom);
  }

  /** Read actual native scroll positions after mouse, keyboard or touch scrolling. */
  readScroll(left, top) {
    if (!finite(left) || !finite(top)) return;
    const frame = this.frame();
    this.x = this.bounds.minX + (clamp(left, 0, frame.width - this.viewportWidth)
      + this.viewportWidth / 2 - frame.offsetX) / this.zoom;
    this.y = this.bounds.minY + (clamp(top, 0, frame.height - this.viewportHeight)
      + this.viewportHeight / 2 - frame.offsetY) / this.zoom;
    this._clampCenter();
  }

  frame() {
    const {minX, minY, width: worldWidth, height: worldHeight} = this.bounds;
    const width = Math.max(worldWidth * this.zoom, this.viewportWidth);
    const height = Math.max(worldHeight * this.zoom, this.viewportHeight);
    const offsetX = (width - worldWidth * this.zoom) / 2;
    const offsetY = (height - worldHeight * this.zoom) / 2;
    return {
      width, height, offsetX, offsetY,
      scrollLeft: clamp((this.x - minX) * this.zoom + offsetX - this.viewportWidth / 2,
        0, width - this.viewportWidth),
      scrollTop: clamp((this.y - minY) * this.zoom + offsetY - this.viewportHeight / 2,
        0, height - this.viewportHeight),
      scale: this.zoom,
    };
  }

  _clampCenter() {
    const {minX, minY, maxX, maxY, width, height} = this.bounds;
    const halfWidth = this.viewportWidth / (2 * this.zoom);
    const halfHeight = this.viewportHeight / (2 * this.zoom);
    this.x = width * this.zoom <= this.viewportWidth ? minX + width / 2
      : clamp(this.x, minX + halfWidth, maxX - halfWidth);
    this.y = height * this.zoom <= this.viewportHeight ? minY + height / 2
      : clamp(this.y, minY + halfHeight, maxY - halfHeight);
  }
}
