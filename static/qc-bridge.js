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
    jobImage = job.image || null;              // ảnh của bài tin → dùng làm ảnh đầu bài SEO
    set('kw', job.title || '');
    set('legal-ref', legalRef((job.title || '') + ' ' + body));
    set('legal-link', '');
    set('legal-content', 'BÀI TIN GỐC' + (job.source ? ' (' + job.source + ')' : '') + ': ' + (job.title || '') +
      (job.url ? '\nNguồn: ' + job.url : '') + '\n\n' + body);
    window._answerQuestionContext = null;
    var rs = document.getElementById('research-status');
    if (rs) rs.innerHTML = '';                               // xóa kết quả nghiên cứu của bài trước
    window.scrollTo({ top: 0, behavior: 'smooth' });
    if (!(document.getElementById('gkey') || {}).value) {
      var msg = '⚠ Chưa có Gemini API Key — nhập key ở mục 1 rồi bấm "Tạo bài viết chuẩn SEO" (nội dung bài tin đã điền sẵn).';
      if (typeof showErr === 'function') showErr(msg); else notify(msg);
      return;
    }
    var info = '✍️ Đang tự tạo bài SEO từ bài tin: "' + (job.title || '') + '" — AI đặt từ khóa, nghiên cứu nguồn rồi viết bài (khoảng 1–3 phút)...';
    if (typeof showInfo === 'function') showInfo(info); else notify(info);
    window._qcJobInfo = true;
    if (window.qcFaithful) window.qcFaithful.begin({ title: job.title || '', body: body, url: job.url || '' });   // bám sát bài gốc
    setBusy(true, 'Đang đặt từ khóa...');
    shortKeyword(job.title || '', body).then(function (k) { if (k) set('kw', k); generate(); });
  }
  window.addEventListener('message', function (e) {
    if (e.origin === location.origin && e.data && e.data.qc === 'seo-job') runJob(e.data.job);
  });
  // Đường dự phòng: tab Tin tức AI ghi bài vào bộ nhớ chung → trang này nhận được ngay cả khi lỡ tin nhắn
  window.addEventListener('storage', function (e) {
    if (e.key === 'qc_seo_job' && e.newValue) { try { runJob(JSON.parse(e.newValue)); } catch (err) {} }
  });
  function setBusy(on, text) {
    var b = document.getElementById('genbtn');
    if (!b) return;
    if (on) {
      if (!b._qcHtml) b._qcHtml = b.innerHTML;
      b.disabled = true;
      b.innerHTML = '<i class="ti ti-loader-2 spin"></i> ' + (text || 'Đang viết bài...');
    } else if (b._qcHtml) {
      b.disabled = false;
      b.innerHTML = b._qcHtml;
      b._qcHtml = null;
    }
  }
  function checkPendingJob() {
    try { var raw = localStorage.getItem('qc_seo_job'); if (raw) runJob(JSON.parse(raw)); } catch (e) {}
  }

  // ── Tự tìm văn bản pháp luật trong bài và gắn link THẬT (phần mềm QC tìm + mở thử từng link) ──
  var VERIFY = 'verify';
  function addVerifyOption() {
    var sel = document.getElementById('legal-link-mode');
    if (!sel || sel.querySelector('option[value="' + VERIFY + '"]')) return;
    // Bỏ chế độ "Để AI tự tìm link" (AI hay gắn link sai / tự bịa link)
    var aiOpt = sel.querySelector('option[value="ai"]');
    if (aiOpt) aiOpt.remove();
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
      if (localStorage.getItem('legal_link_mode') === 'ai') localStorage.setItem('legal_link_mode', VERIFY);
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
        body: JSON.stringify({ parts: parts, gemini_key: (document.getElementById('gkey') || {}).value || '',
                               keep: [(document.getElementById('legal-link') || {}).value || ''] })
      });
      var d = await r.json().catch(function () { return {}; });
      if (!r.ok) { notify('⚠ Không gắn được link văn bản: ' + (d.detail || r.statusText)); return; }
      if (curArticle !== a) return;          // đã tạo bài khác trong lúc chờ
      var out = d.parts || parts;
      secs.forEach(function (s, i) {
        if (out[i] === parts[i] || (s.content || '') !== parts[i]) return;   // đoạn đã bị sửa trong lúc chờ → bỏ qua
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

  // ── Tiêu đề trọn câu + chứa ĐÚNG từ khóa ──────────────────────────────────
  // Trước đây: tiêu đề dài bị cắt cứng ở 70 ký tự → cụt câu; dấu "/" "-" bị xóa làm hỏng số hiệu
  // (398/2026/NĐ-CP → "398 2026 NĐ CP"); tiêu đề không bắt buộc chứa đúng từ khóa.
  var DANGLING = /\s(và|của|cho|với|để|các|những|khi|từ|theo|trong|về|là|có|được|tại|đến|nếu|hay|hoặc|thì|mà|bị|như|một|vào|tới|bao|nhằm|gồm)$/i;
  function norm(t) { return String(t || '').toLowerCase().replace(/\s+/g, ' ').trim(); }
  function hasKw(text, kw) { return !!kw && norm(text).indexOf(norm(kw)) >= 0; }
  function cap(t) { t = String(t || '').trim(); return t.charAt(0).toUpperCase() + t.slice(1); }
  function isShortKw(k) { k = String(k || '').trim(); return k.length >= 3 && k.length <= 60 && k.split(/\s+/).length <= 9; }
  function titleOk(t, kw) {
    t = String(t || '').trim();
    return t.length >= 35 && t.length <= 60 && hasKw(t, kw) && !DANGLING.test(t) && !/[,;:–—\-|]$/.test(t) && !/\.\.\.|…$/.test(t);
  }
  function metaOk(m, kw) {
    m = String(m || '').trim();
    return m.length >= 120 && m.length <= 158 && hasKw(m, kw) && /[.!?)]$/.test(m);
  }
  function cleanTitle(t) {     // bỏ dấu phân cách có khoảng trắng, GIỮ "/" "-" trong số hiệu văn bản, năm 2026-2027
    return String(t || '').replace(/\s*[:|]\s+|\s+[–—\-]\s+/g, ', ').replace(/,\s*,/g, ',').replace(/\s{2,}/g, ' ')
      .replace(/^[,\s]+|[,\s]+$/g, '').trim();
  }
  async function askJSON(prompt) {
    var gkey = ((document.getElementById('gkey') || {}).value || '').trim();
    if (!gkey || typeof callGeminiWithFallback !== 'function') return null;
    try {
      var res = await callGeminiWithFallback(gkey, {
        contents: [{ role: 'user', parts: [{ text: prompt }] }],
        generationConfig: { temperature: 0.4, maxOutputTokens: 1500, responseMimeType: 'application/json' }
      });
      var c = ((res.data.candidates || [])[0] || {}).content;
      var raw = c ? (c.parts || []).map(function (p) { return p.text || ''; }).join('') : '';
      return typeof extractJSON === 'function' ? extractJSON(raw) : JSON.parse(raw);
    } catch (e) { return null; }
  }
  async function shortKeyword(title, body) {
    var j = await askJSON('Đặt 1 TỪ KHÓA SEO chính (2-6 từ, cách người Việt gõ tìm trên Google, viết thường, có dấu) cho bài sau. ' +
      'Chỉ trả về JSON {"keyword":"..."}.\nTiêu đề: ' + title + '\nNội dung: ' + String(body || '').slice(0, 1500));
    var k = j && String(j.keyword || '').trim();
    if (isShortKw(k)) return k;
    return isShortKw(title) ? title : title.split(/\s+/).slice(0, 6).join(' ').replace(/[,:;.]+$/, '');
  }
  function fallbackTitle(kw, oldTitle) {
    var K = cap(kw);
    var tails = [' và những điều doanh nghiệp cần biết', ' mới nhất doanh nghiệp cần biết', ' hướng dẫn chi tiết và dễ hiểu',
                 ' mới nhất năm ' + new Date().getFullYear(), ' cần biết'];
    for (var i = 0; i < tails.length; i++) if ((K + tails[i]).length <= 60 && (K + tails[i]).length >= 35) return K + tails[i];
    return K.length <= 60 ? K : oldTitle;
  }
  function refreshSidebar(a) {
    var te = document.getElementById('seo-title-edit');
    if (te) te.value = a.title;
    if (typeof updateSEOField === 'function') updateSEOField('title', a.title);
    var ke = document.getElementById('seo-kw-edit');
    if (ke) ke.value = a.focusKeyword;
    document.querySelectorAll('#sidebar .meta-pill').forEach(function (p) {
      var lbl = p.querySelector('.meta-lbl'), val = p.querySelector('.meta-val');
      if (lbl && val && /Meta Description/i.test(lbl.textContent)) {
        val.textContent = a.metaDescription;
        if (typeof charBadge === 'function') lbl.innerHTML = 'Meta Description ' + charBadge(a.metaDescription, 160);
      }
    });
    if (typeof seoScore === 'function') {          // chấm lại điểm SEO
      var card = document.querySelector('#sidebar .side-card');
      var r = seoScore(a);
      if (card && r) card.innerHTML = '<div class="side-title"><i class="ti ti-chart-bar" style="font-size:14px"></i>SEO Score</div>' +
        '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px"><span style="font-size:13px;color:var(--text2)">Điểm tổng</span>' +
        '<span style="font-size:26px;font-weight:700;color:' + r.cl + '">' + r.sc + '%</span></div>' +
        '<div class="sc-bar"><div class="sc-fill" style="width:' + r.sc + '%;background:' + r.cl + '"></div></div>' +
        r.checks.map(function (c) { return '<div class="chk-row"><i class="ti ' + (c.ok ? 'ti-circle-check' : 'ti-circle-x') +
          '" style="color:' + (c.ok ? 'var(--success)' : 'var(--danger)') + '"></i><span>' + c.lbl + '</span></div>'; }).join('');
    }
  }
  async function fixTitleKeyword(a) {
    var kwEl = document.getElementById('kw');
    var userKw = ((kwEl || {}).value || '').trim();
    var kw = isShortKw(userKw) ? userKw : (isShortKw(a.focusKeyword) ? String(a.focusKeyword).trim() : await shortKeyword(userKw || a.title, ''));
    a.focusKeyword = kw;
    var full = cleanTitle(a._qcFullTitle || a.title);
    if (titleOk(full, kw) && metaOk(a.metaDescription, kw)) {
      a.title = full;
      refreshSidebar(a);                       // luôn cập nhật ô Từ khóa SEO (AI có lúc không trả focusKeyword → "undefined")
      return;
    }
    notify('✏️ Đang chỉnh tiêu đề cho trọn câu và chứa đúng từ khóa "' + kw + '"...');
    var bodyTxt = (a.sections || []).map(function (s) { return (s.heading || '') + ' ' + plain(s.content); }).join(' ').slice(0, 1500);
    var j = await askJSON('Từ khóa SEO chính: "' + kw + '".\nTiêu đề hiện tại: "' + full + '".\nNội dung bài: ' + bodyTxt +
      '\n\nViết 6 TIÊU ĐỀ (H1) khác nhau. Mỗi tiêu đề: là MỘT CÂU HOÀN CHỈNH, trọn nghĩa, không bị bỏ lửng; dài 45-58 ký tự (đếm cả dấu cách, TỐI ĐA 60); ' +
      'chứa NGUYÊN VĂN cụm từ khóa "' + kw + '" (đúng chính tả, đúng dấu, đúng thứ tự), ưu tiên đặt từ khóa ở đầu; ' +
      'không dùng dấu ":" "|" " - " để ngăn cách; không kết thúc bằng "..." hay giới từ/liên từ; giữ nguyên số hiệu văn bản, con số trong bài.\n' +
      'Viết thêm 2 META DESCRIPTION: 140-155 ký tự (tối đa 158), mở đầu bằng từ khóa "' + kw + '", là câu hoàn chỉnh, kết bằng lời mời hành động và dấu chấm.\n' +
      'Chỉ trả về JSON {"titles":["..."],"metas":["..."]}');
    var titles = ((j && j.titles) || []).map(function (t) { return cleanTitle(t).replace(/["“”]/g, ''); });
    var good = titles.filter(function (t) { return titleOk(t, kw); });
    var lead = function (x) { return norm(x).indexOf(norm(kw)) === 0 ? 1 : 0; };   // từ khóa đứng đầu → ưu tiên
    good.sort(function (x, y) { return lead(y) - lead(x); });
    var t = titleOk(full, kw) ? full : (good[0] || fallbackTitle(kw, full));
    var metas = ((j && j.metas) || []).map(function (m) { return String(m || '').trim(); }).filter(function (m) { return metaOk(m, kw); });
    a.title = t;
    if (!metaOk(a.metaDescription, kw) && metas[0]) a.metaDescription = metas[0];
    refreshSidebar(a);
    notify(titleOk(t, kw) ? '✅ Tiêu đề: "' + t + '" (' + t.length + ' ký tự, có từ khóa)' : '⚠ Nên xem lại tiêu đề — chưa tạo được tiêu đề đạt chuẩn');
  }
  // Giới hạn SEO của trang gốc: không cắt cụt tiêu đề / meta nữa (tiêu đề dài sẽ được AI viết lại trọn câu).
  function wrapLimits() {
    if (typeof enforceSEOLimits === 'function' && !enforceSEOLimits._qc) {
      var orig = enforceSEOLimits;
      window.enforceSEOLimits = function (a) {
        if (!a) return a;
        var title = cleanTitle(a.title), meta = a.metaDescription;
        var out = orig.apply(this, arguments) || a;
        out.title = title;                      // giữ nguyên câu (chỉ bỏ dấu phân cách)
        out._qcFullTitle = title;
        if (meta) out.metaDescription = meta;
        return out;
      };
      window.enforceSEOLimits._qc = true;
    }
  }
  wrapLimits();
  window.qcTitle = { refresh: refreshSidebar, titleOk: titleOk, metaOk: metaOk, cleanTitle: cleanTitle, fallbackTitle: fallbackTitle, fix: fixTitleKeyword };

  function wrapGenerator() {
    if (typeof generate === 'function' && !generate._qc) {
      var origGen = generate;
      // Khi tự tìm link: bảo AI KHÔNG tự gắn link luật (hay sai) — phần mềm sẽ gắn link đã kiểm tra.
      window.generate = async function () {
        var sel = document.getElementById('legal-link-mode');
        var verify = sel && sel.value === VERIFY;
        if (verify) { sel.value = 'strip'; window._qcVerifying = true; }
        var before = typeof curArticle !== 'undefined' ? curArticle : null;
        setBusy(true, 'Đang nghiên cứu & viết bài...');      // nút hiện rõ đang chạy (trang gốc không đổi nút)
        try { return await origGen.apply(this, arguments); }
        finally {
          if (verify) { sel.value = VERIFY; window._qcVerifying = false; }
          if (window.qcFaithful && window.qcFaithful.active()) {       // bài từ Tin tức AI: đối chiếu + sửa cho đúng bài gốc
            var made = typeof curArticle !== 'undefined' && curArticle && curArticle !== before ? curArticle : null;
            setBusy(true, 'Đang đối chiếu với bài gốc...');
            try { await window.qcFaithful.end(made); } catch (e) { console.warn('qcFaithful', e); }
          }
          if (typeof curArticle !== 'undefined' && curArticle && curArticle !== before) {
            setBusy(true, 'Đang chỉnh tiêu đề...');
            try { await fixTitleKeyword(curArticle); } catch (e) { console.warn('fixTitleKeyword', e); }
            setBusy(true, 'Đang tối ưu SEO (URL, từ khóa, ảnh)...');
            try { if (window.qcSeo) await window.qcSeo.finalize(curArticle, true); } catch (e) { console.warn('qcSeo.finalize', e); }
          }
          setBusy(false);
          if (window._qcJobInfo) {                // tắt khung "Đang tự tạo bài..." (vòng xoay) khi đã xong
            window._qcJobInfo = false;
            var inf = document.getElementById('ainfo');
            if (inf) inf.style.display = 'none';
            if (typeof curArticle !== 'undefined' && curArticle && curArticle !== before)
              notify('✅ Đã tạo xong bài SEO — kiểm tra lại rồi bấm "Đăng lên website"');
          }
        }
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
              var own = ((document.getElementById('legal-link') || {}).value || '').trim();
              return legal && !verified[url] && url !== own ? '<strong>' + text + '</strong>' : m;
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

  // ── Ảnh khớp nội dung bài ─────────────────────────────────────────────
  // Trước đây: từ khóa ảnh chung chung + "vietnam" → ra ảnh du lịch/phong cảnh; chọn ảnh ngẫu nhiên
  // trong 5 trang kết quả; không có key thì lấy ảnh ngẫu nhiên (picsum.photos) → ảnh không liên quan.
  // Bây giờ: AI đọc TỪNG ĐOẠN rồi đặt từ khóa ảnh tiếng Anh cụ thể; chấm điểm mô tả ảnh (Pexels alt,
  // Pixabay tags) với từ khóa, loại ảnh du lịch/phong cảnh; không có ảnh khớp thì tạo ảnh bìa có
  // tiêu đề đoạn (luôn đúng nội dung) thay vì ảnh ngẫu nhiên. Bài từ "Tin tức AI" dùng ảnh của bài tin.
  var STOP = { a: 1, an: 1, the: 1, of: 1, and: 1, or: 1, in: 1, on: 1, at: 1, to: 1, for: 1, with: 1, by: 1,
    is: 1, are: 1, from: 1, vietnam: 1, vietnamese: 1, asian: 1, asia: 1, photo: 1, image: 1, stock: 1, scene: 1 };
  var OFF_TOPIC = /\b(temple|pagoda|beach|landscape|mountain|lake|river|noodle|pho|motorbike|scooter|rice field|terrace|bay|tourist|travel|boat|lantern|vacation|wedding|church|sunset|forest|waterfall|island|hotel|resort|dish|food|cuisine|dance|festival|flower|animal|dog|cat|bird)\b/i;
  var VI_EN = [[/hóa đơn/i, 'invoice receipt'], [/thuế/i, 'tax documents calculator'], [/kế toán/i, 'accountant bookkeeping'],
    [/quyết toán/i, 'tax return forms'], [/hộ kinh doanh|cửa hàng|tiểu thương/i, 'small shop owner'],
    [/doanh nghiệp|công ty/i, 'business office team'], [/lương|tiền công|người lao động/i, 'employee salary payroll'],
    [/bảo hiểm|bhxh/i, 'social insurance documents'], [/ngân hàng|tài khoản/i, 'bank account payment'],
    [/phạt|vi phạm|cưỡng chế/i, 'penalty notice documents'], [/doanh thu|lợi nhuận|lãi|lỗ/i, 'revenue profit chart'],
    [/hợp đồng/i, 'contract signing'], [/luật|nghị định|thông tư|quy định/i, 'law regulation documents'],
    [/kê khai|tờ khai|nộp/i, 'filling tax form laptop'], [/hoàn thuế/i, 'tax refund money']];

  function words(s) {
    return String(s || '').toLowerCase().replace(/[^a-z0-9\s]/g, ' ').split(/\s+/)
      .filter(function (w) { return w.length > 2 && !STOP[w]; })
      .map(function (w) { return w.replace(/(ies)$/, 'y').replace(/([^s])s$/, '$1'); });
  }
  function matchScore(query, desc) {
    var q = words(query), d = {};
    words(desc).forEach(function (w) { d[w] = 1; });
    if (!q.length) return 0;
    var hit = q.filter(function (w) { return d[w]; }).length;
    var sc = hit / q.length;
    if (OFF_TOPIC.test(desc) && !OFF_TOPIC.test(query)) sc -= 1;        // ảnh du lịch/món ăn… cho bài thuế
    return sc;
  }
  function plain(html) { return String(html || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim(); }
  function viToEn(text) {
    var out = [];
    VI_EN.forEach(function (p) { if (p[0].test(text) && out.length < 3) out.push(p[1]); });
    return out.length ? out : ['business documents office'];
  }

  async function stockCandidates(q) {
    var out = [], pex = localStorage.getItem('pexkey'), pxb = localStorage.getItem('pkey');
    if (pex) {
      try {
        var r = await fetch('https://api.pexels.com/v1/search?per_page=40&orientation=landscape&query=' + encodeURIComponent(q),
          { headers: { Authorization: pex } });
        if (r.ok) ((await r.json()).photos || []).forEach(function (p) {
          var src = p.src && (p.src.large || p.src.medium);
          if (src) out.push({ src: src, desc: (p.alt || '') + ' ' + String(p.url || '').split('/').slice(-2, -1)[0].replace(/-/g, ' ') });
        });
      } catch (e) {}
    }
    if (pxb) {
      try {
        var r2 = await fetch('https://pixabay.com/api/?image_type=photo&orientation=horizontal&safesearch=true&per_page=40&min_width=600&key=' +
          pxb + '&q=' + encodeURIComponent(q));
        if (r2.ok) ((await r2.json()).hits || []).forEach(function (h) { out.push({ src: h.webformatURL, desc: h.tags || '' }); });
      } catch (e) {}
    }
    return out;
  }

  // Chọn ảnh có mô tả khớp từ khóa nhất (bỏ ảnh đã dùng); skip = số ảnh tốt bỏ qua (nút "Tìm ảnh mới").
  async function pickStock(queries, used, skip) {
    var pool = [];
    for (var i = 0; i < queries.length; i++) {
      var cands = await stockCandidates(queries[i]);
      cands.forEach(function (c, rank) {
        if (used[c.src]) return;
        // điểm khớp + ưu tiên nhẹ kết quả đứng đầu + ưu tiên từ khóa đầu (cụ thể nhất)
        pool.push({ src: c.src, sc: matchScore(queries[i], c.desc) + (0.15 * (1 - rank / 40)) - i * 0.05 });
      });
      var good = pool.filter(function (p) { return p.sc >= 0.6; });
      if (good.length > (skip || 0)) break;                     // đủ ảnh khớp → khỏi tìm thêm
    }
    pool.sort(function (a, b) { return b.sc - a.sc; });
    pool = pool.filter(function (p) { return p.sc >= 0.35; });  // dưới ngưỡng = không liên quan → bỏ
    return pool.length ? pool[(skip || 0) % pool.length].src : null;
  }

  // Ảnh bìa có tiêu đề đoạn — luôn khớp nội dung (dùng khi không có ảnh kho phù hợp / chưa có key ảnh).
  function titleCard(heading, idx) {
    return new Promise(function (resolve) {
      var c = document.createElement('canvas');
      c.width = 1200; c.height = 630;
      var g = c.getContext('2d');
      var themes = [['#0f3d91', '#1e6fd9'], ['#0b6e4f', '#18a274'], ['#7a2e8e', '#b04fc9'], ['#9a3412', '#ea580c'], ['#1e3a5f', '#2f6aa3']];
      var t = themes[(idx || 0) % themes.length];
      var grd = g.createLinearGradient(0, 0, 1200, 630);
      grd.addColorStop(0, t[0]); grd.addColorStop(1, t[1]);
      g.fillStyle = grd; g.fillRect(0, 0, 1200, 630);
      g.globalAlpha = 0.08; g.fillStyle = '#fff';
      for (var k = 0; k < 6; k++) { g.beginPath(); g.arc(1000 - k * 60, 120 + k * 70, 160 - k * 18, 0, 7); g.fill(); }
      g.globalAlpha = 1;
      var icon = /hóa đơn/i.test(heading) ? '🧾' : /lương|lao động/i.test(heading) ? '👥' : /phạt|vi phạm/i.test(heading) ? '⚠️'
        : /doanh thu|lãi|lỗ|lợi nhuận|%/i.test(heading) ? '📊' : /luật|nghị định|thông tư|quy định/i.test(heading) ? '⚖️'
        : /hỏi|\?/.test(heading) ? '💬' : '📌';
      // Chữ canh giữa, chừa lề rộng 2 bên: khung xem trước cắt ảnh theo chiều ngang vẫn không mất chữ
      g.textAlign = 'center';
      g.font = '96px "Segoe UI Emoji","Apple Color Emoji","Noto Color Emoji",sans-serif';
      g.fillText(icon, 600, 160);
      g.fillStyle = '#fff';
      var size = 64, lines;
      do {                                                     // thu nhỏ chữ cho vừa tối đa 4 dòng
        g.font = 'bold ' + size + 'px "Segoe UI",Roboto,Arial,sans-serif';
        lines = []; var cur = '';
        String(heading || '').split(/\s+/).forEach(function (w) {
          var tr = cur ? cur + ' ' + w : w;
          if (g.measureText(tr).width > 760 && cur) { lines.push(cur); cur = w; } else cur = tr;
        });
        if (cur) lines.push(cur);
        size -= 4;
      } while (lines.length > 4 && size > 30);
      var lh = size + 18, top = 330 - (Math.min(lines.length, 4) - 1) * lh / 2;
      lines.slice(0, 4).forEach(function (l, i) { g.fillText(l, 600, top + i * lh); });
      var brand = ((document.getElementById('cta-title') || {}).value || '').trim();
      if (brand) { g.font = '600 30px "Segoe UI",Roboto,Arial,sans-serif'; g.globalAlpha = 0.85; g.fillText(brand, 600, 580); }
      c.toBlob(function (b) { resolve(b ? URL.createObjectURL(b) : c.toDataURL('image/jpeg', 0.9)); }, 'image/jpeg', 0.9);
    });
  }

  // AI đọc từng đoạn → 3 từ khóa ảnh tiếng Anh cụ thể cho mỗi đoạn.
  async function aiImageQueries(a) {
    var gkey = ((document.getElementById('gkey') || {}).value || '').trim();
    var secs = (a.sections || []).map(function (s, i) { return { i: i, s: s }; }).filter(function (x) { return x.s.imageQuery; });
    if (!gkey || !secs.length || typeof callGeminiWithFallback !== 'function') return null;
    var list = secs.map(function (x) {
      return '#' + x.i + ' | ' + (x.s.heading || a.title || '') + ' | ' + plain(x.s.content).slice(0, 350);
    }).join('\n');
    var prompt = 'Bài viết: "' + (a.title || '') + '". Với MỖI đoạn dưới đây, đặt 3 từ khóa tìm ẢNH KHO (Pexels/Pixabay) bằng TIẾNG ANH, ' +
      'mỗi từ khóa 2-4 từ, mô tả VẬT/NGƯỜI/HÀNH ĐỘNG cụ thể nhìn thấy được, khớp đúng nội dung đoạn đó ' +
      '(vd đoạn về giảm thuế cho hộ kinh doanh → "small shop owner calculator", "tax form documents", "cashier counting money"; ' +
      'đoạn về hóa đơn điện tử → "electronic invoice laptop"; đoạn về lương → "payroll salary envelope"). ' +
      'KHÔNG dùng tên quốc gia, phong cảnh, du lịch, địa danh, món ăn, từ trừu tượng (policy, success, growth). ' +
      'Từ khóa đầu tiên là cụ thể nhất. Các đoạn khác nhau phải có ảnh khác nhau.\n' + list +
      '\nTrả về CHỈ JSON: {"items":[{"i":0,"q":["...","...","..."]}]}';
    try {
      var res = await callGeminiWithFallback(gkey, {
        contents: [{ role: 'user', parts: [{ text: prompt }] }],
        generationConfig: { temperature: 0.3, maxOutputTokens: 2000, responseMimeType: 'application/json' }
      });
      var raw = ((res.data.candidates || [])[0] || {}).content;
      raw = raw ? (raw.parts || []).map(function (p) { return p.text || ''; }).join('') : '';
      var j = typeof extractJSON === 'function' ? extractJSON(raw) : JSON.parse(raw);
      var map = {};
      ((j && j.items) || []).forEach(function (it) {
        var q = (it.q || []).map(String).filter(function (x) { return x && !/viet|asia/i.test(x); }).slice(0, 3);
        if (q.length) map[it.i] = q;
      });
      return map;
    } catch (e) { return null; }
  }

  function sectionQueries(s, a, aiMap, i) {
    if (s._qcQueries) return s._qcQueries;
    var q = (aiMap && aiMap[i]) || [];
    var base = String(s.imageQuery || '').replace(/\b(vietnam(ese)?|asian?)\b/gi, '').replace(/\s+/g, ' ').trim();
    if (!q.length) {
      if (base && !/[à-ỹđ]/i.test(base)) q.push(base);       // từ khóa AI viết bài (đã bỏ "vietnam")
      q = q.concat(viToEn((s.heading || '') + ' ' + plain(s.content).slice(0, 300) + ' ' + (a.title || '')));
    }
    s._qcQueries = q;
    return q;
  }

  function loadable(src) {
    return new Promise(function (ok) {
      var im = new Image();
      im.referrerPolicy = 'no-referrer';
      im.onload = function () { ok(im.naturalWidth >= 300); };
      im.onerror = function () { ok(false); };
      im.src = src;
    });
  }

  var jobImage = null;                         // ảnh của bài tin gửi sang từ tab "Tin tức AI"
  async function qcLoadImages(sections) {
    var a = (typeof curArticle !== 'undefined' && curArticle) || { sections: sections };
    var idxs = [];
    (sections || []).forEach(function (s, i) { if (s.imageQuery) idxs.push(i); });
    if (!idxs.length) return;
    notify('🖼 Đang chọn ảnh khớp nội dung từng đoạn...');
    var aiMap = await aiImageQueries(a);
    var used = {};
    for (var k = 0; k < idxs.length; k++) {
      var i = idxs[k], s = sections[i];
      var box = document.getElementById('imgbox-sec-' + i);
      if (!box) continue;
      var src = null;
      if (k === 0 && jobImage && await loadable(jobImage)) src = jobImage;       // ảnh đầu = ảnh bài tin gốc
      if (!src) src = await pickStock(sectionQueries(s, a, aiMap, i), used, 0);
      if (!src) src = await titleCard(s.heading || a.title || '', k);
      used[src] = 1;
      s._imgUrl = src; s._blobUrl = null; s._localFile = null;
      setImg(box, src);
    }
    jobImage = null;
  }

  async function qcRefreshImg(sectionIdx, event) {
    if (event && event.stopPropagation) event.stopPropagation();
    if (typeof curArticle === 'undefined' || !curArticle || !curArticle.sections) return;
    var s = curArticle.sections[sectionIdx];
    var box = document.getElementById('imgbox-sec-' + sectionIdx);
    if (!s || !s.imageQuery || !box) return;
    var loadEl = box.querySelector('.img-loading'), imgEl = box.querySelector('img');
    if (loadEl) loadEl.style.display = 'flex';
    if (imgEl) imgEl.style.display = 'none';
    s._qcRefresh = (s._qcRefresh || 0) + 1;
    var used = {};
    curArticle.sections.forEach(function (x) { if (x._imgUrl) used[x._imgUrl] = 1; });
    var src = await pickStock(sectionQueries(s, curArticle, null, sectionIdx), used, s._qcRefresh - 1)
      || await titleCard(s.heading || curArticle.title || '', sectionIdx + s._qcRefresh);
    s._imgUrl = src; s._blobUrl = null; s._localFile = null;
    setImg(box, src);
    notify('🖼 Đã đổi ảnh khớp nội dung cho đoạn ' + (sectionIdx + 1));
  }

  function wrapImages() {
    if (typeof loadImages === 'function' && !loadImages._qc) { window.loadImages = qcLoadImages; window.loadImages._qc = true; }
    if (typeof refreshImg === 'function' && !refreshImg._qc) { window.refreshImg = qcRefreshImg; window.refreshImg._qc = true; }
  }
  wrapImages();
  window.qcImages = { matchScore: matchScore, pickStock: pickStock, titleCard: titleCard, viToEn: viToEn,
                      setJobImage: function (u) { jobImage = u || null; } };

  // ── Kết nối WordPress ─────────────────────────────────────────────────────
  // Trang này chạy ở 127.0.0.1 nên trình duyệt chặn gọi thẳng sang website khác (CORS → "Failed to fetch").
  // Mọi yêu cầu .../wp-json/... được chuyển qua máy chủ QC (/api/wp-proxy) — website không cần cài thêm gì.
  function siteRoot(u) {
    u = String(u || '').trim();
    if (!u) return '';
    if (!/^https?:\/\//i.test(u)) u = 'https://' + u;
    u = u.split(/\/(?:wp-admin|wp-login\.php|wp-json)(?:[\/?#]|$)/i)[0];
    return u.split('#')[0].split('?')[0].replace(/\/+$/, '');
  }
  function fixWpUrl() {
    var el = document.getElementById('wp-url');
    if (!el || !el.value.trim()) return;
    var root = siteRoot(el.value);
    if (root !== el.value) {
      el.value = root;
      try {
        var pub = JSON.parse(localStorage.getItem('pub') || '{}');
        pub['wp-url'] = root;
        localStorage.setItem('pub', JSON.stringify(pub));
      } catch (e) {}
    }
  }
  function wrapFetch() {
    if (window.fetch._qc) return;
    var orig = window.fetch.bind(window);
    window.fetch = function (input, opts) {
      var url = typeof input === 'string' ? input : (input && input.url) || '';
      var abs = /^https?:\/\//i.test(url) && url.indexOf(location.origin) !== 0;
      if (abs && /\/wp-json\//.test(url)) {
        var i = url.indexOf('/wp-json/');
        var fixed = siteRoot(url.slice(0, i)) + url.slice(i);
        // Header Authorization của WordPress đổi tên (Authorization dành cho đăng nhập bảng điều khiển QC)
        var o = Object.assign({}, opts || {}), h = {};
        new Headers((opts && opts.headers) || (typeof input !== 'string' && input.headers) || {}).forEach(function (v, k) {
          h[k.toLowerCase() === 'authorization' ? 'X-WP-Authorization' : k] = v;
        });
        o.headers = h;
        if (!o.method && typeof input !== 'string' && input.method) o.method = input.method;
        return orig('/api/wp-proxy?url=' + encodeURIComponent(fixed), o);
      }
      return orig(input, opts);
    };
    window.fetch._qc = true;
  }
  wrapFetch();

  function init() {
    fixWpUrl();
    var wpEl = document.getElementById('wp-url');
    if (wpEl) wpEl.addEventListener('change', function () { fixWpUrl(); if (typeof savePub === 'function') savePub(); });
    wrapLimits();
    wrapImages();
    addVerifyOption();
    wrapGenerator();
    addButtons();
    setTimeout(checkPendingJob, 400);
    if (window.parent === window) addBackLink(); // mở trong tab của bảng điều khiển thì không cần
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
  window.qcSendToFanpage = sendToQC;
})();
