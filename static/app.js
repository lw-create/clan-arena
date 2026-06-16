const API = '/api';
let token = localStorage.getItem('token') || '';
let currentUser = null;
let myClans = [];
let activeClanId = null; // 当前选中的部落ID
let _confirmResolve = null; // 自定义确认弹窗回调

// 自定义确认弹窗（替代浏览器原生confirm）
function customConfirm(message, okText = '确定', cancelText = '取消') {
    return new Promise(resolve => {
        _confirmResolve = resolve;
        document.getElementById('confirm-message').textContent = message;
        document.getElementById('confirm-ok').textContent = okText;
        document.getElementById('confirm-cancel').textContent = cancelText;
        document.getElementById('confirm-modal').classList.add('active');
        document.getElementById('confirm-ok').onclick = () => {
            // 点击确认按钮：先标记已处理，再关闭弹窗并resolve(true)
            _confirmResolve = null;
            document.getElementById('confirm-modal').classList.remove('active');
            resolve(true);
        };
    });
}

function closeConfirmModal() {
    document.getElementById('confirm-modal').classList.remove('active');
    if (_confirmResolve) { _confirmResolve(false); _confirmResolve = null; }
}

function showPage(id) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById(id).classList.add('active');
}

function formatDate(d) {
    if (!d) return '-';
    return new Date(d).toLocaleString('zh-CN', { month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit' });
}

// ========== 登录 ==========

// 所有DOM操作必须在DOMContentLoaded后执行
document.addEventListener('DOMContentLoaded', () => {
    const savedUsername = localStorage.getItem('remember_username') || '';
    const savedPassword = localStorage.getItem('remember_password') || '';

    if (savedUsername) {
        document.getElementById('login-username').value = savedUsername;
        document.getElementById('login-password').value = savedPassword;
        document.getElementById('remember-me').checked = true;
    }

    document.getElementById('login-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        try {
            const username = document.getElementById('login-username').value.trim();
            const password = document.getElementById('login-password').value.trim();
            const remember = document.getElementById('remember-me').checked;

            const data = await api('POST', '/login', { username, password });
            token = data.token;
            localStorage.setItem('token', token);
            currentUser = data.user;

            if (remember) {
                localStorage.setItem('remember_username', username);
                localStorage.setItem('remember_password', password);
            } else {
                localStorage.removeItem('remember_username');
                localStorage.removeItem('remember_password');
            }

            loadDashboard(data.user);
        } catch (err) {
            alert(err.message || '登录失败，请检查用户名和密码');
        }
    });
});

async function loadDashboard(user) {
    if (!user) {
        try { user = await api('GET', '/me'); currentUser = user; }
        catch { logout(); return; }
    }
    if (user.role === 'monitor') {
        document.getElementById('monitor-username').textContent = user.username;
        showPage('monitor-page');
        loadMonitorDashboard();
    } else if (user.role === 'admin') {
        document.getElementById('admin-username').textContent = user.username;
        showPage('admin-page');
        loadAdminData();
    } else {
        document.getElementById('nav-username').textContent = user.username;
        showPage('player-page');
        loadPlayerData();
    }
}

function logout() { token = ''; currentUser = null; myClans = []; activeClanId = null; localStorage.removeItem('token'); showPage('login-page'); }

// ========== 玩家面板 ==========
async function loadPlayerData() {
    const data = await api('GET', '/me');
    currentUser = data;
    myClans = data.clans || [];

    // 保持 activeClanId：如果之前选中的部落还在就保持，否则选第一个
    if (myClans.length > 0) {
        if (!activeClanId || !myClans.find(c => c.id === activeClanId)) {
            activeClanId = myClans[0].id;
        }
    } else {
        activeClanId = null;
    }

    document.getElementById('must-change-pwd').style.display = data.must_change_pwd ? '' : 'none';

    renderRoundStatus(data.current_round, data.my_registration);
    renderRoundTime(data.current_round);
    updateConfigHint(data.current_round);

    // 匹配成功提示：隐藏或显示登记区域，并展示胜负大横幅
    const matchSuccessCard = document.getElementById('match-success-card');
    const matchFailedCard = document.getElementById('match-failed-card');
    const matchDone = document.getElementById('match-done');
    const resultBanner = document.getElementById('match-result-banner');
    const regBanner = document.getElementById('registration-status-banner');
    if (data.has_active_match && data.active_match_info) {
        matchSuccessCard.style.display = 'none';
        matchFailedCard.style.display = 'none';
        matchDone.style.display = 'none';
        resultBanner.style.display = '';
        // 根据 result 显示大横幅
        const result = data.active_match_info.result;
        if (result === 'win') {
            resultBanner.className = 'match-result-banner win';
            resultBanner.innerHTML = `
                <div class="banner-big-text">✌ 胜利！</div>
                <div class="banner-detail">
                    <div class="banner-vs">${escapeHTML(data.active_match_info.my_clan_name)} <span class="vs-tag">VS</span> ${escapeHTML(data.active_match_info.opponent_name)}</div>
                    <div class="banner-score">恭喜，积分 +1</div>
                </div>`;
        } else if (result === 'lose') {
            resultBanner.className = 'match-result-banner lose';
            resultBanner.innerHTML = `
                <div class="banner-big-text">✗ 失败</div>
                <div class="banner-detail">
                    <div class="banner-vs">${escapeHTML(data.active_match_info.my_clan_name)} <span class="vs-tag">VS</span> ${escapeHTML(data.active_match_info.opponent_name)}</div>
                    <div class="banner-score">积分 -1，再接再厉！</div>
                </div>`;
            resultBanner.style.display = '';
        } else if (result === 'pending') {
            // 匹配到其他联盟 → 待定
            resultBanner.className = 'match-result-banner pending';
            resultBanner.innerHTML = `<div class="banner-big-text">⏳ 待定</div><div class="banner-detail">${escapeHTML(data.active_match_info.my_clan_name)} vs ${escapeHTML(data.active_match_info.opponent_name)}<br>匹配到其他联盟，积分保持不变<br>请等待部落管理员判定结果</div>`;
            resultBanner.style.display = '';
        } else {
            // admin_notice → 以部落管理通知为准
            resultBanner.className = 'match-result-banner notice';
            resultBanner.innerHTML = `<div class="banner-big-text">📢 以部落管理通知为准</div><div class="banner-detail">${escapeHTML(data.active_match_info.my_clan_name)} vs ${escapeHTML(data.active_match_info.opponent_name)}<br>${data.active_match_info.remark ? '类型：' + escapeHTML(data.active_match_info.remark) + '<br>' : ''}积分保持不变<br>最终结果请以部落管理员通知为准</div>`;
            resultBanner.style.display = '';
        }
    } else {
        // 默认两个卡片都隐藏，等用户从弹窗中选择
        matchSuccessCard.style.display = 'none';
        matchFailedCard.style.display = 'none';
        matchDone.style.display = 'none';
        if (data.cancel_notice) {
            renderAdminCancelNotice(data.cancel_notice);
        } else {
            resultBanner.style.display = 'none';
            resultBanner.innerHTML = '';
        }
    }

    // 配置统计卡片显示控制
    renderConfigStatsCard(data.config_stats_enabled);

    // 积分操作指南
    const guideEl = document.getElementById('score-guide-player');
    if (data.score_guide) {
        guideEl.style.display = '';
        document.getElementById('score-guide-player-content').innerHTML = escapeHTML(data.score_guide).replace(/\n/g, '<br>');
    } else {
        guideEl.style.display = 'none';
    }

    // 通知（常驻卡片）
    if (data.notifications && data.notifications.length > 0) {
        let h = '';
        data.notifications.forEach(n => { h += `<div class="notification-item">${escapeHTML(n.content)}<br><span class="notification-time">${formatDate(n.created_at)}</span></div>`; });
        document.getElementById('notification-list').innerHTML = h;
    } else {
        document.getElementById('notification-list').innerHTML = '<p class="empty-text">暂无通知</p>';
    }

    renderMyClans();
    await Promise.all([loadLeaderboard(), loadMatchHistory(), loadPlayerUnknownClans()]);

    // 触发登记提醒弹窗
    maybeShowMatchPrompt(data);
}

function renderMyClans() {
    const clanEl = document.getElementById('clan-info');
    if (myClans.length > 0) {
        // 部落切换 Tab + 选中部落详情
        let h = '<div class="clan-tabs">';
        myClans.forEach(c => {
            const isActive = c.id === activeClanId;
            h += `<button class="clan-tab${isActive ? ' active' : ''}" onclick="switchClan(${c.id})">${escapeHTML(c.name)}</button>`;
        });
        h += '</div>';

        // 选中部落的详情
        const activeClan = myClans.find(c => c.id === activeClanId) || myClans[0];
        if (activeClan) {
            const scoreClass = activeClan.score >= 0 ? 'score-positive' : 'score-negative';
            h += `<div class="my-clan-item">
                <div class="clan-name-display">🏛️ ${escapeHTML(activeClan.name)}</div>
                <div class="clan-detail-display">标签: ${escapeHTML(activeClan.code)} | 联系人: ${escapeHTML(activeClan.contact) || '-'} | 积分: <span class="${scoreClass}">${activeClan.score}</span></div>
                <div class="clan-item-actions">
                    <button class="btn btn-sm" onclick="editContact(${activeClan.id}, '${escapeHTML(activeClan.contact || '')}')">改联系人</button>
                    <button class="btn btn-sm btn-danger" onclick="unbindClan(${activeClan.id})">解绑</button>
                </div>
            </div>`;
        }

        clanEl.innerHTML = h;

        // 更新出战部落选择框（两个卡片各一份）
        const sel = document.getElementById('my-clan-select');
        const selFailed = document.getElementById('my-clan-select-failed');
        const opts = myClans.map(c => `<option value="${c.id}"${c.id === activeClanId ? ' selected' : ''}>${escapeHTML(c.name)} (${c.score})</option>`).join('');
        sel.innerHTML = opts;
        if (selFailed) selFailed.innerHTML = opts;
        document.getElementById('history-card').style.display = '';
    } else {
        clanEl.innerHTML = `<div class="bind-reminder"><p>⚠️ 您还未绑定部落，请先绑定！</p><button class="btn btn-primary" onclick="showBindModal()">绑定部落</button></div>`;
        document.getElementById('match-success-card').style.display = 'none';
        document.getElementById('match-failed-card').style.display = 'none';
        document.getElementById('history-card').style.display = 'none';
    }
}

function switchClan(clanId) {
    if (activeClanId === clanId) return;
    activeClanId = clanId;
    renderMyClans();
    loadMatchHistory();
}

function renderRoundStatus(currentRound, myRegistration) {
    const statusEl = document.getElementById('round-status-content');
    const bannerEl = document.getElementById('registration-status-banner');

    if (!currentRound) {
        statusEl.innerHTML = `<div class="round-status-none">📋 当前暂无进行中的轮次，请联系管理员开启本轮。</div>`;
        bannerEl.innerHTML = '';
        return;
    }

    const roundNo = currentRound.round_no;
    const isOpen = currentRound.status === 'open';
    const registered = myRegistration && myRegistration.registered;

    // 轮次状态小字（原有卡片内信息）
    if (registered) {
        const t = myRegistration.registered_at ? formatDate(myRegistration.registered_at) : '';
        statusEl.innerHTML = `<div class="round-status-done">✅ 第${roundNo}轮已登记 ${t ? '（' + t + '）' : ''}</div>`;
    } else {
        statusEl.innerHTML = `<div class="round-status-pending">⚠️ 第${roundNo}轮尚未登记，请搜索对手完成登记！</div>`;
    }

    // 醒目横幅（新增大横幅区域）
    if (registered) {
        // 已登记 → 横幅由 loadPlayerData 的 has_active_match 分支处理，此处不再重复
        bannerEl.innerHTML = '';
    } else if (isOpen) {
        // 未登记 + 轮次开启中 → 醒目提示
        bannerEl.innerHTML = `
            <div class="reg-banner reg-banner--warning">
                <div class="reg-banner__round">第 ${roundNo} 轮部落战</div>
                <div class="reg-banner__status">⚠️ 您还未进行登记</div>
                <div class="reg-banner__hint">⚡ 请在本轮结束之前完成登记！</div>
            </div>`;
    } else {
        // 轮次已关闭
        bannerEl.innerHTML = `
            <div class="reg-banner reg-banner--closed">
                <div class="reg-banner__round">第 ${roundNo} 轮部落战</div>
                <div class="reg-banner__status">🔒 本轮已关闭</div>
                <div class="reg-banner__hint">本轮登记已截止，请等待下一轮开启</div>
            </div>`;
    }
}

function renderAdminCancelNotice(cancelNotice) {
    const banner = document.getElementById('match-result-banner');
    const message = cancelNotice && cancelNotice.message
        ? cancelNotice.message
        : '管理员已撤销您的本轮登记，请重新登记';
    banner.className = 'match-result-banner notice';
    banner.style.display = '';
    banner.innerHTML = `
        <div class="banner-big-text">📢 登记已撤销</div>
        <div class="banner-detail">
            ${escapeHTML(message)}<br>
            您现在可以重新选择“匹配成功”或“未匹配成功”进行登记。
        </div>`;
}

function renderRoundTime(currentRound) {
    const card = document.getElementById('round-time-card');
    const el = document.getElementById('round-time-content');
    if (!currentRound) {
        card.style.display = 'none';
        return;
    }
    const start = currentRound.next_match_start_time;
    const end = currentRound.next_match_end_time;
    if (!start && !end) {
        card.style.display = 'none';
        return;
    }
    card.style.display = '';
    let timeText;
    if (start && end) {
        timeText = `${formatDateTime(start)} ~ ${formatDateTime(end)}`;
    } else if (start) {
        timeText = `${formatDateTime(start)} ~ 待定`;
    } else {
        timeText = `待定 ~ ${formatDateTime(end)}`;
    }
    el.innerHTML = `<div class="round-time-item next-round">🕐 下一轮匹配时间：<strong>${timeText}</strong></div>`;
}

function formatDateTime(d) {
    if (!d) return '-';
    const dt = new Date(d);
    return dt.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function formatRoundNo(m) {
    if (!m.round_no) return '-';
    return m.is_current_round ? '🔄 本轮' : `第${m.round_no}轮`;
}

async function loadLeaderboard() {
    const data = await api('GET', '/leaderboard');
    const el = document.getElementById('leaderboard');
    if (data.clans.length === 0) { el.innerHTML = '<p class="empty-text">暂无部落</p>'; return; }
    let html = '<div class="table-wrapper"><table><tr><th>排名</th><th>部落</th><th>联系人</th><th>积分</th></tr>';
    data.clans.forEach((c, i) => {
        const s = c.score >= 0 ? 'score-positive' : 'score-negative';
        const isActive = c.id === activeClanId;
        const nameStyle = isActive ? 'font-weight:bold;color:var(--primary)' : '';
        html += `<tr><td>${i+1}</td><td style="${nameStyle}">${escapeHTML(c.name)}<br><span style="font-size:0.75rem;color:var(--text-muted)">${escapeHTML(c.code)}</span></td><td>${escapeHTML(c.contact) || '-'}</td><td class="${s}">${c.score}</td></tr>`;
    });
    html += '</table></div>';
    el.innerHTML = html;
}

async function loadMatchHistory() {
    const params = activeClanId ? `?clan_id=${activeClanId}` : '';
    const data = await api('GET', `/match-history${params}`);
    const el = document.getElementById('match-history');
    if (data.matches.length === 0) { el.innerHTML = '<p class="empty-text">暂无对战记录</p>'; return; }
    let html = '<div class="table-wrapper"><table><tr><th>轮次</th><th>日期</th><th>对手</th><th>结果</th><th>我的配置</th></tr>';
    data.matches.forEach((m, i) => {
        const myClanIds = myClans.map(c => c.id);
        const iAmA = myClanIds.includes(m.clan_a_id);
        const myClanId = iAmA ? m.clan_a_id : m.clan_b_id;
        const opponentName = iAmA ? m.clan_b_name : m.clan_a_name;
        const iWon = m.winner_id === myClanId;
        const result = iWon ? '✅ 胜' : '❌ 负';
        const cls = iWon ? 'score-positive' : 'score-negative';
        const reg = m.is_registered ? '' : ' <span style="font-size:0.72rem;color:var(--text-muted)">(未登记)</span>';
        const roundLabel = formatRoundNo(m);
        const configDisplay = m.config_remark ? `<span title="${escapeAttr(m.config_remark)}">${escapeHTML(m.config_remark.length > 20 ? m.config_remark.slice(0, 20) + '…' : m.config_remark)}</span>` : '-';
        html += `<tr><td>${roundLabel}</td><td>${formatDate(m.matched_at)}</td><td>${escapeHTML(opponentName)}${reg}</td><td class="${cls}">${result}</td><td style="font-size:0.82rem;max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${configDisplay}</td></tr>`;
    });
    html += '</table></div>';
    el.innerHTML = html;
}

// ========== 绑定部落 ==========
function showBindModal() { document.getElementById('bind-modal').classList.add('active'); }
function closeBindModal() { document.getElementById('bind-modal').classList.remove('active'); }

document.getElementById('bind-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
        await api('POST', '/bind-clan', {
            clan_name: document.getElementById('bind-clan-name').value,
            clan_code: document.getElementById('bind-clan-code').value,
            contact: document.getElementById('bind-clan-contact').value
        });
        closeBindModal();
        loadPlayerData();
    } catch {}
});

async function unbindClan(clanId) {
    if (!await customConfirm('确定要解绑该部落吗？', '解绑')) return;
    try { await api('POST', `/unbind-clan?clan_id=${clanId}`); alert('解绑成功！'); loadPlayerData(); } catch {}
}

async function editContact(clanId, current) {
    const contact = prompt('修改部落联系人（QQ昵称）：', current);
    if (contact === null) return;
    try { await api('PUT', `/clan/${clanId}/contact?contact=${encodeURIComponent(contact)}`); alert('修改成功！'); loadPlayerData(); } catch {}
}

// ========== API 请求封装 ==========
async function api(method, path, body = null, options = {}) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (token) opts.headers['Authorization'] = `Bearer ${token}`;
    if (body) opts.body = JSON.stringify(body);
    let res;
    try {
        res = await fetch(`${API}${path}`, opts);
    } catch (e) {
        if (!options.silent) alert('网络连接失败，请检查网络后重试');
        throw new Error('网络连接失败');
    }
    let data;
    try {
        data = await res.json();
    } catch (e) {
        if (!options.silent) alert('服务器响应异常，请稍后重试');
        throw new Error('服务器响应异常');
    }
    if (!res.ok) {
        if (res.status === 401 && path !== '/login') { logout(); return; }
        // 404 特殊提示
        if (res.status === 404) {
            const detailStr = data.detail ? String(data.detail) : 'Not Found';
            if (detailStr.toLowerCase().includes('not found') || detailStr === 'Not Found') {
                if (!options.silent) alert(`功能接口暂未部署或路径不存在：${path}`);
                throw new Error(`功能接口暂未部署或路径不存在：${path}`);
            }
        }
        let msg = '请求失败';
        if (data.detail) {
            msg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
        }
        if (!options.silent) alert(msg);
        throw new Error(msg);
    }
    return data;
}

function escapeHTML(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function escapeAttr(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ========== 搜索匹配 ==========
async function searchClan() {
    const keyword = document.getElementById('search-keyword').value.trim();
    if (!keyword) { alert('请输入搜索关键词'); return; }
    const el = document.getElementById('search-results');
    el.innerHTML = '<div class="search-empty">🔍 搜索中...</div>';
    try {
        const data = await api('POST', '/search-clan', { keyword });
        if (data.clans.length === 0) {
            el.innerHTML = '<div class="search-empty">🔍 未找到匹配的部落，请在下方填写对方信息完成匹配</div>';
            return;
        }
        let html = '<div class="search-results-header">找到 ' + data.clans.length + ' 个匹配部落：</div>';
        data.clans.forEach(c => {
            const s = c.score >= 0 ? 'score-positive' : 'score-negative';
            const myClanIds = myClans.map(mc => mc.id);
            const isMine = myClanIds.includes(c.id);
            const disabledAttr = isMine ? 'disabled' : '';
            const disabledTip = isMine ? '（自己的部落）' : '';
            html += `<div class="search-result-item">
                <div class="search-result-info">
                    <span class="search-result-name">🏛️ ${escapeHTML(c.name)}</span>${disabledTip}<br>
                    <span class="search-result-detail">标签: ${escapeHTML(c.code)} | 联系人: ${escapeHTML(c.contact) || '-'} | 积分: <span class="${s}">${c.score}</span></span>
                </div>
                <button class="btn btn-accent btn-sm" onclick="matchRegistered(${c.id}, '${escapeAttr(c.name)}')" ${disabledAttr}>登记对战</button>
            </div>`;
        });
        el.innerHTML = html;
    } catch {}
}

async function matchRegistered(clanId, clanName) {
    const myClanId = parseInt(document.getElementById('my-clan-select').value);
    const myClanName = document.getElementById('my-clan-select').selectedOptions[0].text.split(' (')[0];
    const configRemark = document.getElementById('config-remark').value.trim();
    if (isNaN(myClanId)) { alert('请先选择出战部落'); return; }
    // 前端配置必填校验
    const configRequired = currentUser && currentUser.current_round && currentUser.current_round.config_required;
    if (configRequired && !configRemark) { alert('本轮要求填写对战配置，请先填写配置信息'); return; }
    const confirmMsg = `即将与【${clanName || '该部落'}】登记对战\n\n出战部落：${myClanName}\n\n确认匹配？`;
    if (!await customConfirm(confirmMsg, '确认匹配')) return;
    try {
        const data = await api('POST', '/match/registered', { clan_id: clanId, my_clan_id: myClanId, config_remark: configRemark });
        showMatchResult(data);
    } catch {}
}

async function matchUnregistered() {
    const name = document.getElementById('unreg-clan-name').value.trim();
    const code = document.getElementById('unreg-clan-code').value.trim();
    const tags = document.getElementById('unreg-clan-tags').value.trim();
    const category = document.getElementById('unreg-category').value;
    const configRemark = document.getElementById('config-remark-failed').value.trim();
    if (!name || !code) { alert('请填写对方部落名称和标签'); return; }
    // 前端配置必填校验
    const configRequired = currentUser && currentUser.current_round && currentUser.current_round.config_required;
    if (configRequired && !configRemark) { alert('本轮要求填写对战配置，请先填写配置信息'); return; }
    if (!await customConfirm(`对方部落未登记，将默认判输（-1分）\n匹配类型：${category}\n\n确认提交？`, '确认提交')) return;
    try {
        const data = await api('POST', '/match/unregistered', { clan_name: name, clan_code: code, tags: tags, remark: category, config_remark: configRemark });
        showMatchResult(data, 'failed');
    } catch {}
}

function showMatchResult(data, mode) {
    // mode: 'success' / 'failed'，决定结果显示在哪个卡片里
    const elId = mode === 'failed' ? 'match-result-failed' : 'match-result';
    const el = document.getElementById(elId);
    const clanSelect = mode === 'failed' ? document.getElementById('my-clan-select-failed') : document.getElementById('my-clan-select');
    const myClanName = clanSelect.selectedOptions[0].text.split(' (')[0];
    const banner = document.getElementById('match-result-banner');
    const matchDone = document.getElementById('match-done');
    const matchSuccessCard = document.getElementById('match-success-card');
    const matchFailedCard = document.getElementById('match-failed-card');
    if (data.is_registered) {
        const opponentName = data.winner.name === myClanName ? data.loser.name : data.winner.name;
        const iWin = data.winner.name === myClanName;
        if (iWin) {
            banner.className = 'match-result-banner win';
            banner.innerHTML = `
                <div class="banner-big-text">✌ 胜利！</div>
                <div class="banner-detail">
                    <div class="banner-vs">${escapeHTML(myClanName)} <span class="vs-tag">VS</span> ${escapeHTML(opponentName)}</div>
                    <div class="banner-score">恭喜，积分 +1（当前：${data.winner.score}）</div>
                </div>`;
        } else {
            banner.className = 'match-result-banner lose';
            banner.innerHTML = `
                <div class="banner-big-text">✗ 失败</div>
                <div class="banner-detail">
                    <div class="banner-vs">${escapeHTML(myClanName)} <span class="vs-tag">VS</span> ${escapeHTML(opponentName)}</div>
                    <div class="banner-score">积分 -1，再接再厉（当前：${data.loser.score}）</div>
                </div>`;
        }
        banner.style.display = '';
        matchSuccessCard.style.display = 'none';
        matchFailedCard.style.display = 'none';
        matchDone.style.display = 'none';
    } else {
        const opponentName = data.loser.name || '对方部落';
        banner.className = 'match-result-banner pending';
        banner.innerHTML = `
            <div class="banner-big-text">⏳ 待定</div>
            <div class="banner-detail">
                <div class="banner-vs">${escapeHTML(myClanName)} <span class="vs-tag">VS</span> ${escapeHTML(opponentName)}</div>
                <div class="banner-score">对方未登记，积分保持不变（当前：${data.loser.score}）</div>
            </div>`;
        banner.style.display = '';
        matchSuccessCard.style.display = 'none';
        matchFailedCard.style.display = 'none';
        matchDone.style.display = 'none';
    }
    document.getElementById('search-keyword').value = '';
    document.getElementById('search-results').innerHTML = '';
    document.getElementById('unreg-clan-name').value = '';
    document.getElementById('unreg-clan-code').value = '';
    document.getElementById('unreg-category').selectedIndex = 0;
    document.getElementById('config-remark').value = '';
    document.getElementById('config-remark-failed').value = '';
    banner.scrollIntoView({ behavior: 'smooth', block: 'start' });
    loadPlayerDataLight();
}

// 轻量刷新
async function loadPlayerDataLight() {
    try {
        const data = await api('GET', '/me');
        currentUser = data;
        myClans = data.clans || [];
        if (myClans.length > 0 && (!activeClanId || !myClans.find(c => c.id === activeClanId))) {
            activeClanId = myClans[0].id;
        }
        renderRoundStatus(data.current_round, data.my_registration);
        renderMyClans();

        // 更新匹配状态
        const matchDone = document.getElementById('match-done');
        const matchSuccessCard = document.getElementById('match-success-card');
        const matchFailedCard = document.getElementById('match-failed-card');
        const resultBanner = document.getElementById('match-result-banner');
        const regBanner = document.getElementById('registration-status-banner');
        if (data.has_active_match && data.active_match_info) {
            matchSuccessCard.style.display = 'none';
            matchFailedCard.style.display = 'none';
            matchDone.style.display = 'none';
            resultBanner.style.display = '';
            if (data.active_match_info.result === 'win') {
                resultBanner.className = 'match-result-banner win';
                resultBanner.innerHTML = `
                    <div class="banner-big-text">✌ 胜利！</div>
                    <div class="banner-detail">
                        <div class="banner-vs">${escapeHTML(data.active_match_info.my_clan_name)} <span class="vs-tag">VS</span> ${escapeHTML(data.active_match_info.opponent_name)}</div>
                        <div class="banner-score">恭喜，积分 +1</div>
                    </div>`;
            } else if (data.active_match_info.result === 'lose') {
                resultBanner.className = 'match-result-banner lose';
                resultBanner.innerHTML = `
                    <div class="banner-big-text">✗ 失败</div>
                    <div class="banner-detail">
                        <div class="banner-vs">${escapeHTML(data.active_match_info.my_clan_name)} <span class="vs-tag">VS</span> ${escapeHTML(data.active_match_info.opponent_name)}</div>
                        <div class="banner-score">积分 -1，再接再厉！</div>
                    </div>`;
            } else if (data.active_match_info.result === 'pending') {
                resultBanner.className = 'match-result-banner pending';
                resultBanner.innerHTML = `
                    <div class="banner-big-text">⏳ 待定</div>
                    <div class="banner-detail">
                        <div class="banner-vs">${escapeHTML(data.active_match_info.my_clan_name)} <span class="vs-tag">VS</span> ${escapeHTML(data.active_match_info.opponent_name)}</div>
                        <div class="banner-score">匹配到其他联盟，积分保持不变，请等待管理员判定</div>
                    </div>`;
            } else {
                resultBanner.className = 'match-result-banner notice';
                resultBanner.innerHTML = `
                    <div class="banner-big-text">📢 以部落管理通知为准</div>
                    <div class="banner-detail">
                        <div class="banner-vs">${escapeHTML(data.active_match_info.my_clan_name)} <span class="vs-tag">VS</span> ${escapeHTML(data.active_match_info.opponent_name)}</div>
                        <div class="banner-score">积分保持不变，最终结果以管理员通知为准</div>
                    </div>`;
            }
        } else {
            // 轻量刷新不主动展开，保持当前用户的选择
            matchDone.style.display = 'none';
            if (data.cancel_notice) {
                renderAdminCancelNotice(data.cancel_notice);
            } else {
                resultBanner.style.display = 'none';
                resultBanner.innerHTML = '';
            }
        }

        await loadLeaderboard();
    } catch {}
}

// ========== 修改密码（成员） ==========
function showChangePwdModal() { document.getElementById('change-pwd-modal').classList.add('active'); }
function closeChangePwdModal() { document.getElementById('change-pwd-modal').classList.remove('active'); }

async function skipChangePwd() {
    if (!await customConfirm('确定跳过密码修改？\n\n建议尽快修改默认密码以确保账号安全。', '跳过')) return;
    try {
        await api('POST', '/skip-change-pwd');
        alert('已跳过密码修改');
        document.getElementById('must-change-pwd').style.display = 'none';
    } catch {}
}

document.getElementById('change-pwd-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
        await api('POST', '/change-password', {
            old_password: document.getElementById('cp-old-pwd').value,
            new_password: document.getElementById('cp-new-pwd').value
        });
        closeChangePwdModal();
        document.getElementById('cp-old-pwd').value = '';
        document.getElementById('cp-new-pwd').value = '';
        alert('密码修改成功，请重新登录');
        logout();
    } catch {}
});

// ========== 管理员 ==========
async function safeLoadAdminOptional(fn, label) {
    /**安全加载非核心模块，失败时不弹窗打断用户 */
    try {
        await fn();
    } catch (e) {
        console.warn(`[safeLoad] ${label} 加载失败:`, e.message);
    }
}

async function loadMonitorDashboard() {
    try {
        const data = await api('GET', '/monitor/super-admins');
        const countEl = document.getElementById('monitor-super-count');
        if (countEl) countEl.innerHTML = `当前超管数量：<strong>${data.total || 0} / 2</strong>（最多 2 个）`;
        const el = document.getElementById('monitor-super-list');
        if (!data.super_admins || data.super_admins.length === 0) {
            el.innerHTML = '<div class="card"><p class="empty-text">暂无超管账号</p></div>';
            return;
        }
        let html = '';
        for (const u of data.super_admins) {
            let statusBadge = '';
            let actions = '';
            if (u.status === 'active') {
                statusBadge = '<span class="badge badge-active">正常</span>';
                actions = `
                    <button class="btn btn-sm" onclick="monitorSetStatus(${u.id},'${escapeAttr(u.username)}','frozen')">冻结</button>
                    <button class="btn btn-sm btn-danger" onclick="monitorSetStatus(${u.id},'${escapeAttr(u.username)}','disabled')">禁用</button>`;
            } else if (u.status === 'frozen') {
                statusBadge = '<span class="badge badge-frozen">已冻结</span>';
                actions = `
                    <button class="btn btn-sm btn-success" onclick="monitorSetStatus(${u.id},'${escapeAttr(u.username)}','active')">恢复</button>
                    <button class="btn btn-sm btn-danger" onclick="monitorSetStatus(${u.id},'${escapeAttr(u.username)}','disabled')">禁用</button>`;
            } else if (u.status === 'disabled') {
                statusBadge = '<span class="badge badge-disabled">已禁用</span>';
                actions = `<button class="btn btn-sm btn-success" onclick="monitorSetStatus(${u.id},'${escapeAttr(u.username)}','active')">恢复</button>`;
            }
            const pwdFlag = u.must_change_pwd ? ' <span class="badge" style="background:rgba(245,158,11,0.2);color:#f59e0b">需改密码</span>' : '';
            html += `
                <div class="card admin-card">
                    <div class="admin-card-header">
                        <div class="admin-card-title">👑 ${escapeHTML(u.username)}</div>
                        <div>${statusBadge}${pwdFlag}</div>
                    </div>
                    <div class="admin-card-info">
                        <div><span class="info-label">ID:</span> ${u.id}</div>
                        <div><span class="info-label">状态:</span> ${u.status === 'active' ? '正常' : (u.status === 'frozen' ? '已冻结' : '已禁用')}</div>
                        <div><span class="info-label">创建时间:</span> ${formatDate(u.created_at)}</div>
                    </div>
                    <div class="card-actions">
                        ${actions}
                        <button class="btn btn-sm" onclick="monitorChangeSuperAdminPwd(${u.id},'${escapeAttr(u.username)}')">修改密码</button>
                        <button class="btn btn-sm btn-danger" onclick="monitorDelete(${u.id},'${escapeAttr(u.username)}')">删除</button>
                    </div>
                </div>`;
        }
        el.innerHTML = html;
    } catch (e) {
        const el = document.getElementById('monitor-super-list');
        if (el) el.innerHTML = `<div class="card"><p class="empty-text">加载失败：${escapeHTML(e.message)}</p></div>`;
    }
}

async function showCreateSuperAdmin() {
    const username = prompt('请输入新超管账号的用户名：');
    if (!username || !username.trim()) return;
    const password = prompt('请输入密码（至少 6 位）：');
    if (password === null) return;
    if (password.trim().length < 6) { alert('密码至少需要6位'); return; }
    try {
        await api('POST', '/monitor/super-admins', { username: username.trim(), password: password.trim() });
        alert('超管账号创建成功！');
        loadMonitorDashboard();
    } catch {}
}

async function monitorSetStatus(id, name, status) {
    const actionText = status === 'frozen' ? '冻结' : (status === 'disabled' ? '禁用' : '恢复');
    if (!await customConfirm(`确认${actionText}超管【${name}】？`, actionText)) return;
    try {
        await api('PUT', `/monitor/super-admins/${id}/status?status=${status}`);
        alert(`${actionText}成功！`);
        loadMonitorDashboard();
    } catch {}
}

async function monitorChangeSuperAdminPwd(id, name) {
    const newPassword = prompt(`请输入超管【${name}】的新密码（至少6位）`);
    if (newPassword === null) return;
    if (newPassword.trim().length < 6) { alert('新密码至少需要6位'); return; }
    if (!await customConfirm(`确认修改超管【${name}】的密码？`, '修改密码')) return;
    try {
        await api('PUT', `/monitor/super-admins/${id}/password`, { new_password: newPassword.trim() });
        alert('密码修改成功，请通知超管使用新密码登录');
    } catch {}
}

async function monitorDelete(id, name) {
    if (!await customConfirm(`确认删除超管【${name}】？\n此操作不可恢复！`, '删除')) return;
    try {
        await api('DELETE', `/monitor/super-admins/${id}`);
        alert('删除成功！');
        loadMonitorDashboard();
    } catch {}
}

async function loadAdminData() {
    // 核心模块正常加载
    await Promise.all([
        loadUserList(),
        loadRounds(),
        loadClanList(),
        loadAllMatches(),
    ]);
    // 非核心模块：失败时静默，不让弹窗打断用户
    await Promise.all([
        safeLoadAdminOptional(loadUnknownClans, '陌生部落'),
        safeLoadAdminOptional(loadMatchStats, '匹配统计'),
        safeLoadAdminOptional(loadOperationLogs, '操作日志'),
        safeLoadAdminOptional(loadNotificationHistory, '通知管理'),
        safeLoadAdminOptional(loadScoreGuide, '积分指南'),
        safeLoadAdminOptional(loadRoundClanStatus, '本轮部落状态'),
    ]);
}

function switchTab(e, name) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    e.target.classList.add('active');
    document.getElementById(`tab-${name}`).classList.add('active');
    if (name === 'config-stats') {
        loadConfigStats();
    }
}

async function loadUserList() {
    const data = await api('GET', '/admin/users');
    const el = document.getElementById('user-list');
    const isSuperAdmin = currentUser && currentUser.is_super_admin;
    let html = '';
    data.users.forEach(u => {
        const sBadge = `<span class="badge badge-${u.status}">${u.status==='active'?'正常':u.status==='frozen'?'已冻结':'已禁用'}</span>`;
        const rBadge = `<span class="badge badge-${u.role}">${u.role==='admin'?'管理员':'玩家'}</span>`;
        const superBadge = u.is_super_admin ? '<span class="badge" style="background:rgba(245,158,11,0.2);color:#f59e0b">👑 超管</span>' : '';
        const pwdFlag = u.must_change_pwd ? ' <span class="badge" style="background:rgba(245,158,11,0.2);color:#f59e0b">未改密码</span>' : '';
        const clanInfo = (u.clans && u.clans.length > 0) ? u.clans.map(c => c.name).join(', ') : '未绑定';
        html += `<div class="user-item">
            <div class="user-info"><span class="name">${escapeHTML(u.username)}</span> ${rBadge} ${superBadge} ${sBadge} ${pwdFlag}
                <div class="detail">部落: ${escapeHTML(clanInfo)}</div>
            </div>
            <div class="user-actions">
                ${u.status==='frozen' ? `<button class="btn btn-sm btn-success" onclick="setUserStatus(${u.id},'active')">解冻</button>` : ''}
                ${u.status==='active' ? `<button class="btn btn-sm" onclick="setUserStatus(${u.id},'frozen')">冻结</button>` : ''}
                ${u.status!=='disabled' ? `<button class="btn btn-sm btn-danger" onclick="setUserStatus(${u.id},'disabled')">禁用</button>` : ''}
                ${u.status==='disabled' ? `<button class="btn btn-sm btn-success" onclick="setUserStatus(${u.id},'active')">启用</button>` : ''}
                ${isSuperAdmin && !u.is_super_admin ? `<button class="btn btn-sm" onclick="setSuperAdmin(${u.id},true)" style="background:rgba(245,158,11,0.2);color:#f59e0b">设超管</button>` : ''}
                ${isSuperAdmin && u.is_super_admin && u.id !== currentUser.id ? `<button class="btn btn-sm" onclick="setSuperAdmin(${u.id},false)" style="background:rgba(107,114,128,0.2);color:#6b7280">取消超管</button>` : ''}
                <button class="btn btn-sm" onclick="showAdminPwdModal(${u.id})">重置密码</button>
                <button class="btn btn-sm btn-danger" onclick="deleteUser(${u.id},'${escapeAttr(u.username)}')">删除</button>
            </div>
        </div>`;
    });
    el.innerHTML = html || '<p class="empty-text">暂无用户</p>';
}

async function loadClanList() {
    const data = await api('GET', '/admin/clans');
    const el = document.getElementById('clan-list');
    const sel = document.getElementById('adjust-clan-select');
    let html = '<div class="table-wrapper"><table><tr><th>部落</th><th>标签</th><th>联系人</th><th>积分</th><th>成员</th></tr>';
    let opts = '';
    (data.clans || []).forEach(c => {
        const s = c.score >= 0 ? 'score-positive' : 'score-negative';
        html += `<tr><td>${escapeHTML(c.name)}</td><td>${escapeHTML(c.code)}</td><td>${escapeHTML(c.contact) || '-'}</td><td class="${s}">${c.score}</td><td>${c.member_count}</td></tr>`;
        opts += `<option value="${c.id}">${escapeHTML(c.name)} (${c.score})</option>`;
    });
    html += '</table></div>';
    el.innerHTML = html || '<p class="empty-text">暂无部落</p>';
    sel.innerHTML = opts || '<option value="">暂无部落</option>';
}

async function loadAllMatches() {
    const data = await api('GET', '/admin/matches');
    const el = document.getElementById('all-matches');
    if (!data.matches || data.matches.length === 0) { el.innerHTML = '<p class="empty-text">暂无对战记录</p>'; return; }
    let html = '<div class="table-wrapper"><table><tr><th>轮次</th><th>时间</th><th>对战</th><th>胜方</th><th>赛前积分</th><th>状态</th><th>操作</th></tr>';
    data.matches.forEach(m => {
        const reg = m.is_registered ? '已登记' : '<span class="score-negative">未登记</span>';
        const roundLabel = formatRoundNo(m);
        const canAdminCancel = m.is_current_round ? `<button class="btn btn-sm btn-danger" onclick="cancelMatchAdmin(${m.id}, '${escapeAttr(m.clan_a_name)}', '${escapeAttr(m.clan_b_name)}')">撤销</button>` : '';
        html += `<tr><td>${roundLabel}</td><td>${formatDate(m.matched_at)}</td><td>${escapeHTML(m.clan_a_name)} vs ${escapeHTML(m.clan_b_name)}</td><td class="score-positive">${escapeHTML(m.winner_name) || '-'}</td><td>${m.score_before_a} / ${m.score_before_b}</td><td>${reg}</td><td>${canAdminCancel}</td></tr>`;
    });
    html += '</table></div>';
    el.innerHTML = html;
}

async function cancelMatchAdmin(matchId, clanA, clanB) {
    if (!await customConfirm(`确定撤销该对战记录？\n\n${clanA} vs ${clanB}\n\n积分将恢复原值。`, '撤销登记')) return;
    try {
        const data = await api('DELETE', `/admin/match/${matchId}/cancel`);
        alert(data.message);
        await Promise.all([loadAllMatches(), loadClanList()]);
    } catch {}
}

async function loadMatchStats() {
    try {
        const data = await api('GET', '/admin/match-stats', null, { silent: true });
        const el = document.getElementById('match-stats-content');
        let html = '';
        if (data.stats && data.stats.unknown_clan_matches && data.stats.unknown_clan_matches.length > 0) {
            html += '<h3>未登记匹配统计</h3><div class="table-wrapper"><table><tr><th>备注/类型</th><th>次数</th></tr>';
            data.stats.unknown_clan_matches.forEach(r => {
                html += `<tr><td>${escapeHTML(r.remark) || '（无备注）'}</td><td>${r.cnt}</td></tr>`;
            });
            html += '</table></div>';
        }
        el.innerHTML = html || '<p class="empty-text">暂无匹配统计数据</p>';
    } catch {}
}

async function loadOperationLogs() {
    try {
        const data = await api('GET', '/admin/operation-logs', null, { silent: true });
        const el = document.getElementById('operation-logs');
        if (!data.logs || data.logs.length === 0) { el.innerHTML = '<p class="empty-text">暂无操作日志</p>'; return; }
        let html = '<div class="table-wrapper"><table><tr><th>时间</th><th>操作者</th><th>部落</th><th>操作</th><th>对象</th><th>详情</th><th>理由</th></tr>';
        data.logs.forEach(l => {
            html += `<tr><td>${formatDate(l.created_at)}</td><td>${escapeHTML(l.username) || '-'}</td><td style="font-size:0.82rem">${escapeHTML(l.admin_clans) || '-'}</td><td>${escapeHTML(l.action_cn || l.action)}</td><td>${escapeHTML(l.target_type) || '-'}</td><td>${escapeHTML(l.detail) || '-'}</td><td>${escapeHTML(l.reason) || '-'}</td></tr>`;
        });
        html += '</table></div>';
        el.innerHTML = html;
    } catch {}
}

async function loadNotificationHistory() {
    try {
        const data = await api('GET', '/admin/notifications', null, { silent: true });
        const el = document.getElementById('notification-history');
        if (!data.notifications || data.notifications.length === 0) { el.innerHTML = '<p class="empty-text">暂无通知</p>'; return; }
        let html = '';
        data.notifications.forEach(n => { html += `<div class="notification-item">${escapeHTML(n.content)}<br><span class="notification-time">${formatDate(n.created_at)}</span></div>`; });
        el.innerHTML = html;
    } catch {}
}

// 创建用户
document.getElementById('create-user-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
        await api('POST', '/admin/users', {
            username: document.getElementById('new-username').value,
            password: document.getElementById('new-password').value,
            role: document.getElementById('new-role').value
        });
        document.getElementById('new-username').value = '';
        document.getElementById('new-password').value = '';
        loadUserList();
    } catch {}
});

// 调整积分
document.getElementById('adjust-score-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
        const clan_id = parseInt(document.getElementById('adjust-clan-select').value);
        const delta = parseInt(document.getElementById('adjust-delta').value);
        const reason = document.getElementById('adjust-reason').value.trim();
        if (!reason) { alert('请填写调整理由！'); return; }
        const clanName = document.getElementById('adjust-clan-select').selectedOptions[0].text.split(' (')[0];
        const sign = delta >= 0 ? '+' : '';
        if (!await customConfirm(`确定调整【${clanName}】的积分？\n\n调整值：${sign}${delta}\n理由：${reason}`, '确认调整')) return;
        await api('POST', `/admin/score/adjust?clan_id=${clan_id}&delta=${delta}&reason=${encodeURIComponent(reason)}`);
        alert('积分调整成功！');
        document.getElementById('adjust-delta').value = '';
        document.getElementById('adjust-reason').value = '';
        loadClanList();
    } catch {}
});

async function setUserStatus(userId, status) {
    const actionText = status === 'frozen' ? '冻结' : (status === 'disabled' ? '禁用' : '解冻/启用');
    if (!await customConfirm(`确定${actionText}该用户？`, actionText)) return;
    try {
        await api('PUT', `/admin/users/${userId}/status?status=${status}`);
        alert(`${actionText}成功！`);
        loadUserList();
    } catch {}
}

async function deleteUser(userId, username) {
    if (!await customConfirm(`确定删除用户"${username}"？\n不可撤销！`, '删除')) return;
    try {
        await api('DELETE', `/admin/users/${userId}`);
        alert('删除成功！');
        loadUserList();
    } catch {}
}

async function setSuperAdmin(userId, isSuper) {
    const action = isSuper ? '设置该用户为超管（最多2个）' : '取消该用户的超管权限';
    if (!await customConfirm(`确定${action}？`, '确定')) return;
    try {
        await api('PUT', `/admin/users/${userId}/super-admin?is_super=${isSuper}`);
        alert(isSuper ? '已设为超管' : '已取消超管权限');
        loadUserList();
    } catch {}
}

// 管理员重置密码弹窗
async function showAdminPwdModal(userId) {
    if (!await customConfirm('确定要重置该用户的密码吗？\n\n密码将被重置为 000000，\n用户下次登录需修改密码。', '重置密码')) return;
    try {
        await api('PUT', `/admin/users/${userId}/password`);
        alert('密码已重置为 000000，请通知用户登录后修改密码');
        loadUserList();
    } catch {}
}

// 发送通知
async function sendNotification() {
    const content = document.getElementById('notify-content').value.trim();
    if (!content) { alert('请输入通知内容'); return; }
    try {
        await api('POST', '/admin/notifications', { content });
        document.getElementById('notify-content').value = '';
        loadNotificationHistory();
        alert('通知已发送');
    } catch {}
}

// ========== 轮次管理 ==========
async function loadRounds() {
    try {
        const data = await api('GET', '/admin/round/list');
        const el = document.getElementById('round-list');
        const bannerEl = document.getElementById('admin-round-status-banner');

        // 管理员轮次状态横幅
        const openRound = data.rounds ? data.rounds.find(r => r.status === 'open') : null;
        if (openRound) {
            bannerEl.innerHTML = `
                <div class="admin-round-banner admin-round-banner--open">
                    <div class="arb__round">🔄 第 ${openRound.round_no} 轮部落战</div>
                    <div class="arb__status">状态：进行中（开启中）</div>
                    <div class="arb__hint">⚡ 成员可以登记，请管理好本轮对战匹配</div>
                </div>`;
        } else {
            const closedRound = data.rounds && data.rounds.length > 0 ? data.rounds[0] : null;
            if (closedRound) {
                bannerEl.innerHTML = `
                    <div class="admin-round-banner admin-round-banner--closed">
                        <div class="arb__round">🏁 第 ${closedRound.round_no} 轮部落战</div>
                        <div class="arb__status">状态：已关闭</div>
                        <div class="arb__hint">当前无进行中的轮次，请点击「开启新一轮」开始下一轮</div>
                    </div>`;
            } else {
                bannerEl.innerHTML = `
                    <div class="admin-round-banner admin-round-banner--empty">
                        <div class="arb__round">📋 暂无轮次记录</div>
                        <div class="arb__status">系统尚未开启任何轮次</div>
                        <div class="arb__hint">点击「开启新一轮」开始第一轮部落战</div>
                    </div>`;
            }
        }

        if (!data.rounds || data.rounds.length === 0) {
            el.innerHTML = '<p class="empty-text">暂无轮次记录</p>';
            return;
        }
        let html = '<div class="table-wrapper"><table><tr><th>轮次</th><th>状态</th><th>登记人数</th><th>开启者</th><th>下一轮匹配开始</th><th>下一轮匹配结束</th><th>开启时间</th><th>关闭时间</th></tr>';
        data.rounds.forEach(r => {
            const statusBadge = r.status === 'open'
                ? '<span class="badge" style="background:rgba(16,185,129,0.2);color:var(--success)">进行中</span>'
                : '<span class="badge" style="background:rgba(107,114,128,0.2);color:#6b7280">已关闭</span>';
            const regCount = r.registrations_count || 0;
            html += `<tr>
                <td>第${r.round_no}轮</td>
                <td>${statusBadge}</td>
                <td>${regCount}人</td>
                <td>${escapeHTML(r.opened_by_name) || '-'}</td>
                <td>${r.next_match_start_time ? formatDateTime(r.next_match_start_time) : '-'}</td>
                <td>${r.next_match_end_time ? formatDateTime(r.next_match_end_time) : '-'}</td>
                <td>${formatDate(r.opened_at)}</td>
                <td>${r.closed_at ? formatDate(r.closed_at) : '-'}</td>
            </tr>`;
        });
        html += '</table></div>';
        el.innerHTML = html;

        if (openRound) {
            if (openRound.next_match_start_time) {
                document.getElementById('next-match-start-time').value = toLocalDatetime(openRound.next_match_start_time);
            } else {
                document.getElementById('next-match-start-time').value = '';
            }
            if (openRound.next_match_end_time) {
                document.getElementById('next-match-end-time').value = toLocalDatetime(openRound.next_match_end_time);
            } else {
                document.getElementById('next-match-end-time').value = '';
            }
            document.getElementById('config-required-toggle').checked = !!openRound.config_required;
            document.getElementById('maintenance-toggle').checked = !!openRound.maintenance;
        }
        // 加载配置统计开关（与轮次无关）
        try {
            const cs = await api('GET', '/admin/settings/config-stats');
            document.getElementById('config-stats-toggle').checked = !!cs.enabled;
        } catch {}
    } catch {}
}

function toLocalDatetime(d) {
    if (!d) return '';
    const dt = new Date(d);
    const pad = n => String(n).padStart(2, '0');
    return `${dt.getFullYear()}-${pad(dt.getMonth()+1)}-${pad(dt.getDate())}T${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
}

async function openRound() {
    if (!await customConfirm('确定开启新一轮？\n\n开启后，成员的匹配登记会自动记录。\n\n如需设置匹配时间，可在开启后使用"设置本轮时间"功能。', '开启')) return;
    try {
        const data = await api('POST', '/admin/round/open');
        alert(data.message);
        loadRounds();
    } catch {}
}

async function updateRoundTime() {
    const nextStart = document.getElementById('next-match-start-time').value || null;
    const nextEnd = document.getElementById('next-match-end-time').value || null;
    const configRequired = document.getElementById('config-required-toggle').checked;
    const maintenance = document.getElementById('maintenance-toggle').checked;
    const configStatsEnabled = document.getElementById('config-stats-toggle').checked;

    if (nextStart && nextEnd && nextStart >= nextEnd) {
        alert('下一轮匹配开始时间必须早于结束时间');
        return;
    }

    try {
        const body = {
            config_required: configRequired,
            maintenance: maintenance,
            next_match_start_time: nextStart ? (nextStart.replace('T', ' ') + ':00') : '',
            next_match_end_time:   nextEnd   ? (nextEnd.replace('T', ' ') + ':00')   : '',
        };
        const data = await api('PUT', '/admin/round/settings', body);
        // 单独保存配置统计全局开关
        await api('POST', '/admin/settings/config-stats', { enabled: configStatsEnabled });
        alert((data.message || '已保存') + '\n配置统计：' + (configStatsEnabled ? '已开启' : '已关闭'));
        loadRounds();
    } catch {}
}

async function clearAllClanConfigs() {
    if (!await customConfirm('确定要清空全部配置统计数据吗？\n\n此操作不可撤销！', '清空')) return;
    try {
        const data = await api('DELETE', '/admin/clan-configs');
        alert(data.message || '已清空');
        if (document.getElementById('tab-config-stats').classList.contains('active')) {
            loadConfigStats();
        }
    } catch {}
}

async function closeRound() {
    if (!await customConfirm('确定关闭当前轮次？\n\n关闭后，系统会自动冻结连续7轮未登记的用户！', '关闭')) return;
    try {
        const data = await api('POST', '/admin/round/close');
        let msg = data.message;
        if (data.frozen_count > 0) {
            msg += `\n\n已自动冻结 ${data.frozen_count} 个用户：${data.frozen_users.join(', ')}`;
        } else {
            msg += '\n\n本次无用户被冻结。';
        }
        alert(msg);
        loadRounds();
        loadUserList();
    } catch {}
}

async function loadUnknownClans() {
    try {
        const data = await api('GET', '/admin/unknown-clans', null, { silent: true });
        const el = document.getElementById('unknown-clans-list');
        if (!data.unknown_clans || data.unknown_clans.length === 0) {
            el.innerHTML = '<p class="empty-text">暂无陌生部落记录</p>';
            return;
        }
        let html = '<div class="table-wrapper"><table><tr><th>部落名称</th><th>标签</th><th>标签/备注</th><th>遭遇次数</th><th>最近出现</th></tr>';
        data.unknown_clans.forEach(c => {
            html += `<tr>
                <td>${escapeHTML(c.name)}</td>
                <td>${escapeHTML(c.code)}</td>
                <td>${escapeHTML(c.tags) || '-'}</td>
                <td><span class="badge" style="background:rgba(79,70,229,0.2);color:var(--primary)">${c.encounter_count}</span></td>
                <td>${formatDate(c.last_seen)}</td>
            </tr>`;
        });
        html += '</table></div>';
        el.innerHTML = html;
    } catch {}
}

// ========== 本轮部落统计 ==========
async function loadRoundClanStatus() {
    try {
        const data = await api('GET', '/admin/round/clan-status', null, { silent: true });
        const el = document.getElementById('round-clan-status');
        if (!data.current_round) {
            el.innerHTML = '<p class="empty-text">当前无进行中的轮次</p>';
            return;
        }

        let html = `<h3>第${data.current_round.round_no}轮部落匹配状态</h3>`;

        // 状态统计
        const statusCounts = {};
        data.clan_status.forEach(c => { statusCounts[c.status] = (statusCounts[c.status] || 0) + 1; });
        html += '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px">';
        const statusColors = {'匹配成功': 'var(--success)', '匹配到陌生部落': 'var(--warning)', '已登记未匹配': 'var(--primary)', '未登记': 'var(--danger)'};
        for (const [status, count] of Object.entries(statusCounts)) {
            html += `<span class="badge" style="background:${statusColors[status] || '#888'}20;color:${statusColors[status] || '#888'};font-size:0.88rem;padding:4px 12px">${status}: ${count}</span>`;
        }
        html += '</div>';

        // 部落列表
        html += '<div class="table-wrapper"><table><tr><th>部落</th><th>标签</th><th>联系人</th><th>积分</th><th>状态</th></tr>';
        data.clan_status.forEach(c => {
            const color = statusColors[c.status] || '#888';
            html += `<tr><td>${escapeHTML(c.name)}</td><td>${escapeHTML(c.code)}</td><td>${escapeHTML(c.contact) || '-'}</td><td>${c.score}</td><td><span style="color:${color};font-weight:600">${c.status}</span></td></tr>`;
        });
        html += '</table></div>';

        // 连续未登记警告
        if (data.inactive_clans && data.inactive_clans.length > 0) {
            html += '<h3 style="margin-top:16px;color:var(--danger)">⚠️ 连续多轮未登记部落</h3>';
            html += '<div class="table-wrapper"><table><tr><th>部落</th><th>标签</th><th>连续未登记轮数</th><th>统计轮数</th></tr>';
            data.inactive_clans.forEach(c => {
                html += `<tr><td>${escapeHTML(c.name)}</td><td>${escapeHTML(c.code)}</td><td class="score-negative">${c.inactive_rounds}</td><td>${c.total_rounds}</td></tr>`;
            });
            html += '</table></div>';
        }

        el.innerHTML = html;
    } catch {}
}

// ========== 配置必填提示 ==========
function updateConfigHint(currentRound) {
    const hint = document.getElementById('config-remark-hint');
    if (!hint) return;
    const required = currentRound && currentRound.config_required;
    if (required) {
        hint.innerHTML = '（<span style="color:var(--danger);font-weight:600">必填</span>，本轮要求填写出战配置）';
        document.getElementById('config-remark').style.borderColor = 'var(--danger)';
    } else {
        hint.innerHTML = '（选填，记录本次出战配置）';
        document.getElementById('config-remark').style.borderColor = 'var(--border)';
    }
}

// ========== 数据导入导出 ==========
async function exportData() {
    try {
        const token = localStorage.getItem('token');
        const res = await fetch('/api/admin/backup/export', {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (!res.ok) { alert('导出失败'); return; }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        const disposition = res.headers.get('content-disposition');
        let filename = 'clan_arena_backup.json';
        if (disposition) {
            const match = disposition.match(/filename="?([^"]+)"?/);
            if (match) filename = match[1];
        }
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
        alert('数据导出成功！');
    } catch (e) {
        alert('导出失败：' + e.message);
    }
}

async function importData() {
    const fileInput = document.getElementById('import-file');
    if (!fileInput.files.length) { alert('请先选择文件'); return; }
    if (!await customConfirm('⚠️ 导入将覆盖现有全部数据，此操作不可撤销！\n\n建议先导出备份后再导入。\n\n确认继续？', '继续导入')) return;
    if (!await customConfirm('再次确认：真的要覆盖所有数据吗？', '确认覆盖')) return;
    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    try {
        const token = localStorage.getItem('token');
        const res = await fetch('/api/admin/backup/import', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` },
            body: formData
        });
        const data = await res.json();
        if (!res.ok) { alert('导入失败：' + (data.detail || '未知错误')); return; }
        alert('数据导入成功！\n' + JSON.stringify(data.imported, null, 2));
        loadAdminData();
    } catch (e) {
        alert('导入失败：' + e.message);
    }
}

// ========== 管理员积分搜索 ==========
async function searchClanForAdjust() {
    const keyword = document.getElementById('adjust-search-keyword').value.trim();
    if (!keyword) { alert('请输入搜索关键词'); return; }
    try {
        const data = await api('POST', '/search-clan', { keyword });
        const el = document.getElementById('adjust-search-results');
        if (data.clans.length === 0) {
            el.innerHTML = '<p class="empty-text" style="font-size:0.8rem">未找到</p>';
            return;
        }
        let html = '';
        data.clans.forEach(c => {
            html += `<div class="search-result-item" style="padding:6px 10px;cursor:pointer" onclick="selectClanForAdjust(${c.id},'${escapeAttr(c.name)}',${c.score})">
                <span>🏛️ ${escapeHTML(c.name)}</span> <span style="color:var(--text-muted);font-size:0.8rem">(${c.code}) 积分:${c.score}</span>
            </div>`;
        });
        el.innerHTML = html;
    } catch {}
}

function selectClanForAdjust(clanId, clanName, score) {
    const sel = document.getElementById('adjust-clan-select');
    // 选中对应option
    for (let opt of sel.options) {
        if (parseInt(opt.value) === clanId) { opt.selected = true; break; }
    }
    document.getElementById('adjust-search-results').innerHTML = '';
    document.getElementById('adjust-search-keyword').value = '';
}

// ========== 管理员积分指南 ==========
async function loadScoreGuide() {
    try {
        const data = await api('GET', '/admin/score-guide', null, { silent: true });
        document.getElementById('score-guide-content').value = data.content || '';
    } catch {}
}

async function saveScoreGuide() {
    const content = document.getElementById('score-guide-content').value.trim();
    try {
        await api('PUT', '/admin/score-guide', { content });
        alert('积分操作指南已保存');
    } catch {}
}

// ========== 玩家陌生部落 ==========
async function loadPlayerUnknownClans() {
    try {
        const data = await api('GET', '/unknown-clans');
        const el = document.getElementById('player-unknown-clans');
        if (!data.unknown_clans || data.unknown_clans.length === 0) {
            el.innerHTML = '<p class="empty-text">暂无陌生部落记录</p>';
            return;
        }
        let html = '<div class="table-wrapper"><table><tr><th>部落名称</th><th>标签</th><th>备注</th><th>遭遇次数</th><th>最近出现</th></tr>';
        data.unknown_clans.forEach(c => {
            html += `<tr>
                <td>${escapeHTML(c.name)}</td>
                <td>${escapeHTML(c.code)}</td>
                <td>${escapeHTML(c.tags) || '-'}</td>
                <td><span class="badge" style="background:rgba(79,70,229,0.2);color:var(--primary)">${c.encounter_count}</span></td>
                <td>${formatDate(c.last_seen)}</td>
            </tr>`;
        });
        html += '</table></div>';
        el.innerHTML = html;
    } catch {}
}

// ========== 未登记匹配自动识别陌生部落 ==========
let unknownClansCache = null;
async function checkUnknownClan(inputCode) {
    if (!inputCode || inputCode.length < 2) {
        document.getElementById('unknown-clan-hint').innerHTML = '';
        return;
    }
    if (!unknownClansCache) {
        try {
            const data = await api('GET', '/unknown-clans');
            unknownClansCache = data.unknown_clans || [];
        } catch { return; }
    }
    const matches = unknownClansCache.filter(c =>
        c.code.toLowerCase().includes(inputCode.toLowerCase()) ||
        c.name.toLowerCase().includes(inputCode.toLowerCase())
    );
    const el = document.getElementById('unknown-clan-hint');
    if (matches.length > 0) {
        let html = '<div class="unknown-clan-match-hint">';
        matches.forEach(c => {
            html += `<div class="unknown-clan-match-item">
                <strong>🔍 已知陌生部落：${escapeHTML(c.name)}</strong><br>
                <span style="font-size:0.82rem">标签: ${escapeHTML(c.code)} | 遭遇: ${c.encounter_count}次 | 备注: ${escapeHTML(c.tags) || '-'}</span>
            </div>`;
        });
        html += '</div>';
        el.innerHTML = html;
    } else {
        el.innerHTML = '';
    }
}

function fillUnregName(name) {
    document.getElementById('unreg-clan-name').value = name;
}

// ========== 登记提醒弹窗 + 卡片切换 ==========
function maybeShowMatchPrompt(data) {
    // 条件：当前轮次进行中、用户绑定了部落、且未登记本轮
    if (!data.current_round || !data.clans || data.clans.length === 0) return;
    if (data.has_active_match) return;
    if (data.my_registration && data.my_registration.registered) return;

    const roundId = data.current_round.id;
    const flag = `match_prompt_shown_round_${roundId}`;
    if (!data.cancel_notice && sessionStorage.getItem(flag) === '1') return;

    sessionStorage.setItem(flag, '1');
    const modal = document.getElementById('match-prompt-modal');
    if (modal) modal.classList.add('active');
}

function closeMatchPrompt() {
    document.getElementById('match-prompt-modal').classList.remove('active');
}

function chooseMatchSuccess() {
    closeMatchPrompt();
    document.getElementById('match-success-card').style.display = '';
    document.getElementById('match-failed-card').style.display = 'none';
    document.getElementById('match-success-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function chooseMatchFailed() {
    closeMatchPrompt();
    document.getElementById('match-failed-card').style.display = '';
    document.getElementById('match-success-card').style.display = 'none';
    document.getElementById('match-failed-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function switchToFailed() {
    document.getElementById('match-success-card').style.display = 'none';
    document.getElementById('match-failed-card').style.display = '';
    document.getElementById('match-failed-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function switchToSuccess() {
    document.getElementById('match-failed-card').style.display = 'none';
    document.getElementById('match-success-card').style.display = '';
    document.getElementById('match-success-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ========== 配置统计（玩家端） ==========
let csState = { rows: [], target: null, clanId: null };

function renderConfigStatsCard(enabled) {
    const card = document.getElementById('config-stats-card');
    if (!card) return;
    if (!enabled || !myClans || myClans.length === 0) {
        card.style.display = 'none';
        return;
    }
    card.style.display = '';

    // 填充部落选择框
    const sel = document.getElementById('cs-clan-select');
    sel.innerHTML = myClans.map(c => `<option value="${c.id}">${escapeHTML(c.name)} (${escapeHTML(c.code)})</option>`).join('');
    sel.onchange = () => loadClanConfig(parseInt(sel.value));

    // 默认加载第一个部落的配置
    loadClanConfig(parseInt(sel.value));
}

async function loadClanConfig(clanId) {
    csState.clanId = clanId;
    try {
        const data = await api('GET', `/clan-config?clan_id=${clanId}`);
        csState.target = data.target_total;
        csState.rows = (data.items && data.items.length > 0)
            ? data.items.map(it => ({ th: it.th_level, num: it.member_count }))
            : [{ th: '', num: '' }];
        if (data.target_total) {
            const tr = document.querySelector(`input[name="cs-target"][value="${data.target_total}"]`);
            if (tr) tr.checked = true;
        } else {
            document.querySelectorAll('input[name="cs-target"]').forEach(r => r.checked = false);
        }
        renderConfigRows();
    } catch {}
}

function buildLevelOptions(selected) {
    let html = '<option value="">-</option>';
    for (let i = 0; i <= 100; i++) {
        html += `<option value="${i}"${i === selected ? ' selected' : ''}>${i} 本</option>`;
    }
    return html;
}

function buildCountOptions(selected) {
    let html = '<option value="">-</option>';
    for (let i = 0; i <= 40; i++) {
        html += `<option value="${i}"${i === selected ? ' selected' : ''}>${i} 人</option>`;
    }
    return html;
}

function renderConfigRows() {
    const wrap = document.getElementById('cs-rows');
    let html = '';
    csState.rows.forEach((row, idx) => {
        html += `<div class="cs-row" style="display:flex;gap:8px;align-items:center;padding:8px;border:1px solid var(--border);border-radius:6px;margin-bottom:6px">
            <span style="color:var(--text-muted);font-size:0.82rem">第 ${idx + 1} 栏</span>
            <label style="margin:0;font-size:0.82rem">大本营</label>
            <select onchange="updateConfigRow(${idx}, 'th', this.value)" style="width:auto">
                ${buildLevelOptions(row.th === '' ? null : Number(row.th))}
            </select>
            <label style="margin:0;font-size:0.82rem">人数</label>
            <select onchange="updateConfigRow(${idx}, 'num', this.value)" style="width:auto">
                ${buildCountOptions(row.num === '' ? null : Number(row.num))}
            </select>
            <button class="btn btn-sm btn-danger" onclick="removeConfigRow(${idx})" style="margin-left:auto">×</button>
        </div>`;
    });
    wrap.innerHTML = html;
    refreshConfigSummary();
}

function updateConfigRow(idx, field, value) {
    csState.rows[idx][field] = value === '' ? '' : Number(value);
    refreshConfigSummary();
}

function addConfigRow() {
    csState.rows.push({ th: '', num: '' });
    renderConfigRows();
}

function removeConfigRow(idx) {
    csState.rows.splice(idx, 1);
    if (csState.rows.length === 0) csState.rows.push({ th: '', num: '' });
    renderConfigRows();
}

function refreshConfigSummary() {
    const targetRadio = document.querySelector('input[name="cs-target"]:checked');
    const target = targetRadio ? Number(targetRadio.value) : null;
    csState.target = target;
    const sum = csState.rows.reduce((acc, r) => acc + (r.num === '' ? 0 : Number(r.num)), 0);

    // 等级重复检查
    const levels = csState.rows.filter(r => r.th !== '').map(r => Number(r.th));
    const dupes = levels.filter((v, i) => levels.indexOf(v) !== i);

    const summaryEl = document.getElementById('cs-summary');
    const errEl = document.getElementById('cs-error');
    const btn = document.getElementById('cs-save-btn');

    let summaryColor = 'var(--text-muted)';
    if (target !== null) {
        summaryColor = sum === target ? 'var(--success)' : 'var(--danger)';
    }
    summaryEl.innerHTML = `当前合计：<strong style="color:${summaryColor}">${sum}</strong> / ${target ?? '?'}`;

    let err = '';
    if (target === null) err = '请先选择总人数目标（40 或 50）';
    else if (dupes.length > 0) err = `大本营等级 ${[...new Set(dupes)].join(', ')} 不能重复出现`;
    else if (csState.rows.some(r => r.th === '' || r.num === '')) err = '每栏的大本营等级和人数都必须填写';
    else if (sum !== target) err = `合计 ${sum} 不等于目标 ${target}`;

    errEl.textContent = err;
    btn.disabled = !!err;
    btn.style.opacity = err ? '0.5' : '1';
    btn.style.cursor = err ? 'not-allowed' : 'pointer';
}

document.addEventListener('change', (e) => {
    if (e.target && e.target.name === 'cs-target') refreshConfigSummary();
});

async function saveClanConfig() {
    if (!csState.clanId) { alert('请选择部落'); return; }
    if (!csState.target) { alert('请选择总人数目标'); return; }
    const items = csState.rows.map(r => ({ th_level: Number(r.th), member_count: Number(r.num) }));
    try {
        const data = await api('POST', '/clan-config', {
            clan_id: csState.clanId,
            target_total: csState.target,
            items: items,
        });
        alert(data.message || '配置已保存');
    } catch {}
}

// ========== 配置统计（管理员端） ==========
async function loadConfigStats() {
    try {
        const setting = await api('GET', '/admin/settings/config-stats');
        const statusEl = document.getElementById('cs-admin-status');
        if (statusEl) {
            statusEl.textContent = setting.enabled
                ? '配置统计当前已开启，成员可在玩家端填写配置。'
                : '配置统计当前未开启，玩家端不会显示填写入口（已收集的旧数据仍然保留）。';
        }
    } catch {}

    try {
        const ov = await api('GET', '/admin/config-stats/overview');
        const el = document.getElementById('cs-overview-content');
        if (!ov.overview || ov.overview.length === 0) {
            el.innerHTML = '<p class="empty-text">暂无配置数据</p>';
        } else {
            let html = '<div class="table-wrapper"><table><tr><th>大本营等级</th><th>已填部落数</th><th>总人数</th><th>平均每部落人数</th></tr>';
            ov.overview.forEach(r => {
                html += `<tr>
                    <td><strong>${r.th_level} 本</strong></td>
                    <td>${r.clan_count}</td>
                    <td>${r.total_members}</td>
                    <td>${r.avg_per_clan}</td>
                </tr>`;
            });
            html += '</table></div>';
            el.innerHTML = html;
        }
    } catch {}

    try {
        const cl = await api('GET', '/admin/config-stats/clans');
        const detEl = document.getElementById('cs-clans-content');
        if (!cl.configs || cl.configs.length === 0) {
            detEl.innerHTML = '<p class="empty-text">暂无部落填写配置</p>';
        } else {
            let html = '<div class="table-wrapper"><table><tr><th>部落</th><th>总人数</th><th>配置</th><th>更新人</th><th>更新时间</th></tr>';
            cl.configs.forEach(c => {
                const cfg = (c.items || []).map(it => `${it.th_level}×${it.member_count}`).join(', ');
                html += `<tr>
                    <td><strong>${escapeHTML(c.clan_name)}</strong><br><span style="font-size:0.78rem;color:var(--text-muted)">${escapeHTML(c.clan_code)}</span></td>
                    <td>${c.total_members} / ${c.target_total}</td>
                    <td>${escapeHTML(cfg)}</td>
                    <td>${escapeHTML(c.updated_by_name) || '-'}</td>
                    <td>${formatDate(c.updated_at)}</td>
                </tr>`;
            });
            html += '</table></div>';
            detEl.innerHTML = html;
        }

        const missEl = document.getElementById('cs-missing-content');
        if (!cl.missing || cl.missing.length === 0) {
            missEl.innerHTML = '<p class="empty-text">所有部落均已填写配置 🎉</p>';
        } else {
            let mh = '<div class="table-wrapper"><table><tr><th>部落名称</th><th>标签</th></tr>';
            cl.missing.forEach(m => {
                mh += `<tr><td>${escapeHTML(m.name)}</td><td>${escapeHTML(m.code)}</td></tr>`;
            });
            mh += '</table></div>';
            missEl.innerHTML = mh;
        }
    } catch {}
}

// 自动登录
if (token) { loadDashboard(null); }
