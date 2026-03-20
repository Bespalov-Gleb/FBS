import { useState, useEffect, useRef } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Typography,
  Box,
  Chip,
  Divider,
} from '@mui/material';
import LocalPrintshop from '@mui/icons-material/LocalPrintshop';
import type { Order, Marketplace } from '../../types/api';
import { ordersApi } from '../../api/orders';
import { printViaAgent } from '../../api/printAgent';
import { loadBlobIntoWindow, openBlankWindow, openBlobInNewWindow } from '../../utils/printUtils';
import { getProductImageUrl } from '../../api/client';
import { palette } from '../../theme/theme';

async function extractErrorMessage(err: unknown): Promise<string | null> {
  const res = err && typeof err === 'object' && 'response' in err
    ? (err as { response?: { data?: unknown; status?: number } }).response
    : null;
  if (!res?.data) return null;
  let data = res.data;
  if (data instanceof Blob) {
    try {
      const text = await data.text();
      if (text && (data.type?.includes('json') || text.trim().startsWith('{'))) {
        data = JSON.parse(text);
      } else {
        return text?.slice(0, 200) || null;
      }
    } catch {
      return null;
    }
  }
  if (typeof data === 'string') return data;
  // FastAPI: { detail: "..." } или { error: { message, detail } }
  const errObj = data && typeof data === 'object' ? data as Record<string, unknown> : null;
  if (errObj) {
    const d = errObj.detail ?? errObj.message;
    if (d) return Array.isArray(d) ? String(d[0]) : String(d);
    const errBlock = errObj.error;
    if (errBlock && typeof errBlock === 'object') {
      const eb = errBlock as Record<string, unknown>;
      const msg = eb.detail ?? eb.message;
      if (msg) return Array.isArray(msg) ? String(msg[0]) : String(msg);
    }
  }
  return null;
}

interface OrderModalProps {
  order: Order | null;
  marketplaces: Marketplace[];
  /** Автопечать дубля КИЗ после скана (из диспетчера печати) */
  autoPrintKizDuplicate?: boolean;
  /** Формат этикетки 58/80 мм для WB */
  labelFormat?: '58mm' | '80mm';
  /** Режим печати этикеток: as_is_fit → fit, standard_58x40_noscale → noscale */
  labelPrintMode?: 'as_is_fit' | 'standard_58x40_noscale';
  /** Агент печати доступен — тихая печать без диалога */
  agentAvailable?: boolean;
  /** Принтер по умолчанию (для агента) */
  defaultPrinter?: string;
  onClose: () => void;
  onComplete: () => void;
}

const KIZ_MAX_LENGTH = 31;

export default function OrderModal({ order, marketplaces, autoPrintKizDuplicate = true, labelFormat: labelFormatProp, labelPrintMode, agentAvailable = false, defaultPrinter, onClose, onComplete }: OrderModalProps) {
  const kizCount = order?.quantity ?? 1;
  const [kizCodes, setKizCodes] = useState<string[]>(() => Array.from({ length: kizCount }, () => ''));
  const [completing, setCompleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [imageError, setImageError] = useState(false);
  const kizPrintedRef = useRef<Set<string>>(new Set());
  const kizInputRefs = useRef<(HTMLInputElement | null)[]>([]);
  const kizDebounceByIndexRef = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());
  const prevKizValuesRef = useRef<string[]>([]);

  const marketplace = order ? marketplaces.find((m) => m.id === order.marketplace_id) : null;
  const isKizRequired = order?.is_kiz_enabled ?? marketplace?.is_kiz_enabled ?? false;
  const isCompleted = order?.status === 'completed';

  useEffect(() => {
    if (order) {
      const n = order.quantity ?? 1;
      setKizCodes(Array.from({ length: n }, () => ''));
      setError(null);
      setImageError(false);
      kizPrintedRef.current = new Set();
      kizDebounceByIndexRef.current.forEach((t) => clearTimeout(t));
      kizDebounceByIndexRef.current.clear();
      prevKizValuesRef.current = [];
    }
  }, [order?.id]);

  // Фокус на первое поле КИЗ при открытии модалки (после рендера полей)
  useEffect(() => {
    if (order && isKizRequired && !isCompleted && kizCount > 0) {
      const t = setTimeout(() => kizInputRefs.current[0]?.focus(), 150);
      return () => clearTimeout(t);
    }
  }, [order?.id, isKizRequired, isCompleted, kizCount]);

  // Очистка таймеров только при размонтировании
  useEffect(
    () => () => {
      kizDebounceByIndexRef.current.forEach((t) => clearTimeout(t));
      kizDebounceByIndexRef.current.clear();
    },
    [],
  );

  // Автопечать дубля КИЗ (debounce 500ms). Таймер по индексу поля — ввод во 2-е не сбрасывает 1-е.
  useEffect(() => {
    if (!order || !isKizRequired || isCompleted || !autoPrintKizDuplicate) return;

    const prev = prevKizValuesRef.current;
    kizCodes.forEach((raw, i) => {
      const kizFull = raw.trim();
      if (!kizFull) {
        const t = kizDebounceByIndexRef.current.get(i);
        if (t) {
          clearTimeout(t);
          kizDebounceByIndexRef.current.delete(i);
        }
        return;
      }
      if (prev[i] === kizFull) return;
      const t = kizDebounceByIndexRef.current.get(i);
      if (t) clearTimeout(t);
      kizDebounceByIndexRef.current.set(
        i,
        setTimeout(() => {
          kizDebounceByIndexRef.current.delete(i);
          if (kizPrintedRef.current.has(kizFull)) return;
          kizPrintedRef.current.add(kizFull);
          ordersApi.getKizLabelBlob(kizFull).then(async (blob) => {
            if (agentAvailable) {
              await printViaAgent(blob, undefined, 'noscale');
            } else {
              openBlobInNewWindow(blob);
            }
          }).catch(() => {});
        }, 500),
      );
    });
    prevKizValuesRef.current = [...kizCodes];
  }, [order?.id, kizCodes, isKizRequired, isCompleted, autoPrintKizDuplicate, agentAvailable]);

  if (!order) return null;

  const imageUrl = getProductImageUrl(order.product_image_url);
  // Ozon: posting_number (85500607-0760-1). WB: external_id (4712812320 — ID сборочного задания)
  const displayId =
    order.marketplace_type === 'ozon'
      ? (order.posting_number || order.external_id || `#${order.id}`)
      : (order.external_id || order.posting_number || `#${order.id}`);
  // PDF при агенте — точный размер 58×40 мм, печать 100% (noscale)
  const labelFormat = agentAvailable ? 'pdf' : (order.marketplace_type === 'ozon' ? 'pdf' : 'svg');
  const labelWidth = labelFormatProp === '80mm' ? 80 : 58;

  const labelPrintScale = labelPrintMode === 'as_is_fit' ? 'fit' as const : 'noscale' as const;
  const handlePrint = async () => {
    setError(null);

    // Для режима без агента: открываем два пустых окна синхронно до await,
    // чтобы popup-blocker не убил второе окно.
    const shouldOpenPopups = !agentAvailable;
    const barcodesWin = shouldOpenPopups ? openBlankWindow() : null;
    const labelWin = shouldOpenPopups ? openBlankWindow() : null;

    try {
      const lw = labelFormatProp === '80mm' ? 80 : 58;
      // Загружаем оба blob одновременно; при выключенном агенте открываем окна синхронно
      const [barcodesBlob, blob] = await Promise.all([
        ordersApi.getBarcodesPdfBlob(order.id, lw).catch(() => null),
        ordersApi.getLabelBlob(
          order.id,
          labelFormat,
          order.marketplace_type === 'wildberries' ? labelWidth : undefined,
        ),
      ]);
      if (agentAvailable) {
        if (barcodesBlob) await printViaAgent(barcodesBlob, defaultPrinter, 'noscale');
        await printViaAgent(blob, defaultPrinter, labelPrintScale);
      } else {
        // Если окна создались — подставляем в них blob URL.
        // Если окно не создалось — пробуем стандартное открытие.
        if (barcodesBlob) {
          loadBlobIntoWindow(barcodesWin, barcodesBlob);
          if (!barcodesWin) openBlobInNewWindow(barcodesBlob);
        }
        if (blob) {
          loadBlobIntoWindow(labelWin, blob);
          if (!labelWin) openBlobInNewWindow(blob, { forceAnchor: true });
        } else {
          setError('ФБС этикетка не сформировалась (blob пустой)');
        }
      }
    } catch (err: unknown) {
      const msg = await extractErrorMessage(err);
      setError(msg || 'Ошибка загрузки этикетки');
    }
  };

  const handlePrintKizDuplicate = async () => {
    const trimmed = kizCodes.map((k) => k.trim()).filter(Boolean);
    if (!trimmed.length) return;
    try {
      for (const kiz of trimmed) {
        const blob = await ordersApi.getKizLabelBlob(kiz);
        if (agentAvailable) {
          await printViaAgent(blob, defaultPrinter, 'noscale');
        } else {
          openBlobInNewWindow(blob);
        }
      }
    } catch {
      setError('Ошибка печати дубля КИЗ');
    }
  };

  const handleComplete = async () => {
    const trimmed = kizCodes.map((k) => k.trim().slice(0, KIZ_MAX_LENGTH)).filter(Boolean);
    if (isKizRequired && trimmed.length < (order.quantity ?? 1)) {
      setError(`Нужен КИЗ для каждого товара: введите ${order.quantity ?? 1} код(ов) маркировки`);
      return;
    }
    setError(null);
    setCompleting(true);
    try {
      const payload = isKizRequired
        ? (trimmed.length === 1 ? { kiz_code: trimmed[0] } : { kiz_codes: trimmed })
        : undefined;
      await ordersApi.complete(order.id, payload);
      onComplete();
    } catch (err: unknown) {
      const msg = err && typeof err === 'object' && 'response' in err
        ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        : null;
      setError(Array.isArray(msg) ? msg[0] : (msg ?? 'Ошибка'));
    } finally {
      setCompleting(false);
    }
  };

  return (
    <Dialog open={!!order} onClose={onClose} maxWidth="lg" fullWidth disableRestoreFocus sx={{ '& .MuiDialog-paper': { maxWidth: 920 } }}>
      <DialogTitle>{displayId}</DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
          {order.marketplace_type === 'ozon' && order.products && order.products.length > 1 ? (
            <>
              <Typography variant="body2">
                <strong>Количество:</strong>{' '}
                <Box component="span" sx={{ color: order.quantity >= 2 ? palette.accent.red : 'inherit', fontWeight: 600 }}>
                  {order.quantity}
                </Box>
              </Typography>
              {order.products.map((p, i) => (
                <Box key={p.offer_id + i}>
                  {i > 0 && <Divider sx={{ my: 1 }} />}
                  <Box sx={{ display: 'flex', gap: 1.5, alignItems: 'flex-start' }}>
                    {getProductImageUrl(p.image_url) && (
                      <Box
                        component="img"
                        src={getProductImageUrl(p.image_url)!}
                        alt={p.name}
                        sx={{ width: 90, height: 90, objectFit: 'cover', borderRadius: 1, flexShrink: 0 }}
                      />
                    )}
                    <Box sx={{ flex: 1, minWidth: 0 }}>
                      <Typography variant="body2" sx={{ wordBreak: 'break-word', overflowWrap: 'anywhere' }}>
                        <strong>{p.offer_id}</strong>
                      </Typography>
                      <Typography variant="body2" color="text.secondary">{p.name}</Typography>
                      <Typography
                        variant="caption"
                        sx={{ color: order.quantity >= 2 ? palette.accent.red : 'inherit', fontWeight: order.quantity >= 2 ? 600 : 400 }}
                      >
                        ×{p.quantity}
                      </Typography>
                    </Box>
                  </Box>
                </Box>
              ))}
            </>
          ) : (
            <Box sx={{ display: 'flex', gap: 1.5, alignItems: 'flex-start' }}>
              {imageUrl && !imageError && (
                <Box
                  component="img"
                  src={imageUrl}
                  alt={order.product_name}
                  onError={() => setImageError(true)}
                  sx={{
                    width: 130,
                    height: 130,
                    objectFit: 'cover',
                    borderRadius: 1,
                    flexShrink: 0,
                  }}
                />
              )}
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Typography
                  variant="body1"
                  sx={{ wordBreak: 'break-word', overflowWrap: 'anywhere' }}
                >
                  <strong>Артикул:</strong> {order.article}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {order.product_name}
                </Typography>
                {order.marketplace_type !== 'ozon' && (
                  <Typography variant="body2">
                    <strong>Размер:</strong>{' '}
                    <Box component="span" color={order.size ? 'text.primary' : 'text.disabled'}>
                      {order.size || '—'}
                    </Box>
                  </Typography>
                )}
              <Typography variant="body2">
                <strong>Количество:</strong>{' '}
                <Box component="span" sx={{ color: order.quantity >= 2 ? palette.accent.red : 'inherit', fontWeight: 600 }}>
                  {order.quantity}
                </Box>
              </Typography>
              </Box>
            </Box>
          )}
          {order.warehouse_name && (
            <Box>
              <Chip
                label={order.warehouse_name}
                size="small"
                sx={{
                  bgcolor: order.warehouse_color || '#4a5568',
                  color: '#fff',
                }}
              />
            </Box>
          )}
          {order.marketplace_type && (
            <Typography variant="caption" color="text.secondary">
              {order.marketplace_type === 'ozon' ? 'Ozon' : 'WB'}
            </Typography>
          )}
          {isKizRequired && !isCompleted && (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              {kizCodes.map((code, i) => (
                <TextField
                  key={i}
                  inputRef={(el) => { kizInputRefs.current[i] = el; }}
                  label={kizCount > 1 ? `КИЗ товара ${i + 1}` : 'КИЗ (отсканируйте или введите)'}
                  value={code}
                  onChange={(e) => {
                    const next = [...kizCodes];
                    next[i] = e.target.value.slice(0, KIZ_MAX_LENGTH);
                    setKizCodes(next);
                  }}
                  fullWidth
                  size="small"
                  error={!!error && !code.trim()}
                  placeholder="Сканируйте код маркировки"
                  inputProps={{ autoComplete: 'off' }}
                />
              ))}
              {kizCodes.some((k) => k.trim()) && (
                <Button
                  size="small"
                  startIcon={<LocalPrintshop />}
                  onClick={handlePrintKizDuplicate}
                  variant="outlined"
                >
                  Печать дубля КИЗ
                </Button>
              )}
            </Box>
          )}
          {error && (
            <Typography variant="body2" color="error">
              {error}
            </Typography>
          )}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Закрыть</Button>
        {!isCompleted && (
          <>
            <Button startIcon={<LocalPrintshop />} onClick={handlePrint}>
              Печать этикеток
            </Button>
            <Button
              variant="contained"
              onClick={handleComplete}
              disabled={completing || (isKizRequired && kizCodes.filter((k) => k.trim()).length < (order.quantity ?? 1))}
            >
              Собрано
            </Button>
          </>
        )}
      </DialogActions>
    </Dialog>
  );
}
