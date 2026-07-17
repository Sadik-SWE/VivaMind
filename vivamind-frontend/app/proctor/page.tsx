'use client';

// VivaMind — Proctoring module (A2)
// Face-presence + multi-person detection, on-device with MediaPipe.
// No video leaves the browser. Place at:  app/proctor/page.tsx
// MediaPipe is imported dynamically (client-only) so it never runs during SSR.

import { useEffect, useRef, useState } from 'react';
import type { FaceDetector } from '@mediapipe/tasks-vision';

export default function ProctorPage() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const violatedRef = useRef(false);
  const [ready, setReady] = useState(false);
  const [faces, setFaces] = useState(1);
  const [violations, setViolations] = useState(0);
  const [status, setStatus] = useState('Loading model…');

  useEffect(() => {
    let detector: FaceDetector | null = null;
    let stream: MediaStream | null = null;
    let raf = 0;
    let running = true;
    let lastTime = -1;

    const MODEL =
      'https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite';

    async function makeDetector(): Promise<FaceDetector> {
      // Client-only import — keeps this browser library out of server rendering.
      const { FaceDetector, FilesetResolver } = await import('@mediapipe/tasks-vision');
      const vision = await FilesetResolver.forVisionTasks(
        'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision/wasm'
      );
      try {
        return await FaceDetector.createFromOptions(vision, {
          baseOptions: { modelAssetPath: MODEL, delegate: 'GPU' },
          runningMode: 'VIDEO',
        });
      } catch {
        return await FaceDetector.createFromOptions(vision, {
          baseOptions: { modelAssetPath: MODEL, delegate: 'CPU' },
          runningMode: 'VIDEO',
        });
      }
    }

    async function init() {
      detector = await makeDetector();
      stream = await navigator.mediaDevices.getUserMedia({ video: true });
      const v = videoRef.current;
      if (v) {
        v.srcObject = stream;
        await v.play();
      }
      setReady(true);
      setStatus('Monitoring');
      loop();
    }

    function loop() {
      if (!running) return;
      const v = videoRef.current;
      if (detector && v && v.readyState >= 2 && v.currentTime !== lastTime) {
        lastTime = v.currentTime;
        const result = detector.detectForVideo(v, performance.now());
        const n = result.detections.length;
        setFaces(n);

        const bad = n !== 1; // 0 = no face, >1 = extra person
        if (bad && !violatedRef.current) {
          violatedRef.current = true;
          setViolations((c) => c + 1);
        } else if (!bad) {
          violatedRef.current = false;
        }
      }
      raf = requestAnimationFrame(loop);
    }

    init().catch((e) => setStatus('Error: ' + (e?.message ?? String(e))));

    return () => {
      running = false;
      cancelAnimationFrame(raf);
      stream?.getTracks().forEach((t) => t.stop());
      detector?.close?.();
    };
  }, []);

  const verdict = !ready
    ? { text: status, color: '#64748B' }
    : faces === 1
    ? { text: '✅ 1 face — OK', color: '#0E9C8A' }
    : faces === 0
    ? { text: '⚠️ No face detected', color: '#F5A623' }
    : { text: `🚨 ${faces} faces — multiple people!`, color: '#E5484D' };

  return (
    <main
      style={{
        minHeight: '100vh',
        background: '#0F1E3D',
        color: '#fff',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 18,
        fontFamily: 'system-ui, sans-serif',
        padding: 24,
      }}
    >
      <h1 style={{ fontSize: 26, fontWeight: 700, margin: 0 }}>VivaMind — Proctoring</h1>
      <p style={{ color: '#AEC2DF', margin: 0, textAlign: 'center', maxWidth: 520 }}>
        Face-presence &amp; multi-person monitoring. Runs on-device — your video never
        leaves the browser.
      </p>

      <video
        ref={videoRef}
        muted
        playsInline
        style={{
          width: 480,
          maxWidth: '90vw',
          borderRadius: 12,
          transform: 'scaleX(-1)',
          border: `3px solid ${verdict.color}`,
        }}
      />

      <div
        style={{
          padding: '10px 20px',
          borderRadius: 999,
          background: verdict.color,
          fontWeight: 700,
          fontSize: 18,
        }}
      >
        {verdict.text}
      </div>

      <div style={{ color: '#AEC2DF', fontSize: 14 }}>
        Integrity flags this session: <b style={{ color: '#fff' }}>{violations}</b>
      </div>
    </main>
  );
}