/**
 * AB Test Agent Demo — 数据看板 + Agent 交互
 */

// ═══════════════════════════════════════════════════════════
// Mock Data（页面加载即展示）
// ═══════════════════════════════════════════════════════════

const METRICS_RAW = [
    { key:"cvr", name:"购买转化率", type:"primary", typeLabel:"主指标", higher:true,
      ctrl:{mean:0.0342,std:0.0183}, trt:{mean:0.0389,std:0.0196},
      display: v => (v*100).toFixed(2)+'%' },
    { key:"gmv_per_user", name:"人均 GMV", type:"business", typeLabel:"业务指标", higher:true,
      ctrl:{mean:128.5,std:42.3}, trt:{mean:141.2,std:40.8},
      display: v => '¥'+v.toFixed(1) },
    { key:"ctr", name:"点击率", type:"business", typeLabel:"业务指标", higher:true,
      ctrl:{mean:0.128,std:0.042}, trt:{mean:0.136,std:0.040},
      display: v => (v*100).toFixed(1)+'%' },
    { key:"session_duration_s", name:"停留时长", type:"experience", typeLabel:"体验指标", higher:true,
      ctrl:{mean:252,std:108}, trt:{mean:270,std:102},
      display: v => Math.floor(v/60)+'分'+Math.round(v%60)+'秒' },
    { key:"bounce_rate", name:"跳出率", type:"guardrail", typeLabel:"护栏指标", higher:false,
      ctrl:{mean:0.385,std:0.098}, trt:{mean:0.378,std:0.102},
      display: v => (v*100).toFixed(1)+'%' },
    { key:"api_latency_ms", name:"接口响应时间", type:"guardrail", typeLabel:"护栏指标 ⚠", higher:false,
      ctrl:{mean:145,std:32}, trt:{mean:312,std:58},
      display: v => Math.round(v)+'ms' },
    { key:"complaint_rate", name:"客诉率", type:"guardrail", typeLabel:"护栏指标", higher:false,
      ctrl:{mean:0.0021,std:0.0018}, trt:{mean:0.0019,std:0.0019},
      display: v => (v*100).toFixed(2)+'%' },
];

const SEGMENTS = [
    { dim:"设备类型", seg:"iOS", pct:35, nC:15830, nT:15816, cCVR:0.041, tCVR:0.053 },
    { dim:"设备类型", seg:"Android 高端", pct:30, nC:13569, nT:13557, cCVR:0.035, tCVR:0.038 },
    { dim:"设备类型", seg:"Android 中低端", pct:35, nC:15832, nT:15816, cCVR:0.028, tCVR:0.027,
      note:"中低端设备 LLM 推理超时导致推荐不完整 ⚠" },
    { dim:"用户活跃度", seg:"高活（近7天有浏览）", pct:45, nC:20354, nT:20335, cCVR:0.048, tCVR:0.059 },
    { dim:"用户活跃度", seg:"中活（近30天有浏览）", pct:35, nC:15831, nT:15816, cCVR:0.029, tCVR:0.031 },
    { dim:"用户活跃度", seg:"低活（30天以上）", pct:20, nC:9046, nT:9038, cCVR:0.015, tCVR:0.014,
      note:"样本量较小，虽不显著但趋势需关注" },
];

const DAILY = {
    dates: ["05-15","05-16","05-17","05-18","05-19","05-20","05-21",
            "05-22","05-23","05-24","05-25","05-26","05-27","05-28"],
    ctrlCVR:  [0.0338,0.0341,0.0335,0.0344,0.0340,0.0352,0.0345,0.0339,0.0343,0.0338,0.0346,0.0341,0.0344,0.0342],
    trtCVR:   [0.0351,0.0362,0.0371,0.0378,0.0382,0.0388,0.0385,0.0391,0.0387,0.0393,0.0390,0.0392,0.0388,0.0389],
    ctrlLat:  [143,147,144,146,145,148,143,144,146,145,147,144,146,145],
    trtLat:   [328,335,321,318,315,310,308,312,309,314,311,308,313,312],
};

// Agent results cache (filled by SSE events)
const agentStats = {};  // { metric_key: {p_value, lift_pct, is_significant, ...} }

// ═══════════════════════════════════════════════════════════
// Experiment definitions
// ═══════════════════════════════════════════════════════════

const EXPERIMENTS = [
    {
        id: "exp_rec_20260515_llm_embedding_v2",
        name: "推荐算法升级",
        subtitle: "协同过滤 → LLM Embedding v2.0",
        status: "进行中",
        period: "2026-05-15 ~ 05-28（14天）",
        split: "50/50 user_id hash",
        nControl: 45231, nTreatment: 45189,
        hypothesis: "LLM Embedding 替代协同过滤能提升购买转化率",
        mde: "CVR +8%", power: "82%",
        hasFullData: true,
        queries: [
            { label: "🧪 完整分析 + 决策", query: "分析实验 exp_rec_20260515_llm_embedding_v2，先获取列表和详情，然后对全部7个指标运行统计检验，检查细分维度，给出是否上线的建议" },
            { label: "📐 统计检验汇总", query: "对实验 exp_rec_20260515_llm_embedding_v2 的全部7个指标运行统计检验，列出p值、置信区间和效应量" },
            { label: "🔬 Simpson 悖论检测", query: "检查实验 exp_rec_20260515_llm_embedding_v2 在各细分维度（设备类型、用户活跃度）上的效果一致性" },
        ],
    },
    {
        id: "exp_price_20260401_layout_v3",
        name: "商品详情页改版",
        subtitle: "旧版布局 → 新版沉浸式布局",
        status: "已完成",
        period: "2026-04-01 ~ 04-14（14天）",
        split: "50/50 user_id hash",
        nControl: 39100, nTreatment: 39100,
        hypothesis: "沉浸式布局能提升人均浏览深度",
        mde: "浏览深度 +5%", power: "78%",
        hasFullData: false,
        queries: [
            { label: "📋 查看实验列表", query: "列出所有可用的AB实验" },
            { label: "🔍 查看实验详情", query: "查看实验 exp_price_20260401_layout_v3 的基本信息" },
        ],
    },
    {
        id: "exp_ads_20260310_targeting_v5",
        name: "广告定向策略升级",
        subtitle: "人口统计 → 行为兴趣标签",
        status: "已完成",
        period: "2026-03-10 ~ 03-24（14天）",
        split: "50/50 user_id hash",
        nControl: 60000, nTreatment: 60000,
        hypothesis: "行为兴趣标签定向能提升广告CTR",
        mde: "CTR +10%", power: "85%",
        hasFullData: false,
        queries: [
            { label: "📋 查看实验列表", query: "列出所有可用的AB实验" },
            { label: "🔍 查看实验详情", query: "查看实验 exp_ads_20260310_targeting_v5 的基本信息" },
        ],
    },
];

let currentExperiment = 0;

// ═══════════════════════════════════════════════════════════
// Init
// ═══════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
    switchExperiment(0);
});

function switchExperiment(idx) {
    currentExperiment = parseInt(idx);
    const exp = EXPERIMENTS[currentExperiment];
    document.getElementById('experimentSelect').value = idx;

    // ── Update sidebar info ──
    document.getElementById('experimentInfoContent').innerHTML = `
        <strong>${exp.name}</strong><br>
        <span style="font-size:11px;opacity:.7;">${exp.subtitle}<br>${exp.status} · n=${(exp.nControl+exp.nTreatment).toLocaleString()}</span><br>
        <span style="font-size:11px;">周期: ${exp.period}<br>假设: ${exp.hypothesis}</span>
    `;

    // ── Update preset queries ──
    let btnHtml = '';
    for (const q of exp.queries) {
        btnHtml += `<button class="preset-btn${exp.hasFullData ? ' primary' : ''}" onclick="fillQuery('${escAttr(q.query)}')">${q.label}</button>`;
    }
    document.getElementById('presetButtons').innerHTML = btnHtml;

    // ── Update context card story ──
    const storyEl = document.querySelector('.context-card .story');
    if (storyEl) {
        if (exp.hasFullData) {
            storyEl.innerHTML = `
                <strong>前因：</strong>某电商平台商品推荐系统长期使用<strong>协同过滤算法</strong>，根据用户历史行为做推荐。但该算法存在两个问题：①新品冷启动困难（没有历史行为就无法推荐）；②无法理解商品语义（"打游戏的商务手机"这种复合需求理解不了）。<br><br>
                <strong>升级方案：</strong>推荐算法组提出用<strong>大模型 Embedding</strong> 替代协同过滤。将商品标题、描述、属性编码为语义向量，用户查询也编码为向量，通过余弦相似度匹配最相关商品。理论上能解决冷启动和语义理解问题。<br><br>
                <strong>风险隐患：</strong>工程团队担心 LLM Embedding 调用引入了<strong>额外推理延迟</strong>。原有协同过滤是纯内存计算（~145ms），新方案每次推荐需要调用模型推理接口，预估延迟会上升。<br><br>
                <strong>本次实验目标：</strong>验证 LLM Embedding 能否在<strong>不伤害用户体验</strong>的前提下提升购买转化率。主指标为<strong>购买转化率（CVR）</strong>，护栏指标覆盖延迟、跳出率、客诉率。
            `;
        } else {
            storyEl.innerHTML = `
                <strong>实验：</strong>${exp.name} — ${exp.subtitle}。<br><br>
                <strong>假设：</strong>${exp.hypothesis}。<br><br>
                <strong>状态：</strong>该实验已<strong>${exp.status}</strong>，周期 ${exp.period}，共 ${(exp.nControl+exp.nTreatment).toLocaleString()} 名用户。<br><br>
                <strong>说明：</strong>此实验仅提供摘要数据用于演示实验列表和基本信息查询功能。完整的7指标统计检验、Simpson 悖论检测等功能请切换到"推荐算法升级"实验体验。
            `;
        }
    }

    // ── Update context card meta ──
    const contextMeta = document.querySelector('.context-meta');
    if (contextMeta) {
        contextMeta.innerHTML = `
            <div class="ctx-item"><div class="ctx-lbl">实验 ID</div><div class="ctx-val" style="font-family:'JetBrains Mono',monospace;font-size:13px;">${exp.id.split('_').pop()}</div></div>
            <div class="ctx-item"><div class="ctx-lbl">对照组</div><div class="ctx-val">${exp.hasFullData ? '协同过滤' : '旧版本'} · n=${exp.nControl.toLocaleString()}</div></div>
            <div class="ctx-item"><div class="ctx-lbl">实验组</div><div class="ctx-val">${exp.hasFullData ? 'LLM Embedding' : '新版本'} · n=${exp.nTreatment.toLocaleString()}</div></div>
            <div class="ctx-item"><div class="ctx-lbl">功效</div><div class="ctx-val">MDE: ${exp.mde} · Power: ${exp.power}</div></div>
        `;
    }

    // ── Show/hide data sections ──
    const dataWrap = document.querySelector('.data-table-wrap');
    const chartsRow = document.querySelector('.charts-row');
    const segTable = document.querySelector('.segment-table');
    const sectionTitles = document.querySelectorAll('.section-title');
    const dataTitle = sectionTitles[1];   // "数据" section
    const segTitle = sectionTitles[2];    // "细分" section

    if (exp.hasFullData) {
        if (dataWrap) dataWrap.style.display = '';
        if (chartsRow) chartsRow.style.display = '';
        if (segTable) segTable.style.display = '';
        if (dataTitle) dataTitle.style.display = '';
        if (segTitle) segTitle.style.display = '';
        renderMetricsTable();
        renderSegmentTable();
        setTimeout(() => { drawChartCVR(); drawChartLatency(); }, 100);
    } else {
        if (dataWrap) dataWrap.style.display = 'none';
        if (chartsRow) chartsRow.style.display = 'none';
        if (segTable) segTable.style.display = 'none';
        if (dataTitle) dataTitle.style.display = 'none';
        if (segTitle) segTitle.style.display = 'none';
        // Clear agent results for summary-only experiments
        Object.keys(agentStats).forEach(k => delete agentStats[k]);
    }

    // ── Reset agent section ──
    const agentSection = document.getElementById('agentSection');
    if (agentSection) agentSection.style.display = 'none';
    const traceContainer = document.getElementById('traceContainer');
    if (traceContainer) traceContainer.innerHTML = '';
}

// ═══════════════════════════════════════════════════════════
// Render Metrics Table
// ═══════════════════════════════════════════════════════════

function renderMetricsTable() {
    const tbody = document.getElementById('metricsTableBody');
    const typeClass = {primary:'type-primary', business:'type-business', experience:'type-experience', guardrail:'type-guardrail'};

    let html = '';
    for (const m of METRICS_RAW) {
        const ctrlVal = m.display(m.ctrl.mean);
        const trtVal = m.display(m.trt.mean);
        const rawLift = ((m.trt.mean - m.ctrl.mean) / m.ctrl.mean * 100);
        const liftDir = rawLift > 0 ? '+' : '';

        // Check if Agent has filled in stats
        const st = agentStats[m.key];
        const liftCell = st
            ? `<span class="stat-filled ${st.lift_pct > 0 ? (m.higher ? 'lift-positive' : 'lift-negative') : (m.higher ? 'lift-negative' : 'lift-positive')}">${st.lift_pct > 0 ? '+' : ''}${st.lift_pct}%</span>`
            : `<span class="stat-pending">${liftDir}${rawLift.toFixed(1)}%（待检验）</span>`;

        const pCell = st
            ? `<span class="stat-filled ${st.is_significant ? (st.lift_pct > 0 === m.higher ? 'sig-yes' : 'sig-bad') : 'sig-no'}">${st.p_value.toFixed(4)}${st.is_significant ? ' *' : ''}</span>`
            : '<span class="stat-pending">—</span>';

        const ciCell = st
            ? `<span class="stat-filled">[${st.ci_95[0].toFixed(4)}, ${st.ci_95[1].toFixed(4)}]</span>`
            : '<span class="stat-pending">—</span>';

        const dCell = st
            ? `<span class="stat-filled">${st.cohens_d.toFixed(2)}</span>`
            : '<span class="stat-pending">—</span>';

        const verdictCell = st
            ? `<span class="stat-filled ${st.is_significant ? (st.lift_pct > 0 === m.higher ? 'sig-yes' : 'sig-bad') : 'sig-no'}">${st.verdict || (st.is_significant ? '显著' : '不显著')}</span>`
            : '<span class="stat-pending">待检验</span>';

        html += `<tr>
            <td><span class="metric-name">${m.name}</span></td>
            <td><span class="metric-type ${typeClass[m.type]||''}">${m.typeLabel}</span></td>
            <td style="font-family:'JetBrains Mono',monospace;font-size:12px;">${ctrlVal} <span style="font-size:10px;color:var(--text-tertiary);">±${m.display(m.ctrl.std)}</span></td>
            <td style="font-family:'JetBrains Mono',monospace;font-size:12px;">${trtVal} <span style="font-size:10px;color:var(--text-tertiary);">±${m.display(m.trt.std)}</span></td>
            <td>${liftCell}</td>
            <td>${pCell}</td>
            <td>${ciCell}</td>
            <td>${dCell}</td>
            <td>${verdictCell}</td>
        </tr>`;
    }
    tbody.innerHTML = html;
}

// ═══════════════════════════════════════════════════════════
// Render Segment Table
// ═══════════════════════════════════════════════════════════

function renderSegmentTable() {
    const tbody = document.getElementById('segmentTableBody');
    let html = '', lastDim = '';
    for (const s of SEGMENTS) {
        if (s.dim !== lastDim) {
            html += `<tr style="background:#F8FAFC;"><td colspan="8" style="font-weight:600;font-size:12px;color:var(--text-secondary);">${s.dim}</td></tr>`;
            lastDim = s.dim;
        }
        const lift = ((s.tCVR - s.cCVR) / s.cCVR * 100);
        const direction = lift > 0 ? '+' : '';
        const risk = lift < 0 ? '⚠️ 需关注' : '✅ 安全';
        const riskColor = lift < 0 ? 'var(--error)' : 'var(--success)';
        html += `<tr>
            <td></td>
            <td>${s.seg}</td>
            <td>${s.pct}%</td>
            <td style="font-family:'JetBrains Mono',monospace;font-size:12px;">${(s.nC+s.nT).toLocaleString()}</td>
            <td style="font-family:'JetBrains Mono',monospace;font-size:12px;">${(s.cCVR*100).toFixed(1)}%</td>
            <td style="font-family:'JetBrains Mono',monospace;font-size:12px;">${(s.tCVR*100).toFixed(1)}%</td>
            <td style="color:${lift>0?'var(--success)':'var(--error)'};font-weight:600;">${direction}${lift.toFixed(1)}%</td>
            <td style="color:${riskColor};font-size:12px;">${risk}${s.note ? '<br><span style="font-size:10px;color:var(--text-tertiary);">'+escHtml(s.note)+'</span>' : ''}</td>
        </tr>`;
    }
    tbody.innerHTML = html;
}

// ═══════════════════════════════════════════════════════════
// Charts (Canvas)
// ═══════════════════════════════════════════════════════════

function drawLineChart(canvasId, series, colors, yLabel) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = 180 * dpr;
    canvas.style.width = rect.width + 'px';
    canvas.style.height = '180px';
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    const W = rect.width, H = 180;
    const pad = { top: 10, right: 20, bottom: 30, left: 50 };
    const pw = W - pad.left - pad.right;
    const ph = H - pad.top - pad.bottom;

    // Find y range
    let yMin = Infinity, yMax = -Infinity;
    for (const s of series) {
        for (const v of s.data) { if (v < yMin) yMin = v; if (v > yMax) yMax = v; }
    }
    const yPad = (yMax - yMin) * 0.15 || 1;
    yMin -= yPad; yMax += yPad;

    const xScale = i => pad.left + (i / (series[0].data.length - 1)) * pw;
    const yScale = v => pad.top + ph - ((v - yMin) / (yMax - yMin)) * ph;

    // Grid
    ctx.strokeStyle = '#E2E8F0'; ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
        const y = pad.top + (ph / 4) * i;
        ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(W - pad.right, y); ctx.stroke();
        const val = yMax - ((yMax - yMin) / 4) * i;
        ctx.fillStyle = '#94A3B8'; ctx.font = '10px JetBrains Mono';
        ctx.textAlign = 'right'; ctx.fillText(val.toFixed(yMax < 1 ? 4 : 0), pad.left - 6, y + 3);
    }

    // X labels
    ctx.textAlign = 'center'; ctx.fillStyle = '#94A3B8';
    const labels = DAILY.dates;
    const step = Math.max(1, Math.floor(labels.length / 6));
    for (let i = 0; i < labels.length; i += step) {
        ctx.fillText(labels[i], xScale(i), H - pad.bottom + 16);
    }

    // Lines
    for (let si = 0; si < series.length; si++) {
        const s = series[si];
        ctx.strokeStyle = colors[si]; ctx.lineWidth = 2;
        ctx.beginPath();
        for (let i = 0; i < s.data.length; i++) {
            const x = xScale(i), y = yScale(s.data[i]);
            if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();

        // Dots
        ctx.fillStyle = colors[si];
        for (let i = 0; i < s.data.length; i++) {
            ctx.beginPath(); ctx.arc(xScale(i), yScale(s.data[i]), 3, 0, Math.PI * 2); ctx.fill();
        }
    }
}

function drawChartCVR() {
    drawLineChart('chartCVR', [
        { data: DAILY.ctrlCVR },
        { data: DAILY.trtCVR },
    ], ['#94A3B8', '#FF4D1C']);
}

function drawChartLatency() {
    drawLineChart('chartLatency', [
        { data: DAILY.ctrlLat },
        { data: DAILY.trtLat },
    ], ['#94A3B8', '#EF4444']);
}

window.addEventListener('resize', () => { drawChartCVR(); drawChartLatency(); });

// ═══════════════════════════════════════════════════════════
// Agent Interaction (SSE)
// ═══════════════════════════════════════════════════════════

let isLoading = false;

function fillQuery(q) {
    document.getElementById('queryInput').value = q;
    document.getElementById('queryInput').focus();
}

async function sendMessage() {
    const query = document.getElementById('queryInput').value.trim();
    if (!query || isLoading) return;

    isLoading = true;
    const sendBtn = document.getElementById('sendBtn');
    const input = document.getElementById('queryInput');
    sendBtn.disabled = true; input.disabled = true;

    // Status indicators
    const dot = document.getElementById('statusDot');
    dot.classList.add('running');
    document.getElementById('statusText').textContent = 'Agent 推理中';
    document.getElementById('statusHint').textContent = '— 正在调用工具分析实验数据...';

    // Show agent section
    const agentSection = document.getElementById('agentSection');
    agentSection.style.display = 'block';
    const traceContainer = document.getElementById('traceContainer');
    traceContainer.innerHTML = '';

    input.value = '';

    try {
        const resp = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query }),
        });

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        handleEvent(JSON.parse(line.slice(6)), traceContainer);
                    } catch(e) {}
                }
            }
        }
    } catch (err) {
        appendTraceNode(traceContainer, 'error', '连接错误', err.message);
    } finally {
        isLoading = false;
        sendBtn.disabled = false; input.disabled = false;
        dot.classList.remove('running');
        document.getElementById('statusText').textContent = '分析完成';
        document.getElementById('statusHint').textContent = '— 可继续追问或发起新分析';
        input.focus();
    }
}

function handleEvent(ev, container) {
    const t = ev.type, d = ev.data || {};

    switch (t) {
        case 'intent':
            appendTraceNode(container, 'thought', '意图识别', `识别查询意图，准备开始分析实验数据`);
            break;

        case 'mode_select':
            appendTraceNode(container, 'thought', '执行模式', `${d.mode} — ${d.reason || ''}`);
            break;

        case 'react_round': {
            const thought = d.thought || '';
            if (thought && thought !== '正在调用工具获取数据...') {
                appendTraceNode(container, 'thought', `思考 (Round ${d.round})`, thought);
            }
            break;
        }

        case 'tool_call': {
            const toolName = d.tool || '?';
            const args = d.args || {};
            const argsStr = typeof args === 'string' ? args : JSON.stringify(args);
            const labels = {
                'get_experiment_overview': '获取实验元信息',
                'run_statistical_test': '统计检验',
                'run_multi_metric_check': '多指标汇总 + Bonferroni 校正',
                'check_segment_consistency': 'Simpson 悖论检测',
                'make_strategy_decision': '决策判断',
                'get_daily_trend': '获取分日趋势',
            };
            appendTraceNode(container, 'tool', `调用: ${labels[toolName] || toolName}`, argsStr);
            break;
        }

        case 'tool_result': {
            const toolName = d.tool || '?';
            const summary = d.summary || '';

            // Parse and try to extract stats for table update
            try {
                const parsed = JSON.parse(summary);
                if (toolName === 'run_statistical_test' && parsed.metric_key) {
                    // Store agent result for table update
                    agentStats[parsed.metric_key] = {
                        p_value: parsed.p_value,
                        lift_pct: parsed.relative_lift_pct,
                        is_significant: parsed.is_significant,
                        ci_95: parsed.ci_95,
                        cohens_d: parsed.cohens_d,
                        verdict: parsed.verdict,
                    };
                    renderMetricsTable(); // Live update
                }
            } catch(e) {}

            appendTraceNode(container, 'result', `结果: ${toolName}`, summary);
            break;
        }

        case 'reflection':
            appendTraceNode(container, 'thought', '反思纠错', d.reasoning || d.action || '');
            break;

        case 'error':
            appendTraceNode(container, 'error', '错误', d.message || '');
            break;

        case 'done': {
            if (d.answer) {
                const card = document.createElement('div');
                card.className = 'decision-card';
                const verdict = d.answer.match(/【(.+?)】/);
                card.innerHTML = `
                    <div class="verdict">${escHtml(verdict ? verdict[1] : '分析完成')}</div>
                    <div style="font-size:13px;line-height:2;">${escapeHtml(d.answer).replace(/\n/g, '<br>')}</div>
                `;
                container.appendChild(card);
            }
            break;
        }
    }

    document.getElementById('contentArea').scrollTop = document.getElementById('contentArea').scrollHeight;
}

function appendTraceNode(container, type, title, content) {
    const node = document.createElement('div');
    node.className = 'tl-node';
    const display = content.length > 600 ? content.substring(0, 600) + '...' : content;
    const isJSON = display.trim().startsWith('{');
    node.innerHTML = `
        <div class="tl-hdr"><div class="tl-dot ${type}"></div>${escHtml(title)}</div>
        <div class="tl-body">${isJSON ? '<pre>'+escHtml(display)+'</pre>' : escHtml(display)}</div>
    `;
    container.appendChild(node);
}

// ═══════════════════════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════════════════════

function escHtml(s) {
    if (!s) return '';
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

function escapeHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function escAttr(s) {
    return s.replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
