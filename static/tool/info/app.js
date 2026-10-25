// 进度条、顶栏收缩、入场、导航高亮 —— 不含任何图片与外部依赖。
(function () {
  var bar = document.querySelector('.progress i');
  var top = document.querySelector('.top');
  var links = Array.prototype.slice.call(document.querySelectorAll('.nav a'));
  var sections = links.map(function (a) { return document.querySelector(a.getAttribute('href')); });

  function onScroll() {
    var h = document.documentElement;
    var max = h.scrollHeight - h.clientHeight;
    var y = h.scrollTop || document.body.scrollTop;
    if (bar) { bar.style.width = (max > 0 ? (y / max) * 100 : 0) + '%'; }
    if (top) { top.classList.toggle('small', y > 40); }
    var best = -1;
    sections.forEach(function (s, i) {
      if (s && s.getBoundingClientRect().top <= 140) { best = i; }
    });
    links.forEach(function (a, i) { a.classList.toggle('on', i === best); });
  }

  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
    });
  }, { rootMargin: '0px 0px -12% 0px', threshold: 0.08 });

  document.querySelectorAll('[data-reveal]').forEach(function (el) { io.observe(el); });
  // 兜底：无论观察器是否回调，1.2 秒后一律显示（渐进增强，不让内容被 JS 扣住）
  setTimeout(function () {
    document.querySelectorAll('[data-reveal]').forEach(function (el) { el.classList.add('in'); });
  }, 1200);

  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll);
  onScroll();
})();
