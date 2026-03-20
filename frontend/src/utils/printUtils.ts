/**
 * Открытие blob (PDF/SVG/PNG) в новом окне/вкладке.
 * Никогда не заменяет текущую страницу — всегда открывает в _blank.
 */
export function openBlobInNewWindow(
  blob: Blob,
  options?: { triggerPrint?: boolean }
): void {
  const url = URL.createObjectURL(blob);
  const win = window.open(url, '_blank', 'noopener,noreferrer');
  if (win) {
    win.focus();
    if (options?.triggerPrint) {
      win.onload = () => {
        win.print();
        URL.revokeObjectURL(url);
      };
    } else {
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    }
  } else {
    // Fallback: anchor с target="_blank" — часто не блокируется
    const a = document.createElement('a');
    a.href = url;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  }
}

/**
 * Открыть blob в текущем окне/вкладке.
 * Нужно, чтобы ФБС этикетка показывалась "в окне сайта", а не во втором popup.
 */
export function openBlobInSameTab(blob: Blob): void {
  const url = URL.createObjectURL(blob);

  // Раньше мы делали window.location.href, но это прерывает загрузку PDF в некоторых браузерах.
  // Вместо навигации показываем PDF в overlay-iframe поверх текущей страницы.
  const existing = document.getElementById('fbs-pdf-overlay');
  if (existing) existing.remove();

  const overlay = document.createElement('div');
  overlay.id = 'fbs-pdf-overlay';
  overlay.style.position = 'fixed';
  overlay.style.inset = '0';
  overlay.style.background = 'rgba(0,0,0,0.35)';
  overlay.style.zIndex = '9999';
  overlay.style.display = 'flex';
  overlay.style.flexDirection = 'column';

  const header = document.createElement('div');
  header.style.flex = '0 0 auto';
  header.style.display = 'flex';
  header.style.alignItems = 'center';
  header.style.justifyContent = 'space-between';
  header.style.padding = '10px 12px';
  header.style.background = '#fff';
  header.style.borderBottom = '1px solid rgba(0,0,0,0.12)';

  const title = document.createElement('div');
  title.textContent = 'Этикетка (PDF)';
  title.style.fontWeight = '600';
  title.style.fontSize = '14px';

  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.textContent = 'Закрыть';
  closeBtn.style.cursor = 'pointer';
  closeBtn.onclick = () => {
    try {
      overlay.remove();
    } finally {
      URL.revokeObjectURL(url);
    }
  };

  header.appendChild(title);
  header.appendChild(closeBtn);

  const iframe = document.createElement('iframe');
  iframe.style.border = '0';
  iframe.style.flex = '1 1 auto';
  iframe.style.width = '100%';
  iframe.style.height = '100%';
  iframe.src = url;

  overlay.appendChild(header);
  overlay.appendChild(iframe);
  document.body.appendChild(overlay);

  // Если пользователь не нажмёт "Закрыть", всё равно освобождаем URL спустя время.
  setTimeout(() => {
    try {
      if (document.getElementById('fbs-pdf-overlay')) {
        document.getElementById('fbs-pdf-overlay')?.remove();
      }
    } finally {
      URL.revokeObjectURL(url);
    }
  }, 120000);
}
