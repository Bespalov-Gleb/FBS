import { Box } from '@mui/material';
import OrderCard from './OrderCard';
import type { Order } from '../../types/api';

interface OrderCardGridProps {
  orders: Order[];
  onOrderClick: (order: Order) => void;
}

export default function OrderCardGrid({ orders, onOrderClick }: OrderCardGridProps) {
  const active = orders.filter((o) => o.status !== 'completed');
  const completed = orders.filter((o) => o.status === 'completed');

  return (
    <Box>
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))',
          gap: 2,
        }}
      >
        {active.map((order) => (
          <OrderCard key={order.id} order={order} onClick={() => onOrderClick(order)} />
        ))}
      </Box>
      {completed.length > 0 && (
        <>
          <Box
            sx={{
              my: 2,
              display: 'flex',
              alignItems: 'center',
              '&::before, &::after': {
                content: '""',
                flex: 1,
                height: 1,
                bgcolor: 'divider',
              },
            }}
          >
            <Box component="span" sx={{ px: 2, color: 'text.secondary', fontSize: '0.875rem' }}>
              Собранные
            </Box>
          </Box>
          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))',
              gap: 2,
            }}
          >
            {completed.map((order) => (
              <OrderCard key={order.id} order={order} onClick={() => onOrderClick(order)} />
            ))}
          </Box>
        </>
      )}
    </Box>
  );
}
