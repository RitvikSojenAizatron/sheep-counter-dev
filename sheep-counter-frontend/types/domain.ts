export interface Camera {
  id: string;
  name: string;
  tileIndex: number;
  enabled: boolean;
  ipAddress: string;
  password?: string;
  lastFrameTimestamp: string;
  effectiveFps: number;
  online: boolean;
}

export interface Line {
  id?: string;
  name: string;
  cameraId: string;
  endpoints: Array<{ x: number; y: number }>; //endpoints of line
  crossing_vector: Array<{x: number, y:number}>; //direction vector of crossing direction represented as normal to line
}

export interface CountRecord {
  id: string;
  cameraId: string;
  line_id: string;
  timestamp: string;
  count: number,
  delivery: {
    sentToCloud: boolean;
  };
}

export interface LiveStreamConfig {
  whepUrl: string;
  streamId: string;
}

