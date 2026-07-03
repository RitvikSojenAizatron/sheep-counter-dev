import { useCallback, useEffect, useRef, useState } from 'react';

export interface PipelineMetric {
  heartbeat: string;
  fps: number;
  latencyMs: number;
}

export interface CameraMetric {
  lastUpdate: string;
  counts: Record<string, number>;
}

export interface WebSocketState {
  connected: boolean;
  connectedAt: number | null;
  pipelineMetric: PipelineMetric | null;
  cameraMetrics: Record<string, CameraMetric>;
  sourceStatus: Record<string, boolean>;
}

const WS_URL = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000/ws';
const RECONNECT_DELAY_MS = 3_000;

export function useWebSocket(): WebSocketState {
  const [state, setState] = useState<WebSocketState>({
    connected: false,
    connectedAt: null,
    pipelineMetric: null,
    cameraMetrics: {},
    sourceStatus: {},
  });

  const wsRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const deadRef = useRef(false);

  const connect = useCallback(() => {
    if (deadRef.current) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setState((prev) => ({ ...prev, connected: true, connectedAt: Date.now() }));
    };

    ws.onmessage = (event: MessageEvent) => {
      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(event.data as string);
      } catch {
        return;
      }

      const { type } = msg;
      if (type === 'pipeline_metric') {
        setState((prev) => ({
          ...prev,
          pipelineMetric: {
            heartbeat: msg.heartbeat as string,
            fps: msg.fps as number,
            latencyMs: msg.latencyMs as number,
          },
        }));
      } else if (type === 'camera_metric') {
        const cameraId = msg.cameraId as string;
        setState((prev) => ({
          ...prev,
          cameraMetrics: {
            ...prev.cameraMetrics,
            [cameraId]: {
              lastUpdate: msg.lastUpdate as string,
              counts: (msg.counts ?? {}) as Record<string, number>,
            },
          },
        }));
      } else if (type === 'source_status') {
        const cameraId = msg.cameraId as string;
        setState((prev) => ({
          ...prev,
          sourceStatus: {
            ...prev.sourceStatus,
            [cameraId]: msg.online as boolean,
          },
        }));
      }
    };

    ws.onclose = () => {
      setState((prev) => ({ ...prev, connected: false, connectedAt: null }));
      if (!deadRef.current) {
        timerRef.current = setTimeout(connect, RECONNECT_DELAY_MS);
      }
    };

    ws.onerror = () => {
      ws.close();
    };
  }, []);

  useEffect(() => {
    deadRef.current = false;
    connect();
    return () => {
      deadRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return state;
}
