import { apiClient } from './client';
import {
  Camera,
  Line,
  LiveStreamConfig
} from '../types/domain';
import type { AuditEntry, AuditEntryInput } from '../types/audit';
type Vec2 = { x: number; y: number };

export const sheepCounterApi = {
  fetchCameras: () =>
    apiClient.get<Camera[]>('/api/cameras').then((res) => res.data),
  createCamera: (payload: Camera) =>
    apiClient.post('/api/cameras', payload).then((res) => res.data),
  updateCamera: (id: string, payload: Partial<Camera>) =>
    apiClient.patch(`/api/cameras/${id}`, payload).then((res) => res.data),
  deleteCamera: (id: string) =>
    apiClient.delete(`/api/cameras/${id}`).then((res) => res.data),
  fetchLines: () =>
    apiClient.get<Line[]>('/api/lines').then((res) => res.data),
  createLine: (payload: Line) =>
    apiClient.post<Line>('/api/lines', payload).then((res) => res.data),
  updateLine: (id: string, payload: Partial<Line>) =>
    apiClient.patch<Line>(`/api/lines/${id}`, payload).then((res) => res.data),
  deleteLine: (id: string) =>
    apiClient.delete(`/api/lines/${id}`).then((res) => res.data),
  fetchServices: () =>
    apiClient
      .get<SystemService[]>('/api/system/services')
      .then((res) => res.data),

  fetchServiceLogs: (params: FetchServiceLogsParams = {}) =>
    apiClient
      .get<ServiceLogRecord[]>('/api/system/logs', { params })
      .then((res) => res.data),
  restartService: (serviceName: string) =>
    apiClient
      .post(`/api/system/services/${serviceName}/restart`)
      .then((res) => res.data),
  sendCommand: (payload: { action: string }) =>
    apiClient.post('/api/system/commands', payload).then((res) => res.data),
  fetchUptime: () =>
    apiClient.get('/api/analytics/uptime').then((res) => res.data),
  recordCounts: () =>
    apiClient.post('/api/counts/record').then((res) => res.data),
  fetchLiveStreamConfig: () =>
    apiClient.get<LiveStreamConfig>('/api/live/stream').then((res) => res.data),
  fetchHostname: () =>
    apiClient
      .get<HostnameStatus>('/api/system/settings/hostname')
      .then((res) => res.data),
  updateHostname: (payload: HostnameUpdatePayload) =>
    apiClient
      .put<HostnameApplyResult>('/api/system/settings/hostname', payload)
      .then((res) => res.data),
  checkHostname: (name: string) =>
    apiClient
      .post<HostnameCheckResult>('/api/system/settings/hostname/check', { name })
      .then((res) => res.data),
};

export interface HostnameStatus {
  desired: {
    os: string | null;
    avahi: string | null;
    updatedAt: string | null;
    updatedBy: string | null;
    lastRequestId: string | null;
  };
  observed: {
    osHostname: string | null;
    avahiConfiguredName: string | null;
    avahiAdvertisedName: string | null;
    lastUpdated: string | null;
    agentVersion: string | null;
  };
  conflictDetected: boolean;
  mongoConnected: boolean;
}

export interface HostnameUpdatePayload {
  osHostname?: string | null;
  avahiHostname?: string | null;
  force?: boolean;
}

export interface HostnameApplyResult {
  requestId: string;
  osHostnameApplied: string | null;
  avahiHostnameApplied: string | null;
  avahiAdvertisedActual: string | null;
  streamHost: string | null;
  conflictDetected: boolean;
  warnings: string[];
}

export interface HostnameCheckResult {
  requestId: string;
  name: string;
  available: boolean;
  claimedBy: string | null;
}
