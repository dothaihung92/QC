// Chế độ BÁM SÁT BÀI GỐC cho tab "Viết bài SEO" khi bài được gửi sang từ tab "Tin tức AI" (nút ✍️ SEO bài viết).
// Lỗi trước đây: AI bật Google Search + Nghiên cứu sâu nên tự thêm văn bản / mốc hiệu lực / mẫu biểu / con số
// KHÔNG có trong bài gốc và bỏ mất tình huống, số liệu cốt lõi. Bây giờ:
//  1) Khi viết: tắt tìm kiếm + nghiên cứu sâu, bắt AI chỉ dùng bài gốc, giữ đủ tình huống + số liệu + kết luận.
//  2) Viết xong: đối chiếu con số, tỷ lệ, số hiệu văn bản, ngày tháng giữa bài SEO và bài gốc.
//     Có thông tin lạ (không có trong bài gốc) hoặc thiếu số liệu chính → AI sửa lại đúng các đoạn đó, rồi kiểm tra lần nữa.
//  3) Hiện thẻ "Đối chiếu với bài gốc" ở cột phải.
(function () {
  'use strict';
  function notify(m) { if (typeof toast === 'function') toast(m); }
  function plain(h) { return String(h || '').replace(/<[^>]+>/g, ' ').replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ').trim(); }
  function esc(t) { return String(t == null ? '' : t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

  var src = null;               // {title, body, url} của bài tin đang được viết lại
  var FAITHFUL = '\n\n🚨 CHẾ ĐỘ BÁM SÁT BÀI GỐC (ƯU TIÊN CAO NHẤT, thay cho mọi yêu cầu tìm kiếm / nghiên cứu ở trên):\n' +
    '- BÀI TIN GỐC trong phần "NỘI DUNG VĂN BẢN" là nguồn DUY NHẤT. Viết lại thành bài SEO hay hơn, dễ hiểu hơn nhưng ĐÚNG Ý bài gốc.\n' +
    '- GIỮ ĐỦ: tình huống thực tế, MỌI con số / tỷ lệ / số tiền / thời hạn hợp đồng, số hiệu + ngày của văn bản, điều khoản được trích, ' +
    'KẾT LUẬN của cơ quan thuế và các việc doanh nghiệp cần làm có trong bài gốc. Trình bày theo mạch của bài gốc: tình huống → quy định → kết luận → việc cần làm.\n' +
    '- TUYỆT ĐỐI KHÔNG thêm văn bản pháp luật, luật, thông tư, mẫu biểu, mốc hiệu lực, "điểm mới", con số hoặc so sánh với quy định cũ KHÔNG có trong bài gốc. ' +
    'Không đổi ngày ban hành thành ngày hiệu lực. Chỗ bài gốc không nói thì không suy diễn.\n' +
    '- Được thêm: giải thích thuật ngữ bằng lời thường, MỘT ví dụ tính toán CHỈ dùng số liệu có trong bài gốc (phép tính đúng), câu hỏi thường gặp trả lời theo bài gốc.\n';

  // ── trích "dữ kiện" từ văn bản: số tiền, tỷ lệ, số hiệu văn bản, ngày tháng, số tháng/năm ──
  var UNIT = { 'tỷ': 1e9, 'triệu': 1e6, 'nghìn': 1e3, 'ngàn': 1e3 };
  function num(s) {                                   // "3.440.000" → 3440000 ; "21,5" → 21.5 ; "05" → 5
    s = String(s);
    if (/^\d{1,3}(\.\d{3})+$/.test(s)) return +s.replace(/\./g, '');
    if (/^\d{1,3}(,\d{3})+$/.test(s)) return +s.replace(/,/g, '');
    return +s.replace(',', '.');
  }
  function facts(text) {
    var t = ' ' + plain(text) + ' ', out = { codes: {}, dates: {}, money: {}, pct: {}, dur: {}, years: {} };
    (t.match(/\d{1,5}\/\d{4}\/[A-ZĐ][A-ZĐ0-9\-]*|\d{1,5}\/[A-ZĐ]{1,8}-[A-ZĐ0-9\-]+/g) || []).forEach(function (c) { out.codes[c.toUpperCase()] = c; });
    (t.match(/\b\d{1,2}\/\d{1,2}\/\d{4}\b/g) || []).forEach(function (d) {
      var p = d.split('/'); out.dates[(+p[0]) + '/' + (+p[1]) + '/' + p[2]] = d;
    });
    // năm đứng riêng (vd "Luật ... 2025") — bỏ phần đã thuộc số hiệu / ngày tháng
    (t.replace(/\d{1,5}\/\d{4}\/\S+|\d{1,2}\/\d{1,2}\/\d{4}/g, ' ').match(/\b(19|20)\d{2}\b/g) || []).forEach(function (y) { out.years[y] = 'năm ' + y; });
    var re = /(\d[\d.,]*)\s*(%|tỷ|triệu|nghìn|ngàn|đồng|tháng|năm)/gi, m;
    while ((m = re.exec(t))) {
      if (/\/\s*$/.test(t.slice(0, m.index))) continue;    // phần của số hiệu / ngày
      var v = num(m[1]), u = m[2].toLowerCase();
      if (isNaN(v)) continue;
      if (u === '%') out.pct[v] = m[0];
      else if (u === 'tháng' || u === 'năm') { if (v < 100) out.dur[v + ' ' + u] = m[0]; }
      else out.money[Math.round(v * (UNIT[u] || 1))] = m[0];
    }
    return out;
  }
  function derived(v, f) {                            // con số tính ra từ số liệu gốc (vd 10% × 19.440.000) thì không coi là bịa
    var money = Object.keys(f.money).map(Number), pct = Object.keys(f.pct).map(Number);
    for (var i = 0; i < money.length; i++) {
      for (var j = 0; j < pct.length; j++) if (Math.abs(money[i] * pct[j] / 100 - v) < 2) return true;
      for (var k = 0; k < money.length; k++) if (Math.abs(money[i] + money[k] - v) < 2 || Math.abs(money[i] - money[k] - v) < 2) return true;
    }
    return false;
  }
  function articleText(a) {
    return (a.sections || []).map(function (s) { return (s.heading || '') + ' . ' + (s.content || ''); }).join(' . ') + ' . ' +
      (a.qa || []).map(function (q) { return q.q + ' . ' + q.a; }).join(' . ') + ' . ' + (a.conclusion || '');
  }
  function compare(a, source) {
    var S = facts(source.title + ' . ' + source.body), A = facts(articleText(a) + ' . ' + (a.title || '') + ' . ' + (a.metaDescription || ''));
    var extra = [], missing = [];
    Object.keys(A.codes).forEach(function (c) { if (!S.codes[c]) extra.push(A.codes[c]); });
    Object.keys(A.dates).forEach(function (d) { if (!S.dates[d]) extra.push(A.dates[d]); });
    Object.keys(A.money).forEach(function (v) { if (!S.money[v] && !derived(+v, S) && +v >= 1000) extra.push(A.money[v]); });
    Object.keys(A.pct).forEach(function (v) { if (!S.pct[v]) extra.push(A.pct[v]); });
    Object.keys(A.years).forEach(function (y) { if (!S.years[y] && !Object.keys(S.dates).some(function (d) { return d.slice(-4) === y; })) extra.push(A.years[y]); });
    Object.keys(S.codes).forEach(function (c) { if (!A.codes[c]) missing.push(S.codes[c]); });
    Object.keys(S.money).forEach(function (v) { if (!A.money[v] && +v >= 100000) missing.push(S.money[v]); });
    Object.keys(S.pct).forEach(function (v) { if (!A.pct[v]) missing.push(S.pct[v]); });
    Object.keys(S.dur).forEach(function (v) { if (!A.dur[v]) missing.push(S.dur[v]); });
    var uniq = function (x) { return x.filter(function (v, i) { return x.indexOf(v) === i; }); };
    return { extra: uniq(extra), missing: uniq(missing) };
  }

  async function askJSON(prompt) {
    var gkey = ((document.getElementById('gkey') || {}).value || '').trim();
    if (!gkey || typeof callGeminiWithFallback !== 'function') return null;
    try {
      var res = await callGeminiWithFallback(gkey, { contents: [{ role: 'user', parts: [{ text: prompt }] }],
        generationConfig: { temperature: 0.2, maxOutputTokens: 12000, responseMimeType: 'application/json' } });
      var c = ((res.data.candidates || [])[0] || {}).content;
      var raw = c ? (c.parts || []).map(function (p) { return p.text || ''; }).join('') : '';
      return typeof extractJSON === 'function' ? extractJSON(raw) : JSON.parse(raw);
    } catch (e) { return null; }
  }

  async function fix(a, source, diff) {
    var secs = a.sections || [];
    var j = await askJSON('Bạn là biên tập viên thuế. Sửa bài SEO dưới đây cho ĐÚNG với BÀI GỐC.\n\nBÀI GỐC:\n' + source.title + '\n' +
      String(source.body).slice(0, 7000) + '\n\nTHÔNG TIN TRONG BÀI SEO KHÔNG CÓ Ở BÀI GỐC (phải bỏ, hoặc sửa đúng theo bài gốc): ' +
      (diff.extra.join('; ') || '(không)') + '\nSỐ LIỆU CỦA BÀI GỐC BÀI SEO CÒN THIẾU (phải đưa vào đúng chỗ, có giải thích): ' +
      (diff.missing.join('; ') || '(không)') + '\n\nBÀI SEO (mỗi đoạn có chỉ số i):\n' +
      secs.map(function (s, i) { return '[i=' + i + '] ' + (s.heading ? '## ' + s.heading + '\n' : '') + (s.content || ''); }).join('\n\n') +
      '\n\nYÊU CẦU: chỉ sửa các đoạn cần sửa; GIỮ NGUYÊN định dạng HTML, các thẻ <a>, <strong>, <ul>; không thêm văn bản / con số / mốc nào không có trong bài gốc; ' +
      'nếu bài SEO chưa có phần tình huống thực tế và kết luận của cơ quan thuế như bài gốc thì bổ sung vào đoạn phù hợp, kèm một ví dụ tính toán chỉ dùng số liệu bài gốc.\n' +
      'Chỉ trả về JSON {"sections":[{"i":0,"heading":"(giữ nguyên nếu không đổi)","content":"<p>…</p>"}],"qa":[{"q":"…","a":"…"}]} — "qa" chỉ trả khi phần hỏi đáp có thông tin sai.');
    if (!j) return false;
    var changed = false;
    (j.sections || []).forEach(function (x) {
      var i = +x.i, s = secs[i];
      if (!s || !x.content || !/<(p|ul|ol|div|table)/i.test(x.content)) return;
      s.content = String(x.content);
      if (x.heading && s.heading && x.heading.length < 120) s.heading = String(x.heading).replace(/^#+\s*/, '');
      var el = document.getElementById('ed-content-' + i);
      if (el) el.innerHTML = s.content;
      var he = document.getElementById('ed-h-' + i);
      if (he && s.heading) he.textContent = s.heading;
      changed = true;
    });
    if (Array.isArray(j.qa) && j.qa.length >= 3) {
      a.qa = j.qa.filter(function (q) { return q && q.q && q.a; }).map(function (q) { return { q: esc(plain(q.q)), a: esc(plain(q.a)) }; });
      document.querySelectorAll('#ed-sec-qa .qa-item').forEach(function (el, qi) {
        var q = a.qa[qi]; if (!q) return;
        var qt = el.querySelector('.qa-q-text'), at = el.querySelector('.qa-a');
        if (qt) qt.innerHTML = q.q;
        if (at) at.innerHTML = q.a;
      });
      changed = true;
    }
    return changed;
  }

  function report(a, diff, fixed) {
    var side = document.getElementById('sidebar');
    if (!side) return;
    var old = document.getElementById('qc-faith-card');
    if (old) old.remove();
    var ok = !diff.extra.length && !diff.missing.length;
    var card = document.createElement('div');
    card.className = 'side-card';
    card.id = 'qc-faith-card';
    card.innerHTML = '<div class="side-title"><i class="ti ti-file-check" style="font-size:14px"></i>Đối chiếu với bài gốc ' +
      '<span style="margin-left:6px;font-size:11px;font-weight:700;color:' + (ok ? 'var(--success)' : 'var(--warn)') + '">' + (ok ? 'khớp ✓' : 'cần xem') + '</span></div>' +
      (fixed ? '<div style="font-size:12px;color:var(--text2);margin-bottom:6px">AI đã sửa lại các đoạn lệch với bài gốc.</div>' : '') +
      (diff.extra.length ? '<div style="font-size:12px;margin:4px 0"><b style="color:var(--danger)">Có trong bài SEO nhưng KHÔNG có ở bài gốc:</b> ' +
        diff.extra.map(esc).join(', ') + '<br><span style="color:var(--text3)">→ kiểm tra lại, xóa nếu không chắc chắn</span></div>' : '') +
      (diff.missing.length ? '<div style="font-size:12px;margin:4px 0"><b style="color:var(--warn)">Số liệu của bài gốc chưa có trong bài SEO:</b> ' +
        diff.missing.map(esc).join(', ') + '</div>' : '') +
      (ok ? '<div style="font-size:12px;color:var(--success)">Mọi con số, tỷ lệ, số hiệu văn bản, ngày tháng đều có trong bài gốc.</div>' : '') +
      (src && src.url ? '<div style="font-size:11px;margin-top:6px"><a href="' + esc(src.url) + '" target="_blank" style="color:var(--info)">Mở bài gốc ↗</a></div>' : '');
    var first = side.querySelector('.side-card');
    if (first && first.nextSibling) side.insertBefore(card, first.nextSibling); else side.appendChild(card);
  }

  async function verify(a) {
    if (!src || !a) return;
    var source = src;
    var diff = compare(a, source), fixed = false;
    if (diff.extra.length || diff.missing.length) {
      notify('🔎 Bài SEO lệch bài gốc (' + (diff.extra.length + diff.missing.length) + ' chỗ) — AI đang sửa lại...');
      fixed = await fix(a, source, diff);
      if (fixed) {
        diff = compare(a, source);
        if (typeof window.qcLinkLegalDocs === 'function') window.qcLinkLegalDocs();   // gắn lại link văn bản cho đoạn đã sửa
      }
    }
    report(a, diff, fixed);
  }

  // Khi đang ở chế độ bám sát: lệnh viết bài chính không dùng Google Search và có thêm chỉ dẫn bám sát
  function wrapCall() {
    if (typeof callGeminiWithFallback !== 'function' || callGeminiWithFallback._qcFaith) return;
    var orig = callGeminiWithFallback;
    window.callGeminiWithFallback = function (gkey, body, onTry) {
      try {
        var part = src && body && body.contents && body.contents[0] && body.contents[0].parts && body.contents[0].parts[0];
        if (part && typeof part.text === 'string' && /NHIỆM VỤ TÌM KIẾM GOOGLE/.test(part.text)) {
          body = JSON.parse(JSON.stringify(body));
          delete body.tools;
          body.contents[0].parts[0].text = part.text.split('🔍 NHIỆM VỤ TÌM KIẾM GOOGLE')[0] + FAITHFUL + '\nSau đó viết bài SEO đầy đủ theo JSON yêu cầu.';
          if (body.generationConfig) body.generationConfig.temperature = 0.4;
        }
      } catch (e) {}
      return orig.call(this, gkey, body, onTry);
    };
    window.callGeminiWithFallback._qcFaith = true;
  }
  wrapCall();
  document.addEventListener('DOMContentLoaded', wrapCall);

  var deepWas = null;
  window.qcFaithful = {
    begin: function (s) {                              // gọi khi nhận bài từ tab Tin tức AI
      wrapCall();
      src = s && s.body ? s : null;
      var deep = document.getElementById('deep-research-chk');
      if (src && deep) { deepWas = deep.checked; deep.checked = false; }   // nghiên cứu sâu hay kéo thông tin ngoài bài gốc vào
    },
    end: async function (a) {                          // gọi khi viết xong
      try { await verify(a); } finally {
        var deep = document.getElementById('deep-research-chk');
        if (deep && deepWas !== null) deep.checked = deepWas;
        deepWas = null;
        src = null;
      }
    },
    active: function () { return !!src; },
    facts: facts, compare: compare
  };
})();
