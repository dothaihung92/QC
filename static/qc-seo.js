// Tối ưu SEO khi đăng bài lên WordPress (Rank Math / Yoast) — chạy trong tab "Viết bài SEO".
// Máy chủ QC nối file này vào /qc-bridge.js, nên thay seo-writer.html bằng bản mới vẫn giữ được.
//  • Permalink ngắn gọn, có từ khóa, không vượt giới hạn 75 ký tự TÍNH CẢ tên miền (Rank Math đếm cả URL)
//  • Từ khóa xuất hiện ở đầu bài + thẻ H2; kiểm tra kiểu Rank Math trước khi đăng
//  • Ảnh: tải lên WordPress với tên file có từ khóa, alt / title / caption / mô tả rõ ràng cho Google
//  • Thẻ (tags) gắn lên web, chuyên mục, trạng thái Nháp/Live đúng như đã chọn
//  • Gửi tiêu đề SEO / mô tả / từ khóa chính vào Rank Math (và Yoast)
(function () {
  'use strict';
  function notify(m) { if (typeof toast === 'function') toast(m); else alert(m); }
  var STOPW = { va: 1, cua: 1, cho: 1, voi: 1, la: 1, de: 1, nhung: 1, cac: 1, trong: 1, ve: 1, tu: 1, khi: 1, ma: 1,
    hay: 1, hoac: 1, mot: 1, the: 1, nao: 1, co: 1, duoc: 1, den: 1, tai: 1, theo: 1, nen: 1, se: 1, da: 1 };

  function norm(t) { return String(t || '').toLowerCase().replace(/\s+/g, ' ').trim(); }
  function plain(h) { return String(h || '').replace(/<[^>]+>/g, ' ').replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ').trim(); }
  function cap(t) { t = String(t || '').trim(); return t.charAt(0).toUpperCase() + t.slice(1); }
  function esc(t) { return String(t == null ? '' : t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  function slugify(s) {
    return String(s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/g, 'd')
      .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  }
  function hasKw(text, kw) { return !!kw && norm(text).indexOf(norm(kw)) >= 0; }
  function pubCfg() { try { return JSON.parse(localStorage.getItem('pub') || '{}'); } catch (e) { return {}; } }
  function siteBase() { return String(pubCfg()['wp-url'] || '').trim().replace(/\/+$/, ''); }

  // ── Permalink ─────────────────────────────────────────────────────────────
  // Rank Math đếm CẢ địa chỉ (https://ten-mien.com/slug/) so với 75 ký tự → slug phải ngắn theo tên miền.
  function maxSlug() { return Math.max(20, 75 - (siteBase() || 'https://example.com').length - 2); }
  function buildSlug(kw, title) {
    var max = maxSlug(), words = slugify(kw).split('-').filter(Boolean), out = '';
    for (var i = 0; i < words.length; i++) {            // từ khóa trước (cắt ở ranh giới từ)
      var t = out ? out + '-' + words[i] : words[i];
      if (t.length > max) break;
      out = t;
    }
    var have = {};
    words.forEach(function (w) { have[w] = 1; });
    var extra = slugify(title).split('-').filter(function (w) { return w && !have[w] && !STOPW[w]; });
    for (var j = 0; j < extra.length; j++) {            // thêm từ trong tiêu đề cho đến khi gần hết chỗ
      var t2 = out ? out + '-' + extra[j] : extra[j];
      if (t2.length > max) break;
      out = t2;
    }
    return out || slugify(title).slice(0, max).replace(/-+$/, '');
  }

  // ── AI ───────────────────────────────────────────────────────────────────
  async function askJSON(prompt) {
    var gkey = ((document.getElementById('gkey') || {}).value || '').trim();
    if (!gkey || typeof callGeminiWithFallback !== 'function') return null;
    try {
      var res = await callGeminiWithFallback(gkey, {
        contents: [{ role: 'user', parts: [{ text: prompt }] }],
        generationConfig: { temperature: 0.3, maxOutputTokens: 3000, responseMimeType: 'application/json' }
      });
      var c = ((res.data.candidates || [])[0] || {}).content;
      var raw = c ? (c.parts || []).map(function (p) { return p.text || ''; }).join('') : '';
      return typeof extractJSON === 'function' ? extractJSON(raw) : JSON.parse(raw);
    } catch (e) { return null; }
  }

  // ── Kiểm tra kiểu Rank Math ───────────────────────────────────────────────
  function bodyHtml(a) { return (a.sections || []).map(function (s) { return s.content || ''; }).join(' ') + ' ' + (a.conclusion || ''); }
  function wordCount(a) { var t = plain(bodyHtml(a)); return t ? t.split(/\s+/).length : 0; }
  function firstPart(a) {
    var words = plain(((a.sections || [])[0] || {}).content || '').split(/\s+/);
    return words.slice(0, 80).join(' ');
  }
  function imageSections(a) { return (a.sections || []).map(function (s, i) { return { s: s, i: i }; }).filter(function (x) { return x.s.imageQuery; }); }
  function countKw(a, kw) {
    var t = norm(plain(bodyHtml(a))), k = norm(kw), n = 0, i = 0;
    if (!k) return 0;
    while ((i = t.indexOf(k, i)) >= 0) { n++; i += k.length; }
    return n;
  }
  function links(a) {
    var host = '';
    try { host = new URL(siteBase()).host; } catch (e) {}
    var ext = 0, int_ = 0;
    (bodyHtml(a).match(/<a\s[^>]*href=["'][^"']+["']/gi) || []).forEach(function (m) {
      var u = (m.match(/href=["']([^"']+)["']/i) || [])[1] || '';
      if (/^https?:\/\//i.test(u) && (!host || u.indexOf(host) < 0)) ext++; else int_++;
    });
    return { ext: ext, int: int_ };
  }
  function rmChecks(a) {
    var kw = (a.focusKeyword || '').trim(), words = wordCount(a), n = countKw(a, kw), lk = links(a);
    var density = words ? (n * (kw.split(/\s+/).length || 1) / words * 100) : 0;
    var alts = imageSections(a).map(function (x) { return x.s._alt || ''; });
    var slug = a.slug || '';
    return [
      { ok: hasKw(a.title, kw), lbl: 'Từ khóa có trong tiêu đề SEO' },
      { ok: (a.title || '').length <= 60, lbl: 'Tiêu đề SEO ≤ 60 ký tự (' + (a.title || '').length + ')' },
      { ok: hasKw(a.metaDescription, kw), lbl: 'Từ khóa có trong mô tả (meta description)' },
      { ok: (a.metaDescription || '').length <= 160, lbl: 'Mô tả ≤ 160 ký tự (' + (a.metaDescription || '').length + ')' },
      { ok: !!kw && slug.indexOf(slugify(kw)) >= 0, lbl: 'Từ khóa có trong URL' },
      { ok: slug.length + (siteBase() || 'https://example.com').length + 2 <= 75, lbl: 'URL ≤ 75 ký tự tính cả tên miền (' + (slug.length + (siteBase() || 'https://example.com').length + 2) + ')' },
      { ok: hasKw(firstPart(a), kw), lbl: 'Từ khóa ở đầu nội dung (80 từ đầu)' },
      { ok: n > 0, lbl: 'Từ khóa có trong nội dung (' + n + ' lần)' },
      { ok: (a.sections || []).some(function (s) { return hasKw(s.heading, kw); }), lbl: 'Từ khóa có trong thẻ H2' },
      { ok: alts.some(function (t) { return hasKw(t, kw); }), lbl: 'Từ khóa có trong alt của ảnh' },
      { ok: density >= 0.5 && density <= 2.5, lbl: 'Mật độ từ khóa 0,5–2,5% (' + density.toFixed(1).replace('.', ',') + '%)' },
      { ok: words >= 600, lbl: 'Độ dài ≥ 600 từ (' + words + ' từ)' },
      { ok: lk.ext > 0, lbl: 'Có link ra ngoài (' + lk.ext + ')' },
      { ok: lk.int > 0, lbl: 'Có link nội bộ (' + lk.int + ')' },
      { ok: (a.tags || []).length >= 3, lbl: 'Có ≥ 3 thẻ (tags)' },
      { ok: (a.qa || []).length >= 3, lbl: 'Có phần Hỏi đáp (' + (a.qa || []).length + ' câu)' }
    ];
  }
  function renderChecklist(a) {
    var side = document.getElementById('sidebar');
    if (!side) return;
    var old = document.getElementById('qc-rm-card');
    if (old) old.remove();
    var cs = rmChecks(a), ok = cs.filter(function (c) { return c.ok; }).length;
    var card = document.createElement('div');
    card.className = 'side-card';
    card.id = 'qc-rm-card';
    card.innerHTML = '<div class="side-title"><i class="ti ti-rosette-discount-check" style="font-size:14px"></i>Kiểm tra kiểu Rank Math ' +
      '<span style="margin-left:6px;font-size:11px;font-weight:700;color:' + (ok === cs.length ? 'var(--success)' : 'var(--warn)') + '">' + ok + '/' + cs.length + '</span></div>' +
      cs.map(function (c) {
        return '<div class="chk-row"><i class="ti ' + (c.ok ? 'ti-circle-check' : 'ti-circle-x') + '" style="color:' + (c.ok ? 'var(--success)' : 'var(--danger)') +
          '"></i><span>' + esc(c.lbl) + '</span></div>';
      }).join('');
    var first = side.querySelector('.side-card');
    if (first && first.nextSibling) side.insertBefore(card, first.nextSibling); else side.appendChild(card);
  }
  function refreshPermalink(a) {
    document.querySelectorAll('#sidebar .meta-pill').forEach(function (p) {
      var lbl = p.querySelector('.meta-lbl'), val = p.querySelector('.meta-val');
      if (lbl && val && /Permalink/i.test(lbl.textContent)) {
        val.textContent = '/' + a.slug;
        var total = a.slug.length + (siteBase() || 'https://example.com').length + 2;
        lbl.innerHTML = 'Permalink <span style="font-size:10px;font-weight:600;color:' + (total <= 75 ? 'var(--success)' : 'var(--danger)') +
          ';margin-left:6px">' + total + '/75 (cả tên miền) ' + (total <= 75 ? '✓' : '⚠️') + '</span>';
      }
    });
  }

  // ── Tối ưu nội dung: từ khóa ở đầu bài + H2, alt/caption ảnh ─────────────
  function fallbackAlt(a, s, i, k) {
    var kw = a.focusKeyword || '', h = (s.heading || '').trim();
    if (k === 0) return cap(kw) + (h && !hasKw(h, kw) ? ' – ' + h : '');
    return h || (cap(kw) + ' – hình minh họa ' + (k + 1));
  }
  async function optimizeContent(a) {
    var kw = (a.focusKeyword || '').trim(), secs = a.sections || [];
    if (!kw || !secs.length) return;
    var intro = secs[0].content || '', m = intro.match(/<p[^>]*>[\s\S]*?<\/p>/i);
    var needIntro = !!m && !hasKw(firstPart(a), kw);
    var needH2 = !secs.some(function (s) { return hasKw(s.heading, kw); });
    var imgs = imageSections(a);
    var prompt = 'Từ khóa SEO chính: "' + kw + '". Tiêu đề bài: "' + a.title + '".\n' +
      (needIntro ? 'ĐOẠN MỞ ĐẦU HIỆN TẠI (HTML): ' + m[0].slice(0, 1500) + '\n' : '') +
      (needH2 ? 'CÁC TIÊU ĐỀ H2: ' + secs.map(function (s, i) { return s.heading ? i + ': ' + s.heading : ''; }).filter(Boolean).join(' | ') + '\n' : '') +
      'CÁC ẢNH: ' + imgs.map(function (x, k) { return k + ' (đoạn "' + (x.s.heading || 'mở đầu') + '"): ' + plain(x.s.content).slice(0, 160); }).join(' || ') + '\n\n' +
      'Trả về CHỈ JSON {' + (needIntro ? '"intro":"…",' : '') + (needH2 ? '"h2":{"chỉ số":"tiêu đề mới"},' : '') + '"images":[{"k":0,"alt":"…","caption":"…","title":"…"}]} với:\n' +
      (needIntro ? '- intro: viết lại đoạn mở đầu thành MỘT thẻ <p>, giữ nguyên ý và các thẻ <strong>/<a> có sẵn, chứa NGUYÊN VĂN cụm "' + kw + '" ngay trong câu đầu tiên (trong 25 từ đầu), tự nhiên.\n' : '') +
      (needH2 ? '- h2: đổi ĐÚNG MỘT tiêu đề H2 (chọn cái hợp nhất, không phải đoạn mở đầu) để chứa nguyên văn "' + kw + '", tự nhiên, ≤ 70 ký tự.\n' : '') +
      '- images: mỗi ảnh một alt tiếng Việt 50-120 ký tự MÔ TẢ cảnh trong ảnh theo nội dung đoạn (không nhồi từ khóa, không bắt đầu bằng "hình ảnh"/"ảnh"); ' +
      'RIÊNG ảnh k=0 phải chứa nguyên văn "' + kw + '"; caption ≤ 90 ký tự; title ngắn ≤ 60 ký tự.';
    var j = await askJSON(prompt);
    if (j) {
      if (needIntro && j.intro && /^<p/i.test(String(j.intro).trim()) && hasKw(plain(j.intro).split(/\s+/).slice(0, 40).join(' '), kw) &&
          plain(j.intro).length > plain(m[0]).length * 0.6 && plain(j.intro).length < plain(m[0]).length * 2.2) {
        secs[0].content = intro.replace(m[0], String(j.intro).trim());
        var el = document.getElementById('ed-content-0');
        if (el) el.innerHTML = secs[0].content;
      }
      if (needH2 && j.h2) {
        Object.keys(j.h2).some(function (k) {
          var i = parseInt(k, 10), h = String(j.h2[k] || '').trim().replace(/[.:]$/, '');
          if (isNaN(i) || !secs[i] || !secs[i].heading || i === 0 || !hasKw(h, kw) || h.length > 80) return false;
          secs[i].heading = h;
          var he = document.getElementById('ed-h-' + i);
          if (he) he.textContent = h;
          return true;
        });
      }
    }
    imgs.forEach(function (x, k) {
      var r = j && (j.images || []).filter(function (o) { return +o.k === k; })[0] || {};
      var alt = String(r.alt || '').trim();
      if (k === 0 && alt && !hasKw(alt, kw)) alt = '';
      x.s._alt = (alt.length >= 20 && alt.length <= 140) ? alt : fallbackAlt(a, x.s, x.i, k);
      x.s._caption = String(r.caption || '').trim().slice(0, 120) || (x.s.heading || cap(kw));
      x.s._imgTitle = String(r.title || '').trim().slice(0, 80) || (x.s.heading || cap(kw));
      var ie = document.querySelector('#imgbox-sec-' + x.i + ' img');
      if (ie) { ie.alt = x.s._alt; ie.title = x.s._imgTitle; }
    });
  }

  function cleanTags(a) {
    var seen = {}, out = [];
    (a.tags || []).concat([a.focusKeyword || '']).forEach(function (t) {
      t = String(t || '').replace(/^#+/, '').replace(/_/g, ' ').trim();
      if (t && t.length <= 60 && !seen[norm(t)]) { seen[norm(t)] = 1; out.push(t); }
    });
    a.tags = out.slice(0, 7);
  }

  // ── Hỏi đáp (Q&A) ─────────────────────────────────────────────────────────
  // AI có lúc không trả mục "qa" mà viết câu hỏi thành một đoạn thường (chỉ có câu hỏi, không có trả lời)
  // → tự tạo lại 5 câu hỏi + trả lời từ nội dung bài, hiện đúng khung "Câu Hỏi Thường Gặp" như trước.
  var FAQ_RE = /câu hỏi thường gặp|hỏi\s*(?:&amp;|&|và)?\s*đáp|faq|giải đáp thắc mắc|thắc mắc thường gặp/i;
  function faqQuestions(html) {
    var items = (String(html || '').match(/<(li|p)[^>]*>[\s\S]*?<\/\1>/gi) || []).map(plain);
    return items.map(function (t) { return t.replace(/^(câu hỏi|hỏi|q)\s*\d*\s*[:.)-]\s*/i, '').trim(); })
      .filter(function (t) { return t.length > 8 && /\?/.test(t); });
  }
  function renderQA(a) {
    var card = document.getElementById('art-card');
    if (!card) return;
    var old = document.getElementById('ed-sec-qa');
    if (old) old.remove();
    if (!(a.qa || []).length) return;
    var div = document.createElement('div');
    div.className = 'art-sec';
    div.id = 'ed-sec-qa';
    div.innerHTML = '<h2 id="ed-h-qa">❓ Câu Hỏi Thường Gặp</h2><div class="qa-wrap">' + a.qa.map(function (it, qi) {
      return '<div class="qa-item" id="qa-' + qi + '"><div class="qa-q" onclick="toggleQA(' + qi + ')"><div class="qa-q-icon">Q</div>' +
        '<div class="qa-q-text">' + it.q + '</div><i class="ti ti-chevron-down qa-arrow"></i></div><div class="qa-a">' + it.a + '</div></div>';
    }).join('') + '</div>';
    var conc = card.querySelector('.art-conc');
    if (conc) card.insertBefore(div, conc); else card.appendChild(div);
    document.querySelectorAll('#sidebar .stat-box').forEach(function (b) {      // ô "Q&A" trong Thông tin bài
      var l = b.querySelector('.stat-l'), n = b.querySelector('.stat-n');
      if (l && n && /Q&A/i.test(l.textContent)) n.textContent = a.qa.length;
    });
  }
  async function ensureQA(a) {
    var secs = a.sections || [];
    var fi = -1;
    secs.forEach(function (s, i) { if (fi < 0 && FAQ_RE.test(s.heading || '')) fi = i; });
    if ((a.qa || []).length >= 3) {
      if (fi >= 0) hideSection(a, fi);                  // đã có khung Q&A → bỏ đoạn hỏi đáp trùng
      return;
    }
    var qs = fi >= 0 ? faqQuestions(secs[fi].content) : [];
    var j = await askJSON('Viết phần HỎI ĐÁP (FAQ) gồm 5 câu cho bài "' + a.title + '" (từ khóa: "' + (a.focusKeyword || '') + '"). ' +
      (qs.length ? 'Dùng đúng các câu hỏi sau (giữ nguyên ý): ' + qs.slice(0, 6).join(' | ') + '. ' : 'Chọn câu hỏi thực tế mà chủ doanh nghiệp / kế toán hay hỏi. ') +
      'Mỗi câu trả lời 2-4 câu, rõ ràng, CHỈ dựa vào nội dung bài sau, không bịa số liệu hay số hiệu văn bản:\n' +
      plain(bodyHtml(a)).slice(0, 6000) + '\n\nChỉ trả về JSON {"qa":[{"q":"…?","a":"…"}]}');
    var qa = ((j && j.qa) || []).map(function (x) {
      return { q: esc(plain(x.q || '')).trim(), a: esc(plain(x.a || '')).trim() };
    }).filter(function (x) { return x.q.length > 8 && x.a.length > 15; }).slice(0, 6);
    if (qa.length < 3) return;
    a.qa = qa;
    if (fi >= 0) hideSection(a, fi);
    renderQA(a);
  }
  function hideSection(a, i) {
    var s = a.sections[i];
    s.heading = ''; s.content = ''; s.imageQuery = ''; s.type = 'h2';          // khi đăng web bỏ qua đoạn trống này
    var el = document.getElementById('ed-sec-' + i);
    if (el) el.style.display = 'none';
  }

  async function finalize(a, force) {
    if (!a) return;
    if (!a.focusKeyword || a.focusKeyword === 'undefined') a.focusKeyword = ((document.getElementById('kw') || {}).value || '').trim();
    try { await ensureQA(a); } catch (e) { console.warn('ensureQA', e); }
    cleanTags(a);
    a.slug = buildSlug(a.focusKeyword, a.title);
    if (!a._qcFinal || force) {
      try { await optimizeContent(a); } catch (e) { console.warn('optimizeContent', e); }
      a._qcFinal = true;
    }
    if (!a._qcLinked || force) {
      try {
        var res = await internalLinks(a);
        a._qcLinked = true;
        if (res.added && res.added.length) notify('🔗 Đã chèn ' + res.added.length + ' link nội bộ' + (res.box ? ' (khung "Đọc thêm")' : ''));
      } catch (e) { console.warn('internalLinks', e); }
    }
    refreshPermalink(a);
    renderChecklist(a);
    try { if (window.qcTitle && window.qcTitle.refresh) window.qcTitle.refresh(a); } catch (e) {}   // chấm lại điểm SEO
  }

  // ── Internal Links SEO ────────────────────────────────────────────────────
  // Trước đây chỉ chèn khi bài MỚI chứa NGUYÊN VĂN một từ khóa của bài cũ (hiếm khi trùng) → gần như không bao giờ chạy.
  // Bây giờ: chọn bài cũ liên quan theo nội dung, kiểm tra link còn mở được, nhờ AI chọn cụm từ có sẵn trong bài để gắn
  // (hoặc tìm từ khóa trực tiếp); không có chỗ hợp lý thì thêm khung "Đọc thêm". Tối đa 3 link trong bài.
  var MAX_INLINE = 3;
  function ilinkOn() { try { return localStorage.getItem('ilink_enabled') !== '0'; } catch (e) { return true; } }
  function dbItems() { try { return typeof getLinksDB === 'function' ? getLinksDB() : []; } catch (e) { return []; } }
  function nfc(t) { return String(t || '').normalize('NFC'); }
  function toks(t) {
    return slugify(t).split('-').filter(function (w) { return w.length >= 3 && !STOPW[w]; });
  }
  function relevance(item, a) {
    var art = {}, text = toks((a.title || '') + ' ' + (a.focusKeyword || '') + ' ' + (a.sections || []).map(function (s) { return (s.heading || '') + ' ' + plain(s.content); }).join(' '));
    text.forEach(function (w) { art[w] = (art[w] || 0) + 1; });
    var phr = 0, shared = {};
    (item.keywords || []).concat([item.title || '']).forEach(function (k) {
      var ws = toks(k);
      if (ws.length && ws.every(function (w) { return art[w]; })) phr += ws.length >= 2 ? 3 : 1;     // cả cụm xuất hiện trong bài
      ws.forEach(function (w) { if (art[w]) shared[w] = 1; });
    });
    return phr + Object.keys(shared).length;
  }
  async function alive(url) {
    try {
      var r = await fetch('/api/url-check?url=' + encodeURIComponent(url));
      return r.ok ? !!(await r.json()).ok : false;
    } catch (e) { return false; }
  }
  // gắn <a> vào lần xuất hiện đầu tiên của cụm từ, chỉ trong chữ thường (không trong thẻ, link, tiêu đề)
  function linkPhrase(html, phrase, url, title) {
    var ph = nfc(phrase).trim();
    if (!ph || ph.length < 4) return null;
    var re = new RegExp(ph.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s+'), 'i');
    var parts = html.split(/(<[^>]+>)/), inA = 0, inH = 0, done = false;
    for (var i = 0; i < parts.length && !done; i++) {
      var t = parts[i];
      if (t.charAt(0) === '<') {
        var l = t.toLowerCase();
        if (/^<a[\s>]/.test(l)) inA++; else if (l.indexOf('</a') === 0) inA = Math.max(0, inA - 1);
        else if (/^<h[1-6][\s>]/.test(l)) inH++; else if (/^<\/h[1-6]/.test(l)) inH = Math.max(0, inH - 1);
        continue;
      }
      if (inA || inH) continue;
      var m = re.exec(nfc(t));
      if (m) {
        var n = nfc(t);
        parts[i] = n.slice(0, m.index) + '<a href="' + esc(url) + '" title="' + esc(title) + '">' + m[0] + '</a>' + n.slice(m.index + m[0].length);
        done = true;
      }
    }
    return done ? parts.join('') : null;
  }
  function existingLinks(a) {
    var h = bodyHtml(a), out = {};
    (h.match(/href=["']([^"']+)["']/gi) || []).forEach(function (m) { out[m.replace(/^href=["']|["']$/gi, '').replace(/\/$/, '')] = 1; });
    return out;
  }
  async function internalLinks(a) {
    if (!ilinkOn() || !a || !(a.sections || []).length) return { added: [], reason: 'off' };
    var slug = a.slug || '', have = existingLinks(a);
    var cands = dbItems().filter(function (it) {
      return it && it.url && it.slug !== slug && it.url.indexOf('/' + slug + '/') < 0 && !have[it.url.replace(/\/$/, '')];
    }).map(function (it) { return { it: it, sc: relevance(it, a) }; })
      .filter(function (x) { return x.sc >= 2; }).sort(function (x, y) { return y.sc - x.sc; }).slice(0, 5);
    if (!cands.length) return { added: [], reason: 'no-related' };
    var live = await Promise.all(cands.map(function (c) { return alive(c.it.url); }));
    cands = cands.filter(function (c, i) { return live[i]; });
    if (!cands.length) return { added: [], reason: 'not-live' };
    var secs = a.sections, added = [];
    var apply = function (it, phrase, si) {
      var order = si != null && secs[si] ? [si] : [], i;
      for (i = 0; i < secs.length; i++) if (order.indexOf(i) < 0) order.push(i);
      for (var k = 0; k < order.length; k++) {
        var s2 = secs[order[k]];
        if (!s2 || !s2.content) continue;
        var r = linkPhrase(s2.content, phrase, it.url, it.title || phrase);
        if (r) { s2.content = r; var el = document.getElementById('ed-content-' + order[k]); if (el) el.innerHTML = r; return true; }
      }
      return false;
    };
    // 1) AI chọn cụm từ có sẵn trong bài
    var j = await askJSON('Bài viết "' + a.title + '". Gắn link nội bộ tới các bài sau (mỗi bài một link, tối đa ' + MAX_INLINE + ' link):\n' +
      cands.map(function (c, i) { return i + '. ' + (c.it.title || '') + ' — từ khóa: ' + (c.it.keywords || []).slice(0, 6).join(', '); }).join('\n') +
      '\n\nNỘI DUNG BÀI (theo từng đoạn):\n' + secs.map(function (s, i) { return '[' + i + '] ' + plain(s.content).slice(0, 1100); }).join('\n') +
      '\n\nVới mỗi bài liên quan THẬT SỰ về nội dung, chọn MỘT cụm từ 2-6 từ chép NGUYÊN VĂN từ đoạn văn trên (không sửa chữ, không phải tiêu đề) để làm anchor text. ' +
      'Bài nào không có chỗ hợp lý thì bỏ qua. Chỉ trả về JSON {"links":[{"n":0,"section":1,"phrase":"…"}]}');
    var usedN = {};
    ((j && j.links) || []).forEach(function (l) {
      var c = cands[+l.n];
      if (!c || usedN[+l.n] || added.length >= MAX_INLINE || !l.phrase) return;
      if (apply(c.it, String(l.phrase), +l.section)) { usedN[+l.n] = 1; added.push({ kw: String(l.phrase), url: c.it.url, title: c.it.title }); }
    });
    // 2) không có AI / AI không chọn được: tìm thẳng từ khóa của bài cũ trong nội dung
    cands.forEach(function (c, n) {
      if (usedN[n] || added.length >= MAX_INLINE) return;
      var kws = (c.it.keywords || []).slice().sort(function (x, y) { return y.length - x.length; });
      for (var i = 0; i < kws.length; i++) {
        if (kws[i].length >= 4 && apply(c.it, kws[i], null)) { usedN[n] = 1; added.push({ kw: kws[i], url: c.it.url, title: c.it.title }); break; }
      }
    });
    // 3) vẫn chưa có link nào: khung "Đọc thêm" cuối bài (link thật, đã kiểm tra mở được)
    var box = false;
    if (!added.length) {
      var last = null;
      for (var q = secs.length - 1; q >= 0; q--) if (secs[q].content && secs[q].content.trim()) { last = q; break; }
      if (last != null) {
        var rel = cands.slice(0, 3);
        secs[last].content += '<p data-qc-related="1"><strong>Đọc thêm:</strong> ' + rel.map(function (c) {
          return '<a href="' + esc(c.it.url) + '" title="' + esc(c.it.title || '') + '">' + esc(c.it.title || c.it.focusKeyword || c.it.url) + '</a>';
        }).join(' &nbsp;|&nbsp; ') + '</p>';
        var el2 = document.getElementById('ed-content-' + last);
        if (el2) el2.innerHTML = secs[last].content;
        rel.forEach(function (c) { added.push({ kw: 'Đọc thêm', url: c.it.url, title: c.it.title }); });
        box = true;
      }
    }
    a._injectedLinks = (a._injectedLinks || []).concat(added);
    if (added.length && typeof showILinkReport === 'function') { try { showILinkReport(added); } catch (e) {} }
    return { added: added, box: box };
  }
  // Danh sách bài đã đăng lưu cả trên máy chủ QC (không mất khi đổi trình duyệt / địa chỉ truy cập)
  async function syncLinksDB() {
    try {
      var srv = await (await fetch('/api/seo/links-db')).json();
      var loc = dbItems(), seen = {};
      loc.forEach(function (x) { seen[x.url] = 1; });
      var merged = loc.concat((srv || []).filter(function (x) { return x && x.url && !seen[x.url]; }));
      if (merged.length !== loc.length && typeof saveLinksDB === 'function') saveLinksDB(merged);
      else if (merged.length !== (srv || []).length) pushLinksDB(merged);
    } catch (e) {}
  }
  function pushLinksDB(db) {
    try { fetch('/api/seo/links-db', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(db || dbItems()) }); } catch (e) {}
  }

  // ── Đăng lên WordPress ────────────────────────────────────────────────────
  function bAuth(user, pass) {
    var bytes = new TextEncoder().encode(user + ':' + pass), bin = '';
    bytes.forEach(function (b) { bin += String.fromCharCode(b); });
    return 'Basic ' + btoa(bin);
  }
  async function wp(base, auth, method, path, body, headers) {
    var h = Object.assign({ Authorization: auth }, headers || {});
    var isJson = body && !(body instanceof Blob);
    if (isJson) h['Content-Type'] = 'application/json';
    var r = await fetch(base + '/wp-json/' + path, { method: method, headers: h, body: isJson ? JSON.stringify(body) : body });
    var data = await r.json().catch(function () { return {}; });
    return { ok: r.ok, status: r.status, data: data };
  }
  async function imageBlob(s) {
    if (s._localFile) return s._localFile;
    var src = s._imgUrl;
    var r = await fetch(/^(blob|data):/.test(src) ? src : '/api/img-proxy?url=' + encodeURIComponent(src));
    if (!r.ok) throw new Error('không tải được ảnh');
    return await r.blob();
  }
  async function uploadImages(a, base, auth) {
    var imgs = imageSections(a).filter(function (x) { return x.s._imgUrl || x.s._wpImgUrl; }), done = 0, fail = [];
    var kwSlug = slugify(a.focusKeyword || a.slug || 'bai-viet');
    for (var k = 0; k < imgs.length; k++) {
      var s = imgs[k].s;
      if (s._wpMediaId && s._wpImgUrl) { done++; continue; }
      if (typeof showInfo === 'function') showInfo('Đang tải ảnh ' + (k + 1) + '/' + imgs.length + ' lên website (đặt tên file, alt, chú thích chuẩn SEO)...');
      try {
        var blob = await imageBlob(s), mime = blob.type || 'image/jpeg';
        var ext = /png/.test(mime) ? 'png' : /webp/.test(mime) ? 'webp' : /gif/.test(mime) ? 'gif' : 'jpg';
        var part = slugify(s.heading || '').split('-').filter(function (w) { return w && !STOPW[w]; }).slice(0, 5).join('-');
        var name = (kwSlug + (part && part.indexOf(kwSlug) < 0 ? '-' + part : '') + '-' + (k + 1)).slice(0, 70).replace(/-+$/, '') + '.' + ext;
        var up = await wp(base, auth, 'POST', 'wp/v2/media', blob, {
          'Content-Disposition': 'attachment; filename="' + name + '"', 'Content-Type': mime });
        if (!up.ok || !up.data.id) throw new Error(up.data.message || ('mã ' + up.status));
        s._wpMediaId = up.data.id;
        s._wpImgUrl = up.data.source_url;
        var md = up.data.media_details || {};
        s._w = md.width || 0; s._h = md.height || 0;
        s._fileName = name;
        await wp(base, auth, 'POST', 'wp/v2/media/' + up.data.id, {
          alt_text: s._alt || '', title: s._imgTitle || s.heading || '', caption: s._caption || '',
          description: (s._alt || '') + (a.title ? ' — ' + a.title : '') });
        done++;
      } catch (e) {
        fail.push((k + 1) + ': ' + (e.message || e));
      }
    }
    return { total: imgs.length, done: done, fail: fail };
  }
  function decorateContent(a, html) {
    // 1) ảnh: alt / title / width / height / lazy / chú thích
    var byUrl = {};
    imageSections(a).forEach(function (x, k) { var u = x.s._wpImgUrl || x.s._imgUrl; if (u) byUrl[u] = { s: x.s, k: k }; });
    html = html.replace(/<figure[^>]*><img src="([^"]+)"[^>]*\/><\/figure>/g, function (m, src) {
      var o = byUrl[src];
      if (!o) return m;
      var s = o.s;
      return '<figure class="wp-block-image size-large" style="margin:16px 0;text-align:center"><img src="' + esc(src) + '" alt="' + esc(s._alt || s.heading || '') +
        '" title="' + esc(s._imgTitle || s.heading || '') + '"' + (s._w ? ' width="' + s._w + '" height="' + s._h + '"' : '') +
        (s._wpMediaId ? ' class="wp-image-' + s._wpMediaId + '"' : '') + ' loading="' + (o.k === 0 ? 'eager' : 'lazy') + '" decoding="async" style="max-width:100%;height:auto;border-radius:8px"/>' +
        '<figcaption style="font-size:13px;color:#666;margin-top:6px">' + esc(s._caption || '') + '</figcaption></figure>';
    });
    // 2) H2 có id + mục lục
    var heads = [], used = {};
    html = html.replace(/<h2>([\s\S]*?)<\/h2>/g, function (m, inner) {
      var id = slugify(plain(inner)).slice(0, 60) || 'muc', n = 2, base = id;
      while (used[id]) id = base + '-' + (n++);
      used[id] = 1;
      heads.push({ id: id, text: plain(inner) });
      return '<h2 id="' + id + '">' + inner + '</h2>';
    });
    if (heads.length >= 3) {
      var toc = '<div class="qc-toc" style="background:#f6f8fb;border:1px solid #dfe5ee;border-radius:8px;padding:12px 18px;margin:16px 0"><p style="font-weight:700;margin:0 0 6px">Nội dung chính</p><ol style="margin:0;padding-left:20px">' +
        heads.filter(function (h) { return !/Câu Hỏi Thường Gặp/i.test(h.text); }).map(function (h) { return '<li><a href="#' + h.id + '">' + esc(h.text) + '</a></li>'; }).join('') + '</ol></div>';
      var i = html.indexOf('<h2 id=');
      if (i > 0) html = html.slice(0, i) + toc + '\n' + html.slice(i);
    }
    return html;
  }
  async function ensureTags(a, base, auth) {
    var ids = [];
    for (var i = 0; i < (a.tags || []).length; i++) {
      var r = await wp(base, auth, 'POST', 'wp/v2/tags', { name: a.tags[i] });
      var id = r.ok ? r.data.id : (r.data && r.data.code === 'term_exists' && r.data.data ? r.data.data.term_id : 0);
      if (id && ids.indexOf(id) < 0) ids.push(id);
    }
    return ids;
  }
  async function sendRankMath(a, base, auth, id) {
    var meta = { rank_math_title: a.title || '', rank_math_description: a.metaDescription || '',
      rank_math_focus_keyword: (a.focusKeyword || '').toLowerCase() };
    var rm = await wp(base, auth, 'POST', 'rankmath/v1/updateMeta', { objectID: id, objectType: 'post', meta: meta });
    if (rm.ok) return 'Rank Math: đã lưu tiêu đề SEO, mô tả và từ khóa chính';
    var y = { _yoast_wpseo_title: meta.rank_math_title, _yoast_wpseo_metadesc: meta.rank_math_description, _yoast_wpseo_focuskw: meta.rank_math_focus_keyword };
    var alt = await wp(base, auth, 'POST', 'wp/v2/posts/' + id, { meta: Object.assign({}, meta, y) });
    return rm.status === 404
      ? 'Rank Math: website không có Rank Math (hoặc chưa bật REST) — đã thử lưu qua WordPress, nếu thiếu hãy nhập tay 3 ô trong Rank Math'
      : 'Rank Math: chưa lưu được tự động (' + (rm.data.message || rm.status) + ') — hãy nhập tay từ khóa / tiêu đề / mô tả trong Rank Math' + (alt.ok ? '' : '');
  }

  async function qcPublish() {
    var a = typeof curArticle !== 'undefined' ? curArticle : null;
    if (!a) { notify('Chưa có bài viết'); return; }
    var pub = pubCfg(), base = siteBase();
    if (!base || !pub['wp-user'] || !pub['wp-pass']) { showErr('Chưa cấu hình WordPress (URL, user, mật khẩu ứng dụng)'); return; }
    var wantLive = (typeof curStatus !== 'undefined' ? curStatus : 'draft') === 'publish';
    if (wantLive && !confirm('Trạng thái đang chọn là LIVE — bài sẽ được XUẤT BẢN CÔNG KHAI ngay trên website. Tiếp tục?')) return;
    var auth = bAuth(pub['wp-user'], pub['wp-pass']);
    var btn = document.getElementById('pubbtn');
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="ti ti-loader-2 spin"></i> Đang đăng...'; }
    try {
      await finalize(a);
      var up = await uploadImages(a, base, auth);
      var content = decorateContent(a, await buildWPContent(a, base, auth, false));
      var first = imageSections(a).map(function (x) { return x.s; }).filter(function (s) { return s._wpMediaId; })[0];
      if (typeof showInfo === 'function') showInfo('Đang gắn thẻ (tags) và đăng bài...');
      var tagIds = await ensureTags(a, base, auth);
      var live = wantLive;
      var cats = String(pub['wp-cat'] || '').split(/[,\s]+/).map(Number).filter(function (n) { return n > 0; });
      var data = { title: a.title, content: content, status: live ? 'publish' : 'draft', slug: a.slug, excerpt: a.metaDescription || '' };
      if (tagIds.length) data.tags = tagIds;
      if (cats.length) data.categories = cats;
      if (first) data.featured_media = first._wpMediaId;
      var r = await wp(base, auth, 'POST', 'wp/v2/posts', data);
      if (!r.ok || !r.data.id) throw new Error((r.data && r.data.message) || 'Không tạo được bài. Kiểm tra quyền user.');
      var post = r.data;
      var rmMsg = await sendRankMath(a, base, auth, post.id);
      var real = (post.slug || a.slug);
      // Nháp: WordPress trả link dạng ?p=ID (khách không mở được) → dùng đường dẫn thật dự kiến để lưu; mở bài bằng trang sửa bài
      var url = live ? (post.link || (base + '/?p=' + post.id)) : (base + '/wp-admin/post.php?post=' + post.id + '&action=edit');
      a._publishedUrl = live ? ((post.link && post.link.indexOf('?p=') < 0) ? post.link : (base + '/' + real + '/')) : (base + '/' + real + '/');
      try { addToLinksDB(a, base); } catch (e) {}
      try { if (!live) { var dbn = dbItems(); if (dbn[0]) { dbn[0].draft = true; saveLinksDB(dbn); } } pushLinksDB(); } catch (e) {}
      [['fb-article-link', 1], ['idx-url', 0], ['sat-url', 0], ['ans-url', 0], ['bl-url', 0]].forEach(function (p) {
        var el = document.getElementById(p[0]);
        if (el && url && (p[1] || !el.value)) { el.value = url; }
      });
      if (typeof updateFBComment === 'function') updateFBComment();
      if (typeof saveFBSettings === 'function') saveFBSettings();
      showSucc('✅ ' + (live ? 'Đã ĐĂNG CÔNG KHAI lên website' : 'Đã lưu NHÁP trên website — chưa công khai (chọn Live để đăng công khai)') +
        '. <a href="' + url + '" target="_blank" style="color:var(--info);font-weight:600">' + (live ? 'Xem bài ↗' : 'Mở bản nháp trong WordPress ↗') + '</a><br>' +
        '• Đường dẫn: /' + real + (real !== a.slug ? ' (WordPress đã đổi từ /' + a.slug + ')' : '') + '<br>' +
        '• Ảnh: ' + up.done + '/' + up.total + ' đã tải lên (tên file, alt, chú thích chuẩn SEO)' + (up.fail.length ? ' — lỗi ' + up.fail.join('; ') : '') + '<br>' +
        '• Thẻ (tags): ' + tagIds.length + '/' + (a.tags || []).length + ' đã gắn' + (cats.length ? ' · Chuyên mục: ' + cats.join(', ') : '') + '<br>• ' + rmMsg);
    } catch (e) {
      showErr('Lỗi đăng bài: ' + (e.message || ''));
    } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = '<i class="ti ti-world-upload"></i> Đăng lên website'; }
    }
  }

  function install() {
    if (typeof publishArticle === 'function' && !publishArticle._qc) { window.publishArticle = qcPublish; window.publishArticle._qc = true; }
    if (typeof charBadge === 'function' && !charBadge._qc) {          // giới hạn tiêu đề SEO 60 (Rank Math), không phải 70
      var orig = charBadge;
      window.charBadge = function (val, max) { return orig(val, max === 70 ? 60 : max); };
      window.charBadge._qc = true;
    }
  }
  function installLinks() {
    if (typeof getServiceLinkUrl === 'function' && !getServiceLinkUrl._qc) {      // thiếu https:// → link bị hiểu là đường dẫn tương đối
      var og = getServiceLinkUrl;
      window.getServiceLinkUrl = function () {
        var u = og().trim();
        return u && !/^https?:\/\//i.test(u) ? 'https://' + u.replace(/^\/+/, '') : u;
      };
      window.getServiceLinkUrl._qc = true;
    }
    if (typeof saveLinksDB === 'function' && !saveLinksDB._qc) {
      var os = saveLinksDB;
      window.saveLinksDB = function (db) { var r = os.apply(this, arguments); pushLinksDB(db); return r; };
      window.saveLinksDB._qc = true;
    }
    if (typeof reapplyILinks === 'function' && !reapplyILinks._qc) {                // nút "Gắn links vào bài hiện tại"
      window.reapplyILinks = async function () {
        if (typeof curArticle === 'undefined' || !curArticle) { notify('Chưa có bài viết'); return; }
        if (!dbItems().length) { notify('Danh sách rỗng — đăng bài lên web trước hoặc thêm từ khóa + URL.'); return; }
        notify('🔗 Đang tìm bài liên quan và kiểm tra link...');
        var r = await internalLinks(curArticle);
        renderChecklist(curArticle);
        if (r.added && r.added.length) notify('🔗 Đã chèn ' + r.added.length + ' link nội bộ');
        else notify(r.reason === 'off' ? 'Internal links đang TẮT (bật công tắc ở trên)'
          : r.reason === 'not-live' ? 'Các bài liên quan chưa mở được (còn là bản nháp hoặc sai địa chỉ) — hãy xuất bản bài đó trước'
          : 'Chưa có bài cũ nào liên quan đến chủ đề bài này');
      };
      window.reapplyILinks._qc = true;
    }
  }
  installLinks();
  document.addEventListener('DOMContentLoaded', function () { install(); installLinks(); setTimeout(syncLinksDB, 600); });
  install();
  window.qcSeo = { internalLinks: internalLinks, linkPhrase: linkPhrase, relevance: relevance, finalize: finalize, buildSlug: buildSlug, slugify: slugify, rmChecks: rmChecks, maxSlug: maxSlug,
                   decorateContent: decorateContent, publish: qcPublish };
})();
