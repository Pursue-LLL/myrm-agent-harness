/**
 * Pixel-level screenshot comparison using Canvas API and YIQ color space.
 * 
 * @param {Object} args - Comparison arguments
 * @param {string} args.baselineUrl - URL of baseline image
 * @param {string} args.currentUrl - URL of current image
 * @param {number} args.tolerance - Color tolerance (0.0-1.0)
 * @param {boolean} args.includeAA - Enable anti-aliasing detection
 * @returns {Promise<Object>} Comparison result
 */
async (args) => {
  const doc = document;

  function loadImage(url) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error('Failed to load image: ' + url));
      img.src = url;
    });
  }

  function rgb2y(r, g, b) { 
    return r * 0.29889531 + g * 0.58662247 + b * 0.11448223; 
  }
  
  function rgb2i(r, g, b) { 
    return r * 0.59597799 - g * 0.27417610 - b * 0.32180189; 
  }
  
  function rgb2q(r, g, b) { 
    return r * 0.21147017 - g * 0.52261711 + b * 0.31114694; 
  }

  function colorDelta(r1, g1, b1, r2, g2, b2) {
    const y1 = rgb2y(r1, g1, b1), y2 = rgb2y(r2, g2, b2);
    const i1 = rgb2i(r1, g1, b1), i2 = rgb2i(r2, g2, b2);
    const q1 = rgb2q(r1, g1, b1), q2 = rgb2q(r2, g2, b2);
    const dy = y1 - y2, di = i1 - i2, dq = q1 - q2;
    return 0.5053 * dy * dy + 0.299 * di * di + 0.1957 * dq * dq;
  }

  function isAntialiased(data, x, y, w, h) {
    const idx = (y * w + x) * 4;
    const r = data[idx], g = data[idx + 1], b = data[idx + 2];
    let zeroes = 0, positives = 0, negatives = 0;
    let min = 0, max = 0;

    for (let dy = -1; dy <= 1; dy++) {
      for (let dx = -1; dx <= 1; dx++) {
        if (dx === 0 && dy === 0) continue;
        const ny = y + dy, nx = x + dx;
        if (nx < 0 || nx >= w || ny < 0 || ny >= h) continue;
        const nidx = (ny * w + nx) * 4;
        const delta = colorDelta(r, g, b, data[nidx], data[nidx + 1], data[nidx + 2]);
        if (delta === 0) { 
          zeroes++; 
          if (negatives > 1 || positives > 1) return true; 
        } else if (delta < 0) { 
          negatives++; 
          if (positives > 0) return true; 
        } else { 
          positives++; 
          if (negatives > 0) return true; 
        }
        min = Math.min(min, delta);
        max = Math.max(max, delta);
      }
    }
    if (max === 0) return false;
    return (max - min) < 0.02;
  }

  const [imgA, imgB] = await Promise.all([
    loadImage(args.baselineUrl),
    loadImage(args.currentUrl),
  ]);

  if (imgA.width !== imgB.width || imgA.height !== imgB.height) {
    const c = doc.createElement('canvas');
    c.width = 1; 
    c.height = 1;
    return {
      totalPixels: Math.max(imgA.width * imgA.height, imgB.width * imgB.height),
      differentPixels: Math.max(imgA.width * imgA.height, imgB.width * imgB.height),
      mismatchPercentage: 100,
      diffBase64: c.toDataURL('image/png').split(',')[1],
      dimensionMismatch: true,
    };
  }

  const w = imgA.width, h = imgA.height;

  const cA = doc.createElement('canvas');
  cA.width = w; 
  cA.height = h;
  const ctxA = cA.getContext('2d');
  ctxA.drawImage(imgA, 0, 0);
  const dataA = ctxA.getImageData(0, 0, w, h).data;

  const cB = doc.createElement('canvas');
  cB.width = w; 
  cB.height = h;
  const ctxB = cB.getContext('2d');
  ctxB.drawImage(imgB, 0, 0);
  const dataB = ctxB.getImageData(0, 0, w, h).data;

  const diffCanvas = doc.createElement('canvas');
  diffCanvas.width = w; 
  diffCanvas.height = h;
  const ctxDiff = diffCanvas.getContext('2d');
  const diffImg = ctxDiff.createImageData(w, h);
  const diffData = diffImg.data;

  const maxDelta = args.tolerance * args.tolerance * 35215.0;
  let differentPixels = 0;
  const totalPixels = w * h;

  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      const off = i * 4;
      const r1 = dataA[off], g1 = dataA[off+1], b1 = dataA[off+2];
      const r2 = dataB[off], g2 = dataB[off+1], b2 = dataB[off+2];
      const delta = colorDelta(r1, g1, b1, r2, g2, b2);

      if (delta > maxDelta) {
        if (args.includeAA && (isAntialiased(dataA, x, y, w, h) || isAntialiased(dataB, x, y, w, h))) {
          diffData[off] = 255;
          diffData[off+1] = 255;
          diffData[off+2] = 0;
          diffData[off+3] = 128;
        } else {
          differentPixels++;
          diffData[off] = 255;
          diffData[off+1] = 0;
          diffData[off+2] = 0;
          diffData[off+3] = 255;
        }
      } else {
        diffData[off]   = Math.round(dataA[off]   * 0.3);
        diffData[off+1] = Math.round(dataA[off+1] * 0.3);
        diffData[off+2] = Math.round(dataA[off+2] * 0.3);
        diffData[off+3] = 255;
      }
    }
  }

  ctxDiff.putImageData(diffImg, 0, 0);
  const diffBase64 = diffCanvas.toDataURL('image/png').split(',')[1];

  return {
    totalPixels,
    differentPixels,
    mismatchPercentage: Math.round((differentPixels / totalPixels) * 10000) / 100,
    diffBase64,
    dimensionMismatch: false,
  };
}
