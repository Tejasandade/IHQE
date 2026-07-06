import { useState, useEffect } from 'react';
import client from '../api/client';

export default function useCascade(pollInterval = 5000) {
  const [data, setData] = useState({ swing: [], scalp_path: [], scalp_cont: [] });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchCascade = () => {
      client
        .get('/cascade/current')
        .then((res) => {
          setData(res.data || { swing: [], scalp_path: [], scalp_cont: [] });
        })
        .catch(() => {})
        .finally(() => setLoading(false));
    };

    fetchCascade();
    const interval = setInterval(fetchCascade, pollInterval);
    return () => clearInterval(interval);
  }, [pollInterval]);

  return { data, loading };
}
