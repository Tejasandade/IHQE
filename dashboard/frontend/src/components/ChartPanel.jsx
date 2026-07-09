import { useEffect, useRef, useState } from 'react';
import { createChart } from 'lightweight-charts';
import client from '../api/client';
import { BoxPrimitive } from './BoxPrimitive';

const COLORS = {
  background: '#141414',
  text: '#FFFFFF',
  textSecondary: '#888888',
  border: '#2A2A2A',
  gold: '#B8860B',
  goldDim: 'rgba(184, 134, 11, 0.15)',
  bullish: '#26A69A',
  bullishDim: 'rgba(38, 166, 154, 0.12)',
  bearish: '#EF5350',
  bearishDim: 'rgba(239, 83, 80, 0.12)',
  fvgBullish: 'rgba(38, 166, 154, 0.18)',
  fvgBearish: 'rgba(239, 83, 80, 0.18)',
  dimmedGrid: '#444444',
};

function toUnix(ts) {
  if (typeof ts === 'string') return Math.floor(new Date(ts).getTime() / 1000);
  return ts;
}

function getCandleTime(timeframe, timestampMs) {
  const d = new Date(timestampMs);
  if (timeframe === '1H') {
    d.setUTCMinutes(0, 0, 0);
  } else if (timeframe === '4H') {
    const h = d.getUTCHours();
    d.setUTCHours(h - (h % 4), 0, 0, 0);
  } else if (timeframe === '1M') {
    d.setUTCDate(1);
    d.setUTCHours(0, 0, 0, 0);
  } else if (timeframe === 'W') {
    const day = d.getUTCDay();
    const diff = d.getUTCDate() - day + (day === 0 ? -6 : 1);
    d.setUTCDate(diff);
    d.setUTCHours(0, 0, 0, 0);
  } else if (timeframe === '3M') {
    const m = d.getUTCMonth();
    d.setUTCMonth(m - (m % 3), 1);
    d.setUTCHours(0, 0, 0, 0);
  } else if (timeframe === '12M') {
    d.setUTCMonth(0, 1);
    d.setUTCHours(0, 0, 0, 0);
  }
  return Math.floor(d.getTime() / 1000);
}

export default function ChartPanel({ timeframe, label, onPromote, onExpand, livePrice, timezoneMode = 'utc', simulationMode = false, simulationCandles = [], simulationState = null }) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const ohlcvDataRef = useRef([]);      
  const overlaySeriesRef = useRef([]);  
  const customPrimitivesRef = useRef([]);

  const [fvgs, setFvgs] = useState([]);
  const [fibs, setFibs] = useState([]);
  const [bosEvents, setBosEvents] = useState([]);
  const [trades, setTrades] = useState([]);
  const [dataLoaded, setDataLoaded] = useState(0);

  // Initialize chart
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { color: COLORS.background },
        textColor: COLORS.text,
        fontFamily: "'Inter', sans-serif",
      },
      grid: {
        vertLines: { color: '#1E1E1E' },
        horzLines: { color: '#1E1E1E' },
      },
      crosshair: {
        mode: 0,
        vertLine: { color: COLORS.gold, style: 2, width: 1 },
        horzLine: { color: COLORS.gold, style: 2, width: 1 },
      },
      localization: {
        timeFormatter: (time) => {
          const date = new Date(time * 1000);
          if (timezoneMode === 'utc') {
            return date.toISOString().replace('T', ' ').substring(0, 16);
          } else if (timezoneMode === 'local_12h') {
            return date.toLocaleString('en-US', { month: 'short', day: 'numeric', year: '2-digit', hour: 'numeric', minute: '2-digit', hour12: true });
          } else {
            return date.toLocaleString('en-US', { month: 'short', day: 'numeric', year: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
          }
        },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: COLORS.border,
        tickMarkFormatter: (time, tickMarkType, locale) => {
          const date = new Date(time * 1000);
          if (timezoneMode === 'utc') {
            return date.toISOString().replace('T', ' ').substring(5, 16); // MM-DD HH:mm
          }
          const formatter = new Intl.DateTimeFormat('en-US', {
            month: 'short', day: 'numeric',
            ...(tickMarkType <= 2 ? { year: 'numeric' } : {}),
            ...(tickMarkType >= 3 ? { hour: 'numeric', minute: '2-digit', hour12: timezoneMode === 'local_12h' } : {})
          });
          return formatter.format(date);
        }
      },
      rightPriceScale: {
        borderColor: COLORS.border,
        autoScale: true,
      },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: COLORS.bullish,
      downColor: COLORS.bearish,
      borderUpColor: COLORS.bullish,
      borderDownColor: COLORS.bearish,
      wickUpColor: COLORS.bullish,
      wickDownColor: COLORS.bearish,
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;

    return () => {
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
    };
  }, [timeframe]); // Intentionally omitting timezoneMode here to avoid full recreate

  // Handle Timezone mode changes dynamically
  useEffect(() => {
    if (!chartRef.current) return;
    
    chartRef.current.applyOptions({
      localization: {
        timeFormatter: (time) => {
          const date = new Date(time * 1000);
          if (timezoneMode === 'utc') {
            return date.toISOString().replace('T', ' ').substring(0, 16);
          } else if (timezoneMode === 'local_12h') {
            return date.toLocaleString('en-US', { month: 'short', day: 'numeric', year: '2-digit', hour: 'numeric', minute: '2-digit', hour12: true });
          } else {
            return date.toLocaleString('en-US', { month: 'short', day: 'numeric', year: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
          }
        },
      },
      timeScale: {
        tickMarkFormatter: (time, tickMarkType, locale) => {
          const date = new Date(time * 1000);
          if (timezoneMode === 'utc') {
            return date.toISOString().replace('T', ' ').substring(5, 16);
          }
          const formatter = new Intl.DateTimeFormat('en-US', {
            month: 'short', day: 'numeric',
            ...(tickMarkType <= 2 ? { year: 'numeric' } : {}),
            ...(tickMarkType >= 3 ? { hour: 'numeric', minute: '2-digit', hour12: timezoneMode === 'local_12h' } : {})
          });
          return formatter.format(date);
        }
      }
    });
  }, [timezoneMode]);

  // Fetch and set OHLCV data
  useEffect(() => {
    if (simulationMode) return;
    
    console.log(`[ChartPanel ${timeframe}] Fetching data... candleSeriesRef exists:`, !!candleSeriesRef.current);
    if (!candleSeriesRef.current) return;

    client.get(`/ohlcv/${timeframe}`).then((res) => {
      console.log(`[ChartPanel ${timeframe}] Data received:`, res.data?.length);
      const data = res.data || [];
      if (data.length > 0) {
        ohlcvDataRef.current = data;
        try {
          candleSeriesRef.current.setData(data);
          chartRef.current.timeScale().fitContent();
          setDataLoaded(prev => prev + 1);
        } catch(e) {
          console.error(`[ChartPanel ${timeframe}] Error setting data:`, e);
        }
      }
    }).catch((err) => {
      console.error(`[ChartPanel ${timeframe}] Fetch error:`, err);
    });
  }, [timeframe, simulationMode]);

  // Handle live price updates
  useEffect(() => {
    if (simulationMode) return;
    if (!candleSeriesRef.current || !ohlcvDataRef.current || ohlcvDataRef.current.length === 0 || !livePrice) return;
    
    const data = ohlcvDataRef.current;
    const lastCandle = data[data.length - 1];
    
    const nowMs = Date.now();
    const currentCandleTime = getCandleTime(timeframe, nowMs);
    
    if (currentCandleTime > lastCandle.time) {
      // Create new live candle
      const newCandle = {
        time: currentCandleTime,
        open: lastCandle.close,
        high: Math.max(lastCandle.close, livePrice.mid),
        low: Math.min(lastCandle.close, livePrice.mid),
        close: livePrice.mid,
      };
      try {
        candleSeriesRef.current.update(newCandle);
        data.push(newCandle);
      } catch (e) {
        console.error(`[ChartPanel ${timeframe}] Error adding new live candle:`, e);
      }
    } else {
      // Update existing last candle
      const updatedCandle = {
        ...lastCandle,
        close: livePrice.mid,
        high: Math.max(lastCandle.high, livePrice.mid),
        low: Math.min(lastCandle.low, livePrice.mid),
      };
      try {
        candleSeriesRef.current.update(updatedCandle);
        data[data.length - 1] = updatedCandle;
      } catch(e) {
        console.error(`[ChartPanel ${timeframe}] Error updating live price:`, e);
      }
    }
  }, [livePrice, timeframe]);

  // Fetch overlays
  useEffect(() => {
    if (!chartRef.current) return;
    
    if (simulationMode) {
      if (simulationState && simulationState.overlays) {
        setFvgs(simulationState.overlays.fvg[timeframe] || []);
        setFibs(simulationState.overlays.fib[timeframe] || []);
        setBosEvents(simulationState.overlays.bos[timeframe] || []);
      } else {
        setFvgs([]);
        setFibs([]);
        setBosEvents([]);
      }
      return;
    }
    
    Promise.all([
      client.get(`/history/fvg/${timeframe}`),
      client.get(`/history/fib/${timeframe}`),
      client.get(`/history/bos/${timeframe}`),
    ]).then(([fvgRes, fibRes, bosRes]) => {
      setFvgs(fvgRes.data || []);
      setFibs(fibRes.data || []);
      setBosEvents(bosRes.data || []);
    }).catch(err => console.error(`[ChartPanel ${timeframe}] Overlay fetch error:`, err));
  }, [timeframe, dataLoaded, simulationMode, simulationState]); 

  // Handle simulation candles specifically
  useEffect(() => {
    if (simulationMode && candleSeriesRef.current && simulationCandles) {
      candleSeriesRef.current.setData(simulationCandles);
      // Optional: don't fit content on every tick to avoid jittering
      if (simulationCandles.length > 0 && simulationCandles.length <= 200) {
          chartRef.current.timeScale().fitContent();
      }
    }
  }, [simulationMode, simulationCandles]);

  // Draw TradingView Native Tools and Overlays
  useEffect(() => {
    if (!chartRef.current || !candleSeriesRef.current) return;

    const data = ohlcvDataRef.current;
    if (data.length === 0) return;
    const firstTime = data[0].time;
    const lastTime = data[data.length - 1].time;

    // Cleanup previous overlays and primitives
    overlaySeriesRef.current.forEach((s) => {
      try { chartRef.current?.removeSeries(s); } catch {}
    });
    overlaySeriesRef.current = [];

    customPrimitivesRef.current.forEach((p) => {
      try { candleSeriesRef.current?.detachPrimitive(p); } catch {}
    });
    customPrimitivesRef.current = [];

    let markers = [];

    // Helper: BOS time for grid start
    const getGridStartTime = (grid) => {
      const bos = bosEvents.find(b => b.event_id === grid.anchor_event_id);
      if (bos) return toUnix(bos.bos_candle_ts);
      return Math.max(toUnix(grid.swing_low_ts), toUnix(grid.swing_high_ts));
    };

    // Helper: Snap arbitrary time to the closest existing candle time
    const snapTime = (targetUnix) => {
      if (targetUnix < data[0].time) return data[0].time - 1; 
      if (targetUnix > data[data.length - 1].time) return data[data.length - 1].time + 1;
      
      let closest = data[0].time;
      let minDiff = Infinity;
      // Reverse loop since we usually look for recent times
      for (let i = data.length - 1; i >= 0; i--) {
        const diff = Math.abs(data[i].time - targetUnix);
        if (diff < minDiff) {
          minDiff = diff;
          closest = data[i].time;
        }
        if (diff > minDiff) break; // Optimization: since times are sorted, once diff increases, we passed it
      }
      return closest;
    };

    // ──────────────────────────────────────────────────────────
    // 1. Trades (Long/Short Position Tools)
    // ──────────────────────────────────────────────────────────
    const shouldDrawTrades = (timeframe === '4H' || timeframe === '1H' || timeframe === '1M');
    if (shouldDrawTrades && trades.length > 0) {
      const relevantTrades = trades.filter((trade) => {
        if (trade.trade_type === 'scalp' && (timeframe !== '1H' && timeframe !== '4H')) return false;
        if (trade.trade_type !== 'scalp' && timeframe !== '1M') return false;
        
        const endT = trade.exit_ts ? toUnix(trade.exit_ts) : lastTime;
        if (endT < firstTime) return false;

        return true;
      });

      const recentTrades = relevantTrades.slice(-15);

      recentTrades.forEach((trade) => {
        const rawStartT = toUnix(trade.entry_ts);
        const rawEndT = trade.exit_ts ? toUnix(trade.exit_ts) : lastTime;
        
        // Snap times to avoid null coordinates!
        const startT = snapTime(rawStartT);
        const endT = snapTime(rawEndT);
        
        const isWin = trade.pnl_pct > 0;
        const isBullish = trade.direction === 'bullish';
        const rMultiples = trade.pnl_pct.toFixed(1);
        
        const tpBox = new BoxPrimitive(
          startT, 
          endT, 
          trade.entry_price, 
          trade.take_profit, 
          COLORS.bullishDim,
          { borders: true, text: `TP (${trade.take_profit.toFixed(2)})`, firstTime, textPosition: 'top' }
        );
        const slBox = new BoxPrimitive(
          startT, 
          endT, 
          trade.entry_price, 
          trade.stop_loss, 
          COLORS.bearishDim,
          { borders: true, text: `SL (${trade.stop_loss.toFixed(2)})`, firstTime, textPosition: 'bottom' }
        );
        
        candleSeriesRef.current.attachPrimitive(tpBox);
        candleSeriesRef.current.attachPrimitive(slBox);
        customPrimitivesRef.current.push(tpBox, slBox);

        markers.push({
          time: startT,
          position: isBullish ? 'belowBar' : 'aboveBar',
          color: isWin ? COLORS.bullish : COLORS.bearish,
          shape: isBullish ? 'arrowUp' : 'arrowDown',
          text: isWin ? `WIN (+${rMultiples}R)` : `LOSS (${rMultiples}R)`,
        });
      });
    }

    // ──────────────────────────────────────────────────────────
    // 2. Fibonacci Retracements (Shaded Golden Zone + Levels)
    // ──────────────────────────────────────────────────────────
    if (fibs.length > 0) {
      const sortedFibs = [...fibs].sort((a, b) => getGridStartTime(a) - getGridStartTime(b));
      
      const relevantFibs = sortedFibs.filter((grid, index) => {
        const nextGrid = sortedFibs[index + 1];
        const endTime = nextGrid ? getGridStartTime(nextGrid) : lastTime;
        return endTime >= firstTime;
      });

      const recentFibs = relevantFibs.slice(-3);

      recentFibs.forEach((grid, index) => {
        const rawStartTime = getGridStartTime(grid);
        const nextGrid = recentFibs[index + 1];
        const rawEndTime = nextGrid ? getGridStartTime(nextGrid) : lastTime;

        const startTime = snapTime(rawStartTime);
        const endTime = snapTime(rawEndTime);

        const fibLevels = [
          { price: grid.level_1_000, color: '#555555', width: 1, style: 2, label: '1.0' },
          { price: grid.level_0_618, color: '#DAA520', width: 2, style: 0, label: '0.618' },
          { price: grid.level_0_500, color: '#FFFFFF', width: 2, style: 2, label: '0.5' },
          { price: grid.level_0_382, color: '#DAA520', width: 2, style: 0, label: '0.382' },
          { price: grid.level_0_000, color: '#555555', width: 1, style: 2, label: '0.0' }
        ];

        const trendline = {
            t1: snapTime(toUnix(grid.direction === 'bullish' ? grid.swing_low_ts : grid.swing_high_ts)),
            p1: grid.level_0_000,
            t2: snapTime(toUnix(grid.direction === 'bullish' ? grid.swing_high_ts : grid.swing_low_ts)),
            p2: grid.level_1_000
        };

        // Draw outer box from 1.0 to 0.0 with transparent color just to render lines
        const outerBox = new BoxPrimitive(
            startTime, endTime, grid.level_1_000, grid.level_0_000, 'transparent',
            { levels: [fibLevels[0], fibLevels[4]], firstTime, trendline }
        );

        // Draw Golden Zone Box (0.618 to 0.382)
        const fibBox = new BoxPrimitive(
          startTime, 
          endTime, 
          grid.level_0_618, 
          grid.level_0_382, 
          COLORS.goldDim,
          { levels: [fibLevels[1], fibLevels[2], fibLevels[3]], firstTime }
        );
        
        candleSeriesRef.current.attachPrimitive(outerBox);
        candleSeriesRef.current.attachPrimitive(fibBox);
        customPrimitivesRef.current.push(outerBox, fibBox);
      });
    }

    // ──────────────────────────────────────────────────────────
    // 3. FVG Zones (Shaded Rectangles)
    // ──────────────────────────────────────────────────────────
    if (fvgs.length > 0) {
      const unmitigated = fvgs.filter(f => !f.is_mitigated);
      // FVGs extend to lastTime, so they always end at lastTime >= firstTime. 
      // But they shouldn't draw if they are completely offscreen, although lastTime is on screen.
      const recentFvgs = unmitigated.slice(-10);

      recentFvgs.forEach((fvg) => {
        const startT = toUnix(fvg.ts_candle1);
        const endT = lastTime;
        const isBullish = fvg.direction === 'bullish';
        const color = isBullish ? COLORS.fvgBullish : COLORS.fvgBearish;
        
        const fvgBox = new BoxPrimitive(
          startT, 
          endT, 
          fvg.gap_top, 
          fvg.gap_bottom, 
          color,
          { borders: true, text: isBullish ? 'FVG (+)' : 'FVG (-)', firstTime }
        );
        candleSeriesRef.current.attachPrimitive(fvgBox);
        customPrimitivesRef.current.push(fvgBox);
      });
    }

    // ──────────────────────────────────────────────────────────
    // 4. BOS Markers
    // ──────────────────────────────────────────────────────────
    if (bosEvents.length > 0) {
      // Limit to last 20 BOS events
      const recentBos = bosEvents.slice(-20);
      recentBos.forEach((bos) => {
        markers.push({
          time: toUnix(bos.bos_candle_ts),
          position: bos.direction === 'bullish' ? 'belowBar' : 'aboveBar',
          color: bos.direction === 'bullish' ? COLORS.bullish : COLORS.bearish,
          shape: bos.direction === 'bullish' ? 'arrowUp' : 'arrowDown',
          text: `BOS`,
        });
      });
    }

    // Process Markers
    markers.sort((a, b) => a.time - b.time);
    
    // Deduplicate markers at same time (keep trade markers over BOS)
    const uniqueMarkers = [];
    const seenTimes = new Set();
    for (const m of markers) {
      if (!seenTimes.has(m.time)) {
        seenTimes.add(m.time);
        uniqueMarkers.push(m);
      } else {
          if (m.text !== 'BOS') {
              const idx = uniqueMarkers.findIndex(x => x.time === m.time);
              if (idx >= 0) uniqueMarkers[idx] = m;
          }
      }
    }

    try {
      candleSeriesRef.current.setMarkers(uniqueMarkers);
    } catch {}

  }, [fibs, fvgs, bosEvents, trades, timeframe, dataLoaded]);

  return (
    <div className="chart-panel">
      <div className="chart-header">
        <span className="chart-timeframe">{label}</span>
        <span className="chart-tf-badge">{timeframe}</span>
        {fibs.length > 0 && (
          <span className="chart-fib-count">{fibs.length} grid{fibs.length !== 1 ? 's' : ''}</span>
        )}
        {fvgs.length > 0 && (
          <span className="chart-fvg-count">{fvgs.length} FVG{fvgs.length !== 1 ? 's' : ''}</span>
        )}
        {bosEvents.length > 0 && (
          <span className="chart-bos-count">{bosEvents.length} BOS</span>
        )}
        
        {(onPromote || onExpand) && (
          <div className="chart-header-actions">
            {onExpand && (
              <button className="icon-btn" onClick={onExpand} title="Expand Chart">
                ⤢
              </button>
            )}
            {onPromote && (
              <button className="icon-btn" onClick={onPromote} title="Promote to Master">
                ★
              </button>
            )}
          </div>
        )}
      </div>
      <div ref={containerRef} className="chart-container" />
    </div>
  );
}
