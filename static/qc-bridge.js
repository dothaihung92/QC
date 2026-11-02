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

  // Nhận bài tin từ tab "Tin tức AI" → điền form → tự bấm "Tạo bài viết chuẩn SEO".
  function legalRef(text) {
    var m = /(Nghị định|Thông tư|Công văn|Nghị quyết|Quyết định)\s+(?:số\s+)?\d+\/[\w\u00C0-\u1EF9\-\/]+/i.exec(text || '');
    return m ? m[0].replace(/[.,;:]+$/, '') : '';
  }
  var lastJob = 0;
  function runJob(job) {
    if (!job || job.id === lastJob) return;
    if (typeof generate !== 'function' || !document.getElementById('kw')) { setTimeout(function () { runJob(job); }, 300); return; }
    lastJob = job.id;
    try { localStorage.removeItem('qc_seo_job'); } catch (e) {}
    var set = function (id, v) { var el = document.getElementById(id); if (el) el.value = v; };
    var body = String(job.body || '').replace(/\s+\n/g, '\n').slice(0, 7000);
    set('kw', job.title || '');
    set('legal-ref', legalRef((job.title || '') + ' ' + body));
    set('legal-link', '');
    set('legal-content', 'BÀI TIN GỐC' + (job.source ? ' (' + job.source + ')' : '') + ': ' + (job.title || '') +
      (job.url ? '\nNguồn: ' + job.url : '') + '\n\n' + body);
    window._answerQuestionContext = null;
    if (!(document.getElementById('gkey') || {}).value) {
      notify('⚠ Chưa có Gemini API Key — nhập key ở mục 1 rồi bấm "Tạo bài viết chuẩn SEO" (đã điền sẵn nội dung).');
      return;
    }
    notify('✍️ Đang tạo bài SEO từ bài tin...');
    generate();
  }
  window.addEventListener('message', function (e) {
    if (e.origin === location.origin && e.data && e.data.qc === 'seo-job') runJob(e.data.job);
  });
  function checkPendingJob() {
    try { var raw = localStorage.getItem('qc_seo_job'); if (raw) runJob(JSON.parse(raw)); } catch (e) {}
  }

  // ── Tự tìm văn bản pháp luật trong bài và gắn link THẬT (phần mềm QC tìm + mở thử từng link) ──
  var VERIFY = 'verify';
  function addVerifyOption() {
    var sel = document.getElementById('legal-link-mode');
    if (!sel || sel.querySelector('option[value="' + VERIFY + '"]')) return;
    var o = document.createElement('option');
    o.value = VERIFY;
    o.textContent = '🔎 Tự tìm & gắn link THẬT (phần mềm kiểm tra từng link) — khuyên dùng';
    sel.insertBefore(o, sel.firstChild);
    var hint = sel.parentNode.querySelector('.hint-txt');
    if (hint) {
      hint.style.color = '#0d9488';
      hint.textContent = '🔎 Chế độ "Tự tìm & gắn link THẬT": sau khi AI viết xong, phần mềm tự tìm từng Nghị định/Thông tư/Luật/Công văn ' +
        'trong bài trên thuvienphapluat.vn, vanban.chinhphu.vn, luatvietnam.vn…, mở thử để chắc link đúng văn bản rồi mới gắn. ' +
        'Không tìm được link chắc chắn thì chỉ ghi tên văn bản.';
    }
    try {                                   // lần đầu dùng bản này: chuyển sang chế độ tự tìm link
      if (!localStorage.getItem('qc_legal_verify_default')) {
        localStorage.setItem('qc_legal_verify_default', '1');
        localStorage.setItem('legal_link_mode', VERIFY);
      }
    } catch (e) {}
  }
  addVerifyOption();                         // chạy ngay, trước khi trang tự nạp lựa chọn đã lưu

  var linking = false, verified = {};
  async function linkArticle() {
    if (typeof curArticle === 'undefined' || !curArticle || linking) return;
    var a = curArticle;
    var secs = a.sections || [], qa = a.qa || [];
    var parts = secs.map(function (s) { return s.content || ''; })
      .concat([a.conclusion || ''])
      .concat(qa.map(function (q) { return q.a || ''; }));
    linking = true;
    notify('🔎 Đang tìm & kiểm tra link các văn bản pháp luật trong bài...');
    try {
      var r = await fetch('/api/legal/links', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ parts: parts, gemini_key: (document.getElementById('gkey') || {}).value || '' })
      });
      var d = await r.json().catch(function () { return {}; });
      if (!r.ok) { notify('⚠ Không gắn được link văn bản: ' + (d.detail || r.statusText)); return; }
      if (curArticle !== a) return;          // đã tạo bài khác trong lúc chờ
      var out = d.parts || parts;
      secs.forEach(function (s, i) {
        if (out[i] === parts[i]) return;
        s.content = out[i];
        var el = document.getElementById('ed-content-' + i);
        if (el) el.innerHTML = out[i];
      });
      var k = secs.length;
      if (out[k] !== parts[k]) {
        a.conclusion = out[k];
        var c = document.getElementById('ed-conc');
        if (c) c.innerHTML = out[k];
      }
      qa.forEach(function (q, i) {
        if (out[k + 1 + i] === parts[k + 1 + i]) return;
        q.a = out[k + 1 + i];
        var el = document.querySelector('#qa-' + i + ' .qa-a');
        if (el) el.innerHTML = q.a;
      });
      var refs = d.refs || [];
      refs.forEach(function (x) { if (x.url) verified[x.url] = 1; });
      var ok = refs.filter(function (x) { return x.url; });
      var miss = refs.filter(function (x) { return !x.url; });
      if (!refs.length) notify('ℹ Bài không nhắc số hiệu văn bản pháp luật nào để gắn link');
      else notify('🔗 Đã gắn link ' + ok.length + '/' + refs.length + ' văn bản' +
        (miss.length ? ' — chưa tìm được link chắc chắn: ' + miss.map(function (x) { return x.code; }).join(', ') : ''));
    } catch (e) {
      notify('⚠ Không gắn được link văn bản: ' + e.message);
    } finally {
      linking = false;
    }
  }
  window.qcLinkLegalDocs = linkArticle;

  function wrapGenerator() {
    if (typeof generate === 'function' && !generate._qc) {
      var origGen = generate;
      // Khi tự tìm link: bảo AI KHÔNG tự gắn link luật (hay sai) — phần mềm sẽ gắn link đã kiểm tra.
      window.generate = async function () {
        var sel = document.getElementById('legal-link-mode');
        var verify = sel && sel.value === VERIFY;
        if (verify) { sel.value = 'strip'; window._qcVerifying = true; }
        try { return await origGen.apply(this, arguments); }
        finally { if (verify) { sel.value = VERIFY; window._qcVerifying = false; } }
      };
      window.generate._qc = true;
    }
    if (typeof renderArticle === 'function' && !renderArticle._qc) {
      var origRender = renderArticle;
      window.renderArticle = function (a) {
        var sel = document.getElementById('legal-link-mode');
        var verify = window._qcVerifying || (sel && sel.value === VERIFY);
        if (verify && a) {                     // bỏ link luật AI tự gắn (chưa kiểm tra), giữ link phần mềm đã kiểm tra
          var strip = function (h) {
            return String(h || '').replace(/<a\s+[^>]*href=["']([^"']*)["'][^>]*>([\s\S]*?)<\/a>/gi, function (m, url, text) {
              var legal = typeof isLegalLink === 'function' ? isLegalLink(url) : /thuvienphapluat|luatvietnam|chinhphu\.vn/i.test(url);
              return legal && !verified[url] ? '<strong>' + text + '</strong>' : m;
            });
          };
          (a.sections || []).forEach(function (s) { if (s.content) s.content = strip(s.content); });
          if (a.conclusion) a.conclusion = strip(a.conclusion);
          (a.qa || []).forEach(function (q) { if (q.a) q.a = strip(q.a); });
        }
        var res = origRender.apply(this, arguments);
        if (verify) setTimeout(linkArticle, 50);
        return res;
      };
      window.renderArticle._qc = true;
    }
  }
  wrapGenerator();

  function init() {
    addVerifyOption();
    wrapGenerator();
    addButtons();
    setTimeout(checkPendingJob, 400);
    if (window.parent === window) addBackLink(); // mở trong tab của bảng điều khiển thì không cần
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
  window.qcSendToFanpage = sendToQC;
})();
