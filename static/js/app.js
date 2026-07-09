/* ============================================================
   Video Downloader — Frontend logic
   ============================================================ */

const urlInput      = document.getElementById('url-input');
const fetchBtn      = document.getElementById('fetch-btn');
const infoSection   = document.getElementById('info-section');
const inputSection  = document.getElementById('input-section');
const progressSec   = document.getElementById('progress-section');
const doneSec       = document.getElementById('done-section');
const errorSec      = document.getElementById('error-section');

const thumbnail     = document.getElementById('thumbnail');
const videoTitle    = document.getElementById('video-title');
const videoUploader = document.getElementById('video-uploader');
const videoDuration = document.getElementById('video-duration');
const videoViews    = document.getElementById('video-views');
const qualitySelect = document.getElementById('quality-select');
const downloadBtn   = document.getElementById('download-btn');

const progressFill  = document.getElementById('progress-fill');
const progressPct   = document.getElementById('progress-pct');
const progressLabel = document.getElementById('progress-label');

const fileLink      = document.getElementById('file-link');
const resetBtn      = document.getElementById('reset-btn');
const errorMsg      = document.getElementById('error-msg');
const errorResetBtn = document.getElementById('error-reset-btn');

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function show(...sections) {
  [infoSection, progressSec, doneSec, errorSec].forEach(s => s.classList.add('hidden'));
  sections.forEach(s => s.classList.remove('hidden'));
}

function formatDuration(secs) {
  if (!secs) return '';
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  return [h, m, s].filter((v, i) => v > 0 || i > 0).map((v, i, a) =>
    i === 0 ? v : String(v).padStart(2, '0')
  ).join(':');
}

function formatViews(n) {
  if (!n) return '';
  return `${n.toLocaleString()} views`;
}

// ---------------------------------------------------------------------------
// Fetch info
// ---------------------------------------------------------------------------

fetchBtn.addEventListener('click', async () => {
  const url = urlInput.value.trim();
  if (!url) return;

  fetchBtn.disabled = true;
  fetchBtn.textContent = '⏳ Loading…';

  try {
    const res = await fetch('/api/info', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Error fetching info');

    thumbnail.src      = data.thumbnail || '';
    videoTitle.textContent    = data.title || 'Unknown title';
    videoUploader.textContent = data.uploader ? `👤 ${data.uploader}` : '';
    videoDuration.textContent = data.duration ? `⏱ ${formatDuration(data.duration)}` : '';
    videoViews.textContent    = formatViews(data.view_count);

    qualitySelect.innerHTML = '';
    (data.available_qualities || ['best']).forEach(q => {
      const opt = document.createElement('option');
      opt.value = q;
      opt.textContent = q === 'audio_only' ? '🎵 Audio only (MP3)' : q === 'best' ? '⭐ Best quality' : `📺 ${q}`;
      if (q === '1080p') opt.selected = true;
      qualitySelect.appendChild(opt);
    });

    show(infoSection);
  } catch (e) {
    show(errorSec);
    errorMsg.textContent = e.message;
  } finally {
    fetchBtn.disabled = false;
    fetchBtn.textContent = '🔍 Fetch Info';
  }
});

// ---------------------------------------------------------------------------
// Download
// ---------------------------------------------------------------------------

downloadBtn.addEventListener('click', async () => {
  const url     = urlInput.value.trim();
  const quality = qualitySelect.value;
  if (!url) return;

  downloadBtn.disabled = true;
  show(progressSec);
  progressFill.style.width = '0%';
  progressPct.textContent  = '0%';
  progressLabel.textContent = 'Starting download…';

  try {
    const res = await fetch('/api/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, quality }),
    });
    const { job_id } = await res.json();
    if (!res.ok) throw new Error('Failed to start download');
    pollJob(job_id);
  } catch (e) {
    show(errorSec);
    errorMsg.textContent = e.message;
    downloadBtn.disabled = false;
  }
});

// ---------------------------------------------------------------------------
// Poll job
// ---------------------------------------------------------------------------

async function pollJob(jobId) {
  const INTERVAL = 1000; // ms

  const tick = async () => {
    try {
      const res  = await fetch(`/api/jobs/${jobId}`);
      const data = await res.json();

      const pct = Math.round(data.progress || 0);
      progressFill.style.width = `${pct}%`;
      progressPct.textContent  = `${pct}%`;

      if (data.status === 'downloading') {
        progressLabel.textContent = '⬇ Downloading…';
      } else if (data.status === 'processing') {
        progressLabel.textContent = '⚙️ Processing / merging…';
      } else if (data.status === 'done') {
        fileLink.href = `/api/jobs/${jobId}/file`;
        show(doneSec);
        downloadBtn.disabled = false;
        return; // stop polling
      } else if (data.status === 'error') {
        throw new Error(data.error || 'Download failed');
      }

      setTimeout(tick, INTERVAL);
    } catch (e) {
      show(errorSec);
      errorMsg.textContent = e.message;
      downloadBtn.disabled = false;
    }
  };

  setTimeout(tick, INTERVAL);
}

// ---------------------------------------------------------------------------
// Reset
// ---------------------------------------------------------------------------

[resetBtn, errorResetBtn].forEach(btn => btn.addEventListener('click', () => {
  urlInput.value = '';
  show();
  infoSection.classList.add('hidden');
  inputSection.classList.remove('hidden');
  downloadBtn.disabled = false;
}));

// Allow Enter key in URL input
urlInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') fetchBtn.click();
});
