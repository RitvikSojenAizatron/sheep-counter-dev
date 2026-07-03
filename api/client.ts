import axios, { type AxiosRequestConfig } from 'axios';
import { tokenStorage } from '../utils/storage';
import { refreshSession } from '../utils/session';

type RetriableConfig = AxiosRequestConfig & { _retry?: boolean };

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/',
  timeout: 10000,
});

let isRefreshing = false;
let pendingQueue: Array<(token: string | null) => void> = [];

const resolveQueue = (token: string | null) => {
  pendingQueue.forEach((callback) => callback(token));
  pendingQueue = [];
};

apiClient.interceptors.request.use((config) => {
  const token = tokenStorage.getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config as RetriableConfig;
    const isAuthEndpoint = originalRequest.url?.includes('/api/auth/login') || originalRequest.url?.includes('/change-password');
    if (error.response?.status === 403) {
      console.error('Insufficient permissions for this action');
      return Promise.reject(error);
    }

    if (error.response?.status === 401 && !originalRequest._retry && !isAuthEndpoint) {
      originalRequest._retry = true;
      if (!isRefreshing) {
        isRefreshing = true;
        refreshSession()
          .then(() => {
            resolveQueue(tokenStorage.getAccessToken());
          })
          .catch(() => {
            resolveQueue(null);
          })
          .finally(() => {
            isRefreshing = false;
          });
      }
      return new Promise((resolve, reject) => {
        pendingQueue.push((token) => {
          if (!token) {
            reject(error);
            return;
          }
          originalRequest.headers = {
            ...originalRequest.headers,
            Authorization: `Bearer ${token}`,
          };
          resolve(apiClient(originalRequest));
        });
      });
    }
    return Promise.reject(error);
  },
);
