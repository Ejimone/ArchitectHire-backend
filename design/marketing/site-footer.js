(function () {
  if (customElements.get('site-footer')) return;

  var COLS = [
    { h: 'Solutions', items: [
      ['By project type', 'Projects.dc.html'],
      ['By city', 'Cities.dc.html'],
      ['Full architecture', 'Project Landing.dc.html'],
      ['Commercial TI', 'Services Landing.dc.html'],
      ['Jurisdiction database', 'Jurisdiction Database.dc.html'],
    ]},
    { h: 'Services', items: [
      ['Video consult', 'Services.dc.html#catalog'],
      ['Plan review & markup', 'Services.dc.html#catalog'],
      ['CAD drafting', 'CAD Drafting.dc.html'],
      ['As-built packages', 'CAD Drafting.dc.html'],
      ['3D renders & floor plans', '3D Visualization.dc.html'],
      ['Interior design', 'Services.dc.html#catalog'],
      ['Scan-to-BIM', 'Services.dc.html#catalog'],
      ['Permit sets', 'Services.dc.html#catalog'],
      ['All services', 'Services.dc.html'],
    ]},
    { h: 'Resources', items: [
      ['Case studies', 'Case Studies.dc.html'],
      ['Guides', 'Blog.dc.html'],
      ['Inspiration', 'Inspiration.dc.html'],
      ['State permit guides', 'State Permit Guide.dc.html'],
    ]},
    { h: 'Company', items: [
      ['About', 'About.dc.html'],
      ['Careers', 'Careers.dc.html'],
      ['Contact', 'Contact.dc.html'],
      ['Blog', 'Blog.dc.html'],
      ['Privacy', 'Privacy.dc.html'],
    ]},
    { h: 'Join us', items: [
      ['For architects', 'Architect Landing.dc.html'],
      ['For service experts', 'For Experts.dc.html'],
      ['Log in', '../app/Account.dc.html'],
      ['Sign up', '../app/Get Started.dc.html'],
    ]},
  ];

  var LEGAL = [
    ['Terms of Service', 'Privacy.dc.html#terms'],
    ['Privacy Policy', 'Privacy.dc.html'],
  ];

  // Simple monochrome social glyphs
  function icon(paths) {
    return '<svg width="18" height="18" viewBox="0 0 24 24" fill="#9fb4ff" aria-hidden="true">' + paths + '</svg>';
  }
  var SOCIAL = [
    ['X', 'https://x.com', icon('<path d="M18.244 2h3.308l-7.227 8.26L23 22h-6.66l-5.214-6.817L5.16 22H1.85l7.73-8.835L1 2h6.828l4.713 6.231L18.244 2zm-1.161 18h1.833L7.084 3.9H5.117L17.083 20z"/>')],
    ['LinkedIn', 'https://linkedin.com', icon('<path d="M4.98 3.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5zM3 9h4v12H3zM10 9h3.8v1.7h.05c.53-1 1.83-2.05 3.77-2.05C21.5 8.65 22 11.1 22 14.3V21h-4v-5.9c0-1.4-.03-3.2-1.95-3.2-1.96 0-2.26 1.53-2.26 3.1V21h-4z"/>')],
    ['Instagram', 'https://instagram.com', icon('<path d="M12 2.16c3.2 0 3.58.01 4.85.07 1.17.05 1.8.25 2.23.41.56.22.96.48 1.38.9.42.42.68.82.9 1.38.16.42.36 1.06.41 2.23.06 1.27.07 1.65.07 4.85s-.01 3.58-.07 4.85c-.05 1.17-.25 1.8-.41 2.23-.22.56-.48.96-.9 1.38-.42.42-.82.68-1.38.9-.42.16-1.06.36-2.23.41-1.27.06-1.65.07-4.85.07s-3.58-.01-4.85-.07c-1.17-.05-1.8-.25-2.23-.41a3.7 3.7 0 0 1-1.38-.9 3.7 3.7 0 0 1-.9-1.38c-.16-.42-.36-1.06-.41-2.23C2.17 15.58 2.16 15.2 2.16 12s.01-3.58.07-4.85c.05-1.17.25-1.8.41-2.23.22-.56.48-.96.9-1.38.42-.42.82-.68 1.38-.9.42-.16 1.06-.36 2.23-.41C8.42 2.17 8.8 2.16 12 2.16zM12 0C8.74 0 8.33.01 7.05.07 5.78.13 4.9.33 4.14.63a5.9 5.9 0 0 0-2.13 1.38A5.9 5.9 0 0 0 .63 4.14c-.3.76-.5 1.64-.56 2.91C.01 8.33 0 8.74 0 12s.01 3.67.07 4.95c.06 1.27.26 2.15.56 2.91.3.79.72 1.46 1.38 2.13.67.66 1.34 1.08 2.13 1.38.76.3 1.64.5 2.91.56C8.33 23.99 8.74 24 12 24s3.67-.01 4.95-.07c1.27-.06 2.15-.26 2.91-.56a5.9 5.9 0 0 0 2.13-1.38 5.9 5.9 0 0 0 1.38-2.13c.3-.76.5-1.64.56-2.91.06-1.28.07-1.69.07-4.95s-.01-3.67-.07-4.95c-.06-1.27-.26-2.15-.56-2.91a5.9 5.9 0 0 0-1.38-2.13A5.9 5.9 0 0 0 19.86.63c-.76-.3-1.64-.5-2.91-.56C15.67.01 15.26 0 12 0zm0 5.84A6.16 6.16 0 1 0 12 18.16 6.16 6.16 0 0 0 12 5.84zm0 10.16A4 4 0 1 1 12 8a4 4 0 0 1 0 8zm6.4-11.85a1.44 1.44 0 1 0 0 2.88 1.44 1.44 0 0 0 0-2.88z"/>')],
    ['Facebook', 'https://facebook.com', icon('<path d="M24 12a12 12 0 1 0-13.88 11.85v-8.38H7.08V12h3.04V9.36c0-3 1.79-4.67 4.53-4.67 1.31 0 2.68.24 2.68.24v2.95h-1.51c-1.49 0-1.95.93-1.95 1.87V12h3.32l-.53 3.47h-2.79v8.38A12 12 0 0 0 24 12z"/>')],
  ];

  class SiteFooter extends HTMLElement {
    connectedCallback() {
      var logo = '<div style="display:grid;grid-template-columns:repeat(3,1fr);grid-template-rows:repeat(3,1fr);gap:2px;width:22px;height:22px;flex-shrink:0;">' +
        '<div style="background:#fff;"></div><div style="background:#fff;"></div><div style="background:#fff;"></div><div style="background:#fff;"></div><div style="background:#ceff65;"></div><div style="background:#fff;"></div><div style="background:#fff;"></div><div style="background:#fff;"></div><div style="background:#fff;"></div></div>';

      var cols = COLS.map(function (c) {
        var links = c.items.map(function (it) {
          return '<a href="' + it[1] + '" class="sf-link" style="color:#b9c3e8;font-size:14px;text-decoration:none;line-height:1.45;">' + it[0] + '</a>';
        }).join('');
        return '<div><div style="font-size:13px;letter-spacing:.05em;text-transform:uppercase;color:#9fb4ff;margin-bottom:14px;">' + c.h + '</div>' +
          '<div style="display:flex;flex-direction:column;gap:10px;">' + links + '</div></div>';
      }).join('');

      var legal = LEGAL.map(function (l) {
        return '<a href="' + l[1] + '" class="sf-link" style="color:#6f7cae;font-size:13px;text-decoration:none;">' + l[0] + '</a>';
      }).join('');

      var social = SOCIAL.map(function (s) {
        return '<a href="' + s[1] + '" class="sf-social" aria-label="' + s[0] + '" style="display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;border-radius:50%;border:1px solid #1d2f6e;text-decoration:none;transition:border-color .15s ease;">' + s[2] + '</a>';
      }).join('');

      this.innerHTML =
        '<style>' +
          'site-footer .sf-link:hover{color:#fff;}' +
          'site-footer .sf-social:hover{border-color:#ceff65;}' +
          'site-footer .sf-social:hover svg{fill:#ceff65;}' +
          '@media (max-width:900px){site-footer .sf-cols{grid-template-columns:repeat(2,1fr) !important;}site-footer .sf-bottom{flex-direction:column !important;align-items:flex-start !important;gap:20px !important;}}' +
        '</style>' +
        '<footer style="background:#0a1440;color:#b9c3e8;font-family:\'Hanken Grotesk\',sans-serif;">' +
          '<div style="max-width:1200px;margin:0 auto;padding:56px 32px 40px;">' +
            '<div class="sf-cols" style="display:grid;grid-template-columns:repeat(5,1fr);gap:32px;">' + cols + '</div>' +
          '</div>' +
          '<div style="border-top:1px solid #1d2f6e;">' +
            '<div class="sf-bottom" style="max-width:1200px;margin:0 auto;padding:22px 32px;display:flex;align-items:center;justify-content:space-between;gap:24px;flex-wrap:wrap;">' +
              '<div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;">' +
                '<a href="Landing.dc.html" style="display:flex;align-items:center;gap:9px;text-decoration:none;">' + logo +
                  '<span style="font-family:\'Bricolage Grotesque\',sans-serif;font-size:16px;font-weight:700;color:#fff;">ArchitectHire</span></a>' +
                '<span style="font-size:13px;color:#6f7cae;">© 2026 ArchitectHire, Inc.</span>' +
                '<span style="display:flex;gap:16px;">' + legal + '</span>' +
              '</div>' +
              '<div style="display:flex;align-items:center;gap:10px;">' + social + '</div>' +
            '</div>' +
          '</div>' +
        '</footer>';
    }
  }
  customElements.define('site-footer', SiteFooter);
})();
