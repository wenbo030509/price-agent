let currentSessionId = null;
let currentPlatform = 'jd';
let isLoading = false;
let sidebarCollapsed = false;
let currentProducts = []; // 保存当前加载的商品列表
let currentImageUrl = null;  // 当前上传的图片URL
let currentImageFile = null; // 当前图片文件（用于粘贴上传）

// 平台名称映射
const platformNames = {
    'jd': '京东',
    'taobao': '淘宝',
    'pdd': '拼多多',
    'suning': '苏宁'
};

// 侧边栏完全收起/展开
function toggleSidebar() {
    sidebarCollapsed = !sidebarCollapsed;
    const sidebar = document.getElementById('sidebar');
    const chatArea = document.getElementById('chatArea');
    const rightPanel = document.getElementById('rightPanel');
    const sidebarToggleIcon = document.getElementById('sidebarToggleIcon');
    
    if (sidebarCollapsed) {
        sidebar.classList.add('collapsed');
        sidebar.classList.remove('col-md-3');
        sidebar.classList.add('col-md-1');
        chatArea.classList.remove('col-md-6');
        chatArea.classList.add('col-md-7');
        rightPanel.classList.remove('col-md-3');
        rightPanel.classList.add('col-md-4');
        sidebarToggleIcon.textContent = '▶';
    } else {
        sidebar.classList.remove('collapsed');
        sidebar.classList.add('col-md-3');
        sidebar.classList.remove('col-md-1');
        chatArea.classList.add('col-md-6');
        chatArea.classList.remove('col-md-7');
        rightPanel.classList.add('col-md-3');
        rightPanel.classList.remove('col-md-4');
        sidebarToggleIcon.textContent = '◀';
    }
}

// 添加商品折叠
let addProductCollapsed = true;
function toggleAddProductCollapse() {
    addProductCollapsed = !addProductCollapsed;
    const addProductSection = document.getElementById('addProductSection');
    const toggleIcon = document.getElementById('addProductToggleIcon');
    
    if (addProductCollapsed) {
        addProductSection.style.display = 'none';
        toggleIcon.textContent = '▶';
    } else {
        addProductSection.style.display = 'block';
        toggleIcon.textContent = '▼';
    }
}

// 创建新会话
async function createNewSession() {
    try {
        const response = await fetch('/api/sessions', {
            method: 'POST'
        });
        const data = await response.json();
        if (data.success) {
            currentSessionId = data.session.session_id;
            loadSessions();
            clearChat();
        }
    } catch (error) {
        console.error('创建会话失败:', error);
    }
}

// 加载会话列表
async function loadSessions() {
    try {
        const response = await fetch('/api/sessions');
        const data = await response.json();
        if (data.success) {
            renderSessions(data.sessions);
            if (data.sessions.length > 0 && !currentSessionId) {
                switchSession(data.sessions[0].session_id);
            }
        }
    } catch (error) {
        console.error('加载会话失败:', error);
    }
}

// 渲染会话列表
function renderSessions(sessions) {
    const container = document.getElementById('sessionList');
    container.innerHTML = sessions.map(session => `
        <div class="session-item ${session.session_id === currentSessionId ? 'active' : ''}"
             onclick="switchSession('${session.session_id}')">
            <div class="session-info">
                <div class="session-title">会话 ${session.session_id.substring(0, 8)}...</div>
                <div class="session-date">${new Date(session.created_at).toLocaleString('zh-CN')}</div>
            </div>
            <button class="btn btn-danger btn-sm delete-btn" onclick="event.stopPropagation(); deleteSession('${session.session_id}')">
                ×
            </button>
        </div>
    `).join('');
}

// 切换会话
async function switchSession(sessionId) {
    currentSessionId = sessionId;
    loadSessions();
    clearChat();

    try {
        const response = await fetch(`/api/sessions/${sessionId}/messages`);
        const data = await response.json();
        if (data.success) {
            renderMessages(data.messages);
        }
    } catch (error) {
        console.error('加载消息失败:', error);
    }
}

// 删除会话
async function deleteSession(sessionId) {
    if (!confirm('确定要删除这个会话吗？')) return;

    try {
        const response = await fetch(`/api/sessions/${sessionId}`, {
            method: 'DELETE'
        });
        const data = await response.json();
        if (data.success) {
            if (currentSessionId === sessionId) {
                currentSessionId = null;
                clearChat();
            }
            loadSessions();
        }
    } catch (error) {
        console.error('删除会话失败:', error);
    }
}

// 清空聊天区域
function clearChat() {
    document.getElementById('chatMessages').innerHTML = '';
    document.getElementById('reasoningContent').innerHTML = '<p class="text-muted">发送问题后，ReAct推理过程将显示在这里...</p>';
}

// 滚动到聊天区域底部
function scrollToBottom() {
    const container = document.getElementById('chatMessages');
    requestAnimationFrame(() => {
        container.scrollTop = container.scrollHeight;
        setTimeout(() => {
            container.scrollTop = container.scrollHeight;
        }, 100);
    });
}

// 渲染消息
function renderMessages(messages) {
    const container = document.getElementById('chatMessages');
    container.innerHTML = messages.map(msg => `
        <div class="message ${msg.role}">
            <div class="message-content">${escapeHtml(msg.content)}</div>
        </div>
    `).join('');
    scrollToBottom();
}

// 添加消息到聊天区域
function addMessageToChat(role, content, imageUrl) {
    const container = document.getElementById('chatMessages');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    let html = '';
    if (imageUrl) {
        html += `<img src="${escapeHtml(imageUrl)}" class="message-image" onclick="zoomMessageImage('${escapeHtml(imageUrl)}')" title="点击放大">`;
    }
    html += `<div class="message-content">${escapeHtml(content)}</div>`;
    messageDiv.innerHTML = html;
    container.appendChild(messageDiv);
    scrollToBottom();
}

// 点击消息中的图片放大
function zoomMessageImage(url) {
    document.getElementById('imageZoomImg').src = url;
    const modal = new bootstrap.Modal(document.getElementById('imageZoomModal'));
    modal.show();
}

// ── 图片上传 / 粘贴 / 预览 / 删除 ──────────────────────────────────────────

// 处理文件选择
function handleImageFile(event) {
    const file = event.target.files[0];
    if (!file) return;
    uploadImageFile(file);
    event.target.value = '';  // 重置以便重新选择同一文件
}

// 上传图片文件到服务器
async function uploadImageFile(file) {
    if (currentImageUrl) {
        removeImage();  // 只允许一张图片，先移除旧的
    }

    const formData = new FormData();
    formData.append('image', file);

    try {
        const resp = await fetch('/api/upload-image', { method: 'POST', body: formData });
        const data = await resp.json();
        if (data.success) {
            showImagePreview(data.image_url);
        } else {
            alert('图片上传失败: ' + (data.error || '未知错误'));
        }
    } catch (e) {
        console.error('上传图片失败:', e);
        alert('图片上传失败，请重试');
    }
}

// 显示图片缩略图
function showImagePreview(imageUrl) {
    currentImageUrl = imageUrl;
    const area = document.getElementById('imagePreviewArea');
    const thumb = document.getElementById('imagePreviewThumb');
    thumb.src = imageUrl;
    area.style.display = 'block';
}

// 删除已上传图片
function removeImage() {
    currentImageUrl = null;
    currentImageFile = null;
    document.getElementById('imagePreviewArea').style.display = 'none';
    document.getElementById('imagePreviewThumb').src = '';
}

// 点击缩略图放大
function zoomImage() {
    if (!currentImageUrl) return;
    document.getElementById('imageZoomImg').src = currentImageUrl;
    const modal = new bootstrap.Modal(document.getElementById('imageZoomModal'));
    modal.show();
}

// Ctrl+V 粘贴图片
document.addEventListener('paste', function(e) {
    // 如果焦点在 input 上且粘贴的是文本，不拦截
    const activeEl = document.activeElement;
    if (activeEl && activeEl.tagName === 'INPUT' && activeEl.type === 'text') {
        // 检查剪贴板是否有图片
        const items = e.clipboardData.items;
        for (let i = 0; i < items.length; i++) {
            if (items[i].type.startsWith('image/')) {
                e.preventDefault();
                const file = items[i].getAsFile();
                uploadImageFile(file);
                return;
            }
        }
        return;  // 纯文本粘贴，正常处理
    }

    // 焦点不在输入框，检查是否有图片
    const items = e.clipboardData.items;
    for (let i = 0; i < items.length; i++) {
        if (items[i].type.startsWith('image/')) {
            e.preventDefault();
            const file = items[i].getAsFile();
            uploadImageFile(file);
            return;
        }
    }
});

// 拖拽上传
const chatInputEl = document.querySelector('.chat-input');
if (chatInputEl) {
    chatInputEl.addEventListener('dragover', function(e) {
        e.preventDefault();
        e.stopPropagation();
        this.classList.add('drag-over');
    });
    chatInputEl.addEventListener('dragleave', function(e) {
        e.preventDefault();
        e.stopPropagation();
        this.classList.remove('drag-over');
    });
    chatInputEl.addEventListener('drop', function(e) {
        e.preventDefault();
        e.stopPropagation();
        this.classList.remove('drag-over');
        const files = e.dataTransfer.files;
        if (files.length > 0 && files[0].type.startsWith('image/')) {
            uploadImageFile(files[0]);
        }
    });
}

// 发送消息
async function sendMessage() {
    if (isLoading) return;

    const input = document.getElementById('userInput');
    const message = input.value.trim();

    if (!message) return;

    input.value = '';

    // 展示用户消息（含图片）
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

    // 自动切换到推理过程tab
    const reasoningTab = document.getElementById('reasoning-tab');
    const bsReasoningTab = bootstrap.Tab.getOrCreateInstance(reasoningTab);
    bsReasoningTab.show();

    // 显示加载状态
    const container = document.getElementById('chatMessages');
    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'message assistant';
    loadingDiv.id = 'loadingMessage';
    loadingDiv.innerHTML = `<div class="message-content"><span class="loading"></span> 思考中...</div>`;
    container.appendChild(loadingDiv);
    scrollToBottom();

    // 推理过程显示loading
    document.getElementById('reasoningContent').innerHTML = `
        <div class="reasoning-loading">
            <div class="spinner-border spinner-border-sm text-primary me-2" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
            <span>正在推理分析...</span>
        </div>
        <div class="reasoning-step mt-2 text-muted small">
            步骤1: 理解用户问题...
        </div>
    `;

    // 模拟推理步骤动画
    let step = 1;
    const stepTexts = [
        '步骤1: 理解用户问题...',
        '步骤2: 规划工具调用策略...',
        '步骤3: 执行工具查询...',
        '步骤4: 整合分析结果...'
    ];
    const stepInterval = setInterval(() => {
        if (step < stepTexts.length) {
            const stepEl = document.querySelector('.reasoning-step');
            if (stepEl) {
                stepEl.textContent = stepTexts[step];
                step++;
            }
        }
    }, 1500);

    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                message: message,
                session_id: currentSessionId,
                image_url: imageUrlToSend || ''
            })
        });

        const data = await response.json();

        // 停止推理步骤动画
        clearInterval(stepInterval);

        if (data.success) {
            currentSessionId = data.session_id;
            loadSessions();

            // 移除加载状态，显示真实回复
            document.getElementById('loadingMessage').remove();
            addMessageToChat('assistant', data.answer);

            // 显示推理过程
            document.getElementById('reasoningContent').innerHTML = `<pre class="reasoning-text">${escapeHtml(data.reasoning)}</pre>`;
        }
    } catch (error) {
        console.error('发送消息失败:', error);
        clearInterval(stepInterval);
        document.getElementById('loadingMessage').remove();
        addMessageToChat('assistant', '抱歉，发生错误，请稍后重试。');
        document.getElementById('reasoningContent').innerHTML = `<p class="text-danger">推理过程中发生错误</p>`;
    }

    isLoading = false;
}

// 处理回车发送
function handleKeyPress(event) {
    if (event.key === 'Enter') {
        sendMessage();
    }
}

// HTML转义
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 切换平台
async function switchPlatform(platformId) {
    currentPlatform = platformId;
    
    // 更新标签状态
    updatePlatformTabs(platformId);
    
    // 更新标题
    document.getElementById('productListTitle').textContent = 
        `${platformNames[platformId]} - 商品列表`;
    
    // 加载对应平台的商品
    await loadPlatformProducts(platformId);
}

// 更新平台标签状态
function updatePlatformTabs(activePlatformId) {
    const tabs = ['jd', 'taobao', 'pdd', 'suning'];
    tabs.forEach(platformId => {
        const tab = document.getElementById(`platform-${platformId}-tab`);
        if (tab) {
            if (platformId === activePlatformId) {
                tab.classList.add('active');
            } else {
                tab.classList.remove('active');
            }
        }
    });
}

// 加载指定平台的商品
async function loadPlatformProducts(platformId) {
    const container = document.getElementById('productList');
    
    try {
        container.innerHTML = '<p class="text-center">加载中...</p>';
        
        const response = await fetch(`/api/platforms/${platformId}/products`);
        const data = await response.json();
        
        if (data.success) {
            currentProducts = data.products; // 保存当前商品列表
            // 清空搜索框
            document.getElementById('productSearch').value = '';
            renderPlatformProducts(currentProducts, platformId);
        } else {
            container.innerHTML = `<p class="text-danger">加载失败: ${data.error}</p>`;
        }
    } catch (error) {
        console.error('加载商品失败:', error);
        container.innerHTML = '<p class="text-danger">加载失败，请稍后重试</p>';
    }
}

// 搜索商品
function searchProducts() {
    const searchTerm = document.getElementById('productSearch').value.trim().toLowerCase();
    
    if (!searchTerm) {
        // 搜索词为空时显示所有商品
        renderPlatformProducts(currentProducts, currentPlatform);
        return;
    }
    
    // 模糊搜索：匹配商品名称、品类、颜色、内存
    const filteredProducts = currentProducts.filter(product => {
        return (
            product.product_name && product.product_name.toLowerCase().includes(searchTerm) ||
            product.category && product.category.toLowerCase().includes(searchTerm) ||
            product.color && product.color.toLowerCase().includes(searchTerm) ||
            product.memory && product.memory.toLowerCase().includes(searchTerm)
        );
    });
    
    renderPlatformProducts(filteredProducts, currentPlatform);
}

// 渲染平台商品列表
function renderPlatformProducts(products, platformId) {
    const container = document.getElementById('productList');
    
    if (!products || products.length === 0) {
        container.innerHTML = '<p class="text-muted text-center">暂无商品</p>';
        return;
    }
    
    container.innerHTML = products.map(product => `
        <div class="product-item">
            <div class="d-flex justify-content-between align-items-start">
                <div>
                    <div class="product-name">${escapeHtml(product.product_name)}</div>
                    <div class="product-info">
                        参考价: ¥${product.price} | 平台价: ¥${product.platform_price} | 
                        运费: ¥${product.shipping_fee} | 库存: ${product.stock} | 品类: ${escapeHtml(product.category)}
                        ${product.color ? ' | 颜色: ' + escapeHtml(product.color) : ''}
                        ${product.memory ? ' | 内存: ' + escapeHtml(product.memory) : ''}
                        ${!product.is_in_stock ? ' <span class="text-danger">(缺货)</span>' : ''}
                    </div>
                </div>
                <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-primary" onclick="editProduct(${product.id}, '${platformId}')">编辑</button>
                    <button class="btn btn-outline-danger" onclick="deleteProduct(${product.id}, '${platformId}')">删除</button>
                </div>
            </div>
        </div>
    `).join('');
}

// 添加商品
async function handleAddProduct(event) {
    event.preventDefault();

    const productName = document.getElementById('productName').value.trim();
    const productPrice = document.getElementById('productPrice').value;
    const productPlatformPrice = document.getElementById('productPlatformPrice').value;
    const productStock = document.getElementById('productStock').value;
    const productCategory = document.getElementById('productCategory').value.trim();
    const productColor = document.getElementById('productColor').value.trim();
    const productMemory = document.getElementById('productMemory').value.trim();
    const productShippingFee = document.getElementById('productShippingFee').value;
    const productInStock = document.getElementById('productInStock').checked;

    if (!productName || !productPrice || !productStock || !productCategory) {
        alert('请填写完整信息');
        return;
    }

    try {
        const response = await fetch(`/api/platforms/${currentPlatform}/products`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                product_name: productName,
                price: productPrice,
                platform_price: productPlatformPrice || null,
                stock: productStock,
                category: productCategory,
                color: productColor || null,
                memory: productMemory || null,
                shipping_fee: productShippingFee || 0,
                is_in_stock: productInStock
            })
        });

        const data = await response.json();

        if (data.success) {
            alert('商品添加成功！');
            document.getElementById('addProductForm').reset();
            document.getElementById('productInStock').checked = true;
            document.getElementById('productShippingFee').value = 0;
            await loadPlatformProducts(currentPlatform);
        } else {
            alert('添加失败: ' + data.error);
        }
    } catch (error) {
        console.error('添加商品失败:', error);
        alert('添加失败，请稍后重试');
    }
}

// 编辑模态框实例
let editProductModal = null;

// 商品全字段编辑
async function editProduct(productId, platformId) {
    try {
        const getResponse = await fetch(`/api/platforms/${platformId}/products`);
        const getResult = await getResponse.json();
        
        if (!getResult.success) {
            alert('获取商品信息失败');
            return;
        }
        
        const products = getResult.products;
        const product = products.find(p => p.id === productId);
        
        if (!product) {
            alert('商品不存在');
            return;
        }
        
        // 填充表单数据
        document.getElementById('editProductId').value = productId;
        document.getElementById('editProductPlatformId').value = platformId;
        document.getElementById('editProductName').value = product.product_name;
        document.getElementById('editProductPrice').value = product.price;
        document.getElementById('editProductPlatformPrice').value = product.platform_price || '';
        document.getElementById('editProductStock').value = product.stock;
        document.getElementById('editProductCategory').value = product.category;
        document.getElementById('editProductColor').value = product.color || '';
        document.getElementById('editProductMemory').value = product.memory || '';
        document.getElementById('editProductShippingFee').value = product.shipping_fee || 0;
        document.getElementById('editProductInStock').checked = product.is_in_stock;
        
        // 显示模态框
        if (!editProductModal) {
            editProductModal = new bootstrap.Modal(document.getElementById('editProductModal'));
        }
        editProductModal.show();
        
    } catch (error) {
        console.error('打开编辑界面失败:', error);
        alert('打开编辑界面失败，请稍后重试');
    }
}

// 保存编辑
async function saveEditProduct() {
    try {
        const productId = parseInt(document.getElementById('editProductId').value);
        const platformId = document.getElementById('editProductPlatformId').value;
        
        const productName = document.getElementById('editProductName').value.trim();
        const productPrice = document.getElementById('editProductPrice').value;
        const productPlatformPrice = document.getElementById('editProductPlatformPrice').value;
        const productStock = document.getElementById('editProductStock').value;
        const productCategory = document.getElementById('editProductCategory').value.trim();
        const productColor = document.getElementById('editProductColor').value.trim();
        const productMemory = document.getElementById('editProductMemory').value.trim();
        const productShippingFee = document.getElementById('editProductShippingFee').value;
        const productInStock = document.getElementById('editProductInStock').checked;
        
        if (!productName || !productPrice || !productStock || !productCategory) {
            alert('请填写完整信息');
            return;
        }
        
        const response = await fetch(`/api/platforms/${platformId}/products/${productId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                product_name: productName,
                price: productPrice || null,
                platform_price: productPlatformPrice || null,
                stock: productStock || null,
                category: productCategory || null,
                color: productColor || null,
                memory: productMemory || null,
                shipping_fee: productShippingFee || null,
                is_in_stock: productInStock
            })
        });

        const data = await response.json();

        if (data.success) {
            alert('商品更新成功！');
            editProductModal.hide();
            await loadPlatformProducts(platformId);
        } else {
            alert('更新失败: ' + data.error);
        }
    } catch (error) {
        console.error('保存商品失败:', error);
        alert('保存失败，请稍后重试');
    }
}

// 删除商品
async function deleteProduct(productId, platformId) {
    if (!confirm('确定要删除这个商品吗？')) return;

    try {
        const response = await fetch(`/api/platforms/${platformId}/products/${productId}`, {
            method: 'DELETE'
        });

        const data = await response.json();

        if (data.success) {
            alert('商品删除成功！');
            await loadPlatformProducts(platformId);
        } else {
            alert('删除失败: ' + data.error);
        }
    } catch (error) {
        console.error('删除商品失败:', error);
        alert('删除失败，请稍后重试');
    }
}

// 多平台比价
async function comparePrice() {
    const productName = document.getElementById('compareProductName').value.trim();
    if (!productName) {
        alert('请输入商品名称');
        return;
    }

    const resultDiv = document.getElementById('compareResult');
    resultDiv.innerHTML = '<p class="text-center"><span class="loading"></span> 正在查询各平台...</p>';

    try {
        const response = await fetch('/api/multi-platform/compare', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                product_name: productName
            })
        });

        const data = await response.json();

        if (data.success) {
            resultDiv.textContent = data.formatted_text;
        } else {
            resultDiv.innerHTML = `<p class="text-danger">查询失败: ${data.error}</p>`;
        }
    } catch (error) {
        console.error('比价失败:', error);
        resultDiv.innerHTML = '<p class="text-danger">查询失败，请稍后重试</p>';
    }
}

// 快速查询商品
function quickCompare(productName) {
    document.getElementById('compareProductName').value = productName;
    comparePrice();
}

// 加载快速查询商品
async function loadQuickProducts() {
    try {
        const response = await fetch('/api/multi-platform/products');
        const data = await response.json();
        if (data.success) {
            const products = [];
            for (const platformId in data.data.results) {
                const platformProducts = data.data.results[platformId].products;
                platformProducts.forEach(p => {
                    if (!products.find(x => x.product_name === p.product_name)) {
                        products.push(p);
                    }
                });
            }
            renderQuickProducts(products);
        }
    } catch (error) {
        console.error('加载商品失败:', error);
    }
}

// 渲染快速查询商品
function renderQuickProducts(products) {
    const container = document.getElementById('quickProducts');
    const uniqueNames = [...new Set(products.map(p => p.product_name))].slice(0, 8);
    container.innerHTML = uniqueNames.map(name => `
        <span class="quick-product-tag" onclick="quickCompare('${escapeHtml(name)}')">
            ${escapeHtml(name)}
        </span>
    `).join('');
}

// 页面加载初始化
document.addEventListener('DOMContentLoaded', () => {
    loadSessions();
    loadQuickProducts();
    loadPlatformProducts('jd');
    document.getElementById('addProductForm').addEventListener('submit', handleAddProduct);
    document.getElementById('saveEditProductBtn').addEventListener('click', saveEditProduct);
});
