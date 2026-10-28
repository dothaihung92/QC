// Cầu nối SEO Article Writer ↔ phần mềm Quảng cáo Fanpage (QC).
// Máy chủ QC tự chèn file này vào /seo-writer, nên thay seo-writer.html bằng bản
// mới hơn vẫn giữ được các nút dưới đây.
(function () {
  function notify(msg) {
    if (typeof toast === 'function') toast(msg); else alert(msg);
  }

  function postText() {
    var el = document.getElementById('fb-preview');
    var text = el && el.value.trim();
    if ((!text || text.startsWith('Nhấn')) && typeof buildFBPostText === 'function') text = buildFBPostText();
    return text || '';
  }

  function articleLink() {
    var el = document.getElementById('fb-article-link');
    return el ? el.value.trim() : '';
  }

  async function sendToQC(publish) {
    var message = postText();
    var link = articleLink();
    if (!message) { notify('Chưa có nội dung post — tạo bài viết rồi bấm "Tạo tiêu đề" trước'); return; }
    // Đăng lên Page qua API thì link gắn thẳng vào bài, không cần "link ở cmt ghim".
    if (link) message = message.split('\n').filter(function (l) { return !/cmt ghim/i.test(l); }).join('\n').trim();
    if (publish && !confirm('Đăng bài này lên Fanpage ngay?')) return;
    try {
      var r = await fetch('/api/posts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: message, link: link, template_key: 'seo-writer', publish_now: !!publish })
      });
      var d = await r.json().catch(function () { return {}; });
      if (!r.ok) { notify('⚠ ' + (d.detail || r.statusText)); return; }
      if (window.parent !== window) window.parent.postMessage({ qc: 'post-saved', id: d.id }, location.origin);
      notify(d.status === 'posted' ? '✅ Đã đăng lên Fanpage'
        : d.status === 'failed' ? '⚠ Đăng lỗi: ' + d.error
        : '💾 Đã lưu nháp — xem ở tab Bài đăng');
    } catch (e) {
      notify('⚠ Không kết nối được phần mềm QC: ' + e.message);
    }
  }

  function addButtons() {
    var openBtn = document.getElementById('fb-open-btn');
    if (!openBtn || document.getElementById('qc-bridge-row')) return;
    var row = document.createElement('div');
    row.id = 'qc-bridge-row';
    row.style.cssText = 'display:flex;gap:8px;margin-top:8px';
    row.innerHTML =
      '<button class="btn btn-sm" id="qc-draft-btn" style="flex:1;justify-content:center;font-size:12px">' +
      '💾 Lưu nháp vào QC</button>' +
      '<button class="btn-fb" id="qc-publish-btn" style="flex:1;justify-content:center">' +
      '📤 Đăng ngay lên Fanpage</button>';
    openBtn.parentNode.insertAdjacentElement('afterend', row);
    document.getElementById('qc-draft-btn').onclick = function () { sendToQC(false); };
    document.getElementById('qc-publish-btn').onclick = function () { sendToQC(true); };
  }

  function addBackLink() {
    var a = document.createElement('a');
    a.href = '/';
    a.textContent = '← Bảng điều khiển QC';
    a.style.cssText = 'position:fixed;right:14px;bottom:14px;z-index:9999;background:#1877f2;color:#fff;' +
      'padding:8px 14px;border-radius:99px;font:600 13px system-ui,sans-serif;text-decoration:none;' +
      'box-shadow:0 2px 8px rgba(0,0,0,.2)';
    document.body.appendChild(a);
  }

  function init() {
    addButtons();
    if (window.parent === window) addBackLink(); // mở trong tab của bảng điều khiển thì không cần
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
  window.qcSendToFanpage = sendToQC;
})();
