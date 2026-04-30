import { useState, useEffect, useRef } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  IconButton,
  Button,
  TextField,
  Typography,
  Box,
  Chip,
  Divider,
} from '@mui/material';
import LocalPrintshop from '@mui/icons-material/LocalPrintshop';
import Close from '@mui/icons-material/Close';
import type { Order, Marketplace } from '../../types/api';
import { ordersApi } from '../../api/orders';
import { printViaAgent } from '../../api/printAgent';
import { openBlobInNewWindow, openBlobInSameTab } from '../../utils/printUtils';
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

// Полный КИЗ нужен для WB API и корректного DataMatrix; 31 символ — только человекочитаемая часть.
const KIZ_MAX_LENGTH = 255;

function normalizeKizInput(raw: string): string {
  let s = (raw || '').replace(/[\r\n\t]/g, '').trim();
  // AIM-префиксы некоторых сканеров DataMatrix (не часть самого кода).
  s = s.replace(/^\](?:C1|c1|D2|d2|Q3|q3)/, '');
  // Убираем ведущие служебные символы кроме GS (0x1D), который может быть частью GS1.
  s = s.replace(/^[\u0000-\u001c\u001e-\u001f]+/g, '');
  return s;
}

export default function OrderModal({ order, marketplaces, autoPrintKizDuplicate = true, labelFormat: labelFormatProp, agentAvailable = false, defaultPrinter, onClose, onComplete }: OrderModalProps) {
  const kizCount = order?.quantity ?? 1;
  const [kizCodes, setKizCodes] = useState<string[]>(() => Array.from({ length: kizCount }, () => ''));
  const [loadingSuggestedKiz, setLoadingSuggestedKiz] = useState(false);
  const [suggestedKizReason, setSuggestedKizReason] = useState<string | null>(null);
  const [completing, setCompleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [imageError, setImageError] = useState(false);
  const [previewImage, setPreviewImage] = useState<string | null>(null);
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
      setLoadingSuggestedKiz(false);
      setSuggestedKizReason(null);
      setError(null);
      setImageError(false);
      kizPrintedRef.current = new Set();
      kizDebounceByIndexRef.current.forEach((t) => clearTimeout(t));
      kizDebounceByIndexRef.current.clear();
      prevKizValuesRef.current = [];
    }
  }, [order?.id]);

  useEffect(() => {
    if (!order || !isKizRequired || isCompleted) return;
    let cancelled = false;
    setLoadingSuggestedKiz(true);
    ordersApi.suggestKizCodes(order.id)
      .then(({ kiz_codes, reason }) => {
        if (cancelled) return;
        setSuggestedKizReason(reason ?? null);
        if (!kiz_codes.length) return;
        const prepared = Array.from({ length: order.quantity ?? 1 }, (_, i) =>
          normalizeKizInput(kiz_codes[i] ?? '').slice(0, KIZ_MAX_LENGTH),
        );
        setKizCodes(prepared);
      })
      .catch(() => {
        // Ошибку покажет backend при финальном "Собрано", здесь не блокируем работу.
      })
      .finally(() => {
        if (!cancelled) setLoadingSuggestedKiz(false);
      });
    return () => {
      cancelled = true;
    };
  }, [order?.id, isKizRequired, isCompleted]);

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
      const kizFull = normalizeKizInput(raw);
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
              await printViaAgent(blob, undefined, 'noscale', 'kiz');
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
  const orderBarcode = (
    order.barcode ||
    (order as Order & { product_barcode?: string; sku?: string }).product_barcode ||
    (order as Order & { product_barcode?: string; sku?: string }).sku ||
    order.products?.[0]?.barcode ||
    ''
  ).toString().trim();
  // Ozon: posting_number (85500607-0760-1). WB: external_id (4712812320 — ID сборочного задания)
  const displayId =
    order.marketplace_type === 'ozon'
      ? (order.posting_number || order.external_id || `#${order.id}`)
      : (order.external_id || order.posting_number || `#${order.id}`);
  // PDF при агенте — точный размер 58×40 мм, печать 100% (noscale)
  const labelFormat = agentAvailable ? 'pdf' : (order.marketplace_type === 'ozon' ? 'pdf' : 'svg');
  const labelWidth = labelFormatProp === '80mm' ? 80 : 58;

  // Вариант 1: агент печатает строго `noscale`, без поворота/переопределения ориентации.
  // Поворот и увеличение делаем в формировании PDF (backend), чтобы MediaBox/размер страницы не сбивался.
  const labelPrintSettingsAgent = 'noscale' as const;
  const handlePrint = async () => {
    setError(null);

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
        if (barcodesBlob) await printViaAgent(barcodesBlob, defaultPrinter, 'noscale', 'barcode');
        await printViaAgent(blob, defaultPrinter, labelPrintSettingsAgent, 'fbs');
      } else {
        if (barcodesBlob) openBlobInNewWindow(barcodesBlob);
        if (blob) openBlobInSameTab(blob);
        else setError('ФБС этикетка не сформировалась (blob пустой)');
      }
    } catch (err: unknown) {
      const msg = await extractErrorMessage(err);
      setError(msg || 'Ошибка загрузки этикетки');
    }
  };

  const handlePrintKizDuplicate = async () => {
    const trimmed = kizCodes.map((k) => normalizeKizInput(k)).filter(Boolean);
    if (!trimmed.length) return;
    try {
      for (const kiz of trimmed) {
        const blob = await ordersApi.getKizLabelBlob(kiz);
        if (agentAvailable) {
          await printViaAgent(blob, defaultPrinter, 'noscale', 'kiz');
        } else {
          openBlobInNewWindow(blob);
        }
      }
    } catch {
      setError('Ошибка печати дубля КИЗ');
    }
  };

  const handleComplete = async () => {
    const trimmed = kizCodes.map((k) => normalizeKizInput(k).slice(0, KIZ_MAX_LENGTH)).filter(Boolean);
    setError(null);
    setCompleting(true);
    try {
      const payload = isKizRequired
        ? (trimmed.length === 0
          ? undefined
          : (trimmed.length === 1 ? { kiz_code: trimmed[0] } : { kiz_codes: trimmed }))
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
                        onClick={() => setPreviewImage(getProductImageUrl(p.image_url)!)}
                        sx={{ width: 90, height: 90, objectFit: 'cover', borderRadius: 1, flexShrink: 0 }}
                      />
                    )}
                    <Box sx={{ flex: 1, minWidth: 0 }}>
                      <Typography variant="body1" sx={{ wordBreak: 'break-word', overflowWrap: 'anywhere', fontWeight: 600 }}>
                        <strong>{p.offer_id}</strong>
                      </Typography>
                      <Typography variant="body2">
                        <strong>ШК:</strong>{' '}
                        {(p.barcode || (p as typeof p & { sku?: string }).sku || '—').toString().trim() || '—'}
                      </Typography>
                      <Typography variant="body1" color="text.secondary">{p.name}</Typography>
                      <Typography
                        variant="body1"
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
                  onClick={() => setPreviewImage(imageUrl)}
                  onError={() => setImageError(true)}
                  sx={{
                    width: 130,
                    height: 130,
                    objectFit: 'cover',
                    borderRadius: 1,
                    flexShrink: 0,
                    cursor: 'zoom-in',
                  }}
                />
              )}
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Typography
                  variant="h6"
                  sx={{ wordBreak: 'break-word', overflowWrap: 'anywhere' }}
                >
                  <strong>Артикул:</strong> {order.article}
                </Typography>
                <Typography variant="body1" color="text.secondary">
                  {order.product_name}
                </Typography>
                <Typography variant="body1">
                  <strong>ШК:</strong>{' '}
                  <Box component="span" color={orderBarcode ? 'text.primary' : 'text.disabled'}>
                    {orderBarcode || '—'}
                  </Box>
                </Typography>
                {order.marketplace_type !== 'ozon' && (
                  <Typography variant="body1">
                    <strong>Размер:</strong>{' '}
                    <Box component="span" color={order.size ? 'text.primary' : 'text.disabled'}>
                      {order.size || '—'}
                    </Box>
                  </Typography>
                )}
              <Typography variant="body1">
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
              <Typography variant="caption" color="text.secondary">
                КИЗ подставляется автоматически по настройкам администратора (FIFO). Поля ниже можно использовать только как ручное переопределение.
              </Typography>
              {loadingSuggestedKiz && (
                <Typography variant="caption" color="text.secondary">
                  Подбираем КИЗ из пула...
                </Typography>
              )}
              {!loadingSuggestedKiz && suggestedKizReason && (
                <Typography variant="caption" color="warning.main">
                  Автоподбор КИЗ: {suggestedKizReason}
                </Typography>
              )}
              {kizCodes.map((code, i) => (
                <TextField
                  key={i}
                  inputRef={(el) => { kizInputRefs.current[i] = el; }}
                  label={kizCount > 1 ? `КИЗ товара ${i + 1} (опционально)` : 'КИЗ (опционально)'}
                  value={code}
                  onChange={(e) => {
                    const next = [...kizCodes];
                    next[i] = normalizeKizInput(e.target.value).slice(0, KIZ_MAX_LENGTH);
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
              disabled={completing}
            >
              Собрано
            </Button>
          </>
        )}
      </DialogActions>

      <Dialog
        open={!!previewImage}
        onClose={() => setPreviewImage(null)}
        maxWidth="lg"
        fullWidth
      >
        <DialogTitle sx={{ pr: 6 }}>
          Просмотр изображения
          <IconButton
            onClick={() => setPreviewImage(null)}
            sx={{ position: 'absolute', right: 8, top: 8 }}
          >
            <Close />
          </IconButton>
        </DialogTitle>
        <DialogContent sx={{ display: 'flex', justifyContent: 'center', p: 2 }}>
          {previewImage && (
            <Box
              component="img"
              src={previewImage}
              alt="Предпросмотр товара"
              sx={{
                width: '100%',
                maxHeight: '75vh',
                objectFit: 'contain',
                borderRadius: 1,
              }}
            />
          )}
        </DialogContent>
      </Dialog>
    </Dialog>
  );
}
