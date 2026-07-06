import { useState, useEffect, useRef, useCallback } from 'react';

export default function useLivePrice() {
  const [price, setPrice] = useState(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);

  const connect = useCallback(() => {
    const ws = new WebSocket('ws://localhost:8000/api/live/price');
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onclose = () => {
      setConnected(false);
      setTimeout(connect, 3000);
    };
    ws.onerror = () => ws.close();
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'price') {
          setPrice({
            mid: data.midPrice,
            bid: data.bidPrice,
            ask: data.askPrice,
            timestamp: data.timestamp,
          });
        }
      } catch {}
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (wsRef.current) wsRef.current.close();
    };
  }, [connect]);

  return { price, connected };
}
