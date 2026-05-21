/* ============================================================
   Price Agent — 前端应用控制器
   ============================================================ */

let currentSessionId = null;
let currentPlatform = 'jd';
let isLoading = false;
let sidebarCollapsed = false;
let currentProducts = [];
let currentImageUrl = null;
let currentImageFile = null;
let allSessions = [];  // 用于搜索过滤

const platformNames = { 'jd': '京东', 'taobao': '淘宝', 'pdd': '拼多多', 'suning': '苏宁' };

// ── 相对时间格式化 ────────────────────────────────────────────

function relativeTime(dateStr) {
    const now = new Date();
    const date = new Date(dateStr);
    const diff = now - date;
    const sec = Math.floor(diff / 1000);
    const min = Math.floor(sec / 60);
    const hour = Math.floor(min / 60);
    const day = Math.floor(hour / 24);

    if (sec < 60) return '刚刚';
    if (min < 60) return `${min}分钟前`;
    if (hour < 24) return `${hour}小时前`;
    if (day === 1) return '昨天';
    if (day < 7) return `${day}天前`;
    if (day < 30) return `${Math.floor(day / 7)}周前`;
    return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
}

// ── 快捷提问 ──────────────────────────────────────────────────

function quickAsk(question) {
    document.getElementById('userInput').value = question;
    document.getElementById('userInput').focus();
}

// ── Markdown 渲染 ─────────────────────────────────────────────

function renderMarkdown(text) {
    if (typeof marked === 'undefined') return escapeHtml(text);
    marked.setOptions({ breaks: true, gfm: true });
    let html = marked.parse(text);

    // 价格高亮：¥数字 和 数字元
    html = html.replace(/(¥\s*\d+(?:\.\d+)?)/g, '<span class="price-highlight">$1</span>');
    html = html.replace(/(\d+(?:\.\d+)?\s*元)/g, '<span class="price-highlight">$1</span>');

    // 平台名标记为 tag
    const platforms = ['京东', '淘宝', '拼多多', '苏宁'];
    platforms.forEach(p => {
        // 只在非链接、非 tag 中的平台名后追加 tag 标记
        const regex = new RegExp(`(?<!<)(${p})(?!>)`, 'g');
        html = html.replace(regex, '<span class="platform-tag" style="display:inline-flex;margin:0 2px;">$1</span>');
    });

    return html;
}

// ── 推理时间线渲染 ────────────────────────────────────────────

let reasoningNodes = [];

// L3: 模式追踪状态
let modeState = { mode: '', model: '' };               // 当前执行模式
let shoppingState = { phase: '', slots: {}, slotDefs: [] };  // M5 状态机
let planDAG = { steps: [], stepStatus: {}, model: '' };       // Plan-Execute DAG
let stepTimings = [];                                          // 时间瀑布数据

function addReasoningNode(type, title, detail, elapsedMs) {
    reasoningNodes.push({ type, title, detail, elapsedMs });
    renderTimeline();
}

function clearReasoning() {
    reasoningNodes = [];
    modeState = { mode: '', model: '' };
    shoppingState = { phase: '', slots: {}, slotDefs: [] };
    planDAG = { steps: [], stepStatus: {}, model: '' };
    stepTimings = [];
    renderTimeline();
}

const NODE_ICONS = {
    thought: '🤔', action: '⚡', observation: '👁',
    plan: '📋', warning: '⚠', error: '✗',
    phase: '🔄', slot: '📌',
};
const NODE_LABELS = {
    thought: 'Thought', action: 'Action', observation: 'Observation',
    plan: 'Plan', warning: 'Reflection', error: 'Error',
    phase: 'Phase', slot: 'Slot',
};
const NODE_COLORS = {
    thought: '#94A3B8', action: 'var(--brand)', observation: 'var(--success)',
    plan: '#8B5CF6', warning: 'var(--warning)', error: 'var(--error)',
    phase: '#3B82F6', slot: '#10B981',
};

function renderTimeline() {
    const container = document.getElementById('reasoningContent');
    if (reasoningNodes.length === 0) {
        container.innerHTML = '<p class="text-muted">发送问题后，推理过程将显示在这里...</p>';
        return;
    }

    let html = '';

    // L3: M5 购物状态机
    if (modeState.mode === 'shopping') {
        html += renderShoppingStepper();
    }

    // L3: Plan-Execute DAG
    if (modeState.mode === 'plan_execute' && planDAG.steps.length > 0) {
        html += renderPlanDAGView();
    }

    // 主时间线
    html += `<div class="timeline">${reasoningNodes.map((n, i) => {
        const icon = NODE_ICONS[n.type] || '●';
        const label = NODE_LABELS[n.type] || n.type;
        const color = NODE_COLORS[n.type] || '#94A3B8';
        const hasBody = n.detail && n.detail.length > 0;
        const bodyClass = hasBody ? 'expanded' : 'no-body';

        // L3: 模型徽章 — 对 plan_generated / react_round / synthesize 节点
        let modelBadge = '';
        if (n._model) {
            modelBadge = `<span class="model-badge" title="模型: ${escapeHtml(n._model)}">${escapeHtml(n._model)}</span>`;
        }

        return `
        <div class="timeline-node ${bodyClass}" id="timelineNode${i}">
            <div class="timeline-dot" style="background:${color}">${icon}</div>
            <div class="timeline-header" ${hasBody ? `onclick="toggleTimelineNode(${i})"` : ''}>
                <span class="timeline-title">
                    <span class="icon">${icon}</span>
                    ${label} · ${escapeHtml(n.title)} ${modelBadge}
                </span>
                <span class="timeline-meta">
                    ${n.elapsedMs ? `<span class="time-badge">${n.elapsedMs}ms</span>` : ''}
                    ${hasBody ? '<span class="timeline-chevron">▶</span>' : ''}
                </span>
            </div>
            ${hasBody ? `<div class="timeline-body">${escapeHtml(n.detail)}</div>` : ''}
        </div>
    `}).join('')}</div>`;

    // L3: 时间瀑布
    if (stepTimings.length > 0) {
        html += renderTimingWaterfall();
    }

    container.innerHTML = html;
}

// ── L3: M5 购物状态机 ──────────────────────────────────────────

const SHOPPING_PHASES = [
    { key: 'greeting', label: '问候', icon: '👋' },
    { key: 'slot_filling', label: '了解需求', icon: '📋' },
    { key: 'searching', label: '搜索商品', icon: '🔍' },
    { key: 'recommending', label: '推荐结果', icon: '📊' },
    { key: 'comparing', label: '商品对比', icon: '⚖' },
    { key: 'follow_up', label: '跟进', icon: '💬' },
];

function renderShoppingStepper() {
    const currentIdx = SHOPPING_PHASES.findIndex(p => p.key === shoppingState.phase);
    const filledSlots = Object.keys(shoppingState.slots).length;

    let stepperHTML = '<div class="l3-shopping-stepper">';
    stepperHTML += '<div class="l3-stepper-title">🛒 引导式购物</div>';
    stepperHTML += '<div class="l3-stepper-track">';

    SHOPPING_PHASES.forEach((p, i) => {
        let cls = 'l3-step';
        if (i < currentIdx) cls += ' done';
        else if (i === currentIdx) cls += ' active';
        stepperHTML += `
            <div class="${cls}">
                <div class="l3-step-dot">${p.icon}</div>
                <div class="l3-step-label">${p.label}</div>
            </div>`;
    });

    stepperHTML += '</div>';

    // 槽位进度
    if (filledSlots > 0) {
        const slotEntries = Object.entries(shoppingState.slots).map(([k, v]) =>
            `<span class="l3-slot-chip">${escapeHtml(k)}=${escapeHtml(String(v))}</span>`
        ).join('');
        stepperHTML += `<div class="l3-slot-bar">已收集: ${slotEntries} (${filledSlots} 项)</div>`;
    }

    stepperHTML += '</div>';
    return stepperHTML;
}

// ── L3: Plan-Execute DAG ────────────────────────────────────────

function renderPlanDAGView() {
    const steps = planDAG.steps;
    if (steps.length === 0) return '';

    // 分组：独立步骤 vs 依赖步骤
    const independent = steps.filter(s => !s.depends_on);
    const dependent = steps.filter(s => s.depends_on);

    let html = '<div class="l3-plan-dag">';
    html += `<div class="l3-dag-title">📋 执行计划 · ${steps.length} 步 <span class="model-badge">${escapeHtml(planDAG.model || '')}</span></div>`;

    // 独立组（可并行）
    if (independent.length > 0) {
        html += '<div class="l3-dag-group parallel">';
        html += `<div class="l3-dag-group-label">⚡ 并行执行 (${independent.length})</div>`;
        html += '<div class="l3-dag-nodes">';
        independent.forEach(s => {
            const st = planDAG.stepStatus[s.step] || 'pending';
            html += renderDAGStepNode(s, st);
        });
        html += '</div></div>';
    }

    // 依赖组（串行）
    if (dependent.length > 0) {
        html += '<div class="l3-dag-group serial">';
        html += `<div class="l3-dag-group-label">🔗 串行执行 (${dependent.length})</div>`;
        html += '<div class="l3-dag-nodes">';
        dependent.forEach((s, i) => {
            const st = planDAG.stepStatus[s.step] || 'pending';
            if (i > 0) {
                html += '<div class="l3-dag-arrow">↓</div>';
            }
            html += renderDAGStepNode(s, st);
        });
        html += '</div></div>';
    }

    html += '</div>';
    return html;
}

function renderDAGStepNode(step, status) {
    const statusIcon = { pending: '○', running: '◉', done: '✓', error: '✗' };
    const statusCls = 'l3-dag-node ' + status;
    const icon = statusIcon[status] || '○';
    const depends = step.depends_on ? ` ← Step ${step.depends_on}` : '';
    return `
        <div class="${statusCls}">
            <span class="l3-dag-status">${icon}</span>
            <span class="l3-dag-tool">${escapeHtml(step.tool || '')}</span>
            <span class="l3-dag-purpose">${escapeHtml(step.purpose || '')}</span>
            ${depends ? `<span class="l3-dag-dep">${escapeHtml(depends)}</span>` : ''}
        </div>`;
}

// ── L3: 时间瀑布 ───────────────────────────────────────────────

function renderTimingWaterfall() {
    const timings = stepTimings;
    if (timings.length === 0) return '';

    const maxElapsed = Math.max(...timings.map(t => t.elapsed), 1);

    let html = '<div class="l3-timing-waterfall">';
    html += '<div class="l3-timing-title">⏱ 步骤耗时</div>';

    timings.forEach(t => {
        const pct = Math.round((t.elapsed / maxElapsed) * 100);
        const barCls = t.success ? 'l3-timing-bar' : 'l3-timing-bar error';
        html += `
            <div class="l3-timing-row">
                <span class="l3-timing-label">Step ${t.step}</span>
                <div class="l3-timing-track">
                    <div class="${barCls}" style="width:${pct}%"></div>
                </div>
                <span class="l3-timing-val">${t.elapsed}ms</span>
            </div>`;
    });

    html += '</div>';
    return html;
}

function toggleTimelineNode(index) {
    const node = document.getElementById('timelineNode' + index);
    if (node) node.classList.toggle('expanded');
}

// ── 侧边栏 ────────────────────────────────────────────────────

function toggleSidebar() {
    sidebarCollapsed = !sidebarCollapsed;
    const sidebar = document.getElementById('sidebar');
    const chatArea = document.getElementById('chatArea');
    const rightPanel = document.getElementById('rightPanel');
    const icon = document.getElementById('sidebarToggleIcon');

    if (sidebarCollapsed) {
        sidebar.classList.add('collapsed');
        sidebar.classList.remove('col-md-3'); sidebar.classList.add('col-md-1');
        chatArea.classList.remove('col-md-6'); chatArea.classList.add('col-md-7');
        rightPanel.classList.remove('col-md-3'); rightPanel.classList.add('col-md-4');
        icon.textContent = '▶';
    } else {
        sidebar.classList.remove('collapsed');
        sidebar.classList.add('col-md-3'); sidebar.classList.remove('col-md-1');
        chatArea.classList.add('col-md-6'); chatArea.classList.remove('col-md-7');
        rightPanel.classList.add('col-md-3'); rightPanel.classList.remove('col-md-4');
        icon.textContent = '◀';
    }
}

function filterSessions() {
    const query = document.getElementById('sessionSearch').value.trim().toLowerCase();
    if (!query) { renderSessions(allSessions); return; }
    const filtered = allSessions.filter(s => {
        const title = (s.title || '').toLowerCase();
        return title.includes(query);
    });
    renderSessions(filtered);
}

// ── 会话 CRUD ─────────────────────────────────────────────────

function switchRightTab(tabId) {
    const tabEl = document.getElementById(tabId);
    if (tabEl) {
        bootstrap.Tab.getOrCreateInstance(tabEl).show();
    }
}

async function createNewSession() {
    try {
        const resp = await fetch('/api/sessions', { method: 'POST' });
        const data = await resp.json();
        if (data.success) {
            currentSessionId = data.session.session_id;
            loadSessions();
            clearChat();
            document.getElementById('sessionSearch').value = '';
            // 新建会话 → 默认显示商品管理 Tab
            switchRightTab('products-tab');
        }
    } catch (e) { console.error('创建会话失败:', e); }
}

async function loadSessions() {
    try {
        const resp = await fetch('/api/sessions');
        const data = await resp.json();
        if (data.success) {
            allSessions = data.sessions;
            renderSessions(data.sessions);
            if (data.sessions.length > 0 && !currentSessionId) {
                switchSession(data.sessions[0].session_id);
            }
        }
    } catch (e) { console.error('加载会话失败:', e); }
}

function renderSessions(sessions) {
    const container = document.getElementById('sessionList');
    container.innerHTML = sessions.map(s => {
        const title = s.title || s.session_id.substring(0, 8) + '...';
        const safeTitle = escapeHtml(title);
        const time = relativeTime(s.created_at);
        return `
            <div class="session-item ${s.session_id === currentSessionId ? 'active' : ''}"
                 onclick="switchSession('${s.session_id}')">
                <div class="session-info">
                    <div class="session-title" title="${safeTitle}">${safeTitle}</div>
                    <div class="session-date">${time}</div>
                </div>
                <button class="session-delete"
                        onclick="event.stopPropagation();deleteSession('${s.session_id}')"
                        title="删除">×</button>
            </div>
        `;
    }).join('');
}

async function switchSession(sessionId) {
    currentSessionId = sessionId;
    loadSessions();
    clearChat();
    // 切换历史会话 → 默认显示推理过程 Tab
    switchRightTab('reasoning-tab');
    try {
        const resp = await fetch(`/api/sessions/${sessionId}/messages`);
        const data = await resp.json();
        if (data.success) renderMessages(data.messages);
    } catch (e) { console.error('加载消息失败:', e); }
}

async function deleteSession(sessionId) {
    if (!confirm('确定要删除这个会话吗？')) return;
    try {
        await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
        if (currentSessionId === sessionId) { currentSessionId = null; clearChat(); }
        loadSessions();
    } catch (e) { console.error('删除会话失败:', e); }
}

// ── 聊天 ──────────────────────────────────────────────────────

function clearChat() {
    const container = document.getElementById('chatMessages');
    container.innerHTML = `
        <div class="welcome-state" id="welcomeState">
            <div class="welcome-logo">⚡</div>
            <div class="welcome-title">Price Agent</div>
            <div class="welcome-subtitle">智能识物比价助手 — 拍照搜同款、跨平台比价、帮你找到最具性价比的选择</div>
            <div class="welcome-actions">
                <div class="welcome-chip" onclick="quickAsk('iPhone 15 在哪个平台最便宜')">📱 比较最新 iPhone 价格</div>
                <div class="welcome-chip" onclick="quickAsk('小米14 黑色 256GB 各平台价格')">🔍 查找小米14 最优惠价</div>
                <div class="welcome-chip" onclick="quickAsk('我想买平板，帮我看看各平台有什么')">📋 浏览各平台平板电脑</div>
                <div class="welcome-chip" onclick="quickAsk('AirPods Pro 2 在哪买最划算')">🎧 查找 AirPods 最低价</div>
            </div>
        </div>`;
    clearReasoning();
}

function hideWelcome() {
    const welcome = document.getElementById('welcomeState');
    if (welcome) welcome.style.display = 'none';
}

function scrollToBottom() {
    const container = document.getElementById('chatMessages');
    requestAnimationFrame(() => { container.scrollTop = container.scrollHeight; });
}

function renderMessages(messages) {
    hideWelcome();
    const container = document.getElementById('chatMessages');
    container.innerHTML = messages.map(msg => {
        if (msg.role === 'assistant') {
            return `<div class="message assistant"><div class="message-content">${renderMarkdown(msg.content)}</div></div>`;
        }
        return `<div class="message user"><div class="message-content">${escapeHtml(msg.content)}</div></div>`;
    }).join('');
    scrollToBottom();
}

function addMessageToChat(role, content, imageUrl) {
    hideWelcome();
    const container = document.getElementById('chatMessages');
    const div = document.createElement('div');
    div.className = `message ${role}`;
    let inner = '';
    if (imageUrl) {
        inner += `<img src="${escapeHtml(imageUrl)}" class="message-image"
                       onclick="zoomMessageImage('${escapeHtml(imageUrl)}')" title="点击放大">`;
    }
    if (role === 'assistant') {
        inner += `<div class="message-content">${renderMarkdown(content)}</div>`;
    } else {
        inner += `<div class="message-content">${escapeHtml(content)}</div>`;
    }
    div.innerHTML = inner;
    container.appendChild(div);
    scrollToBottom();
}

function zoomMessageImage(url) {
    document.getElementById('imageZoomImg').src = url;
    new bootstrap.Modal(document.getElementById('imageZoomModal')).show();
}

// ── 发送消息 ──────────────────────────────────────────────────

async function sendMessage() {
    if (isLoading) return;
    const input = document.getElementById('userInput');
    const message = input.value.trim();
    if (!message) return;

    input.value = '';
    hideWelcome();
    if (currentImageUrl) {
        addMessageToChat('user', message, currentImageUrl);
    } else {
        addMessageToChat('user', message);
    }

    const imageUrlToSend = currentImageUrl;
    currentImageUrl = null;
    document.getElementById('imagePreviewArea').style.display = 'none';
    document.getElementById('imagePreviewThumb').src = '';
    isLoading = true;

    // 切换到推理 Tab
    const reasoningTab = document.getElementById('reasoning-tab');
    bootstrap.Tab.getOrCreateInstance(reasoningTab).show();
    clearReasoning();

    // Loading 占位
    const container = document.getElementById('chatMessages');
    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'message assistant';
    loadingDiv.id = 'loadingMessage';
    loadingDiv.innerHTML = `<div class="message-content" style="padding:12px 18px;">
        <div class="loading-dots"><span></span><span></span><span></span></div>
    </div>`;
    container.appendChild(loadingDiv);
    scrollToBottom();

    // 推理面板保持初始空状态，等待 SSE 事件到达后实时填充

    try {
        const resp = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message, session_id: currentSessionId, image_url: imageUrlToSend || '' })
        });

        if (!resp.ok) {
            throw new Error(`HTTP ${resp.status}`);
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let finalAnswer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            // SSE 数据行: "data: {json}\n\n"
            const lines = buffer.split('\n\n');
            // 最后一个可能不完整，保留到下次
            buffer = lines.pop() || '';

            for (const line of lines) {
                const trimmed = line.trim();
                if (!trimmed.startsWith('data: ')) continue;
                const jsonStr = trimmed.substring(6);
                try {
                    const ev = JSON.parse(jsonStr);
                    if (ev.type === 'session') {
                        currentSessionId = (ev.data && ev.data.session_id) || currentSessionId;
                    } else if (ev.type === 'done') {
                        finalAnswer = (ev.data && ev.data.answer) || '';
                    } else if (ev.type === 'error') {
                        reasoningNodes.push({ type: 'error', title: '服务端错误', detail: (ev.data && ev.data.message) || '', elapsedMs: null });
                        renderTimeline();
                    } else {
                        addTraceEvent(ev);
                    }
                } catch (e) {
                    // 跳过非 JSON 行
                }
            }
        }

        // 移除 loading
        document.getElementById('loadingMessage').remove();

        if (finalAnswer) {
            addMessageToChat('assistant', finalAnswer);
        }
        loadSessions();

    } catch (e) {
        console.error('发送失败:', e);
        document.getElementById('loadingMessage').remove();
        addMessageToChat('assistant', '抱歉，发生错误，请稍后重试。');
    }
    isLoading = false;
}

// ── 解析服务端推理输出 ────────────────────────────────────────

function parseReasoningOutput(raw) {
    reasoningNodes = [];
    const lines = raw.split('\n');
    let currentNode = null;

    for (const line of lines) {
        if (line.includes('Thought') || line.includes('思考')) {
            if (currentNode) reasoningNodes.push(currentNode);
            currentNode = { type: 'thought', title: 'Thought', detail: line, elapsedMs: null };
        } else if (line.includes('Action') || line.includes('调用工具')) {
            if (currentNode) reasoningNodes.push(currentNode);
            currentNode = { type: 'action', title: 'Action', detail: line, elapsedMs: null };
        } else if (line.includes('Observation') || line.includes('结果')) {
            if (currentNode) reasoningNodes.push(currentNode);
            currentNode = { type: 'observation', title: 'Observation', detail: line, elapsedMs: null };
        } else if (currentNode) {
            currentNode.detail += '\n' + line;
        }
    }
    if (currentNode) reasoningNodes.push(currentNode);
    renderTimeline();
}

// ── 结构化 Trace 渲染（L1/L2）───────────────────────────────────

function mapEventToNode(ev) {
    const d = ev.data || {};
    switch (ev.type) {
        case 'intent':
            return { type: 'thought', title: `意图: ${d.intent}`,
                     detail: `用户查询: ${d.query || ''}\n检测到 ${d.model_count || 0} 个已知型号`, elapsedMs: null };

        case 'mode_select': {
            const modeNames = { react: 'ReAct 循环', plan_execute: 'Plan-Execute 策略', shopping: '引导式购物' };
            return { type: 'plan', title: `模式: ${modeNames[d.mode] || d.mode}`,
                     detail: `原因: ${d.reason || ''}\n模型: ${d.model || ''}`, elapsedMs: null };
        }

        case 'plan_generated': {
            const stepsSummary = (d.steps || []).map(s =>
                `  Step ${s.step}: ${s.tool}${s.depends_on ? ` (依赖 Step ${s.depends_on})` : ''} — ${s.purpose || ''}`
            ).join('\n');
            return { type: 'plan', title: `计划: ${d.step_count} 步`,
                     detail: `模型: ${d.model || ''}\n${stepsSummary}`, elapsedMs: null, _model: d.model || '' };
        }

        case 'step_start':
            return { type: 'action', title: `Step ${d.step}: ${d.purpose || d.tool}`,
                     detail: `工具: ${d.tool}\n依赖: ${d.depends_on ? 'Step ' + d.depends_on : '无（并行）'}\n分组: ${d.group || ''}`, elapsedMs: null };

        case 'step_end': {
            const icon = d.success ? '✓' : '✗';
            return { type: d.success ? 'observation' : 'error',
                     title: `${icon} Step ${d.step} ${d.success ? '完成' : '失败'}`,
                     detail: `${d.summary || ''}${d.error ? '\n错误: ' + d.error : ''}`,
                     elapsedMs: d.elapsed_ms || null };
        }

        case 'react_round':
            return { type: 'thought', title: `Round ${d.round} · Thought`,
                     detail: d.thought || '', elapsedMs: null, _model: d.model || '' };

        case 'tool_call': {
            const argsStr = typeof d.args === 'object' ? JSON.stringify(d.args) : String(d.args || '');
            const where = d.step ? `Step ${d.step} Round ${d.round || 1}` : `Round ${d.round || ''}`;
            return { type: 'action', title: `${d.tool}`,
                     detail: `${where}\n参数: ${argsStr}`, elapsedMs: null };
        }

        case 'tool_result': {
            const resultIcon = d.found ? '✓' : (d.error ? '✗' : '⚠');
            const resultTitle = d.found ? `找到 ${d.match_count} 个匹配`
                : (d.error ? `错误: ${(d.error || '').substring(0, 60)}` : '未找到匹配');
            let resultDetail = d.summary || '';
            if (d.cheapest) {
                resultDetail += `\n最便宜: ${d.cheapest.platform_name || ''} ¥${d.cheapest.platform_price || ''}`;
            }
            return { type: d.found ? 'observation' : 'warning',
                     title: `${resultIcon} ${d.tool}: ${resultTitle}`,
                     detail: resultDetail, elapsedMs: null };
        }

        case 'reflection':
            return { type: 'warning', title: `反思: ${d.action}`,
                     detail: `工具: ${d.tool}\n重试次数: ${d.retry_count}\n决策: ${d.reasoning || ''}`, elapsedMs: null };

        case 'synthesize_start':
            return { type: 'plan', title: 'Phase 3: 综合分析',
                     detail: `模型: ${d.model || ''}`, elapsedMs: null, _model: d.model || '' };

        case 'synthesize_end':
            return { type: 'observation', title: '综合完成',
                     detail: `生成 ${d.char_count || 0} 字符\n模型: ${d.model || ''}`, elapsedMs: null };

        case 'shopping_phase':
            return { type: 'phase', title: `M5: ${d.from_phase} → ${d.phase}`,
                     detail: '', elapsedMs: null };

        case 'slot_filled':
            return { type: 'slot', title: `槽位: ${d.slot} = ${d.value}`,
                     detail: `阶段: ${d.phase || ''}`, elapsedMs: null };

        case 'error':
            return { type: 'error', title: `错误: ${d.context || ''}`,
                     detail: d.message || '', elapsedMs: null };

        default:
            return null;
    }
}

function addTraceEvent(ev) {
    const d = ev.data || {};

    // L3: 追踪模式状态
    if (ev.type === 'mode_select') {
        modeState = { mode: d.mode || '', model: d.model || '' };
    }
    // L3: 追踪 M5 购物状态
    if (ev.type === 'shopping_phase') {
        shoppingState.phase = d.phase || '';
    }
    if (ev.type === 'slot_filled') {
        shoppingState.slots[d.slot] = d.value;
    }
    // L3: 追踪 Plan-Execute DAG
    if (ev.type === 'plan_generated') {
        const steps = d.steps || [];
        planDAG = { steps: steps, stepStatus: {}, model: d.model || '' };
        steps.forEach(s => { planDAG.stepStatus[s.step] = 'pending'; });
    }
    if (ev.type === 'step_start') {
        if (planDAG.stepStatus[d.step] !== undefined) {
            planDAG.stepStatus[d.step] = 'running';
        }
    }
    if (ev.type === 'step_end') {
        if (planDAG.stepStatus[d.step] !== undefined) {
            planDAG.stepStatus[d.step] = d.success ? 'done' : 'error';
        }
        if (d.elapsed_ms) {
            stepTimings.push({ step: d.step, elapsed: d.elapsed_ms, success: d.success });
        }
    }

    const node = mapEventToNode(ev);
    if (node) {
        reasoningNodes.push(node);
        renderTimeline();
        // 滚动推理面板到底部
        const content = document.getElementById('reasoningContent');
        if (content) {
            requestAnimationFrame(() => { content.scrollTop = content.scrollHeight; });
        }
    }
}

function renderTrace(events) {
    reasoningNodes = [];
    for (const ev of events) {
        const node = mapEventToNode(ev);
        if (node) reasoningNodes.push(node);
    }
    renderTimeline();
}

// ── 图片上传 ──────────────────────────────────────────────────

function handleImageFile(event) {
    const file = event.target.files[0];
    if (!file) return;
    uploadImageFile(file);
    event.target.value = '';
}

async function uploadImageFile(file) {
    if (currentImageUrl) removeImage();
    const formData = new FormData();
    formData.append('image', file);
    try {
        const resp = await fetch('/api/upload-image', { method: 'POST', body: formData });
        const data = await resp.json();
        if (data.success) showImagePreview(data.image_url);
        else alert('图片上传失败: ' + (data.error || '未知错误'));
    } catch (e) { console.error('上传失败:', e); }
}

function showImagePreview(url) {
    currentImageUrl = url;
    document.getElementById('imagePreviewArea').style.display = 'block';
    document.getElementById('imagePreviewThumb').src = url;
}

function removeImage() {
    currentImageUrl = null;
    document.getElementById('imagePreviewArea').style.display = 'none';
    document.getElementById('imagePreviewThumb').src = '';
}

function zoomImage() {
    if (!currentImageUrl) return;
    document.getElementById('imageZoomImg').src = currentImageUrl;
    new bootstrap.Modal(document.getElementById('imageZoomModal')).show();
}

// ── 粘贴 / 拖拽 ───────────────────────────────────────────────

document.addEventListener('paste', function(e) {
    const items = e.clipboardData.items;
    for (let i = 0; i < items.length; i++) {
        if (items[i].type.startsWith('image/')) {
            e.preventDefault();
            uploadImageFile(items[i].getAsFile());
            return;
        }
    }
});

const chatInputEl = document.querySelector('.chat-input');
if (chatInputEl) {
    chatInputEl.addEventListener('dragover', function(e) { e.preventDefault(); this.classList.add('drag-over'); });
    chatInputEl.addEventListener('dragleave', function(e) { e.preventDefault(); this.classList.remove('drag-over'); });
    chatInputEl.addEventListener('drop', function(e) {
        e.preventDefault(); this.classList.remove('drag-over');
        const files = e.dataTransfer.files;
        if (files.length > 0 && files[0].type.startsWith('image/')) uploadImageFile(files[0]);
    });
}

// ── 商品管理 ──────────────────────────────────────────────────

let addProductCollapsed = true;
function toggleAddProductCollapse() {
    addProductCollapsed = !addProductCollapsed;
    document.getElementById('addProductSection').style.display = addProductCollapsed ? 'none' : 'block';
    document.getElementById('addProductToggleIcon').textContent = addProductCollapsed ? '▶' : '▼';
}

function handleKeyPress(event) { if (event.key === 'Enter') sendMessage(); }
function escapeHtml(text) { const div = document.createElement('div'); div.textContent = text; return div.innerHTML; }

function toggleFormGroup(id) {
    const body = document.getElementById(id);
    const icon = document.getElementById(id + 'Icon');
    if (!body || !icon) return;
    const show = body.style.display === 'none';
    body.style.display = show ? 'block' : 'none';
    icon.classList.toggle('open', show);
}

function toggleProductCard(cardId) {
    const expand = document.getElementById(cardId);
    if (expand) expand.classList.toggle('show');
}

function getUseCaseTags(selector) {
    return Array.from(document.querySelectorAll(selector + ':checked'))
        .map(cb => cb.value).filter(Boolean);
}

function setUseCaseTags(selector, tags) {
    const tagList = typeof tags === 'string' ? JSON.parse(tags || '[]') : (tags || []);
    document.querySelectorAll(selector).forEach(cb => {
        cb.checked = tagList.includes(cb.value);
    });
}

async function switchPlatform(platformId) {
    currentPlatform = platformId;
    document.getElementById('productListTitle').textContent = platformNames[platformId] + ' - 商品列表';
    document.getElementById('productSearch').value = '';
    await loadPlatformProducts(platformId);
}

async function loadPlatformProducts(platformId) {
    const container = document.getElementById('productList');
    try {
        container.innerHTML = '<p class="text-center small">加载中...</p>';
        const resp = await fetch(`/api/platforms/${platformId}/products`);
        const data = await resp.json();
        if (data.success) {
            currentProducts = data.products;
            renderPlatformProducts(currentProducts, platformId);
        } else { container.innerHTML = `<p class="text-danger small">${data.error}</p>`; }
    } catch (e) { container.innerHTML = '<p class="text-danger small">加载失败</p>'; }
}

function searchProducts() {
    const q = document.getElementById('productSearch').value.trim().toLowerCase();
    if (!q) { renderPlatformProducts(currentProducts, currentPlatform); return; }
    const filtered = currentProducts.filter(p =>
        (p.product_name && p.product_name.toLowerCase().includes(q)) ||
        (p.category && p.category.toLowerCase().includes(q)) ||
        (p.color && p.color.toLowerCase().includes(q)) ||
        (p.memory && p.memory.toLowerCase().includes(q))
    );
    renderPlatformProducts(filtered, currentPlatform);
}

function renderPlatformProducts(products, platformId) {
    const container = document.getElementById('productList');
    if (!products || products.length === 0) {
        container.innerHTML = '<p class="text-muted small text-center">暂无商品</p>'; return;
    }
    container.innerHTML = products.map((p, i) => {
        const cardId = 'card-' + platformId + '-' + i;
        const brand = p.brand || '';
        const tier = p.performance_tier || '';
        const tierLabel = tier === 'flagship' ? '旗舰' : tier === 'mid' ? '中端' : tier === 'budget' ? '入门' : '';
        const specs = [];
        if (p.processor) specs.push(p.processor);
        if (p.screen_size) specs.push(p.screen_size + '″');
        if (p.battery) specs.push(p.battery + 'mAh');
        const tags = (() => { try { return JSON.parse(p.use_case_tags || '[]'); } catch { return []; } })();
        return `
        <div class="product-item">
            <div class="product-card-main" onclick="toggleProductCard('${cardId}')">
                <div class="product-card-left">
                    <div class="product-card-title">
                        ${brand ? '<span class="brand-tag">' + escapeHtml(brand) + '</span>' : ''}${escapeHtml(p.product_name)}
                    </div>
                    <div class="product-card-meta">
                        <span class="price">¥${p.platform_price || p.price}</span>
                        ${tier ? '<span class="tier tier-' + tier + '">' + tierLabel + '</span>' : ''}
                        <span>${escapeHtml(p.category)}</span>
                        <span>库存${p.stock}</span>
                        ${!p.is_in_stock ? '<span style="color:var(--error)">缺货</span>' : ''}
                    </div>
                    ${specs.length ? '<div class="product-card-specs">' + specs.map(s => escapeHtml(s)).join(' · ') + '</div>' : ''}
                </div>
                <div class="product-card-actions" onclick="event.stopPropagation()">
                    <button class="btn-sm" onclick="editProduct(${p.id},'${platformId}')">编辑</button>
                    <button class="btn-sm btn-danger" onclick="deleteProduct(${p.id},'${platformId}')">删除</button>
                </div>
            </div>
            <div id="${cardId}" class="product-card-expand">
                ${tags.length ? '<div class="tags-row">' + tags.map(t => '<span class="tag-chip">' + escapeHtml(t) + '</span>').join('') + '</div>' : ''}
                <div>颜色: ${p.color || '-'} | 内存: ${p.memory || '-'} | 运费: ¥${p.shipping_fee || 0}</div>
                ${p.description ? '<div style="margin-top:4px;color:var(--text-secondary);font-style:italic;">' + escapeHtml(p.description) + '</div>' : ''}
            </div>
        </div>
        `;
    }).join('');
}

async function handleAddProduct(event) {
    event.preventDefault();
    const data = {
        product_name: document.getElementById('productName').value.trim(),
        brand: document.getElementById('productBrand').value.trim() || null,
        price: document.getElementById('productPrice').value,
        platform_price: document.getElementById('productPlatformPrice').value || null,
        stock: document.getElementById('productStock').value,
        category: document.getElementById('productCategory').value.trim(),
        processor: document.getElementById('productProcessor').value.trim() || null,
        processor_brand: document.getElementById('productProcessorBrand').value || null,
        performance_tier: document.getElementById('productPerformanceTier').value || null,
        color: document.getElementById('productColor').value.trim() || null,
        memory: document.getElementById('productMemory').value.trim() || null,
        screen_size: document.getElementById('productScreenSize').value || null,
        battery: document.getElementById('productBattery').value || null,
        shipping_fee: document.getElementById('productShippingFee').value || 0,
        is_in_stock: document.getElementById('productInStock').checked,
        use_case_tags: JSON.stringify(getUseCaseTags('.add-use-case')),
        description: document.getElementById('productDescription').value.trim() || null,
    };
    if (!data.product_name || !data.price || !data.stock || !data.category) { alert('请填写完整信息'); return; }
    try {
        const resp = await fetch(`/api/platforms/${currentPlatform}/products`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
        });
        const r = await resp.json();
        if (r.success) { alert('商品添加成功！'); document.getElementById('addProductForm').reset(); loadPlatformProducts(currentPlatform); }
        else alert('添加失败: ' + r.error);
    } catch (e) { console.error(e); }
}

let editProductModal = null;
async function editProduct(productId, platformId) {
    try {
        const resp = await fetch(`/api/platforms/${platformId}/products`);
        const data = await resp.json();
        if (!data.success) { alert('获取失败'); return; }
        const p = data.products.find(x => x.id === productId);
        if (!p) { alert('商品不存在'); return; }
        document.getElementById('editProductId').value = productId;
        document.getElementById('editProductPlatformId').value = platformId;
        // 基础信息
        document.getElementById('editProductName').value = p.product_name;
        document.getElementById('editProductBrand').value = p.brand || '';
        document.getElementById('editProductCategory').value = p.category;
        document.getElementById('editProductPrice').value = p.price;
        document.getElementById('editProductPlatformPrice').value = p.platform_price || '';
        document.getElementById('editProductStock').value = p.stock;
        // 规格参数
        document.getElementById('editProductProcessor').value = p.processor || '';
        document.getElementById('editProductProcessorBrand').value = p.processor_brand || '';
        document.getElementById('editProductPerformanceTier').value = p.performance_tier || '';
        document.getElementById('editProductColor').value = p.color || '';
        document.getElementById('editProductMemory').value = p.memory || '';
        document.getElementById('editProductScreenSize').value = p.screen_size || '';
        document.getElementById('editProductBattery').value = p.battery || '';
        document.getElementById('editProductShippingFee').value = p.shipping_fee || 0;
        document.getElementById('editProductInStock').checked = p.is_in_stock;
        // 标签与描述
        setUseCaseTags('.edit-use-case', p.use_case_tags || '[]');
        document.getElementById('editProductDescription').value = p.description || '';
        if (!editProductModal) editProductModal = new bootstrap.Modal(document.getElementById('editProductModal'));
        editProductModal.show();
    } catch (e) { console.error(e); }
}

async function saveEditProduct() {
    const id = parseInt(document.getElementById('editProductId').value);
    const platformId = document.getElementById('editProductPlatformId').value;
    const data = {
        product_name: document.getElementById('editProductName').value.trim(),
        brand: document.getElementById('editProductBrand').value.trim() || null,
        price: document.getElementById('editProductPrice').value || null,
        platform_price: document.getElementById('editProductPlatformPrice').value || null,
        stock: document.getElementById('editProductStock').value || null,
        category: document.getElementById('editProductCategory').value.trim() || null,
        processor: document.getElementById('editProductProcessor').value.trim() || null,
        processor_brand: document.getElementById('editProductProcessorBrand').value || null,
        performance_tier: document.getElementById('editProductPerformanceTier').value || null,
        color: document.getElementById('editProductColor').value.trim() || null,
        memory: document.getElementById('editProductMemory').value.trim() || null,
        screen_size: document.getElementById('editProductScreenSize').value || null,
        battery: document.getElementById('editProductBattery').value || null,
        shipping_fee: document.getElementById('editProductShippingFee').value || null,
        is_in_stock: document.getElementById('editProductInStock').checked,
        use_case_tags: JSON.stringify(getUseCaseTags('.edit-use-case')),
        description: document.getElementById('editProductDescription').value.trim() || null,
    };
    try {
        const resp = await fetch(`/api/platforms/${platformId}/products/${id}`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
        });
        const r = await resp.json();
        if (r.success) { alert('商品更新成功！'); editProductModal.hide(); loadPlatformProducts(platformId); }
        else alert('更新失败: ' + r.error);
    } catch (e) { console.error(e); }
}

async function deleteProduct(productId, platformId) {
    if (!confirm('确定要删除这个商品吗？')) return;
    try {
        const resp = await fetch(`/api/platforms/${platformId}/products/${productId}`, { method: 'DELETE' });
        const data = await resp.json();
        if (data.success) { alert('商品删除成功！'); loadPlatformProducts(platformId); }
        else alert('删除失败: ' + data.error);
    } catch (e) { console.error(e); }
}

// ── 多平台比价 ────────────────────────────────────────────────

async function comparePrice() {
    const name = document.getElementById('compareProductName').value.trim();
    if (!name) { alert('请输入商品名称'); return; }
    const resultDiv = document.getElementById('compareResult');
    resultDiv.innerHTML = '<p class="small"><span class="loading-dots"><span></span><span></span><span></span></span></p>';
    try {
        const resp = await fetch('/api/multi-platform/compare', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ product_name: name })
        });
        const data = await resp.json();
        resultDiv.textContent = data.success ? data.formatted_text : '查询失败: ' + data.error;
    } catch (e) { resultDiv.innerHTML = '<p class="text-danger small">查询失败</p>'; }
}

function quickCompare(name) {
    document.getElementById('compareProductName').value = name;
    comparePrice();
}

async function loadQuickProducts() {
    try {
        const resp = await fetch('/api/multi-platform/products');
        const data = await resp.json();
        if (data.success) {
            const seen = new Set();
            const products = [];
            for (const pid in data.data.results) {
                for (const p of data.data.results[pid].products) {
                    if (!seen.has(p.product_name)) { seen.add(p.product_name); products.push(p); }
                }
            }
            const container = document.getElementById('quickProducts');
            const names = [...new Set(products.map(p => p.product_name))].slice(0, 8);
            container.innerHTML = names.map(n =>
                `<span class="quick-product-tag" onclick="quickCompare('${escapeHtml(n)}')">${escapeHtml(n)}</span>`
            ).join('');
        }
    } catch (e) { console.error(e); }
}

// ══════════════════════════════════════════════════════════════════
// L4: 调试仪表盘 — Trace 回放与性能分析
// ══════════════════════════════════════════════════════════════════

let playbackTrace = null;       // 当前回放的 trace 数据
let playbackIndex = 0;          // 当前回放位置
let playbackTimer = null;       // 自动播放定时器
let playbackSpeed = 1000;       // 播放间隔 ms

async function loadTraceList() {
    const container = document.getElementById('traceList');
    container.innerHTML = '<p class="small">加载中...</p>';

    // 按当前会话过滤 trace
    let url = '/api/traces';
    if (currentSessionId) {
        url += '?session_id=' + encodeURIComponent(currentSessionId);
    }

    try {
        const resp = await fetch(url);
        const data = await resp.json();
        if (!data.success || !data.traces || data.traces.length === 0) {
            const hint = currentSessionId
                ? '当前会话暂无 Trace。发送一条消息后会自动保存。'
                : '请先选择一个会话。';
            container.innerHTML = `<p class="text-muted small">${hint}</p>`;
            return;
        }
        container.innerHTML = data.traces.map((t, i) => `
            <div class="trace-item" onclick="loadTraceForPlayback('${escapeHtml(t.filename)}')">
                <div class="trace-item-header">
                    <span class="trace-item-query">${escapeHtml(t.query || '(空查询)')}</span>
                    <span class="trace-item-meta">${t.event_count} 事件 · ${t.timestamp}</span>
                </div>
                <div class="trace-item-preview">${escapeHtml(t.answer_preview || '')}</div>
                <button class="trace-item-delete"
                    onclick="event.stopPropagation();deleteTraceFile('${escapeHtml(t.filename)}')">×</button>
            </div>
        `).join('');
    } catch (e) {
        container.innerHTML = '<p class="text-danger small">加载失败</p>';
    }
}

function stopPlayback() {
    if (playbackTimer) { clearInterval(playbackTimer); playbackTimer = null; }
}

function closePlayback() {
    stopPlayback();
    document.getElementById('tracePlaybackSection').style.display = 'none';
    document.getElementById('traceListSection').style.display = 'block';
}

async function loadTraceForPlayback(filename) {
    try {
        const resp = await fetch(`/api/traces/${encodeURIComponent(filename)}`);
        const data = await resp.json();
        if (!data.success) { alert('加载失败: ' + data.error); return; }

        playbackTrace = data.trace;
        playbackIndex = -1;
        stopPlayback();

        document.getElementById('traceListSection').style.display = 'none';
        document.getElementById('tracePlaybackSection').style.display = 'block';
        document.getElementById('playbackQuery').textContent =
            (playbackTrace.meta && playbackTrace.meta.query) || filename;

        // 渲染性能摘要
        renderPerformanceSummary(playbackTrace.events || []);

        // 渲染完整时间线
        renderPlaybackTimeline(-1);
        updatePlaybackCounter();

        // 切换到 Debug Tab
        const debugTab = document.getElementById('debug-tab');
        if (debugTab) bootstrap.Tab.getOrCreateInstance(debugTab).show();

    } catch (e) {
        console.error('加载 trace 失败:', e);
    }
}

function renderPlaybackTimeline(activeIdx) {
    const container = document.getElementById('playbackTimeline');
    const events = playbackTrace ? (playbackTrace.events || []) : [];

    if (events.length === 0) {
        container.innerHTML = '<p class="text-muted small">无事件</p>';
        return;
    }

    container.innerHTML = events.map((ev, i) => {
        const node = mapEventToNode(ev);
        if (!node) return '';
        const isActive = i === activeIdx;
        const isPast = i < activeIdx;
        const dotColor = isActive ? 'var(--brand)' : (isPast ? 'var(--success)' : '#94A3B8');
        const rowCls = isActive ? 'pb-row active' : (isPast ? 'pb-row past' : 'pb-row');
        const icon = NODE_ICONS[node.type] || '●';
        const label = NODE_LABELS[node.type] || node.type;

        return `
            <div class="${rowCls}" id="pbRow${i}">
                <div class="pb-dot" style="background:${dotColor}">${icon}</div>
                <div class="pb-info">
                    <span class="pb-title">${label} · ${escapeHtml(node.title)}</span>
                    ${isActive ? '<span class="pb-active-marker">◀ 当前</span>' : ''}
                </div>
                <span class="pb-meta">${node.elapsedMs ? node.elapsedMs + 'ms' : ''}</span>
            </div>`;
    }).join('');

    // 滚动到当前
    if (activeIdx >= 0) {
        const row = document.getElementById('pbRow' + activeIdx);
        if (row) row.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

function updatePlaybackCounter() {
    const total = playbackTrace ? (playbackTrace.events || []).length : 0;
    document.getElementById('playbackCounter').textContent =
        `${Math.max(0, playbackIndex + 1)} / ${total}`;

    const btn = document.getElementById('playbackPlayBtn');
    if (btn) btn.textContent = playbackTimer ? '⏸' : '▶';
}

function playbackToggle() {
    if (playbackTimer) {
        stopPlayback();
        updatePlaybackCounter();
        return;
    }
    // 如果已播完，从头开始
    const total = playbackTrace ? (playbackTrace.events || []).length : 0;
    if (playbackIndex >= total - 1) playbackIndex = -1;

    playbackTimer = setInterval(() => {
        const total = playbackTrace ? (playbackTrace.events || []).length : 0;
        if (playbackIndex >= total - 1) {
            stopPlayback();
            updatePlaybackCounter();
            return;
        }
        playbackStep(1);
    }, playbackSpeed);
    updatePlaybackCounter();
}

function playbackStep(direction) {
    if (!playbackTrace) return;
    const events = playbackTrace.events || [];
    if (events.length === 0) return;

    playbackIndex = Math.max(-1, Math.min(events.length - 1, playbackIndex + direction));
    renderPlaybackTimeline(playbackIndex);
    updatePlaybackCounter();
}

function playbackSetSpeed(speed) {
    playbackSpeed = parseInt(speed) || 1000;
    if (playbackTimer) {
        stopPlayback();
        playbackToggle();  // 以新速度重启
    }
}

function renderPerformanceSummary(events) {
    const container = document.getElementById('playbackPerf');

    // 计算各阶段耗时
    let planTime = 0, toolTime = 0, synthTime = 0, totalEvents = events.length;
    let eventTypes = {};
    let modelUsage = {};

    events.forEach(ev => {
        const d = ev.data || {};
        // 事件类型统计
        eventTypes[ev.type] = (eventTypes[ev.type] || 0) + 1;

        // 模型使用统计
        if (d.model) {
            modelUsage[d.model] = (modelUsage[d.model] || 0) + 1;
        }

        // 耗时累计
        if (ev.type === 'step_end' && d.elapsed_ms) {
            toolTime += d.elapsed_ms;
        }
    });

    // 从时间戳估算 LLM 时间
    if (events.length >= 2) {
        const firstTs = events[0].ts || 0;
        const lastTs = events[events.length - 1].ts || 0;
        const totalWall = Math.round((lastTs - firstTs) * 1000);
        if (totalWall > 0 && toolTime < totalWall) {
            planTime = Math.round((totalWall - toolTime) * 0.3);
            synthTime = Math.round((totalWall - toolTime) * 0.7);
        }
    }

    const modelList = Object.entries(modelUsage).map(([m, c]) =>
        `<span class="perf-chip">${escapeHtml(m)} (${c})</span>`
    ).join('') || '<span class="text-muted">无</span>';

    const typeList = Object.entries(eventTypes).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([t, c]) =>
        `<span class="perf-chip">${escapeHtml(t)}: ${c}</span>`
    ).join('');

    container.innerHTML = `
        <div class="perf-card">
            <div class="perf-title">📊 性能摘要</div>
            <div class="perf-grid">
                <div class="perf-item">
                    <span class="perf-label">总事件数</span>
                    <span class="perf-value">${totalEvents}</span>
                </div>
                <div class="perf-item">
                    <span class="perf-label">工具耗时</span>
                    <span class="perf-value">${toolTime}ms</span>
                </div>
                <div class="perf-item">
                    <span class="perf-label">事件类型</span>
                    <span class="perf-value small">${typeList}</span>
                </div>
                <div class="perf-item">
                    <span class="perf-label">使用模型</span>
                    <span class="perf-value small">${modelList}</span>
                </div>
            </div>
        </div>`;
}

async function deleteTraceFile(filename) {
    if (!confirm('删除这条 Trace？')) return;
    try {
        await fetch(`/api/traces/${encodeURIComponent(filename)}`, { method: 'DELETE' });
        loadTraceList();
    } catch (e) {
        console.error('删除失败:', e);
    }
}

async function clearAllTraces() {
    if (!confirm('确定要删除所有 Trace 文件？此操作不可撤销。')) return;
    try {
        const resp = await fetch('/api/traces');
        const data = await resp.json();
        if (data.traces) {
            for (const t of data.traces) {
                await fetch(`/api/traces/${encodeURIComponent(t.filename)}`, { method: 'DELETE' });
            }
        }
        loadTraceList();
    } catch (e) {
        console.error('清空失败:', e);
    }
}

// ── 初始化 ────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    loadSessions();
    loadQuickProducts();
    loadPlatformProducts('jd');
    document.getElementById('addProductForm').addEventListener('submit', handleAddProduct);
    document.getElementById('saveEditProductBtn').addEventListener('click', saveEditProduct);

    // L4: Debug Tab 每次切换时自动刷新 trace 列表
    const debugTab = document.getElementById('debug-tab');
    if (debugTab) {
        debugTab.addEventListener('shown.bs.tab', () => {
            loadTraceList();
        });
    }
});
