/**
 * Открытие blob (PDF/SVG/PNG) в новом окне/вкладке.
 * Никогда не заменяет текущую страницу — всегда открывает в _blank.
 */
export function openBlobInNewWindow(
  blob: Blob,
  options?: { triggerPrint?: boolean; forceAnchor?: boolean }
): void {
  const url = URL.createObjectURL(blob);
  if (options?.forceAnchor) {
    // Для второго окна иногда надёжнее открывать через anchor, чтобы не упиралось в popup-blocker.
    const a = document.createElement('a');
    a.href = url;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
    return;
  }

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
