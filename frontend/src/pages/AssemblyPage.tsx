import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import {
  Box,
  Typography,
  Button,
  Snackbar,
  Alert,
  Menu,
  MenuItem,
  Pagination,
  PaginationItem,
} from '@mui/material';
import Sync from '@mui/icons-material/Sync';
import Download from '@mui/icons-material/Download';
import { useSelector } from 'react-redux';
import OrderFilters, { defaultFilters, type OrderFiltersState } from '../components/orders/OrderFilters';
import OrderCardGrid from '../components/orders/OrderCardGrid';
import OrderModal from '../components/orders/OrderModal';
import LoadingSpinner from '../components/common/LoadingSpinner';
import ErrorAlert from '../components/common/ErrorAlert';
import { ordersApi, type OrdersParams } from '../api/orders';
import { marketplacesApi } from '../api/marketplaces';
import { warehousesApi } from '../api/warehouses';
import { printSettingsApi } from '../api/printSettings';
import { isPrintAgentAvailable, printViaAgent } from '../api/printAgent';
import type { Order } from '../types/api';
import type { RootState } from '../store';

export default function AssemblyPage() {
  const queryClient = useQueryClient();
  const user = useSelector((state: RootState) => state.auth.user);
  const isAdmin = user?.role === 'admin';

  const [filters, setFilters] = useState<OrderFiltersState>(defaultFilters);
  const [page, setPage] = useState(1);
  const [selectedOrder, setSelectedOrder] = useState<Order | null>(null);
  const [snackbar, setSnackbar] = useState<{ message: string } | null>(null);
  const [kizMenuAnchor, setKizMenuAnchor] = useState<HTMLElement | null>(null);
  const [agentAvailable, setAgentAvailable] = useState(false);

  useEffect(() => {
    isPrintAgentAvailable().then(setAgentAvailable);
  }, []);

  const pageSize = filters.page_size;
  const params: OrdersParams = {
    skip: (page - 1) * pageSize,
    limit: pageSize,
    marketplace_ids:
      filters.marketplace_ids.length > 0 ? filters.marketplace_ids : undefined,
    marketplace_types:
      filters.marketplace_types.length > 0 ? filters.marketplace_types : undefined,
    warehouse_ids:
      filters.warehouse_ids.length > 0 ? filters.warehouse_ids : undefined,
    status: filters.status || undefined,
    search: filters.search || undefined,
    sort_by: filters.sort_by,
    sort_desc: filters.sort_desc,
  };

  const { data: ordersData, isLoading, error, refetch } = useQuery({
    queryKey: ['orders', params],
    queryFn: () => ordersApi.list(params),
    placeholderData: keepPreviousData,
  });
  const orders = ordersData?.items ?? [];
  const total = ordersData?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  // Сброс на страницу 1 при смене фильтров
  useEffect(() => {
    setPage(1);
  }, [
    filters.marketplace_ids,
    filters.marketplace_types,
    filters.warehouse_ids,
    filters.status,
    filters.search,
    filters.sort_by,
    filters.sort_desc,
    filters.page_size,
  ]);

  // Если страниц стало меньше — перейти на последнюю
  useEffect(() => {
    if (total > 0 && page > totalPages) {
      setPage(totalPages);
    }
  }, [total, page, totalPages]);

  const { data: marketplaces = [] } = useQuery({
    queryKey: ['marketplaces'],
    queryFn: () => marketplacesApi.list(),
    enabled: isAdmin,
  });

  const { data: warehouses = [] } = useQuery({
    queryKey: ['warehouses'],
    queryFn: () => warehousesApi.listAll(),
    enabled: true,
  });

  const { data: printSettings } = useQuery({
    queryKey: ['print-settings'],
    queryFn: () => printSettingsApi.get(),
  });

  const syncMutation = useMutation({
    mutationFn: () => ordersApi.syncAll(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['orders'] });
    },
  });

  const handleSync = () => syncMutation.mutate();

  const handleKizDownload = async (format: 'xlsx' | 'txt') => {
    setKizMenuAnchor(null);
    try {
      const marketplaceId =
        filters.marketplace_ids.length === 1 ? filters.marketplace_ids[0] : undefined;
      const blob = await ordersApi.getKizExportBlob({ marketplace_id: marketplaceId, format });
      const ext = format === 'xlsx' ? 'xlsx' : 'txt';
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `kiz-export.${ext}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setSnackbar({ message: 'Ошибка выгрузки КИЗ' });
    }
  };

  const printBlob = async (blob: Blob, options?: { noFallback?: boolean }) => {
    if (agentAvailable) {
      const ok = await printViaAgent(blob, printSettings?.default_printer || undefined);
      if (ok) return;
    }
    const url = URL.createObjectURL(blob);
    const win = window.open(url, '_blank', 'noopener,noreferrer');
    if (win) win.focus();
    else if (!options?.noFallback) window.location.href = url;
  };

  const handleOrderClick = async (order: Order) => {
    if (order.is_locked_by_other) return;
    if (order.status === 'completed') {
      setSelectedOrder(order);
      return;
    }
    try {
      await ordersApi.claim(order.id);
      setSelectedOrder(order);
      // ТЗ: при клике печатать 2 этикетки (если включено в диспетчере)
      const shouldAutoPrint = printSettings?.auto_print_on_click !== false;
      if (shouldAutoPrint) {
        const labelFormat = order.marketplace_type === 'ozon' ? 'pdf' : agentAvailable ? 'png' : 'svg';
        const labelWidth = printSettings?.label_format === '80mm' ? 80 : 58;
        try {
          const productBarcode = await ordersApi.getProductBarcodeBlob(order.id);
          const labelBlob = await ordersApi.getLabelBlob(
            order.id,
            labelFormat,
            order.marketplace_type === 'wildberries' ? labelWidth : undefined,
          );
          if (productBarcode) await printBlob(productBarcode);
          if (agentAvailable) {
            await printBlob(labelBlob, { noFallback: !!productBarcode });
          } else {
            setTimeout(
              () => printBlob(labelBlob, { noFallback: !!productBarcode }),
              150,
            );
          }
        } catch {
          // игнорируем ошибки печати
        }
      }
    } catch (err: unknown) {
      const res = err && typeof err === 'object' && 'response' in err
        ? (err as { response?: { status?: number; data?: { detail?: { assigned_to_name?: string } } } }).response
        : null;
      if (res?.status === 409) {
        const name = res.data?.detail?.assigned_to_name ?? 'другой упаковщик';
        setSnackbar({ message: `Заказ открыт: ${name}` });
      }
    }
  };

  const handleModalClose = async () => {
    if (selectedOrder && selectedOrder.status !== 'completed') {
      try {
        await ordersApi.release(selectedOrder.id);
      } catch {
        // ignore
      }
    }
    setSelectedOrder(null);
    refetch();
  };

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h4" fontWeight={600}>
          Сборка
        </Typography>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button
            startIcon={<Download />}
            onClick={(e) => setKizMenuAnchor(e.currentTarget)}
          >
            Скачать КИЗ
          </Button>
          <Menu
            anchorEl={kizMenuAnchor}
            open={!!kizMenuAnchor}
            onClose={() => setKizMenuAnchor(null)}
            anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
          >
            <MenuItem onClick={() => handleKizDownload('xlsx')}>Excel (.xlsx)</MenuItem>
            <MenuItem onClick={() => handleKizDownload('txt')}>Текст (.txt)</MenuItem>
          </Menu>
          {isAdmin && (
            <Button
              startIcon={<Sync />}
              onClick={handleSync}
              disabled={syncMutation.isPending}
            >
              Синхронизировать
            </Button>
          )}
        </Box>
      </Box>
      <OrderFilters
        filters={filters}
        onChange={setFilters}
        marketplaces={marketplaces}
        warehouses={warehouses}
      />
      {error && (
        <ErrorAlert
          message={error instanceof Error ? error.message : 'Ошибка загрузки'}
          onRetry={() => refetch()}
        />
      )}
      {isLoading ? (
        <LoadingSpinner />
      ) : (
        <>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
            <Typography variant="body2" color="text.secondary">
              {total} заказов
              {total > 0 && (
                <> (стр. {page} из {totalPages})</>
              )}
            </Typography>
          </Box>
          <OrderCardGrid orders={orders} onOrderClick={handleOrderClick} />
          {totalPages > 1 && (
            <Box sx={{ display: 'flex', justifyContent: 'center', mt: 3, mb: 2 }}>
              <Pagination
                count={totalPages}
                page={page}
                onChange={(_, p) => setPage(p)}
                siblingCount={2}
                boundaryCount={1}
                color="primary"
                showFirstButton
                showLastButton
                renderItem={(item) => (
                  <PaginationItem
                    {...item}
                    sx={{
                      ...(item.type === 'page' && item.page === page
                        ? { fontWeight: 700 }
                        : {}),
                    }}
                  />
                )}
              />
            </Box>
          )}
        </>
      )}
      <OrderModal
        order={selectedOrder}
        marketplaces={marketplaces}
        autoPrintKizDuplicate={printSettings?.auto_print_kiz_duplicate !== false}
        labelFormat={printSettings?.label_format}
        agentAvailable={agentAvailable}
        defaultPrinter={printSettings?.default_printer}
        onClose={handleModalClose}
        onComplete={() => {
          refetch();
          setSelectedOrder(null);
        }}
      />
      <Snackbar
        open={!!snackbar}
        autoHideDuration={4000}
        onClose={() => setSnackbar(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert onClose={() => setSnackbar(null)} severity="info">
          {snackbar?.message}
        </Alert>
      </Snackbar>
    </Box>
  );
}
