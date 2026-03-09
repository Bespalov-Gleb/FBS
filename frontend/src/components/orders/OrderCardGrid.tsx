import { Box } from '@mui/material';
import OrderCard from './OrderCard';
import type { Order } from '../../types/api';

interface OrderCardGridProps {
  orders: Order[];
  completedOrders?: Order[];
  onOrderClick: (order: Order) => void;
}

export default function OrderCardGrid({ orders, completedOrders = [], onOrderClick }: OrderCardGridProps) {
  const active = orders.filter((o) => o.status !== 'completed');
  const completed = completedOrders.length > 0 ? completedOrders : orders.filter((o) => o.status === 'completed');

  return (
    <Box>
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
          gap: 1.5,
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
              Собрано
            </Box>
          </Box>
          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
              gap: 1.5,
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
