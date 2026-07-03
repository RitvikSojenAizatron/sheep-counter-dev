import { useEffect, useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Box,
  Button,
  Paper,
  Stack,
  Typography,
  Switch,
  FormControlLabel,
  Chip,
  TextField,
  Tooltip,
} from '@mui/material';
import FullscreenIcon from '@mui/icons-material/Fullscreen';
import FullscreenExitIcon from '@mui/icons-material/FullscreenExit';
import SaveIcon from '@mui/icons-material/Save';
import DirectionsCarIcon from '@mui/icons-material/DirectionsCar';
import PeopleAltIcon from '@mui/icons-material/PeopleAlt';
import VideocamOffIcon from '@mui/icons-material/VideocamOff';
import EditIcon from '@mui/icons-material/Edit';
import SwapHorizIcon from '@mui/icons-material/SwapHoriz';
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord';
import StopIcon from '@mui/icons-material/Stop';
import { webRtcClient } from '../utils/webrtcClient';
import { sheepCounterApi } from '../api/visionApi';
import { useWebSocket } from '../utils/useWebSocket';
import { parseISO } from 'date-fns';
import { Camera, Line, LiveStreamConfig } from '../types/domain';

const PIPELINE_STALE_MS = 10_000;
const PIPELINE_GRACE_MS = 5_000;

const computeCrossingVector = (
  start: { x: number; y: number },
  end: { x: number; y: number },
  flip: boolean,
) => {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const mag = Math.sqrt(dx * dx + dy * dy) || 1;
  return flip
    ? { x: dy / mag, y: -dx / mag }
    : { x: -dy / mag, y: dx / mag };
};

export const LivePage = () => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const videoContainerRef = useRef<HTMLDivElement>(null);
  const {
    connected: wsConnected,
    connectedAt: wsConnectedAt,
    pipelineMetric,
    cameraMetrics,
    sourceStatus,
  } = useWebSocket();
  const [showMetricsOverlay, setShowMetricsOverlay] = useState(true);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [videoError, setVideoError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  const retryDelayRef = useRef(2_000);

  const [videoSize, setVideoSize] = useState({ w: 16, h: 9 });
  const [containerSize, setContainerSize] = useState({ w: 0, h: 0 });

  useEffect(() => {
    const el = videoRef.current;
    if (!el) return;
    const onMeta = () => {
      if (el.videoWidth && el.videoHeight)
        setVideoSize({ w: el.videoWidth, h: el.videoHeight });
    };
    el.addEventListener('loadedmetadata', onMeta);
    return () => el.removeEventListener('loadedmetadata', onMeta);
  }, [retryKey]);

  useEffect(() => {
    const el = videoContainerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setContainerSize({ w: width, h: height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const [drawMode, setDrawMode] = useState(false);
  const [drawPoints, setDrawPoints] = useState<{ x: number; y: number }[]>([]);
  const [pendingLine, setPendingLine] = useState<{
    start: { x: number; y: number };
    end: { x: number; y: number };
  } | null>(null);
  const [lineName, setLineName] = useState('');
  const [flipCrossing, setFlipCrossing] = useState(false);
  const [editingLineId, setEditingLineId] = useState<string | null>(null);
  const [editingCameraId, setEditingCameraId] = useState<string | null>(null);

  const queryClient = useQueryClient();

  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 3_000);
    return () => clearInterval(id);
  }, []);

  const pipelineStatus: 'loading' | 'online' | 'offline' = (() => {
    if (!wsConnected) return 'loading';
    if (pipelineMetric === null) {
      if (wsConnectedAt !== null && now - wsConnectedAt < PIPELINE_GRACE_MS) return 'loading';
      return 'offline';
    }
    return now - parseISO(pipelineMetric.heartbeat).getTime() < PIPELINE_STALE_MS
      ? 'online'
      : 'offline';
  })();


  const streamConfigQuery = useQuery<LiveStreamConfig>({
    queryKey: ['live-stream-config'],
    queryFn: sheepCounterApi.fetchLiveStreamConfig,
  });


  useEffect(() => {
    if (videoError === null) return;
    const id = setTimeout(() => setRetryKey((k) => k + 1), retryDelayRef.current);
    return () => clearTimeout(id);
  }, [videoError]);

  const camerasQuery = useQuery<Camera[]>({
    queryKey: ['cameras'],
    queryFn: sheepCounterApi.fetchCameras,
  });

  const linesQuery = useQuery<Line[]>({
    queryKey: ['lines'],
    queryFn: sheepCounterApi.fetchLines,
  });

  const recordCountsMutation = useMutation({
    mutationFn: sheepCounterApi.recordCounts,
  });

  const [isRecording, setIsRecording] = useState(false);

  const startRecordingMutation = useMutation({
    mutationFn: sheepCounterApi.startRecording,
    onSuccess: () => setIsRecording(true),
  });

  const stopRecordingMutation = useMutation({
    mutationFn: sheepCounterApi.stopRecording,
    onSuccess: () => setIsRecording(false),
  });

  const createLineMutation = useMutation({
    mutationFn: (line: Line) => sheepCounterApi.createLine(line),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lines'] });
      setPendingLine(null);
      setLineName('');
      setFlipCrossing(false);
      setDrawMode(false);
      setDrawPoints([]);
    },
  });

  const updateLineMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<Line> }) =>
      sheepCounterApi.updateLine(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lines'] });
      setPendingLine(null);
      setLineName('');
      setFlipCrossing(false);
      setDrawMode(false);
      setDrawPoints([]);
      setEditingLineId(null);
      setEditingCameraId(null);
    },
  });

  useEffect(() => {
    const whepUrl = streamConfigQuery.data?.whepUrl;
    if (!whepUrl) return;

    let cleanup: (() => Promise<void>) | undefined;
    setVideoError(null);

    const attach = async () => {
      if (!videoRef.current) return;
      try {
        cleanup = await webRtcClient.attachRealStream(videoRef.current, whepUrl, (reason) => {
          setVideoError(reason);
        });
        retryDelayRef.current = 2_000;
      } catch (err) {
        const isRetryable = err instanceof Error && (err as Error & { retryable?: boolean }).retryable;
        retryDelayRef.current = isRetryable ? 2_000 : 5_000;
        setVideoError(err instanceof Error ? err.message : 'Stream connection failed');
      }
    };

    void attach();

    return () => {
      if (cleanup) void cleanup();
    };
  }, [streamConfigQuery.data?.whepUrl, retryKey]);

  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(Boolean(document.fullscreenElement));
    };
    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => {
      document.removeEventListener('fullscreenchange', handleFullscreenChange);
    };
  }, []);

  const onFullscreen = () => {
    if (document.fullscreenElement) {
      document.exitFullscreen?.();
    } else if (videoContainerRef.current?.requestFullscreen) {
      videoContainerRef.current.requestFullscreen();
    }
  };

  const getMetricState = (cameraId: string) => {
    const metric = cameraMetrics[cameraId];
    if (cameraId in sourceStatus) {
      return { metric, isStale: false, isOffline: !sourceStatus[cameraId] };
    }
    const isStale = metric
      ? Date.now() - parseISO(metric.lastUpdate).getTime() > 15000
      : true;
    return { metric, isStale, isOffline: false };
  };

  // Compute where the video is actually rendered within the container (objectFit: contain).
  const letterbox = (() => {
    const { w: cW, h: cH } = containerSize;
    const { w: vW, h: vH } = videoSize;
    if (!cW || !cH) return { x: 0, y: 0, w: cW || 1, h: cH || 1 };
    const vAspect = vW / vH;
    const cAspect = cW / cH;
    if (vAspect >= cAspect) {
      const rH = cW / vAspect;
      return { x: 0, y: (cH - rH) / 2, w: cW, h: rH };
    }
    const rW = cH * vAspect;
    return { x: (cW - rW) / 2, y: 0, w: rW, h: cH };
  })();

  // Normalized (0–1 of video frame) → SVG % of container.
  const toSvgPct = (nx: number, ny: number) => ({
    x: ((nx * letterbox.w + letterbox.x) / (containerSize.w || 1)) * 100,
    y: ((ny * letterbox.h + letterbox.y) / (containerSize.h || 1)) * 100,
  });

  // Container-relative pixels → normalized (0–1 of video frame), clamped.
  const toNorm = (px: number, py: number) => ({
    x: Math.max(0, Math.min(1, (px - letterbox.x) / (letterbox.w || 1))),
    y: Math.max(0, Math.min(1, (py - letterbox.y) / (letterbox.h || 1))),
  });

  const handleVideoContainerClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!drawMode || !videoContainerRef.current) return;
    if ((e.target as HTMLElement).closest('button')) return;

    const rect = videoContainerRef.current.getBoundingClientRect();
    const { x: nx, y: ny } = toNorm(e.clientX - rect.left, e.clientY - rect.top);

    if (drawPoints.length === 0) {
      setDrawPoints([{ x: nx, y: ny }]);
    } else {
      setPendingLine({ start: drawPoints[0], end: { x: nx, y: ny } });
      setDrawPoints([]);
    }
  };

  const handleSaveLine = () => {
    if (!pendingLine || !lineName.trim()) return;
    const cv = computeCrossingVector(pendingLine.start, pendingLine.end, flipCrossing);
    if (editingLineId) {
      updateLineMutation.mutate({
        id: editingLineId,
        payload: {
          name: lineName.trim(),
          cameraId: editingCameraId ?? camerasQuery.data?.[0]?.id ?? '',
          endpoints: [pendingLine.start, pendingLine.end],
          crossing_vector: [cv],
        },
      });
    } else {
      createLineMutation.mutate({
        name: lineName.trim(),
        cameraId: camerasQuery.data?.[0]?.id ?? '',
        endpoints: [pendingLine.start, pendingLine.end],
        crossing_vector: [cv],
      });
    }
  };

  const cancelPending = () => {
    setPendingLine(null);
    setLineName('');
    setFlipCrossing(false);
    setEditingLineId(null);
    setEditingCameraId(null);
  };

  const handleEditLine = (line: Line) => {
    if (!line.id || line.endpoints.length < 2) return;
    const [start, end] = line.endpoints;
    const storedCv = line.crossing_vector?.[0];
    let flip = false;
    if (storedCv) {
      const noFlipCv = computeCrossingVector(start, end, false);
      flip = noFlipCv.x * storedCv.x + noFlipCv.y * storedCv.y < 0;
    }
    setPendingLine({ start, end });
    setLineName(line.name);
    setFlipCrossing(flip);
    setEditingLineId(line.id);
    setEditingCameraId(line.cameraId);
    setDrawMode(false);
    setDrawPoints([]);
  };

  // Line endpoints are stored as 0-1 fractions of the video frame.
  const lineToSvgCoords = (line: {
    endpoints: { x: number; y: number }[];
    crossing_vector?: { x: number; y: number }[];
  }) => {
    if (line.endpoints.length < 2) return null;
    const p1 = toSvgPct(line.endpoints[0].x, line.endpoints[0].y);
    const p2 = toSvgPct(line.endpoints[1].x, line.endpoints[1].y);
    const mid = { x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 };
    const cv = line.crossing_vector?.[0];
    const midNorm = {
      x: (line.endpoints[0].x + line.endpoints[1].x) / 2,
      y: (line.endpoints[0].y + line.endpoints[1].y) / 2,
    };
    const arrowEnd = cv ? toSvgPct(midNorm.x + cv.x * 0.05, midNorm.y + cv.y * 0.05) : null;
    return { p1, p2, mid, arrowEnd };
  };

  const pendingSvgCoords = (() => {
    if (!pendingLine) return null;
    const p1 = toSvgPct(pendingLine.start.x, pendingLine.start.y);
    const p2 = toSvgPct(pendingLine.end.x, pendingLine.end.y);
    const mid = { x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 };
    const cv = computeCrossingVector(pendingLine.start, pendingLine.end, flipCrossing);
    const midNorm = {
      x: (pendingLine.start.x + pendingLine.end.x) / 2,
      y: (pendingLine.start.y + pendingLine.end.y) / 2,
    };
    const arrowEnd = toSvgPct(midNorm.x + cv.x * 0.05, midNorm.y + cv.y * 0.05);
    return { p1, p2, mid, arrowEnd };
  })();

  const showOfflineOverlay = videoError !== null;

  const camera = camerasQuery.data?.[0];
  const { metric, isStale, isOffline } = camera
    ? getMetricState(camera.id)
    : { metric: undefined, isStale: true, isOffline: false };

  return (
    <Stack spacing={3}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Stack direction="row" spacing={2} alignItems="center">
          <Typography variant="h4">Live Operations</Typography>
          {pipelineStatus === 'offline' ? (
            <Chip label="Pipeline offline" size="small" color="error" variant="outlined" />
          ) : (
            <Stack
              direction="row"
              spacing={1.5}
              alignItems="center"
              sx={{
                backgroundColor: 'action.hover',
                borderRadius: 999,
                px: 1.5,
                py: 0.5,
              }}
            >
              <Typography variant="caption" color="text.secondary">FPS</Typography>
              <Typography variant="body2">
                {pipelineMetric?.fps ? pipelineMetric.fps.toFixed(1) : '--'}
              </Typography>
              <Typography variant="caption" color="text.secondary">Latency</Typography>
              <Typography variant="body2">
                {pipelineMetric?.latencyMs
                  ? `${pipelineMetric.latencyMs.toFixed(0)} ms`
                  : '--'}
              </Typography>
            </Stack>
          )}
        </Stack>
        <Stack direction="row" spacing={2} alignItems="center">
          <FormControlLabel
            control={
              <Switch
                checked={showMetricsOverlay}
                onChange={(e) => setShowMetricsOverlay(e.target.checked)}
              />
            }
            label="Metrics overlay"
          />
          <Tooltip
            title={
              drawMode
                ? drawPoints.length === 0
                  ? 'Click to place start point'
                  : 'Click to place end point'
                : 'Draw a counting line on the stream'
            }
          >
            <Button
              variant={drawMode ? 'contained' : 'outlined'}
              color={drawMode ? 'warning' : 'inherit'}
              startIcon={<EditIcon />}
              onClick={() => {
                setDrawMode((m) => !m);
                setDrawPoints([]);
                cancelPending();
              }}
            >
              {drawMode
                ? drawPoints.length === 0
                  ? 'Click start…'
                  : 'Click end…'
                : 'Draw Line'}
            </Button>
          </Tooltip>
          <Button
            variant="outlined"
            startIcon={<SaveIcon />}
            onClick={() => recordCountsMutation.mutate()}
            disabled={recordCountsMutation.isPending}
          >
            {recordCountsMutation.isPending ? 'Saving…' : 'Record Counts'}
          </Button>
          <Button
            variant={isRecording ? 'contained' : 'outlined'}
            color={isRecording ? 'error' : 'inherit'}
            startIcon={isRecording ? <StopIcon /> : <FiberManualRecordIcon />}
            onClick={() => {
              if (isRecording) {
                stopRecordingMutation.mutate();
              } else {
                startRecordingMutation.mutate();
              }
            }}
            disabled={startRecordingMutation.isPending || stopRecordingMutation.isPending}
          >
            {isRecording ? 'Stop Recording' : 'Record'}
          </Button>
          <Button variant="outlined" startIcon={<FullscreenIcon />} onClick={onFullscreen}>
            Fullscreen
          </Button>
        </Stack>
      </Stack>

      <Box
        ref={videoContainerRef}
        onClick={handleVideoContainerClick}
        sx={{
          position: 'relative',
          borderRadius: 2,
          overflow: 'hidden',
          backgroundColor: 'common.black',
          boxSizing: 'border-box',
          maxHeight: 'calc(100vh - 200px)',
          aspectRatio: `${videoSize.w} / ${videoSize.h}`,
          width: '100%',
          cursor: drawMode ? 'crosshair' : 'default',
          '&:fullscreen': {
            width: '100vw',
            height: '100vh',
            borderRadius: 0,
          },
        }}
      >
        <Box
          component="video"
          ref={videoRef}
          muted
          playsInline
          autoPlay
          sx={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            display: 'block',
            objectFit: 'contain',
            zIndex: 0,
            outline: 'none',
            border: 'none',
          }}
        />

        {showMetricsOverlay && camera && (
          <Stack
            direction="row"
            spacing={1}
            alignItems="center"
            sx={{
              position: 'absolute',
              top: 12,
              left: 12,
              zIndex: 2,
              backgroundColor: 'rgba(15, 23, 42, 0.75)',
              borderRadius: 999,
              px: 1.5,
              py: 0.75,
              color: 'common.white',
              pointerEvents: 'none',
            }}
          >
            <Typography variant="caption" sx={{ opacity: 0.85 }}>{camera.name}</Typography>
            <Chip
              size="small"
              label={isOffline ? 'Offline' : isStale ? 'Stale' : 'Live'}
              color={isOffline ? 'error' : isStale ? 'warning' : 'success'}
            />
            {Object.entries(metric?.counts ?? {}).map(([label, count]) => (
              <Stack key={label} direction="row" spacing={0.5} alignItems="center">
                {label === 'person' ? (
                  <PeopleAltIcon fontSize="small" color="info" />
                ) : label === 'car' ? (
                  <DirectionsCarIcon fontSize="small" color="warning" />
                ) : (
                  <Typography variant="caption" sx={{ opacity: 0.7 }}>{label}</Typography>
                )}
                <Typography variant="caption">{count}</Typography>
              </Stack>
            ))}
          </Stack>
        )}

        <Box
          component="svg"
          sx={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            zIndex: 3,
            pointerEvents: 'none',
            overflow: 'visible',
          }}
        >
          <defs>
            <marker id="arrow-cyan" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
              <path d="M0,0 L0,6 L8,3 z" fill="cyan" />
            </marker>
            <marker id="arrow-yellow" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
              <path d="M0,0 L0,6 L8,3 z" fill="yellow" />
            </marker>
          </defs>

          {(linesQuery.data ?? []).map((line) => {
            const coords = lineToSvgCoords(line);
            if (!coords) return null;
            const { p1, p2, mid, arrowEnd } = coords;
            return (
              <g key={line.id ?? line.name}>
                <line
                  x1={`${p1.x}%`} y1={`${p1.y}%`}
                  x2={`${p2.x}%`} y2={`${p2.y}%`}
                  stroke="cyan" strokeWidth={2}
                />
                {arrowEnd && (
                  <line
                    x1={`${mid.x}%`} y1={`${mid.y}%`}
                    x2={`${arrowEnd.x}%`} y2={`${arrowEnd.y}%`}
                    stroke="cyan" strokeWidth={2}
                    markerEnd="url(#arrow-cyan)"
                  />
                )}
                <text
                  x={`${mid.x}%`} y={`${mid.y}%`}
                  fill="cyan" fontSize={11} fontFamily="sans-serif"
                  textAnchor="middle" dy="-4"
                >
                  {line.name}
                </text>
              </g>
            );
          })}

          {drawPoints.length === 1 && (() => {
            const pt = toSvgPct(drawPoints[0].x, drawPoints[0].y);
            return <circle cx={`${pt.x}%`} cy={`${pt.y}%`} r={5} fill="yellow" />;
          })()}

          {pendingSvgCoords && (
            <g>
              <line
                x1={`${pendingSvgCoords.p1.x}%`} y1={`${pendingSvgCoords.p1.y}%`}
                x2={`${pendingSvgCoords.p2.x}%`} y2={`${pendingSvgCoords.p2.y}%`}
                stroke="yellow" strokeWidth={2} strokeDasharray="6 3"
              />
              <line
                x1={`${pendingSvgCoords.mid.x}%`} y1={`${pendingSvgCoords.mid.y}%`}
                x2={`${pendingSvgCoords.arrowEnd.x}%`} y2={`${pendingSvgCoords.arrowEnd.y}%`}
                stroke="yellow" strokeWidth={2}
                markerEnd="url(#arrow-yellow)"
              />
              <circle cx={`${pendingSvgCoords.p1.x}%`} cy={`${pendingSvgCoords.p1.y}%`} r={5} fill="yellow" />
              <circle cx={`${pendingSvgCoords.p2.x}%`} cy={`${pendingSvgCoords.p2.y}%`} r={5} fill="yellow" />
            </g>
          )}
        </Box>

        {showOfflineOverlay && (
          <Box
            sx={{
              position: 'absolute',
              inset: 0,
              zIndex: 4,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 1.5,
              backgroundColor: 'rgba(15, 23, 42, 0.88)',
              color: 'common.white',
            }}
          >
            <VideocamOffIcon sx={{ fontSize: 52, color: 'text.disabled' }} />
            <Typography variant="h6">
              {pipelineStatus === 'offline' ? 'Pipeline offline' : 'Reconnecting video...'}
            </Typography>
            <Typography variant="body2" color="text.secondary" textAlign="center" maxWidth={340}>
              {pipelineStatus === 'offline'
                ? 'The inference pipeline is not running. Video and metrics will resume once it starts.'
                : 'Pipeline is online — waiting for the video stream to become available.'}
            </Typography>
          </Box>
        )}

        {isFullscreen && (
          <Button
            variant="contained"
            color="inherit"
            size="small"
            startIcon={<FullscreenExitIcon />}
            onClick={onFullscreen}
            sx={{
              position: 'absolute',
              bottom: 16,
              left: '50%',
              transform: 'translateX(-50%)',
              zIndex: 5,
              backgroundColor: 'rgba(15, 23, 42, 0.75)',
              color: 'common.white',
              '&:hover': { backgroundColor: 'rgba(15, 23, 42, 0.9)' },
            }}
          >
            Exit Fullscreen
          </Button>
        )}
      </Box>

      {pendingLine && (
        <Paper
          component="form"
          onSubmit={(e) => { e.preventDefault(); handleSaveLine(); }}
          variant="outlined"
          sx={{ p: 2 }}
        >
          <Stack direction="row" spacing={2} alignItems="center">
            <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'nowrap' }}>
              {editingLineId ? 'Edit line' : 'Save line'}
            </Typography>
            <TextField
              label="Line name"
              value={lineName}
              onChange={(e) => setLineName(e.target.value)}
              size="small"
              autoFocus
              sx={{ flex: 1 }}
            />
            {editingLineId && (
              <Tooltip title="Re-draw line endpoints on the video">
                <Button
                  variant="outlined"
                  size="small"
                  startIcon={<EditIcon />}
                  onClick={() => {
                    setPendingLine(null);
                    setDrawPoints([]);
                    setDrawMode(true);
                  }}
                >
                  Redraw
                </Button>
              </Tooltip>
            )}
            <Button
              variant="outlined"
              size="small"
              startIcon={<SwapHorizIcon />}
              onClick={() => setFlipCrossing((f) => !f)}
            >
              {flipCrossing ? 'Flipped' : 'Default'}
            </Button>
            <Button onClick={() => { cancelPending(); setDrawMode(false); setDrawPoints([]); }} size="small">Cancel</Button>
            <Button
              type="submit"
              variant="contained"
              size="small"
              disabled={!lineName.trim() || createLineMutation.isPending || updateLineMutation.isPending}
            >
              {editingLineId ? 'Update' : 'Save'}
            </Button>
          </Stack>
        </Paper>
      )}

      {(linesQuery.data ?? []).length > 0 && !pendingLine && (
        <Paper variant="outlined" sx={{ p: 2 }}>
          <Typography variant="subtitle2" color="text.secondary" gutterBottom>
            Counting lines
          </Typography>
          <Stack spacing={1}>
            {(linesQuery.data ?? []).map((line) => (
              <Stack
                key={line.id ?? line.name}
                direction="row"
                alignItems="center"
                spacing={2}
              >
                <Box
                  sx={{
                    width: 16,
                    height: 2,
                    backgroundColor: 'cyan',
                    flexShrink: 0,
                  }}
                />
                <Typography variant="body2" sx={{ flex: 1 }}>
                  {line.name}
                </Typography>
                <Button
                  size="small"
                  startIcon={<EditIcon />}
                  onClick={() => handleEditLine(line)}
                >
                  Edit
                </Button>
              </Stack>
            ))}
          </Stack>
        </Paper>
      )}
    </Stack>
  );
};
