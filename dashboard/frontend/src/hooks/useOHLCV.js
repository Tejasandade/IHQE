import { useState, useEffect } from 'react';
import client from '../api/client';

export default function useOHLCV(timeframe, start, end) {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!timeframe) return;
    setLoading(true);
    const params = {};
    if (start) params.start = start;
    if (end) params.end = end;

    client
      .get(`/ohlcv/${timeframe}`, { params })
      .then((res) => {
        setData(res.data || []);
        setError(null);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [timeframe, start, end]);

  return { data, loading, error };
}
