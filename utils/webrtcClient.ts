// The frontend handles a single tiled composite stream; never per-camera streams.
export class WebRTCClient {
  async attachRealStream(video: HTMLVideoElement, whepUrl: string) {
    if (!whepUrl) {
      throw new Error('Missing WHEP URL');
    }

    const pc = new RTCPeerConnection();
    let sessionUrl: string | null = null;

    pc.addTransceiver('video', { direction: 'recvonly' });
    pc.ontrack = (event) => {
      video.srcObject = event.streams[0] ?? null;
      void video.play();
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
      throw new Error(`Failed to establish WHEP session (${response.status})`);
    }

    const location = response.headers.get('location');
    if (location) {
      sessionUrl = new URL(location, whepUrl).toString();
    }

    const answerSdp = await response.text();
    await pc.setRemoteDescription({ type: 'answer', sdp: answerSdp });

    return async () => {
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

  private waitForIceGathering(pc: RTCPeerConnection) {
    if (pc.iceGatheringState === 'complete') return Promise.resolve();

    return new Promise<void>((resolve) => {
      const onStateChange = () => {
        if (pc.iceGatheringState === 'complete') {
          pc.removeEventListener('icegatheringstatechange', onStateChange);
          resolve();
        }
      };
      pc.addEventListener('icegatheringstatechange', onStateChange);
    });
  }
}

export const webRtcClient = new WebRTCClient();
