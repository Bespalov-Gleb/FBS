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
import { openBlobInNewWindow } from '../../utils/printUtils';
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
  /** Агент печати доступен — тихая печать без диалога */
  agentAvailable?: boolean;
  /** Принтер по умолчанию (для агента) */
  defaultPrinter?: string;
  onClose: () => void;
  onComplete: () => void;
}

export default function OrderModal({ order, marketplaces, autoPrintKizDuplicate = true, labelFormat: labelFormatProp, agentAvailable = false, defaultPrinter, onClose, onComplete }: OrderModalProps) {
  const [kizCode, setKizCode] = useState('');
  const [completing, setCompleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [imageError, setImageError] = useState(false);
  const kizPrintedRef = useRef<string | null>(null);
  const kizInputRef = useRef<HTMLInputElement>(null);

  const marketplace = order ? marketplaces.find((m) => m.id === order.marketplace_id) : null;
  const isKizRequired = order?.is_kiz_enabled ?? marketplace?.is_kiz_enabled ?? false;
  const isCompleted = order?.status === 'completed';

  useEffect(() => {
    if (order) {
      setKizCode('');
      setError(null);
      setImageError(false);
      kizPrintedRef.current = null;
    }
  }, [order?.id]);

  // Фокус на поле КИЗ при открытии модалки (для товаров с маркировкой)
  useEffect(() => {
    if (order && isKizRequired && !isCompleted) {
      const t = setTimeout(() => kizInputRef.current?.focus(), 100);
      return () => clearTimeout(t);
    }
  }, [order?.id, isKizRequired, isCompleted]);

  // ТЗ: после скана печатать дубль КИЗ сразу же, как у markznak.ru (если включено в диспетчере)
  useEffect(() => {
    if (!order || !isKizRequired || isCompleted || !kizCode.trim() || !autoPrintKizDuplicate) return;
    const kizTrimmed = kizCode.trim().slice(0, 31);
    if (!kizTrimmed || kizPrintedRef.current === kizTrimmed) return;
    kizPrintedRef.current = kizTrimmed;
    ordersApi.getKizLabelBlob(kizTrimmed).then(async (blob) => {
      if (agentAvailable) {
        await printViaAgent(blob);
      } else {
        openBlobInNewWindow(blob);
      }
    }).catch(() => {});
  }, [order, kizCode, isKizRequired, isCompleted, autoPrintKizDuplicate, agentAvailable]);

  if (!order) return null;

  const imageUrl = getProductImageUrl(order.product_image_url);
  // Ozon: posting_number (85500607-0760-1). WB: external_id (4712812320 — ID сборочного задания)
  const displayId =
    order.marketplace_type === 'ozon'
      ? (order.posting_number || order.external_id || `#${order.id}`)
      : (order.external_id || order.posting_number || `#${order.id}`);
  const labelFormat = order.marketplace_type === 'ozon' ? 'pdf' : agentAvailable ? 'png' : 'svg';
  const labelWidth = labelFormatProp === '80mm' ? 80 : 58;

  const handlePrint = async () => {
    setError(null);
    try {
      const blob = await ordersApi.getLabelBlob(
        order.id,
        labelFormat,
        order.marketplace_type === 'wildberries' ? labelWidth : undefined,
      );
      if (agentAvailable) {
        await printViaAgent(blob, defaultPrinter);
      } else {
        openBlobInNewWindow(blob);
      }
    } catch (err: unknown) {
      const msg = await extractErrorMessage(err);
      setError(msg || 'Ошибка загрузки этикетки');
    }
  };

  const handlePrintKizDuplicate = async () => {
    if (!kizCode.trim()) return;
    try {
      const blob = await ordersApi.getKizLabelBlob(kizCode);
      if (agentAvailable) {
        await printViaAgent(blob, defaultPrinter);
      } else {
        openBlobInNewWindow(blob);
      }
    } catch {
      setError('Ошибка печати дубля КИЗ');
    }
  };

  const handleComplete = async () => {
    if (isKizRequired && !kizCode.trim()) {
      setError('Введите КИЗ');
      return;
    }
    setError(null);
    setCompleting(true);
    try {
      await ordersApi.complete(order.id, isKizRequired ? { kiz_code: kizCode.trim().slice(0, 31) } : undefined);
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
    <Dialog open={!!order} onClose={onClose} maxWidth="sm" fullWidth disableRestoreFocus>
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
                        sx={{ width: 56, height: 56, objectFit: 'cover', borderRadius: 1, flexShrink: 0 }}
                      />
                    )}
                    <Box sx={{ flex: 1, minWidth: 0 }}>
                      <Typography variant="body2"><strong>{p.offer_id}</strong></Typography>
                      <Typography variant="body2" color="text.secondary">
                        {p.name}
                        {p.size && ` • ${p.size}`}
                      </Typography>
                      <Typography
                        variant="caption"
                        sx={{ color: p.quantity >= 2 ? palette.accent.red : 'inherit', fontWeight: p.quantity >= 2 ? 600 : 400 }}
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
                    width: 80,
                    height: 80,
                    objectFit: 'cover',
                    borderRadius: 1,
                    flexShrink: 0,
                  }}
                />
              )}
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Typography variant="body1">
                  <strong>Артикул:</strong> {order.article}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {order.product_name}
                  {order.size && ` • Размер: ${order.size}`}
                </Typography>
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
              <TextField
                inputRef={kizInputRef}
                label="КИЗ (отсканируйте или введите)"
                value={kizCode}
                onChange={(e) => setKizCode(e.target.value)}
                fullWidth
                size="small"
                error={!!error && !kizCode.trim()}
                placeholder="Сканируйте код маркировки"
                inputProps={{ autoComplete: 'off' }}
              />
              {kizCode.trim() && (
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
              disabled={completing || (isKizRequired && !kizCode.trim())}
            >
              Собрано
            </Button>
          </>
        )}
      </DialogActions>
    </Dialog>
  );
}
