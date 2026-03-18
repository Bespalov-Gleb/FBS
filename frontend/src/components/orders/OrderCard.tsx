import { useState } from 'react';
import { Card, CardContent, Typography, Chip, Box, Divider } from '@mui/material';
import type { Order, OrderProduct } from '../../types/api';
import { palette } from '../../theme/theme';
import { getProductImageUrl } from '../../api/client';

interface OrderCardProps {
  order: Order;
  onClick: () => void;
}

function ProductRow({ product, highlightQuantity }: { product: OrderProduct; highlightQuantity?: boolean }) {
  const [imgErr, setImgErr] = useState(false);
  const imgUrl = getProductImageUrl(product.image_url);
  const glow = highlightQuantity ?? (product.quantity >= 2);
  return (
    <Box sx={{ display: 'flex', gap: 1, alignItems: 'flex-start', py: 0.5 }}>
      {imgUrl && !imgErr && (
        <Box
          component="img"
          src={imgUrl}
          alt={product.name}
          onError={() => setImgErr(true)}
          sx={{ width: 64, height: 64, objectFit: 'cover', borderRadius: 1, flexShrink: 0 }}
        />
      )}
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Typography
          variant="caption"
          color="text.primary"
          sx={{ lineHeight: 1.3, display: 'block', wordBreak: 'break-word' }}
        >
          {product.offer_id || product.name}
        </Typography>
        <Typography
          variant="caption"
          sx={{
            fontWeight: 500,
            color: glow ? palette.accent.red : palette.text.secondary,
          }}
        >
          ×{product.quantity}
        </Typography>
      </Box>
    </Box>
  );
}

export default function OrderCard({ order, onClick }: OrderCardProps) {
  const [imageError, setImageError] = useState(false);
  const imageUrl = getProductImageUrl(order.product_image_url);
  // Ozon: posting_number (номер отправления). WB: external_id (ID сборочного задания) — как в модалке
  const displayId =
    order.marketplace_type === 'ozon'
      ? (order.posting_number || order.external_id || `#${order.id}`)
      : (order.external_id || order.posting_number || `#${order.id}`);
  const isLockedByOther = order.is_locked_by_other;
  const isLockedByMe = order.is_locked_by_me;
  const isCompleted = order.status === 'completed';
  const borderColor = order.warehouse_color || palette.sidebar.lighter;
  const isOzonMulti = order.marketplace_type === 'ozon' && order.products && order.products.length > 1;

  return (
    <Card
      onClick={isLockedByOther ? undefined : onClick}
      sx={{
        cursor: isLockedByOther ? 'not-allowed' : 'pointer',
        opacity: isLockedByOther ? 0.8 : 1,
        borderLeft: 4,
        borderLeftColor: borderColor,
        '&:hover': isLockedByOther ? {} : { boxShadow: 2 },
      }}
    >
      <CardContent sx={{ p: '10px !important', '&:last-child': { pb: '10px !important' } }}>
        {isOzonMulti ? (
          <>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 0.5 }}>
              <Typography variant="body2" fontWeight={600} noWrap sx={{ fontSize: '0.75rem' }}>
                {displayId}
              </Typography>
              <Chip
                label={isCompleted ? 'Собран' : 'New'}
                size="small"
                color={isCompleted ? 'success' : 'default'}
                variant={isCompleted ? 'filled' : 'outlined'}
                sx={{ fontSize: '0.6rem', height: 18, '& .MuiChip-label': { px: 0.75 } }}
              />
            </Box>
            {order.products!.map((p, i) => (
              <Box key={p.offer_id + i}>
                {i > 0 && <Divider sx={{ my: 0.25 }} />}
                <ProductRow product={p} highlightQuantity={order.quantity >= 2} />
              </Box>
            ))}
            <Box sx={{ display: 'flex', gap: 0.5, mt: 0.5, flexWrap: 'wrap', alignItems: 'center' }}>
              <Typography
                variant="caption"
                component="span"
                sx={{
                  color: order.quantity >= 2 ? palette.accent.red : 'inherit',
                  fontWeight: order.quantity >= 2 ? 600 : 500,
                }}
              >
                ×{order.quantity}
              </Typography>
              {order.warehouse_name && (
                <Chip
                  label={order.warehouse_name}
                  size="small"
                  sx={{ bgcolor: order.warehouse_color || palette.sidebar.lighter, color: '#fff', fontSize: '0.65rem', height: 18, '& .MuiChip-label': { px: 0.75 } }}
                />
              )}
              <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.65rem' }}>Ozon</Typography>
            </Box>
          </>
        ) : (
          <Box sx={{ display: 'flex', gap: 1, mb: 0.5 }}>
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
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <Typography variant="body2" fontWeight={600} noWrap sx={{ fontSize: '0.75rem' }}>
                  {displayId}
                </Typography>
                <Chip
                  label={isCompleted ? 'Собран' : 'New'}
                  size="small"
                  color={isCompleted ? 'success' : 'default'}
                  variant={isCompleted ? 'filled' : 'outlined'}
                  sx={{ fontSize: '0.6rem', height: 18, '& .MuiChip-label': { px: 0.75 } }}
                />
              </Box>
              <Typography
                variant="caption"
                color="text.primary"
                sx={{ fontWeight: 500, display: 'block', wordBreak: 'break-word', overflowWrap: 'anywhere' }}
              >
                {order.article}
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', wordBreak: 'break-word' }}>
                {order.product_name}
                {order.marketplace_type !== 'ozon' && order.size && ` • ${order.size}`}
              </Typography>
              <Box sx={{ display: 'flex', gap: 0.5, mt: 0.5, flexWrap: 'wrap', alignItems: 'center' }}>
              <Typography
                variant="caption"
                component="span"
                sx={{
                  color: order.quantity >= 2 ? palette.accent.red : 'inherit',
                  fontWeight: order.quantity >= 2 ? 600 : 500,
                }}
              >
                ×{order.quantity}
              </Typography>
                {order.warehouse_name && (
                  <Chip
                    label={order.warehouse_name}
                    size="small"
                    sx={{
                      bgcolor: order.warehouse_color || palette.sidebar.lighter,
                      color: '#fff',
                      fontSize: '0.65rem',
                      height: 18,
                      '& .MuiChip-label': { px: 0.75 },
                    }}
                  />
                )}
                {order.marketplace_type && (
                  <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.65rem' }}>
                    {order.marketplace_type === 'ozon' ? 'Ozon' : order.marketplace_type === 'wildberries' ? 'WB' : order.marketplace_type}
                  </Typography>
                )}
              </Box>
            </Box>
          </Box>
        )}
        {isLockedByOther && (
          <Typography variant="caption" color="error" sx={{ display: 'block', mt: 1 }}>
            Занят: {order.assigned_to_name}
          </Typography>
        )}
        {isLockedByMe && (
          <Typography variant="caption" color="success.main" sx={{ display: 'block', mt: 1 }}>
            Вы работаете
          </Typography>
        )}
      </CardContent>
    </Card>
  );
}
