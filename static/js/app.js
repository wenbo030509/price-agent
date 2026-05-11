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

function addReasoningNode(type, title, detail, elapsedMs) {
    reasoningNodes.push({ type, title, detail, elapsedMs });
    renderTimeline();
}

function clearReasoning() {
    reasoningNodes = [];
    renderTimeline();
}

function renderTimeline() {
    const container = document.getElementById('reasoningContent');
    if (reasoningNodes.length === 0) {
        container.innerHTML = '<p class="text-muted">发送问题后，推理过程将显示在这里...</p>';
        return;
    }

    const icons = { thought: '🤔', action: '⚡', observation: '👁' };
    const labels = { thought: 'Thought', action: 'Action', observation: 'Observation' };

    container.innerHTML = `<div class="timeline">${reasoningNodes.map((n, i) => `
        <div class="timeline-node expanded" id="timelineNode${i}">
            <div class="timeline-dot ${n.type}">${icons[n.type]}</div>
            <div class="timeline-header" onclick="toggleTimelineNode(${i})">
                <span class="timeline-title">
                    <span class="icon">${icons[n.type]}</span>
                    ${labels[n.type]} · ${escapeHtml(n.title)}
                </span>
                <span class="timeline-meta">
                    ${n.elapsedMs ? `<span>${n.elapsedMs}ms</span>` : ''}
                    <span class="timeline-chevron">▶</span>
                </span>
            </div>
            <div class="timeline-body">${escapeHtml(n.detail)}</div>
        </div>
    `).join('')}</div>`;
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

async function createNewSession() {
    try {
        const resp = await fetch('/api/sessions', { method: 'POST' });
        const data = await resp.json();
        if (data.success) {
            currentSessionId = data.session.session_id;
            loadSessions();
            clearChat();
            document.getElementById('sessionSearch').value = '';
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

    // 推理模拟步骤
    const steps = [
        { type: 'thought', title: '理解用户意图', detail: '分析用户问题，判断是否需要调用工具...' },
        { type: 'thought', title: '规划执行策略', detail: '根据问题复杂度，选择 ReAct 或 Plan-Execute 模式...' },
        { type: 'action', title: '执行工具查询', detail: '调用工具查询各平台数据...' },
        { type: 'observation', title: '获取查询结果', detail: '等待各平台返回数据...' },
    ];
    let stepIdx = 0;
    const stepInterval = setInterval(() => {
        if (stepIdx < steps.length) {
            addReasoningNode(steps[stepIdx].type, steps[stepIdx].title, steps[stepIdx].detail, null);
            stepIdx++;
        }
    }, 1200);

    try {
        const resp = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message, session_id: currentSessionId, image_url: imageUrlToSend || '' })
        });
        const data = await resp.json();
        clearInterval(stepInterval);

        if (data.success) {
            currentSessionId = data.session_id;
            loadSessions();
            document.getElementById('loadingMessage').remove();
            addMessageToChat('assistant', data.answer);

            // 解析真实推理过程
            if (data.reasoning) {
                parseReasoningOutput(data.reasoning);
            }
        }
    } catch (e) {
        console.error('发送失败:', e);
        clearInterval(stepInterval);
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
    container.innerHTML = products.map(p => `
        <div class="product-item">
            <div class="d-flex justify-content-between align-items-start">
                <div>
                    <div class="product-name">${escapeHtml(p.product_name)}</div>
                    <div class="product-info">
                        参考价: <span class="price">¥${p.price}</span> |
                        平台价: <span class="price">¥${p.platform_price}</span> |
                        运费: ¥${p.shipping_fee} | 库存: ${p.stock} | ${escapeHtml(p.category)}
                        ${p.color ? ' | ' + escapeHtml(p.color) : ''}
                        ${p.memory ? ' | ' + escapeHtml(p.memory) : ''}
                        ${!p.is_in_stock ? ' <span style="color:var(--error)">(缺货)</span>' : ''}
                    </div>
                </div>
                <div>
                    <button class="btn-sm" onclick="editProduct(${p.id},'${platformId}')">编辑</button>
                    <button class="btn-sm btn-danger" onclick="deleteProduct(${p.id},'${platformId}')">删除</button>
                </div>
            </div>
        </div>
    `).join('');
}

async function handleAddProduct(event) {
    event.preventDefault();
    const data = {
        product_name: document.getElementById('productName').value.trim(),
        price: document.getElementById('productPrice').value,
        platform_price: document.getElementById('productPlatformPrice').value || null,
        stock: document.getElementById('productStock').value,
        category: document.getElementById('productCategory').value.trim(),
        color: document.getElementById('productColor').value.trim() || null,
        memory: document.getElementById('productMemory').value.trim() || null,
        shipping_fee: document.getElementById('productShippingFee').value || 0,
        is_in_stock: document.getElementById('productInStock').checked,
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
        document.getElementById('editProductName').value = p.product_name;
        document.getElementById('editProductPrice').value = p.price;
        document.getElementById('editProductPlatformPrice').value = p.platform_price || '';
        document.getElementById('editProductStock').value = p.stock;
        document.getElementById('editProductCategory').value = p.category;
        document.getElementById('editProductColor').value = p.color || '';
        document.getElementById('editProductMemory').value = p.memory || '';
        document.getElementById('editProductShippingFee').value = p.shipping_fee || 0;
        document.getElementById('editProductInStock').checked = p.is_in_stock;
        if (!editProductModal) editProductModal = new bootstrap.Modal(document.getElementById('editProductModal'));
        editProductModal.show();
    } catch (e) { console.error(e); }
}

async function saveEditProduct() {
    const id = parseInt(document.getElementById('editProductId').value);
    const platformId = document.getElementById('editProductPlatformId').value;
    const data = {
        product_name: document.getElementById('editProductName').value.trim(),
        price: document.getElementById('editProductPrice').value || null,
        platform_price: document.getElementById('editProductPlatformPrice').value || null,
        stock: document.getElementById('editProductStock').value || null,
        category: document.getElementById('editProductCategory').value.trim() || null,
        color: document.getElementById('editProductColor').value.trim() || null,
        memory: document.getElementById('editProductMemory').value.trim() || null,
        shipping_fee: document.getElementById('editProductShippingFee').value || null,
        is_in_stock: document.getElementById('editProductInStock').checked,
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

// ── 初始化 ────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    loadSessions();
    loadQuickProducts();
    loadPlatformProducts('jd');
    document.getElementById('addProductForm').addEventListener('submit', handleAddProduct);
    document.getElementById('saveEditProductBtn').addEventListener('click', saveEditProduct);
});
