// Classic worker: MediaPipe's WASM loader can use importScripts here.
let landmarker;
self.onmessage = async ({data}) => {
  try {
    if (data.kind === 'init') {
      const {FilesetResolver, FaceLandmarker} = await import('/camera-assets/vision_bundle.mjs');
      const files = await FilesetResolver.forVisionTasks('/camera-assets/wasm');
      landmarker = await FaceLandmarker.createFromOptions(files, {
        baseOptions: {modelAssetPath: '/camera-assets/face_landmarker.task', delegate: 'CPU'},
        runningMode: 'VIDEO', numFaces: 1, outputFaceBlendshapes: true,
      });
      self.postMessage({kind: 'ready'});
    } else if (data.kind === 'frame') {
      try {
        const result = landmarker.detectForVideo(data.bitmap, data.timestamp);
        const categories = result.faceBlendshapes?.[0]?.categories;
        const score = categories ? ['mouthSmileLeft', 'mouthSmileRight'].reduce((sum, name) =>
          sum + (categories.find(c => c.categoryName === name)?.score || 0), 0) / 2 : null;
        self.postMessage({kind: 'score', score});
      } finally { data.bitmap.close(); }
    }
  } catch (error) {
    self.postMessage({kind: 'error', message: 'Smile detector could not start. Check the camera model setup and reload.'});
  }
};
