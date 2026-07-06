import axios from 'axios';

const API_BASE = 'http://localhost:8000/api';

const client = axios.create({
  baseURL: API_BASE,
  timeout: 10000,
});

export default client;
