// The frontend handles a single tiled composite stream; never per-camera streams.
export class WebRTCClient {
  async attachRealStream(
    video: HTMLVideoElement,
    whepUrl: string,
    onDisconnect?: (reason: string) => void,
  ) {
    if (!whepUrl) {
      throw new Error('Missing WHEP URL');
    }

    const pc = new RTCPeerConnection({
      iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
    });
    let sessionUrl: string | null = null;

    pc.addTransceiver('video', { direction: 'recvonly' });
    pc.ontrack = (event) => {
      // Some WHEP servers omit a=msid, leaving event.streams empty.
      // Fall back to wrapping the bare track so the video element always gets a stream.
      video.muted = true;
      video.srcObject = event.streams[0] ?? new MediaStream([event.track]);
      void video.play();

      // Tell the browser to render frames as soon as they arrive instead of
      // accumulating a playout buffer. This is the WebRTC equivalent of what
      // makes the MJPEG stream feel immediate — on localhost there's no network
      // jitter to smooth over, so the buffer only adds latency.
      const receiver = pc.getReceivers().find((r) => r.track === event.track);
      if (receiver && 'jitterBufferTarget' in receiver) {
        (receiver as RTCRtpReceiver & { jitterBufferTarget: number }).jitterBufferTarget = 0;
      }
    };

    // Notify the caller when the connection drops after a successful connect so
    // LivePage can set videoError and trigger the retry loop.
    pc.onconnectionstatechange = () => {
      const state = pc.connectionState;
      if (state === 'failed' || state === 'disconnected' || state === 'closed') {
        onDisconnect?.(`stream disconnected (${state})`);
      }
    };

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await this.waitForIceGathering(pc);

    const sdpOffer = pc.localDescription?.sdp;
    if (!sdpOffer) {
      throw new Error('Failed to generate SDP offer');
    }

    const response = await fetch(whepUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/sdp',
      },
      body: sdpOffer,
    });

    if (!response.ok) {
      pc.close();
      const err = new Error(`Failed to establish WHEP session (${response.status})`);
      (err as Error & { retryable: boolean }).retryable = response.status === 404 || response.status === 503;
      throw err;
    }

    const location = response.headers.get('location');
    if (location) {
      sessionUrl = new URL(location, whepUrl).toString();
    }

    const answerSdp = await response.text();
    await pc.setRemoteDescription({ type: 'answer', sdp: answerSdp });

    return async () => {
      // Clear handler before closing so the close event doesn't fire onDisconnect
      // and trigger a spurious retry after intentional cleanup.
      pc.onconnectionstatechange = null;
      pc.ontrack = null;
      pc.close();
      if (sessionUrl) {
        try {
          await fetch(sessionUrl, { method: 'DELETE' });
        } catch {
          // ignore cleanup errors for dev sessions
        }
      }
    };
  }

  private waitForIceGathering(pc: RTCPeerConnection, timeoutMs = 3000) {
    if (pc.iceGatheringState === 'complete') return Promise.resolve();

    return new Promise<void>((resolve) => {
      const timer = setTimeout(resolve, timeoutMs);
      const onStateChange = () => {
        if (pc.iceGatheringState === 'complete') {
          clearTimeout(timer);
          pc.removeEventListener('icegatheringstatechange', onStateChange);
          resolve();
        }
      };
      pc.addEventListener('icegatheringstatechange', onStateChange);
    });
  }
}

export const webRtcClient = new WebRTCClient();
