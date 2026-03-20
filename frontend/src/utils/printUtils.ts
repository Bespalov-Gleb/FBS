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

/**
 * Надёжное создание popup до любых async-await операций.
 * Затем можно подставить в окно blob URL.
 */
export function openBlankWindow(): Window | null {
  try {
    return window.open('about:blank', '_blank', 'noopener,noreferrer');
  } catch {
    return null;
  }
}

/**
 * Загрузить blob в уже открытое окно.
 * Важно: окно должно быть создано синхронно в момент user-gesture (до await).
 */
export function loadBlobIntoWindow(win: Window | null, blob: Blob): void {
  if (!win) return;
  const url = URL.createObjectURL(blob);
  try {
    win.location.href = url;
    win.focus();
  } catch {
    // если окно закрылось/не доступно — просто выходим
  }
  // Освобождаем URL спустя время, чтобы окно успело подхватить blob
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}
