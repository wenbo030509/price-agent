/**
 * Trace 数据处理工坊 — 步骤向导交互
 * 功能: Trace选择 | 格式提取+编辑 | 质量评估+LLM Judge+人工审核 | 导出
 */

// ── 全局状态 ──
const state = {
    currentStep: 1,
    allTraces: [],
    filteredTraces: [],
    selectedFilenames: new Set(),
    samples: [],
    filterThreshold: 60,
    requireTools: false,
    requireNoError: false,
    currentSampleIdx: 0,
    // Pagination
    currentPage: 1,
    pageSize: 50,
    expandedTrace: null,
    // Review
    reviews: {},       // {filename/index: {status: 'pending'|'approved'|'rejected', notes: ''}}
    reviewFilter: 'all',
    // LLM Judge
    judgeResults: {},  // {index: {overall_score, dimensions, ...}}
    judgeLoading: false,
    // Edit
    editSampleIdx: -1,
    editBackup: null,
};

// ── 初始化 ──
document.addEventListener('DOMContentLoaded', () => {
    loadTraces();
});

// ── Step 导航 ──
function showStep(step) {
    state.currentStep = step;
    for (let i = 1; i <= 4; i++) {
        const content = document.getElementById('step' + i + 'Content');
        const indicator = document.getElementById('stepInd' + i);
        if (content) content.style.display = (i === step) ? '' : 'none';
        if (indicator) {
            indicator.classList.remove('active', 'done');
            if (i < step) indicator.classList.add('done');
            if (i === step) indicator.classList.add('active');
        }
    }
    for (let i = 1; i <= 3; i++) {
        const conn = document.getElementById('stepConn' + i);
        if (conn) conn.classList.toggle('done', i < step);
    }
}

function goToStep1() { showStep(1); }
function goToStep2() {
    if (state.samples.length === 0) {
        if (state.selectedFilenames.size === 0) return;
        extractSamples();
        return;
    }
    showStep(2);
    renderCurrentSample();
}
function goToStep3() { showStep(3); renderQualityView(); }
function goToStep4() { showStep(4); renderExportView(); }

// ══════════════════════════════════════════════════════════
// Step 1: Trace 选择
// ══════════════════════════════════════════════════════════

async function loadTraces() {
    try {
        const resp = await fetch('/api/training/traces');
        const data = await resp.json();
        if (!data.success) throw new Error(data.error);
        state.allTraces = data.traces;
        document.getElementById('traceCountLabel').textContent = `共 ${data.total} 条 Trace`;
        applyFilters();
    } catch (err) {
        document.getElementById('traceTableBody').innerHTML =
            `<tr><td colspan="6"><div class="empty-state"><div class="icon">❌</div><p>加载失败: ${err.message}</p></div></td></tr>`;
    }
}

function applyFilters() {
    const intent = document.getElementById('filterIntent').value;
    const mode = document.getElementById('filterMode').value;
    const tools = document.getElementById('filterTools').value;
    state.filteredTraces = state.allTraces.filter(t => {
        if (intent && t.intent !== intent) return false;
        if (mode && t.mode !== mode) return false;
        if (tools !== '' && t.tool_count < parseInt(tools)) return false;
        return true;
    });
    state.currentPage = 1;
    state.expandedTrace = null;
    document.getElementById('selectAllCheckbox').checked = false;
    renderTraceTable();
    renderPagination();
    updateSelectionSummary();
}

function renderTraceTable() {
    const tbody = document.getElementById('traceTableBody');
    const start = (state.currentPage - 1) * state.pageSize;
    const pageTraces = state.filteredTraces.slice(start, start + state.pageSize);
    if (pageTraces.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6"><div class="empty-state"><div class="icon">📭</div><p>无匹配 Trace</p></div></td></tr>';
        return;
    }
    const intentLabels = {comparison:'比价', shopping:'购物', recommendation:'推荐', query:'查询'};
    const modeLabels = {react:'ReAct', plan_execute:'Plan-Exec', shopping:'Shopping'};
    let html = '';
    for (const t of pageTraces) {
        const sel = state.selectedFilenames.has(t.filename) ? ' selected' : '';
        const expanded = state.expandedTrace === t.filename;
        const ts = t.timestamp.replace(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})$/, '$1-$2-$3 $4:$5:$6');
        html += `<tr class="${sel}" data-filename="${t.filename}" onclick="toggleTraceRow('${t.filename}', event)">
            <td class="tc-checkbox" onclick="event.stopPropagation();">
                <input type="checkbox" ${sel ? 'checked' : ''} onchange="toggleTrace('${t.filename}')">
            </td>
            <td class="tc-timestamp">${ts}</td>
            <td class="tc-query" title="${escAttr(t.query)}">${escHtml(t.query)}</td>
            <td><span class="badge badge-intent">${intentLabels[t.intent]||t.intent||'?'}</span></td>
            <td><span class="badge badge-mode">${modeLabels[t.mode]||t.mode||'?'}</span></td>
            <td><span class="badge ${t.tool_count > 0 ? 'badge-tools' : 'badge-no-tools'}">${t.tool_count} 工具</span></td>
        </tr>`;
        if (expanded) {
            html += `<tr class="trace-detail" onclick="event.stopPropagation()"><td colspan="6">
                <div class="detail-grid">
                    <div class="detail-item"><span class="detail-label">Session ID</span><span class="detail-value" style="font-family:'JetBrains Mono',monospace;font-size:11px;">${escHtml(t.session_id||'-')}</span></div>
                    <div class="detail-item"><span class="detail-label">统计</span><span class="detail-value">${intentLabels[t.intent]||'?'} / ${modeLabels[t.mode]||'?'} | ${t.round_count}轮 | ${t.event_count}事件</span></div>
                    <div class="detail-answer"><span class="detail-label">回答预览</span><div style="margin-top:4px;">${escHtml(t.answer_preview||t.query)}</div></div>
                </div>
            </td></tr>`;
        }
    }
    tbody.innerHTML = html;
}

function toggleTraceRow(filename, event) {
    if (event.target.tagName === 'INPUT') return;
    state.expandedTrace = (state.expandedTrace === filename) ? null : filename;
    renderTraceTable();
}

function renderPagination() {
    const totalPages = Math.ceil(state.filteredTraces.length / state.pageSize);
    const bar = document.getElementById('paginationBar');
    if (totalPages <= 1) { bar.innerHTML = ''; return; }
    let html = `<button onclick="goToPage(${state.currentPage - 1})" ${state.currentPage <= 1 ? 'disabled' : ''}>← 上一页</button>`;
    const maxButtons = 7;
    let sp = Math.max(1, state.currentPage - 3), ep = Math.min(totalPages, sp + maxButtons - 1);
    if (ep - sp < maxButtons - 1) sp = Math.max(1, ep - maxButtons + 1);
    if (sp > 1) { html += `<button onclick="goToPage(1)">1</button>`; if (sp > 2) html += `<span class="page-info">...</span>`; }
    for (let i = sp; i <= ep; i++) html += `<button onclick="goToPage(${i})" class="${i === state.currentPage ? 'active' : ''}">${i}</button>`;
    if (ep < totalPages) { if (ep < totalPages - 1) html += `<span class="page-info">...</span>`; html += `<button onclick="goToPage(${totalPages})">${totalPages}</button>`; }
    html += `<button onclick="goToPage(${state.currentPage + 1})" ${state.currentPage >= totalPages ? 'disabled' : ''}>下一页 →</button>`;
    html += `<span class="page-info">共 ${state.filteredTraces.length} 条</span>`;
    bar.innerHTML = html;
}

function goToPage(page) {
    const totalPages = Math.ceil(state.filteredTraces.length / state.pageSize);
    if (page < 1 || page > totalPages) return;
    state.currentPage = page; state.expandedTrace = null;
    document.getElementById('selectAllCheckbox').checked = false;
    renderTraceTable(); renderPagination();
}

function toggleSelectAll(checked) {
    const start = (state.currentPage - 1) * state.pageSize;
    const pageTraces = state.filteredTraces.slice(start, start + state.pageSize);
    for (const t of pageTraces) {
        if (checked) state.selectedFilenames.add(t.filename);
        else state.selectedFilenames.delete(t.filename);
    }
    renderTraceTable(); updateSelectionSummary();
    document.getElementById('btnToStep2').disabled = state.selectedFilenames.size === 0;
}

function toggleTrace(filename) {
    if (state.selectedFilenames.has(filename)) state.selectedFilenames.delete(filename);
    else state.selectedFilenames.add(filename);
    renderTraceTable(); updateSelectionSummary();
    const start = (state.currentPage - 1) * state.pageSize;
    const pageTraces = state.filteredTraces.slice(start, start + state.pageSize);
    const allSel = pageTraces.length > 0 && pageTraces.every(t => state.selectedFilenames.has(t.filename));
    document.getElementById('selectAllCheckbox').checked = allSel;
    document.getElementById('btnToStep2').disabled = state.selectedFilenames.size === 0;
}

function selectAllTraces() {
    state.filteredTraces.forEach(t => state.selectedFilenames.add(t.filename));
    document.getElementById('selectAllCheckbox').checked = true;
    renderTraceTable(); renderPagination(); updateSelectionSummary();
    document.getElementById('btnToStep2').disabled = state.selectedFilenames.size === 0;
}

function deselectAllTraces() {
    state.filteredTraces.forEach(t => state.selectedFilenames.delete(t.filename));
    document.getElementById('selectAllCheckbox').checked = false;
    renderTraceTable(); renderPagination(); updateSelectionSummary();
    document.getElementById('btnToStep2').disabled = true;
}

function updateSelectionSummary() {
    document.getElementById('selectedCount').textContent = state.selectedFilenames.size;
    document.getElementById('estimatedSamples').textContent = state.selectedFilenames.size;
}

// ══════════════════════════════════════════════════════════
// Step 2: 格式提取 + JSONL 编辑
// ══════════════════════════════════════════════════════════

async function extractSamples() {
    showStep(2);
    document.getElementById('traceEventPreview').textContent = '提取中...';
    document.getElementById('jsonlPreview').textContent = '提取中...';
    try {
        const resp = await fetch('/api/training/extract', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({filenames: Array.from(state.selectedFilenames)}),
        });
        const data = await resp.json();
        if (!data.success) throw new Error(data.error);
        state.samples = data.samples;
        state.currentSampleIdx = 0;
        // Init reviews and judge results
        state.reviews = {};
        state.judgeResults = {};
        const llmInline = document.getElementById('sbLLMInline');
        if (llmInline) llmInline.style.display = 'none';
        const judgeStatusStep2 = document.getElementById('judgeStatusStep2');
        if (judgeStatusStep2) judgeStatusStep2.style.display = 'none';
        renderCurrentSample();
    } catch (err) {
        document.getElementById('traceEventPreview').textContent = '提取失败';
        document.getElementById('jsonlPreview').textContent = err.message;
    }
}

function renderCurrentSample() {
    if (state.samples.length === 0) return;
    const s = state.samples[state.currentSampleIdx];
    document.getElementById('sampleCounter').textContent = `样本 ${state.currentSampleIdx + 1} / ${state.samples.length}`;

    // Left: event summary
    const lines = [];
    lines.push(`查询: ${s.query}`);
    lines.push(`意图: ${s.intent} | 模式: ${s.mode}`);
    lines.push('');
    lines.push('--- Messages ---');
    for (const m of s.messages) {
        if (m.role === 'system') lines.push(`[system] ${m.content.substring(0, 150)}...`);
        else if (m.role === 'user') lines.push(`[user] ${m.content}`);
        else if (m.role === 'assistant' && m.tool_calls) {
            lines.push(`[assistant] tool_calls: [${m.tool_calls.map(tc=>tc.function.name).join(', ')}]`);
        } else if (m.role === 'tool') lines.push(`[tool] call_id=${m.tool_call_id}, len=${m.content.length}`);
        else if (m.role === 'assistant') lines.push(`[assistant] answer (${m.content.length} chars)`);
    }
    lines.push('');
    lines.push(`质量分: ${s.quality_score}`);
    for (const [k, v] of Object.entries(s.quality_details)) {
        lines.push(`  ${k}: ${JSON.stringify(v)}`);
    }
    document.getElementById('traceEventPreview').textContent = lines.join('\n');

    // Right: JSONL
    document.getElementById('jsonlPreview').textContent = buildJsonlString(s);

    // ── Render sidebar ──
    renderSidebar();
}

function buildJsonlString(sample) {
    const record = { messages: sample.messages, tools: sample.tools, parallel_tool_calls: sample.tool_count > 1 };
    return JSON.stringify(record, null, 2);
}

function renderSidebar() {
    const idx = state.currentSampleIdx;
    const s = state.samples[idx];
    if (!s) return;

    // ── Section 1: Heuristic score breakdown ──
    const totalEl = document.getElementById('sbHeuristicTotal');
    if (totalEl) totalEl.textContent = s.quality_score;

    const dimsContainer = document.getElementById('sbHeuristicDims');
    const dimDefs = [
        { key: 'capability_score', label: 'Agent 能力展现', max: 40, cls: 'a' },
        { key: 'execution_score', label: '执行质量', max: 30, cls: 'b' },
        { key: 'grounding_score', label: '回答可信度', max: 20, cls: 'c' },
        { key: 'completeness_score', label: '数据完整度', max: 10, cls: 'd' },
    ];
    if (dimsContainer) {
        let html = '';
        for (const d of dimDefs) {
            const score = s.quality_details ? (s.quality_details[d.key] || 0) : 0;
            const pct = d.max > 0 ? Math.round((score / d.max) * 100) : 0;
            html += `<div class="sb-dim-row">
                <span class="sb-dim-badge ${d.cls}">${d.cls.toUpperCase()}</span>
                <span class="sb-dim-name">${d.label}</span>
                <div class="sb-dim-bar"><div class="sb-dim-bar-fill ${d.cls}" style="width:${pct}%;"></div></div>
                <span class="sb-dim-val">${score}/${d.max}</span>
            </div>`;
        }
        dimsContainer.innerHTML = html;
    }

    // ── LLM judge result (inline in heuristic section) ──
    const llmInline = document.getElementById('sbLLMInline');
    const llmScore = document.getElementById('sbLLMScore');
    const llmBody = document.getElementById('sbLLMBody');
    const judgeResult = state.judgeResults[idx];

    if (llmInline && llmScore && llmBody) {
        if (judgeResult && !judgeResult.error) {
            llmInline.style.display = '';
            llmScore.textContent = judgeResult.overall_score + ' 分';

            const dims = judgeResult.dimensions || {};
            const dimLabels = {
                agent_capability: 'A. Agent 能力展现', execution_quality: 'B. 执行质量',
                response_grounding: 'C. 回答可信度', data_completeness: 'D. 数据完整度',
            };
            let dimsHtml = '';
            for (const [k, v] of Object.entries(dimLabels)) {
                const score = dims[k] !== undefined ? dims[k] : '-';
                dimsHtml += `<div class="sb-llm-dim-item">
                    <span class="lbl">${v}</span>
                    <span class="val">${score}/10</span>
                </div>`;
            }
            let html = dimsHtml;
            if (judgeResult.summary) {
                html += `<div style="font-size:11px;color:var(--text-secondary);border-top:1px solid var(--border-light);padding-top:6px;margin-top:4px;">💬 ${escHtml(judgeResult.summary)}</div>`;
            }
            if (judgeResult.issues && judgeResult.issues.length > 0) {
                html += `<div style="font-size:11px;color:var(--error);margin-top:4px;">⚠️ ${judgeResult.issues.map(escHtml).join('; ')}</div>`;
            }
            llmBody.innerHTML = html;
        } else if (judgeResult && judgeResult.error) {
            llmInline.style.display = '';
            llmScore.textContent = '失败';
            llmBody.innerHTML = `<div style="color:var(--error);font-size:11px;">❌ 评估失败: ${escHtml(judgeResult.summary)}</div>`;
        } else {
            llmInline.style.display = 'none';
        }
    }

    // ── Section 3: Review status ──
    const statusEl = document.getElementById('sbReviewStatus');
    if (statusEl) {
        const rev = state.reviews[idx];
        const status = rev ? rev.status : 'pending';
        const statusLabels = {pending: '⏳ 待审', approved: '✓ 通过', rejected: '✗ 拒绝'};
        const statusColors = {
            pending: 'background:#F1F5F9;color:#64748B;',
            approved: 'background:var(--success-bg);color:var(--success);',
            rejected: 'background:var(--error-bg);color:var(--error);',
        };
        statusEl.textContent = statusLabels[status];
        statusEl.setAttribute('style', 'padding:2px 10px;border-radius:var(--radius-full);font-size:11px;font-weight:600;' + (statusColors[status] || statusColors.pending));
    }
}

function prevSample() {
    if (state.samples.length === 0) return;
    state.currentSampleIdx = (state.currentSampleIdx - 1 + state.samples.length) % state.samples.length;
    renderCurrentSample();
}

function nextSample() {
    if (state.samples.length === 0) return;
    state.currentSampleIdx = (state.currentSampleIdx + 1) % state.samples.length;
    renderCurrentSample();
}

// ── JSONL Edit Modal ──

function openEditModal() {
    if (state.samples.length === 0) return;
    state.editSampleIdx = state.currentSampleIdx;
    const s = state.samples[state.editSampleIdx];
    state.editBackup = JSON.parse(JSON.stringify({ messages: s.messages, tools: s.tools }));
    document.getElementById('editTextarea').value = buildJsonlString(s);
    document.getElementById('editModal').style.display = 'flex';
}

function closeEditModal() {
    document.getElementById('editModal').style.display = 'none';
    state.editSampleIdx = -1;
    state.editBackup = null;
}

function resetEditModal() {
    if (state.editBackup && state.editSampleIdx >= 0) {
        state.samples[state.editSampleIdx].messages = state.editBackup.messages;
        state.samples[state.editSampleIdx].tools = state.editBackup.tools;
        document.getElementById('editTextarea').value = buildJsonlString(state.samples[state.editSampleIdx]);
    }
}

function formatJsonInModal() {
    const ta = document.getElementById('editTextarea');
    try {
        const parsed = JSON.parse(ta.value);
        ta.value = JSON.stringify(parsed, null, 2);
    } catch (e) {
        alert('JSON 格式错误，无法格式化: ' + e.message);
    }
}

function saveEditModal() {
    const ta = document.getElementById('editTextarea');
    try {
        const edited = JSON.parse(ta.value);
        // Validate structure
        if (!edited.messages || !Array.isArray(edited.messages)) throw new Error('缺少 messages 字段');
        // Update sample
        const s = state.samples[state.editSampleIdx];
        s.messages = edited.messages;
        s.tools = edited.tools || [];
        s.tool_count = edited.tools ? edited.tools.length : s.tool_count;
        // Refresh views
        renderCurrentSample();
        closeEditModal();
    } catch (e) {
        alert('JSON 解析错误: ' + e.message);
    }
}

// Click outside modal to close
document.addEventListener('click', function(e) {
    const modal = document.getElementById('editModal');
    if (e.target === modal) closeEditModal();
});

// ══════════════════════════════════════════════════════════
// Step 3: 质量评估 + LLM Judge + 人工审核
// ══════════════════════════════════════════════════════════

function renderQualityView() {
    const samples = state.samples;
    if (samples.length === 0) return;

    updateQualityStats();
    updateReviewFilterButtons();
    renderReviewList();

    document.getElementById('btnToStep4').disabled = getEffectivePassed().length === 0;
}

function getEffectivePassed() {
    const threshold = state.filterThreshold;
    const requireTools = document.getElementById('requireTools').checked;
    const hasAnyReview = Object.values(state.reviews).some(r => r.status !== 'pending');

    return state.samples.filter((s, i) => {
        if (s.quality_score < threshold) return false;
        if (requireTools && !s.has_tool_calls) return false;
        if (hasAnyReview) {
            const rev = state.reviews[i];
            if (rev && rev.status === 'rejected') return false;
        }
        return true;
    });
}

function updateThreshold(val) {
    if (val !== undefined) {
        state.filterThreshold = parseInt(val);
        document.getElementById('thresholdLabel').textContent = val;
    }
    renderQualityView();
}

// ── Review List (card-based) ──

function renderReviewList() {
    const list = document.getElementById('reviewList');
    const threshold = state.filterThreshold;
    const requireTools = document.getElementById('requireTools').checked;

    let filtered = state.samples.map((s, i) => ({sample: s, idx: i}));

    // Apply review filter
    if (state.reviewFilter === 'pending') {
        filtered = filtered.filter(({idx}) => !state.reviews[idx] || state.reviews[idx].status === 'pending');
    } else if (state.reviewFilter === 'approved') {
        filtered = filtered.filter(({idx}) => state.reviews[idx] && state.reviews[idx].status === 'approved');
    } else if (state.reviewFilter === 'rejected') {
        filtered = filtered.filter(({idx}) => state.reviews[idx] && state.reviews[idx].status === 'rejected');
    }

    if (filtered.length === 0) {
        list.innerHTML = '<div class="empty-state"><div class="icon">📭</div><p>无匹配样本</p></div>';
        return;
    }

    let html = '';
    for (const {sample: s, idx} of filtered) {
        const hScore = s.quality_score;
        const heuristicPassed = hScore >= threshold && (!requireTools || s.has_tool_calls);
        const jResult = state.judgeResults[idx];
        const jScore = jResult && !jResult.error ? jResult.overall_score : null;
        const rev = state.reviews[idx];
        const status = rev ? rev.status : 'pending';
        const statusLabels = {pending: '⏳ 待审', approved: '✓ 通过', rejected: '✗ 拒绝'};

        const rejectedClass = (status === 'rejected' || !heuristicPassed) ? ' rejected-card' : '';

        // Build LLM detail (if available)
        let judgeDetail = '';
        if (jResult && !jResult.error) {
            const dims = jResult.dimensions || {};
            const dimLabels = {
                agent_capability: 'A. Agent 能力展现', execution_quality: 'B. 执行质量',
                response_grounding: 'C. 回答可信度', data_completeness: 'D. 数据完整度',
            };
            let dimsHtml = '';
            for (const [k, v] of Object.entries(dimLabels)) {
                const score = dims[k] || '-';
                dimsHtml += `<div class="item"><span class="lbl">${v}</span><span class="val">${score}/10</span></div>`;
            }
            judgeDetail = `
                <div class="rc-detail-grid">
                    ${dimsHtml}
                    <div class="item" style="grid-column:1/-1;">
                        <span class="lbl">LLM 评语</span>
                        <span class="val">${escHtml(jResult.summary || '')}</span>
                    </div>`;
            if (jResult.issues && jResult.issues.length > 0) {
                judgeDetail += `<div class="item" style="grid-column:1/-1;">
                    <span class="lbl" style="color:var(--error);">问题</span>
                    <span class="val" style="color:var(--error);">${jResult.issues.map(escHtml).join('; ')}</span>
                </div>`;
            }
            judgeDetail += '</div>';
        }

        // Answer preview
        const finalMsg = [...s.messages].reverse().find(m => m.role === 'assistant' && m.content);
        const answerPreview = finalMsg ? finalMsg.content.substring(0, 300) : '';

        html += `
        <div class="review-card${rejectedClass}" id="reviewCard${idx}">
            <div class="rc-main" onclick="toggleReviewCard(${idx})">
                <div class="rc-query" title="${escAttr(s.query)}">${escHtml(s.query)}</div>
                <div class="rc-scores">
                    <div class="rc-score heuristic${heuristicPassed ? '' : ' low'}">
                        <div class="val">${hScore}</div>
                        <div class="lbl">启发式</div>
                    </div>
                    <div class="rc-score llm">
                        <div class="val">${jScore !== null ? jScore : '-'}</div>
                        <div class="lbl">LLM</div>
                    </div>
                </div>
                <div class="rc-status ${status}">${statusLabels[status]}</div>
                <div class="rc-actions" onclick="event.stopPropagation();">
                    <button class="btn-approve" onclick="reviewSample(${idx},'approved')" title="通过">✓</button>
                    <button class="btn-reject" onclick="reviewSample(${idx},'rejected')" title="拒绝">✗</button>
                </div>
            </div>
            <div class="rc-detail">
                ${judgeDetail}
                ${answerPreview ? `<div class="rc-detail-answer"><strong>回答预览:</strong>\n${escHtml(answerPreview)}</div>` : ''}
                <div style="margin-top:8px;display:flex;gap:8px;">
                    <button class="btn-outline btn-sm" onclick="state.currentSampleIdx=${idx};showStep(2);">📋 在 Step 2 中查看</button>
                    ${!jResult ? `<button class="btn-outline btn-sm" onclick="runLLMJudgeForIndex(${idx})">🤖 LLM 评估此条</button>` : ''}
                </div>
            </div>
        </div>`;
    }
    list.innerHTML = html;
}

function toggleReviewCard(idx) {
    const card = document.getElementById('reviewCard' + idx);
    if (card) card.classList.toggle('expanded');
}

function toggleHeuristicRules() {
    const body = document.getElementById('hrBody');
    const icon = document.getElementById('hrToggleIcon');
    if (body) {
        if (body.style.display === 'none') {
            body.style.display = '';
            if (icon) icon.textContent = '▼';
        } else {
            body.style.display = 'none';
            if (icon) icon.textContent = '▶';
        }
    }
}

function reviewSample(idx, status) {
    if (!state.reviews[idx]) state.reviews[idx] = {status: 'pending', notes: ''};
    state.reviews[idx].status = status;
    renderReviewList();
    updateQualityStats();
    renderSidebar();
}

function filterReview(filter) {
    state.reviewFilter = filter;
    updateReviewFilterButtons();
    renderReviewList();
}

function updateReviewFilterButtons() {
    ['all','pending','approved','rejected'].forEach(f => {
        const btn = document.getElementById('reviewFilter' + f.charAt(0).toUpperCase() + f.slice(1));
        if (btn) {
            if (state.reviewFilter === f) btn.classList.add('active');
            else btn.classList.remove('active');
        }
    });
}

function approveAllFiltered() {
    const threshold = state.filterThreshold;
    const requireTools = document.getElementById('requireTools').checked;
    let count = 0;
    state.samples.forEach((s, i) => {
        if (s.quality_score >= threshold && (!requireTools || s.has_tool_calls)) {
            if (!state.reviews[i]) state.reviews[i] = {status: 'pending', notes: ''};
            state.reviews[i].status = 'approved';
            count++;
        }
    });
    renderReviewList();
    updateQualityStats();
    renderSidebar();
}

function updateQualityStats() {
    const samples = state.samples;
    const total = samples.length;
    const avgScore = total > 0 ? (samples.reduce((s, sm) => s + sm.quality_score, 0) / total).toFixed(1) : '-';
    const threshold = state.filterThreshold;
    const requireTools = document.getElementById('requireTools').checked;
    const passed = samples.filter(s => s.quality_score >= threshold && (!requireTools || s.has_tool_calls)).length;
    const reviewed = Object.values(state.reviews).filter(r => r.status !== 'pending').length;
    const approved = Object.values(state.reviews).filter(r => r.status === 'approved').length;

    document.getElementById('qsTotal').textContent = total;
    document.getElementById('qsAvg').textContent = avgScore;
    document.getElementById('qsPass').textContent = passed;
    document.getElementById('qsReviewed').textContent = reviewed;
    document.getElementById('qsApproved').textContent = approved;
    document.getElementById('btnToStep4').disabled = getEffectivePassed().length === 0;

    // Also update toolbar threshold slider
    document.getElementById('thresholdSlider').value = state.filterThreshold;
    document.getElementById('thresholdLabel').textContent = state.filterThreshold;
}

// ── LLM-as-Judge ──

async function runLLMJudge(scope) {
    if (state.judgeLoading) return;
    state.judgeLoading = true;

    const statusDiv = document.getElementById('judgeStatus');
    statusDiv.style.display = 'block';

    const btnAll = document.getElementById('btnJudgeAll');
    if (btnAll) btnAll.disabled = true;

    let targets = [];
    if (scope === 'current') {
        targets = [state.currentSampleIdx];
    } else {
        targets = state.samples.map((_, i) => i);
    }

    let success = 0, failed = 0;

    for (const idx of targets) {
        const s = state.samples[idx];
        statusDiv.innerHTML = `🔄 LLM 评估中: <strong>${idx + 1}/${targets.length}</strong> — ${escHtml(s.query.substring(0, 60))}...`;

        try {
            const resp = await fetch('/api/training/judge', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({sample: s}),
            });
            const data = await resp.json();
            if (data.success && data.judge) {
                state.judgeResults[idx] = data.judge;
                success++;
            } else {
                state.judgeResults[idx] = {overall_score: 0, error: true, summary: data.error || '评估失败'};
                failed++;
            }
        } catch (err) {
            state.judgeResults[idx] = {overall_score: 0, error: true, summary: err.message};
            failed++;
        }
    }

    const judged = Object.keys(state.judgeResults).length;
    const avgJScore = judged > 0
        ? (Object.values(state.judgeResults).reduce((s,r)=>s+(r.overall_score||0), 0) / judged).toFixed(1) : '-';
    statusDiv.innerHTML = `✅ LLM 评估完成: ${success} 成功, ${failed} 失败 | LLM 均分: <strong>${avgJScore}</strong> | 已评估: ${judged}/${state.samples.length}`;

    state.judgeLoading = false;
    if (btnAll) btnAll.disabled = false;
    renderReviewList();
    updateQualityStats();
}

async function runLLMJudgeForIndex(idx) {
    // Evaluate a single sample and expand its card
    const statusDiv = document.getElementById('judgeStatus');
    statusDiv.style.display = 'block';
    statusDiv.innerHTML = '🔄 LLM 评估中...';

    const s = state.samples[idx];
    try {
        const resp = await fetch('/api/training/judge', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({sample: s}),
        });
        const data = await resp.json();
        if (data.success && data.judge) {
            state.judgeResults[idx] = data.judge;
            statusDiv.innerHTML = `✅ LLM 评估完成: <strong>${data.judge.overall_score}</strong> 分 — ${escHtml(data.judge.summary || '')}`;
        } else {
            statusDiv.innerHTML = `❌ 评估失败: ${data.error || '未知错误'}`;
        }
    } catch (err) {
        statusDiv.innerHTML = `❌ 评估失败: ${err.message}`;
    }
    renderReviewList();
    updateQualityStats();
    // Expand the card
    setTimeout(() => {
        const card = document.getElementById('reviewCard' + idx);
        if (card) card.classList.add('expanded');
    }, 100);
}

async function runLLMJudgeCurrentSample() {
    // Evaluate current Step 2 sample via LLM judge
    const idx = state.currentSampleIdx;
    if (state.judgeLoading || state.samples.length === 0) return;
    state.judgeLoading = true;

    const statusDiv = document.getElementById('judgeStatusStep2');
    statusDiv.style.display = 'block';
    statusDiv.innerHTML = '🔄 LLM 评估中...';

    const btn = document.getElementById('btnLLMJudgeCurrent');
    if (btn) btn.disabled = true;

    const s = state.samples[idx];
    try {
        const resp = await fetch('/api/training/judge', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({sample: s}),
        });
        const data = await resp.json();
        if (data.success && data.judge) {
            state.judgeResults[idx] = data.judge;
            statusDiv.innerHTML = `✅ LLM 评估完成: <strong>${data.judge.overall_score}</strong> 分`;
        } else {
            state.judgeResults[idx] = {overall_score: 0, error: true, summary: data.error || '评估失败'};
            statusDiv.innerHTML = `❌ 评估失败: ${escHtml(data.error || '未知错误')}`;
        }
    } catch (err) {
        state.judgeResults[idx] = {overall_score: 0, error: true, summary: err.message};
        statusDiv.innerHTML = `❌ 评估失败: ${escHtml(err.message)}`;
    }

    state.judgeLoading = false;
    if (btn) btn.disabled = false;
    renderCurrentSample();
    updateQualityStats();
}

// ══════════════════════════════════════════════════════════
// Step 4: 导出
// ══════════════════════════════════════════════════════════

function renderExportView() {
    const effectivePassed = getEffectivePassed();
    const hasAnyReview = Object.values(state.reviews).some(r => r.status !== 'pending');

    document.getElementById('esSamples').textContent = effectivePassed.length;
    document.getElementById('esAvgScore').textContent = effectivePassed.length > 0
        ? (effectivePassed.reduce((s, sm) => s + sm.quality_score, 0) / effectivePassed.length).toFixed(1) : '-';
    document.getElementById('esToolCalls').textContent = effectivePassed.reduce((s, sm) => s + sm.tool_count, 0);

    const previewSamples = effectivePassed.slice(0, 3);
    const jsonlLines = previewSamples.map(s => buildJsonlString(s));

    const fullJsonl = effectivePassed.map(s => buildJsonlString(s)).join('\n');
    const sizeKB = (new Blob([fullJsonl]).size / 1024).toFixed(1);
    document.getElementById('esFileSize').textContent = sizeKB + ' KB';

    const label = hasAnyReview ? '（仅包含人工审核通过的样本）' : '（仅包含阈值过滤通过的样本）';
    document.getElementById('exportPreview').textContent = effectivePassed.length === 0
        ? '没有符合条件的样本，请返回 Step 3 调整过滤条件或审核通过更多样本。'
        : jsonlLines.join('\n\n') + `\n\n... 共 ${effectivePassed.length} 条 ${label}`;

    document.getElementById('btnDownload').disabled = effectivePassed.length === 0;
}

async function downloadDataset() {
    const effectivePassed = getEffectivePassed();
    const btn = document.getElementById('btnDownload');
    btn.textContent = '生成中...'; btn.disabled = true;

    try {
        const resp = await fetch('/api/training/export', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ samples: effectivePassed, min_score: 0, require_tools: false }),
        });
        if (!resp.ok) throw new Error('导出失败');
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `training_data_${effectivePassed.length}samples.jsonl`;
        document.body.appendChild(a); a.click(); document.body.removeChild(a);
        URL.revokeObjectURL(url);
        btn.textContent = '✓ 下载完成';
    } catch (err) {
        btn.textContent = '下载失败，重试';
        btn.disabled = false;
        alert('导出失败: ' + err.message);
    }
}

// ══════════════════════════════════════════════════════════
// Utilities
// ══════════════════════════════════════════════════════════

function escHtml(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
}

function escAttr(s) {
    return s.replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
