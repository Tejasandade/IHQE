export class BoxPrimitive {
  constructor(time1, time2, price1, price2, color, options = {}) {
    this._time1 = time1;
    this._time2 = time2;
    this._price1 = price1;
    this._price2 = price2;
    this._color = color;
    this._options = options;
    this._paneView = null;
    this._series = null;
    this._chart = null;
    this._requestUpdate = null;
  }

  attached(param) {
    this._series = param.series;
    this._chart = param.chart;
    this._requestUpdate = param.requestUpdate;
  }

  detached() {
    this._series = null;
    this._chart = null;
  }

  updateAllViews() {
    if (this._paneView) {
      this._paneView.update();
    }
  }

  paneViews() {
    if (!this._paneView) {
      this._paneView = new BoxPaneView(this);
    }
    return [this._paneView];
  }
}

class BoxPaneView {
  constructor(primitive) {
    this._primitive = primitive;
  }

  update() {}

  renderer() {
    return new BoxRenderer(this._primitive);
  }
}

class BoxRenderer {
  constructor(primitive) {
    this._primitive = primitive;
  }

  draw(target) {
    target.useBitmapCoordinateSpace((scope) => {
      const ctx = scope.context;
      const primitive = this._primitive;
      const series = primitive._series;
      const timeScale = primitive._chart.timeScale();
      const hRatio = scope.horizontalPixelRatio;
      const vRatio = scope.verticalPixelRatio;

      let x1_css = timeScale.timeToCoordinate(primitive._time1);
      let x2_css = timeScale.timeToCoordinate(primitive._time2);

      // Handle off-screen coordinates safely
      if (x1_css === null) {
        x1_css = (primitive._time1 < primitive._options.firstTime) ? -1000 : scope.mediaSize.width + 1000;
      }
      if (x2_css === null) {
        x2_css = (primitive._time2 < primitive._options.firstTime) ? -1000 : scope.mediaSize.width + 1000;
      }

      const y1_css = series.priceToCoordinate(primitive._price1);
      const y2_css = series.priceToCoordinate(primitive._price2);

      if (y1_css === null || y2_css === null) return;

      const x1 = Math.round(x1_css * hRatio);
      const x2 = Math.round(x2_css * hRatio);
      const y1 = Math.round(y1_css * vRatio);
      const y2 = Math.round(y2_css * vRatio);

      ctx.fillStyle = primitive._color;
      
      const left = Math.min(x1, x2);
      const top = Math.min(y1, y2);
      const width = Math.max(1, Math.abs(x2 - x1));
      const height = Math.max(1, Math.abs(y2 - y1));

      // Do not draw if width or height is 0 (e.g. completely offscreen)
      if (width <= 1 && left < 0) return;

      // Draw the main shaded box
      ctx.fillRect(left, top, width, height);

      // Draw borders if specified
      if (primitive._options.borders) {
          ctx.strokeStyle = primitive._color.replace(/[\d.]+\)$/g, '0.8)');
          ctx.lineWidth = 1 * hRatio;
          ctx.strokeRect(left, top, width, height);
      }
      
      // Draw inner levels if it's a Fib grid
      if (primitive._options.levels) {
          primitive._options.levels.forEach(level => {
              const y_css = series.priceToCoordinate(level.price);
              if (y_css !== null) {
                  const y = Math.round(y_css * vRatio);
                  ctx.strokeStyle = level.color;
                  ctx.lineWidth = (level.width || 1) * hRatio;
                  
                  if (level.style === 2) ctx.setLineDash([5 * hRatio, 5 * hRatio]);
                  else ctx.setLineDash([]);
                  
                  ctx.beginPath();
                  ctx.moveTo(left, y);
                  ctx.lineTo(left + width, y);
                  ctx.stroke();
                  ctx.setLineDash([]);
                  
                  // Draw label
                  ctx.fillStyle = level.color;
                  ctx.font = `${11 * hRatio}px Inter`;
                  ctx.fillText(level.label, left + 5 * hRatio, y - (4 * vRatio));
              }
          });
      }

      // Draw Text Label if it's a Long/Short tool
      if (primitive._options.text) {
          ctx.fillStyle = primitive._options.textColor || '#FFFFFF';
          ctx.font = `bold ${11 * hRatio}px Inter`;
          
          const textWidth = ctx.measureText(primitive._options.text).width;
          const textX = left + 5 * hRatio; 
          
          let textY;
          if (primitive._options.textPosition === 'top') {
              textY = top + (14 * vRatio);
          } else {
              textY = top + height - (6 * vRatio);
          }
          
          if (width > 20) {
              ctx.fillText(primitive._options.text, textX, textY);
          }
      }

      // Draw A-B Trendline (For Fibonacci)
      if (primitive._options.trendline) {
          const tl = primitive._options.trendline;
          let tx1_css = timeScale.timeToCoordinate(tl.t1);
          let tx2_css = timeScale.timeToCoordinate(tl.t2);
          
          // Fallback if offscreen
          if (tx1_css === null) tx1_css = (tl.t1 < primitive._options.firstTime) ? -1000 : scope.mediaSize.width + 1000;
          if (tx2_css === null) tx2_css = (tl.t2 < primitive._options.firstTime) ? -1000 : scope.mediaSize.width + 1000;

          const ty1_css = series.priceToCoordinate(tl.p1);
          const ty2_css = series.priceToCoordinate(tl.p2);

          if (ty1_css !== null && ty2_css !== null) {
              const tx1 = Math.round(tx1_css * hRatio);
              const tx2 = Math.round(tx2_css * hRatio);
              const ty1 = Math.round(ty1_css * vRatio);
              const ty2 = Math.round(ty2_css * vRatio);

              ctx.strokeStyle = 'rgba(255,255,255,0.4)';
              ctx.lineWidth = 1 * hRatio;
              ctx.setLineDash([4 * hRatio, 4 * hRatio]);
              
              ctx.beginPath();
              ctx.moveTo(tx1, ty1);
              ctx.lineTo(tx2, ty2);
              ctx.stroke();
              
              ctx.setLineDash([]);
          }
      }
    });
  }
}
