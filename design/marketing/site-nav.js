(function () {
  if (customElements.get('site-nav')) return;

  // ---- Services mega-dropdown (wide, 3-col) ----
  var SVC = [
    { name: 'Consults & reviews', items: [
      ['Video consult', '$145', 'Services.dc.html#catalog'],
      ['Plan review & markup', '$150', 'Services.dc.html#catalog'],
      ['Feasibility check', '$250', 'Services.dc.html#catalog'],
    ]},
    { name: 'Drafting & docs', items: [
      ['CAD drafting', '$65/hr', 'CAD Drafting.dc.html'],
      ['As-built package', '$2,500', 'CAD Drafting.dc.html'],
      ['PDF-to-CAD', '$10/sht', 'CAD Drafting.dc.html'],
    ]},
    { name: '3D & visualization', items: [
      ['Single render', '$99', '3D Visualization.dc.html'],
      ['3D floor plan', '$100', '3D Visualization.dc.html'],
      ['Walkthrough', '$50/s', '3D Visualization.dc.html'],
    ]},
    { name: 'Scanning & BIM', items: [
      ['3D laser scanning', '$0.20/sf', 'Services.dc.html#catalog'],
      ['Scan-to-BIM', '$0.50/sf', 'Services.dc.html#catalog'],
    ]},
    { name: 'Engineering', items: [
      ['Title-24 / energy', '$300', 'Services.dc.html#catalog'],
      ['Structural stamp', '$1,500', 'Services.dc.html#catalog'],
      ['Code consulting', '$150/hr', 'Services.dc.html#catalog'],
    ]},
    { name: 'Permits & full design', items: [
      ['Permit set', '$2,000', 'Services.dc.html#catalog'],
      ['Zoning study', '$1,500', 'Services.dc.html#catalog'],
      ['Full ADU / home', '$7,490', 'Project Landing.dc.html'],
    ]},
    { name: 'Interior design', items: [
      ['Interior design package', '$1,200', 'Services.dc.html#catalog'],
      ['Virtual staging', '$75', 'Services.dc.html#catalog'],
      ['Furniture & FF&E plan', '$600', 'Services.dc.html#catalog'],
    ]},
  ];

  // ---- Projects (architecture project types) ----
  var PROJECTS = [
    ['Backyard ADU', 'From $2,400', 'Project Landing.dc.html'],
    ['Home addition', 'From $11,000', 'Project Landing.dc.html'],
    ['Whole-home renovation', 'From $8,500', 'Project Landing.dc.html'],
    ['Kitchen & bath', 'From $2,400', 'Project Landing.dc.html'],
    ['New custom home', 'From $26,000', 'Project Landing.dc.html'],
    ['Garage conversion', 'From $4,500', 'Project Landing.dc.html'],
    ['Commercial TI', 'From $8,000', 'Project Landing.dc.html'],
    ['Change of use', 'From $6,000', 'Project Landing.dc.html'],
  ];

  // ---- Locations (cities) ----
  var CITIES = [
    ['Oakland, CA', 'City Landing.dc.html'],
    ['San Francisco, CA', 'City Landing.dc.html'],
    ['San Jose, CA', 'City Landing.dc.html'],
    ['Los Angeles, CA', 'City Landing.dc.html'],
    ['San Diego, CA', 'City Landing.dc.html'],
    ['Sacramento, CA', 'City Landing.dc.html'],
    ['Seattle, WA', 'City Landing.dc.html'],
    ['Portland, OR', 'City Landing.dc.html'],
    ['Austin, TX', 'City Landing.dc.html'],
    ['Denver, CO', 'City Landing.dc.html'],
    ['Phoenix, AZ', 'City Landing.dc.html'],
    ['New York, NY', 'City Landing.dc.html'],
  ];

  var LK = "color:#232c57;font-weight:600;text-decoration:none;white-space:nowrap;transition:color .15s ease;";
  var LK_ACTIVE = "color:#135bff;";

  function panelWrap(inner, width) {
    return '<div class="sn-panel" style="position:absolute;left:-24px;top:calc(100% + 14px);width:' + width + 'px;background:#fff;border:1px solid #e2e8f5;border-radius:16px;box-shadow:0 20px 50px rgba(10,20,64,.18);padding:18px 20px;z-index:60;opacity:0;visibility:hidden;transform:translateY(-6px);transition:opacity .16s ease, transform .16s ease, visibility .16s;">' + inner + '</div>';
  }
  function ctaLink(href, label) {
    return '<a href="' + href + '" style="display:block;text-align:center;margin-top:10px;padding:11px;border-radius:10px;background:#0a1440;color:#fff;font-size:13.5px;font-weight:700;text-decoration:none;">' + label + '</a>';
  }
  function svcItem(it) {
    return '<a href="' + it[2] + '" class="sn-svc-link" style="display:flex;justify-content:space-between;gap:12px;padding:6px 8px;border-radius:8px;font-size:13.5px;color:#232c57;font-weight:600;text-decoration:none;">' +
      '<span style="white-space:nowrap;">' + it[0] + '</span><span style="font-family:\'IBM Plex Mono\',monospace;font-size:12px;color:#8b93b5;">' + it[1] + '</span></a>';
  }

  function dropdown(label, topHref, panelInner, panelWidth, active, activeKey) {
    var isActive = active === activeKey;
    return '<div class="sn-dd" style="position:relative;">' +
      '<a href="' + topHref + '" style="' + LK + (isActive ? LK_ACTIVE : '') + 'display:inline-flex;align-items:center;gap:5px;">' + label +
        '<span class="sn-caret" style="display:inline-block;font-size:11px;transition:transform .16s ease;">▾</span></a>' +
      panelWrap(panelInner, panelWidth) +
    '</div>';
  }

  class SiteNav extends HTMLElement {
    connectedCallback() {
      this.style.display = 'block';
      this.style.position = 'sticky';
      this.style.top = '0';
      this.style.zIndex = '40';

      var active = (this.getAttribute('active') || '').toLowerCase();

      var logo = '<div style="width:26px;height:26px;display:grid;grid-template-columns:repeat(3,1fr);grid-template-rows:repeat(3,1fr);gap:2.5px;flex-shrink:0;">' +
        '<div style="background:#0a1440;"></div><div style="background:#0a1440;"></div><div style="background:#0a1440;"></div><div style="background:#0a1440;"></div><div style="background:#ceff65;"></div><div style="background:#0a1440;"></div><div style="background:#0a1440;"></div><div style="background:#0a1440;"></div><div style="background:#0a1440;"></div></div>';

      // Services panel (3-col mega)
      var svcGroups = SVC.map(function (g) {
        var items = g.items.map(svcItem).join('');
        return '<div style="padding:8px 0;"><div style="font-family:\'IBM Plex Mono\',monospace;font-size:11px;letter-spacing:.05em;color:#8b93b5;text-transform:uppercase;margin-bottom:8px;">' + g.name + '</div>' +
          '<div style="display:flex;flex-direction:column;gap:3px;">' + items + '</div></div>';
      }).join('');
      var svcPanel = '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px 26px;">' + svcGroups + '</div>' +
        ctaLink('Services.dc.html', 'Browse the full services catalog →');

      // Projects panel (links, no pricing, + featured image)
      var projItems = PROJECTS.map(function (p) {
        return '<a href="' + p[2] + '" class="sn-svc-link" style="display:block;padding:7px 8px;border-radius:8px;font-size:13.5px;color:#232c57;font-weight:600;text-decoration:none;white-space:nowrap;">' + p[0] + '</a>';
      }).join('');
      var projFeatured = '<a href="Project Landing.dc.html" style="display:block;width:236px;flex-shrink:0;border-radius:12px;overflow:hidden;border:1px solid #e2e8f5;text-decoration:none;">' +
        '<div style="height:132px;background:repeating-linear-gradient(135deg,#eef2fb,#eef2fb 11px,#e4eaf7 11px,#e4eaf7 22px);display:flex;align-items:center;justify-content:center;">' +
          '<span style="font-family:\'IBM Plex Mono\',monospace;font-size:11px;letter-spacing:.04em;color:#9aa3c4;">featured project</span></div>' +
        '<div style="padding:13px 15px;">' +
          '<div style="font-family:\'IBM Plex Mono\',monospace;font-size:10.5px;letter-spacing:.05em;color:#135bff;">MOST POPULAR</div>' +
          '<div style="font-family:\'Bricolage Grotesque\',sans-serif;font-weight:700;font-size:15px;color:#0a1440;margin-top:4px;">Backyard ADUs</div>' +
          '<div style="font-size:12.5px;color:#5b6493;margin-top:2px;">2–3 weeks to a stamped set</div>' +
        '</div></a>';
      var projPanel = '<div style="display:flex;gap:24px;">' +
        '<div style="flex:1 1 auto;min-width:340px;">' +
          '<div style="font-family:\'IBM Plex Mono\',monospace;font-size:11px;letter-spacing:.05em;color:#8b93b5;text-transform:uppercase;margin-bottom:8px;">By project type</div>' +
          '<div style="display:grid;grid-template-columns:1fr 1fr;gap:2px 16px;">' + projItems + '</div>' +
          ctaLink('Projects.dc.html', 'Browse all project types →') +
        '</div>' + projFeatured +
      '</div>';

      // Locations panel (2-col cities)
      var cityItems = CITIES.map(function (c) {
        return '<a href="' + c[1] + '" class="sn-svc-link" style="display:block;padding:6px 8px;border-radius:8px;font-size:13.5px;color:#232c57;font-weight:600;text-decoration:none;">' + c[0] + '</a>';
      }).join('');
      var locPanel = '<div style="font-family:\'IBM Plex Mono\',monospace;font-size:11px;letter-spacing:.05em;color:#8b93b5;text-transform:uppercase;margin-bottom:8px;">By city</div>' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:2px 14px;">' + cityItems + '</div>' +
        ctaLink('Cities.dc.html', 'Browse all cities →');

      var nav =
        dropdown('Services', 'Services Landing.dc.html', svcPanel, 720, active, 'services') +
        dropdown('Projects', 'Projects.dc.html', projPanel, 640, active, 'projects') +
        dropdown('Locations', 'Cities.dc.html', locPanel, 340, active, 'locations');

      // Mobile menu top-level links
      var MOBILE = [['Services', 'Services Landing.dc.html'], ['Projects', 'Projects.dc.html'], ['Locations', 'Cities.dc.html']];
      var mobileLinks = MOBILE.map(function (l) {
        return '<a href="' + l[1] + '" style="padding:11px 4px;font-size:16px;font-weight:600;color:#232c57;text-decoration:none;border-bottom:1px solid #eef2fb;">' + l[0] + '</a>';
      }).join('');

      var searchIcon = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#8b93b5" stroke-width="2" stroke-linecap="round" style="position:absolute;left:12px;top:50%;transform:translateY(-50%);pointer-events:none;"><circle cx="11" cy="11" r="7"></circle><path d="M21 21l-4.3-4.3"></path></svg>';
      var searchForm = '<form class="sn-search" action="Search.dc.html" method="get" style="position:relative;margin-left:auto;flex:0 1 260px;min-width:150px;">' + searchIcon +
        '<input name="q" aria-label="Search" placeholder="Search services, projects, cities…" style="width:100%;background:#fff;border:1px solid #dbe2f2;border-radius:10px;padding:9px 12px 9px 36px;font-size:14px;font-family:inherit;color:#0a1440;outline:none;"></form>';
      var mobileSearch = '<form action="Search.dc.html" method="get" style="position:relative;margin:6px 0 10px;">' + searchIcon +
        '<input name="q" aria-label="Search" placeholder="Search…" style="width:100%;background:#fff;border:1px solid #dbe2f2;border-radius:10px;padding:12px 12px 12px 36px;font-size:15px;font-family:inherit;color:#0a1440;outline:none;"></form>';

      this.innerHTML =
        '<style>' +
          'site-nav .sn-link:hover,site-nav .sn-dd>a:hover{color:#135bff;}' +
          'site-nav .sn-svc-link:hover{background:#eef2fb;color:#135bff;}' +
          'site-nav .sn-search input:focus,site-nav .sn-mobile input:focus{border-color:#135bff;}' +
          'site-nav .sn-dd:hover .sn-panel{opacity:1 !important;visibility:visible !important;transform:translateY(0) !important;}' +
          'site-nav .sn-dd:hover .sn-caret{transform:rotate(180deg);}' +
          '@media (max-width:1040px){site-nav .sn-nav,site-nav .sn-cta,site-nav .sn-search{display:none !important;}site-nav .sn-burger{display:inline-flex !important;}}' +
          '@media (min-width:1041px){site-nav .sn-mobile{display:none !important;}}' +
          '@media (max-width:1040px){site-nav .sn-mobile{display:block !important;}}' +
        '</style>' +
        '<header style="background:rgba(243,246,253,.94);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);border-bottom:1px solid #dbe2f2;font-family:\'Hanken Grotesk\',sans-serif;">' +
          '<div style="max-width:1200px;margin:0 auto;padding:15px 32px;display:flex;align-items:center;gap:20px;">' +
            '<a href="Landing.dc.html" style="display:flex;align-items:center;gap:10px;flex-shrink:0;text-decoration:none;">' + logo +
              '<span style="font-family:\'Bricolage Grotesque\',sans-serif;font-size:20px;font-weight:700;letter-spacing:-.01em;color:#0a1440;">ArchitectHire</span></a>' +
            '<nav class="sn-nav" style="display:flex;align-items:center;gap:24px;font-size:15px;min-width:0;">' + nav + '</nav>' +
            searchForm +
            '<div class="sn-cta" style="display:flex;align-items:center;gap:14px;flex-shrink:0;">' +
              '<a href="../app/Account.dc.html" class="sn-link" style="' + LK + 'font-size:15px;">Log in</a>' +
              '<a href="../app/Get Started.dc.html" style="background:#135bff;color:#fff;padding:11px 20px;border-radius:9px;font-size:15px;font-weight:700;text-decoration:none;white-space:nowrap;box-shadow:0 2px 0 #0b3fcc;">Sign up</a>' +
            '</div>' +
            '<button class="sn-burger" aria-label="Menu" style="display:none;margin-left:auto;flex-shrink:0;align-items:center;justify-content:center;width:42px;height:42px;border:1px solid #dbe2f2;border-radius:10px;background:#fff;cursor:pointer;">' +
              '<span style="display:block;width:18px;height:2px;background:#0a1440;box-shadow:0 -6px 0 #0a1440,0 6px 0 #0a1440;"></span></button>' +
          '</div>' +
          '<div class="sn-mobile" style="overflow:hidden;max-height:0;transition:max-height .25s ease;background:#fff;border-bottom:1px solid #dbe2f2;">' +
            '<div style="max-width:1200px;margin:0 auto;padding:8px 24px 18px;display:flex;flex-direction:column;gap:2px;">' + mobileSearch + mobileLinks +
              '<div style="display:flex;gap:12px;margin-top:12px;">' +
                '<a href="../app/Account.dc.html" style="flex:1;text-align:center;padding:12px;border-radius:9px;border:1px solid #dbe2f2;color:#232c57;font-weight:700;font-size:15px;text-decoration:none;">Log in</a>' +
                '<a href="../app/Get Started.dc.html" style="flex:1;text-align:center;padding:12px;border-radius:9px;background:#135bff;color:#fff;font-weight:700;font-size:15px;text-decoration:none;">Sign up</a>' +
              '</div>' +
            '</div>' +
          '</div>' +
        '</header>';

      var burger = this.querySelector('.sn-burger');
      var mobile = this.querySelector('.sn-mobile');
      if (burger && mobile) {
        burger.addEventListener('click', function () {
          var open = mobile.style.maxHeight && mobile.style.maxHeight !== '0px';
          mobile.style.maxHeight = open ? '0px' : (mobile.scrollHeight + 20) + 'px';
        });
      }
    }
  }
  customElements.define('site-nav', SiteNav);
})();
