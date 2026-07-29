const API = '/api/v1';

const api = {
    async request(method, path, body) {
        const opts = { method, headers: {} };
        const token = localStorage.getItem('token');
        if (token) opts.headers['Authorization'] = `Bearer ${token}`;
        if (body) {
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(body);
        }
        const res = await fetch(`${API}${path}`, opts);
        if (res.status === 401) { logout(); return null; }
        if (res.status === 204) return null;
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.message || 'Request failed');
        return data;
    },
    register: (e, p) => api.request('POST', '/auth/register', { email: e, password: p }),
    login: (e, p) => {
        const f = new URLSearchParams(); f.set('username', e); f.set('password', p);
        return fetch(`${API}/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: f }).then(r => { if (!r.ok) throw new Error('Login failed'); return r.json(); });
    },
    blueprint: () => api.request('POST', '/blueprint/generate'),
    blueprintToday: () => api.request('GET', '/blueprint/today'),
    search: (q) => api.request('GET', `/search?q=${encodeURIComponent(q)}&type=all`),
    albumTracks: (id, artist) => api.request('GET', `/search/album/${id}/tracks${artist ? '?artist=' + encodeURIComponent(artist) : ''}`),
    playTrack: (t) => api.request('POST', '/playback/complete', {
        track_id: t.track_id, title: t.title || t.track || t.track_name,
        artist: t.artist || t.artist_name, album: t.album || t.collection_name,
        artwork_url: t.artwork_url || t.art_url,
        completed: true, skipped: false, play_duration_sec: 30,
        track_duration_sec: t.duration_ms || 180000
    }),
    playlists: () => api.request('GET', '/playlists'),
    createPlaylist: (n, d) => api.request('POST', '/playlists', { name: n, description: d }),
    deletePlaylist: (id) => api.request('DELETE', `/playlists/${id}`),
    playlistTracks: (id) => api.request('GET', `/playlists/${id}`),
    stats: () => api.request('GET', '/profile/stats'),
    topArtists: () => api.request('GET', '/profile/top-artists'),
    genres: () => api.request('GET', '/profile/genres'),
};

function logout() {
    localStorage.removeItem('token');
    showAuth();
}

function showAuth() {
    document.getElementById('nav').classList.add('hidden');
    document.getElementById('auth-page').classList.remove('hidden');
    document.querySelectorAll('.page').forEach(p => p.classList.add('hidden'));
}

function showApp() {
    document.getElementById('nav').classList.remove('hidden');
    document.getElementById('auth-page').classList.add('hidden');
    switchTab('dashboard');
}

function switchTab(tab) {
    document.querySelectorAll('.page').forEach(p => p.classList.add('hidden'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    const page = document.getElementById(`${tab}-page`);
    if (page) page.classList.remove('hidden');
    const btn = document.querySelector(`[data-tab="${tab}"]`);
    if (btn) btn.classList.add('active');
    if (tab === 'dashboard') loadDashboard();
    if (tab === 'playlists') loadPlaylists();
    if (tab === 'profile') loadProfile();
}

function showError(el, msg) { el.textContent = msg; el.classList.remove('hidden'); }
function hideError(el) { el.classList.add('hidden'); }
function $(id) { return document.getElementById(id); }

// ===== YOUTUBE PLAYER (Spotify-style, audio only) =====
const player = { yt: null, track: null, queue: [], queueIndex: -1, played: false, progressTimer: null };

function initYTPlayer() {
    if (player.yt) return;
    player.yt = new YT.Player('youtube-player', {
        height: '240', width: '320',
        playerVars: {
            autoplay: 0, controls: 0, disablekb: 1,
            fs: 0, modestbranding: 1, rel: 0, iv_load_policy: 3
        },
        events: {
            onReady: () => {},
            onStateChange: onPlayerStateChange,
            onError: onPlayerError
        }
    });
}

function onPlayerStateChange(e) {
    if (e.data === YT.PlayerState.PLAYING) {
        player.played = true;
        $('player-play-btn').textContent = '⏸';
        if (!player.progressTimer) startProgressTimer();
    } else if (e.data === YT.PlayerState.PAUSED) {
        $('player-play-btn').textContent = '▶';
    } else if (e.data === YT.PlayerState.ENDED) {
        $('player-play-btn').textContent = '▶';
        $('player-progress').value = 0;
        $('player-current').textContent = '0:00';
        stopProgressTimer();
        if (player.track && player.played) {
            api.playTrack(player.track).catch(() => {});
        }
    } else if (e.data === YT.PlayerState.CUED) {
        $('player-play-btn').textContent = '▶';
    }
}

function onPlayerError(e) {
    console.warn('YouTube error:', e.data);
}

function startProgressTimer() {
    stopProgressTimer();
    player.progressTimer = setInterval(() => {
        if (!player.yt || !player.yt.getCurrentTime) return;
        const ct = player.yt.getCurrentTime();
        const dur = player.yt.getDuration();
        if (dur) {
            $('player-progress').value = (ct / dur) * 100;
            $('player-current').textContent = formatTime(ct);
            $('player-duration').textContent = formatTime(dur);
        }
    }, 500);
}

function stopProgressTimer() {
    if (player.progressTimer) { clearInterval(player.progressTimer); player.progressTimer = null; }
}

function formatTime(s) {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, '0')}`;
}

function trackCardHtml(t, index, listId) {
    const title = t.title || t.track || t.track_name || 'Unknown';
    const artist = t.artist || t.artist_name || 'Unknown';
    const album = t.album || t.collection_name || '';
    const art = t.artwork_url || t.art_url || '';
    return `<div class="track-card clickable" data-index="${index}" data-list="${listId}">
        ${art ? `<div class="track-art-wrap"><img src="${art}" alt=""><div class="play-overlay">&#9654;</div></div>` : '<div class="track-art-wrap no-art"><div class="play-overlay">&#9654;</div></div>'}
        <div class="track-info">
            <div class="track-title">${title}</div>
            <div class="track-artist">${artist}</div>
            ${album ? `<div class="track-album">${album}</div>` : ''}
        </div>
    </div>`;
}

function showPlayer(track) {
    $('player-bar').classList.remove('hidden');
    $('player-art').src = track.artwork_url || track.art_url || '';
    $('player-title').textContent = track.title || track.track || track.track_name || '';
    $('player-artist').textContent = track.artist || track.artist_name || '';
    $('player-play-btn').textContent = '▶';
    $('player-progress').value = 0;
    $('player-current').textContent = '0:00';
    $('player-duration').textContent = '0:00';
    player.track = track;
    player.played = false;

    if (typeof YT === 'undefined' || !YT.Player) { return; }
    initYTPlayer();

    const videoId = track.video_id || track.youtube_video_id;
    if (videoId) {
        if (player.yt && player.yt.loadVideoById) {
            player.yt.loadVideoById(videoId);
        }
    } else {
        const name = track.title || track.track || track.track_name || '';
        const artist = track.artist || track.artist_name || '';
        const album = track.album || track.collection_name || '';
        const durMs = track.duration_ms || 0;
        fetch(`${API}/search/youtube/versions?artist=${encodeURIComponent(artist)}&title=${encodeURIComponent(name)}&album=${encodeURIComponent(album)}&duration_ms=${durMs}`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        }).then(r => r.json()).then(data => {
            const best = data.best_version;
            if (best && best.video_id && player.yt && player.yt.loadVideoById) {
                player.yt.loadVideoById(best.video_id);
            }
        }).catch(() => {});
    }
}

async function playTrackInYT(track, el) {
    if (el) el.classList.add('played');
    showPlayer(track);
}

$('player-play-btn').addEventListener('click', () => {
    if (!player.yt || !player.yt.getPlayerState) return;
    const state = player.yt.getPlayerState();
    if (state === YT.PlayerState.PLAYING) {
        player.yt.pauseVideo();
    } else {
        player.yt.playVideo();
    }
});

$('player-progress').addEventListener('input', function () {
    if (player.yt && player.yt.getDuration) {
        const dur = player.yt.getDuration();
        if (dur) player.yt.seekTo((this.value / 100) * dur, true);
    }
});

$('player-prev').addEventListener('click', () => {});
$('player-next').addEventListener('click', () => {});

$('player-close').addEventListener('click', () => {
    if (player.yt && player.yt.stopVideo) player.yt.stopVideo();
    stopProgressTimer();
    $('player-bar').classList.add('hidden');
    player.track = null;
});

// Track click delegation
document.addEventListener('click', e => {
    const card = e.target.closest('.track-card.clickable');
    if (!card) return;
    const listId = card.dataset.list;
    const index = parseInt(card.dataset.index);
    let tracks = [];
    if (listId === 'search') tracks = window._searchTracks || [];
    else if (listId === 'blueprint') tracks = window._blueprintTracks || [];
    else if (listId === 'playlist') tracks = window._playlistTracks || [];
    else if (listId === 'album') tracks = window._albumTracks || [];
    const t = tracks[index];
    if (t) playTrackInYT(t, card);
});

// ===== AUTH =====
let isLogin = true;
$('auth-toggle-link').addEventListener('click', e => {
    e.preventDefault();
    isLogin = !isLogin;
    $('auth-submit').textContent = isLogin ? 'Login' : 'Register';
    $('auth-toggle-text').textContent = isLogin ? "Don't have an account?" : 'Already have an account?';
    $('auth-toggle-link').textContent = isLogin ? 'Register' : 'Login';
    hideError($('auth-error'));
});

$('auth-form').addEventListener('submit', async e => {
    e.preventDefault();
    const email = $('auth-email').value;
    const password = $('auth-password').value;
    hideError($('auth-error'));
    try {
        let data;
        if (isLogin) {
            data = await api.login(email, password);
        } else {
            data = await api.register(email, password);
        }
        localStorage.setItem('token', data.access_token);
        showApp();
        loadDashboard();
    } catch (err) {
        showError($('auth-error'), err.message);
    }
});

// ===== NAV =====
document.querySelectorAll('.tab-btn[data-tab]').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});
$('logout-btn').addEventListener('click', logout);

// ===== DASHBOARD =====
async function loadDashboard() {
    try {
        const [bp, stats, artists] = await Promise.all([
            api.blueprintToday().catch(() => null),
            api.stats().catch(() => null),
            api.topArtists().catch(() => null),
        ]);

        if (bp) {
            const s = bp.strategy || {};
            $('blueprint-strategy').innerHTML = `
                <h3>Mood Arc</h3>
                <div class="mood-tags">${(s.mood_arc || []).map(m => `<span class="mood-tag">${m}</span>`).join('')}</div>
                <h3 style="margin-top:12px;">Focus Genres</h3>
                <div class="mood-tags">${(s.focus_genres || []).map(g => `<span class="genre-tag">${g}</span>`).join('')}</div>
                <p style="margin-top:8px;font-size:0.85rem;color:var(--text-dim);">Discovery: ${Math.round((s.discovery_ratio||0)*100)}% &middot; Repeat: ${Math.round((s.repeat_comfort_ratio||0)*100)}%</p>
            `;

            const tracks = bp.seed_tracks || [];
            window._blueprintTracks = tracks;
            $('blueprint-tracks').innerHTML = `
                <h3>Seed Tracks (${tracks.length})</h3>
                <div class="results-grid">${tracks.map((t, i) =>
                    trackCardHtml(t, i, 'blueprint')
                ).join('')}</div>
            `;
        } else {
            $('blueprint-strategy').innerHTML = '<p>No blueprint yet. Click Refresh to generate one.</p>';
            $('blueprint-tracks').innerHTML = '';
        }

        if (stats) {
            $('blueprint-stats').innerHTML = `
                <h3>Quick Stats</h3>
                <div class="stat-row"><span class="stat-label">Total Plays</span><span class="stat-value">${stats.total_plays}</span></div>
                <div class="stat-row"><span class="stat-label">Unique Artists</span><span class="stat-value">${stats.unique_artists}</span></div>
                <div class="stat-row"><span class="stat-label">Completion Rate</span><span class="stat-value">${stats.completion_rate}%</span></div>
                <div class="stat-row"><span class="stat-label">Streak</span><span class="stat-value">${stats.listening_streak} days</span></div>
            `;
        }
    } catch (e) {
        $('blueprint-strategy').innerHTML = `<p class="error">Failed to load dashboard</p>`;
    }
}

$('refresh-blueprint').addEventListener('click', async () => {
    $('refresh-blueprint').textContent = 'Generating...';
    $('refresh-blueprint').disabled = true;
    try {
        await api.blueprint();
        await loadDashboard();
    } catch (e) {
        alert('Blueprint generation failed: ' + e.message);
    }
    $('refresh-blueprint').textContent = 'Refresh Blueprint';
    $('refresh-blueprint').disabled = false;
});

// ===== SEARCH =====
$('search-form').addEventListener('submit', async e => {
    e.preventDefault();
    const q = $('search-query').value;
    $('album-detail').classList.add('hidden');
    $('search-results').classList.remove('hidden');
    $('search-results').innerHTML = '<div class="spinner"></div>';
    try {
        const data = await api.search(q);
        const tracks = data.tracks || [];
        const albums = data.albums || [];
        const artists = data.artists || [];

        window._searchTracks = tracks;
        window._searchAlbums = albums;
        window._searchArtists = artists;

        let html = '';

        if (albums.length) {
            html += `<h3 style="margin:16px 0 8px;font-size:1.1rem;color:var(--accent);">Albums</h3>
            <div class="results-grid">${albums.map((a, i) => `
                <div class="album-card clickable" data-album-index="${i}" data-album-list="search">
                    ${a.artwork_url ? `<img src="${a.artwork_url}" alt="" class="album-art">` : '<div class="album-art no-art">📀</div>'}
                    <div class="album-info">
                        <div class="album-title">${a.title}</div>
                        <div class="album-artist">${a.artist}</div>
                        <div class="album-meta">${a.track_count || '?'} tracks</div>
                    </div>
                </div>
            `).join('')}</div>`;
        }

        if (artists.length) {
            html += `<h3 style="margin:16px 0 8px;font-size:1.1rem;color:var(--accent);">Artists</h3>
            <div class="results-grid">${artists.map((a, i) => `
                <div class="artist-card">
                    ${a.artwork_url ? `<img src="${a.artwork_url}" alt="" class="artist-art">` : '<div class="artist-art no-art">🎤</div>'}
                    <div class="artist-name">${a.name}</div>
                    <div class="artist-genre">${a.genre || ''}</div>
                </div>
            `).join('')}</div>`;
        }

        if (tracks.length) {
            html += `<h3 style="margin:16px 0 8px;font-size:1.1rem;color:var(--accent);">Tracks</h3>
            <div class="results-grid">${tracks.map((t, i) =>
                trackCardHtml(t, i, 'search')
            ).join('')}</div>`;
        }

        $('search-results').innerHTML = html || '<p>No results found</p>';
    } catch (e) {
        $('search-results').innerHTML = `<p class="error">Search failed: ${e.message}</p>`;
    }
});

// Album click → fetch tracks with YouTube versions
document.addEventListener('click', e => {
    const card = e.target.closest('.album-card.clickable');
    if (!card) return;
    const idx = parseInt(card.dataset.albumIndex);
    const list = card.dataset.albumList;
    let albums = [];
    if (list === 'search') albums = window._searchAlbums || [];
    const album = albums[idx];
    if (!album) return;
    loadAlbumDetail(album);
});

async function loadAlbumDetail(album) {
    $('search-results').classList.add('hidden');
    $('album-detail').classList.remove('hidden');
    $('album-detail').innerHTML = '<div class="spinner"></div>';
    try {
        const data = await api.albumTracks(album.album_id, album.artist);
        const a = data.album;
        const tracks = data.tracks || [];

        window._albumTracks = tracks;

        $('album-detail').innerHTML = `
            <button id="back-to-results" class="btn" style="margin-bottom:16px;">← Back to results</button>
            <div class="album-header">
                <div class="album-header-art">
                    ${a.artwork_url ? `<img src="${a.artwork_url}" alt="">` : '<div class="no-art big">📀</div>'}
                </div>
                <div class="album-header-info">
                    <div class="album-header-title">${a.title}</div>
                    <div class="album-header-artist">${a.artist}</div>
                    <div class="album-header-meta">${tracks.length} tracks · ${a.release_date || ''} · ${a.genre || ''}</div>
                </div>
            </div>
            <div class="album-tracks">
                ${tracks.length ? tracks.map((t, i) => `
                    <div class="track-card clickable album-track" data-index="${i}" data-list="album">
                        <div class="track-num">${i + 1}</div>
                        <div class="track-info">
                            <div class="track-title">${t.title}</div>
                            <div class="track-artist">${t.artist || a.artist}</div>
                        </div>
                        <div class="track-duration">${formatTime(t.duration_ms / 1000)}</div>
                    </div>
                `).join('') : '<p>No tracks found</p>'}
            </div>
        `;

        document.getElementById('back-to-results').addEventListener('click', () => {
            $('album-detail').classList.add('hidden');
            $('search-results').classList.remove('hidden');
        });

    } catch (e) {
        $('album-detail').innerHTML = `<p class="error">Failed to load album: ${e.message}</p>
            <button id="back-to-results" class="btn" style="margin-top:16px;">← Back to results</button>`;
        setTimeout(() => {
            const btn = document.getElementById('back-to-results');
            if (btn) btn.addEventListener('click', () => {
                $('album-detail').classList.add('hidden');
                $('search-results').classList.remove('hidden');
            });
        }, 100);
    }
}

// ===== PLAYLISTS =====
let currentPlaylistId = null;

async function loadPlaylists() {
    $('playlist-detail').classList.add('hidden');
    $('playlists-list').classList.remove('hidden');
    try {
        const data = await api.playlists();
        const pls = data.playlists || data || [];
        $('playlists-list').innerHTML = pls.length ? pls.map(p => `
            <div class="playlist-item" data-id="${p.id}">
                <div>
                    <div class="playlist-name">${p.name}</div>
                    <div class="playlist-meta">${p.track_count || 0} tracks${p.description ? ' &middot; ' + p.description : ''}</div>
                </div>
                <button class="playlist-delete" data-del="${p.id}">Delete</button>
            </div>
        `).join('') : '<p>No playlists yet</p>';

        document.querySelectorAll('.playlist-item').forEach(el => {
            el.addEventListener('click', e => {
                if (e.target.classList.contains('playlist-delete')) return;
                showPlaylistDetail(el.dataset.id);
            });
        });
        document.querySelectorAll('.playlist-delete').forEach(btn => {
            btn.addEventListener('click', async e => {
                e.stopPropagation();
                if (confirm('Delete this playlist?')) {
                    await api.deletePlaylist(btn.dataset.del);
                    loadPlaylists();
                }
            });
        });
    } catch (e) {
        $('playlists-list').innerHTML = `<p class="error">Failed to load playlists</p>`;
    }
}

async function showPlaylistDetail(id) {
    currentPlaylistId = id;
    $('playlists-list').classList.add('hidden');
    $('playlist-detail').classList.remove('hidden');
    try {
        const data = await api.playlistTracks(id);
        const pl = data.playlist || data;
        $('playlist-detail-title').textContent = pl.name || 'Playlist';
        const tracks = pl.tracks || [];
        window._playlistTracks = tracks;
        $('playlist-tracks').innerHTML = tracks.length ? tracks.map((t, i) =>
            trackCardHtml(t, i, 'playlist')
        ).join('') : '<p>Empty playlist</p>';
    } catch (e) {
        $('playlist-tracks').innerHTML = `<p class="error">Failed to load playlist</p>`;
    }
}

$('back-to-playlists').addEventListener('click', loadPlaylists);
$('new-playlist-btn').addEventListener('click', () => $('new-playlist-form').classList.remove('hidden'));
$('cancel-playlist').addEventListener('click', () => $('new-playlist-form').classList.add('hidden'));
$('create-playlist').addEventListener('click', async () => {
    const name = $('playlist-name').value;
    if (!name) return;
    const desc = $('playlist-desc').value;
    await api.createPlaylist(name, desc || undefined);
    $('playlist-name').value = '';
    $('playlist-desc').value = '';
    $('new-playlist-form').classList.add('hidden');
    loadPlaylists();
});

// ===== PROFILE =====
async function loadProfile() {
    try {
        const [stats, artists, genres] = await Promise.all([
            api.stats().catch(() => null),
            api.topArtists().catch(() => null),
            api.genres().catch(() => null),
        ]);

        if (stats) {
            $('profile-stats').innerHTML = `
                <h3>Statistics</h3>
                <div class="stat-row"><span class="stat-label">Total Plays</span><span class="stat-value">${stats.total_plays}</span></div>
                <div class="stat-row"><span class="stat-label">Unique Artists</span><span class="stat-value">${stats.unique_artists}</span></div>
                <div class="stat-row"><span class="stat-label">Completion Rate</span><span class="stat-value">${stats.completion_rate}%</span></div>
                <div class="stat-row"><span class="stat-label">Skip Rate</span><span class="stat-value">${stats.skip_rate}%</span></div>
                <div class="stat-row"><span class="stat-label">Listening Streak</span><span class="stat-value">${stats.listening_streak} days</span></div>
            `;
        }

        if (artists) {
            const list = artists.artists || artists || [];
            $('profile-top-artists').innerHTML = `
                <h3>Top Artists</h3>
                ${list.length ? list.map(a => `
                    <div class="stat-row">
                        <span class="stat-label">${a.artist_name || a.artist || 'Unknown'}</span>
                        <span class="stat-value">${Math.round((a.affinity_score || 0) * 100)}%</span>
                    </div>
                `).join('') : '<p>No data yet</p>'}
            `;
        }

        if (genres) {
            const list = genres.genres || genres || [];
            $('profile-genres').innerHTML = `
                <h3>Genre Breakdown</h3>
                ${list.length ? list.map(g => `
                    <div class="stat-row">
                        <span class="stat-label">${g.genre || g.name || 'Unknown'}</span>
                        <span class="stat-value">${Math.round(g.percentage || 0)}%</span>
                    </div>
                `).join('') : '<p>No data yet</p>'}
            `;
        }
    } catch (e) {
        $('profile-stats').innerHTML = `<p class="error">Failed to load profile</p>`;
    }
}

// ===== INIT =====
if (localStorage.getItem('token')) {
    showApp();
} else {
    showAuth();
}
