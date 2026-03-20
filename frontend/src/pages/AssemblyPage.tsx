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
import DeleteSweep from '@mui/icons-material/DeleteSweep';
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
import { openBlobInNewWindow, openBlobInSameTab } from '../utils/printUtils';
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
  const [kizClearConfirm, setKizClearConfirm] = useState(false);

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

  const completedParams = {
    skip: 0,
    limit: 50,
    marketplace_ids: filters.marketplace_ids.length > 0 ? filters.marketplace_ids : undefined,
    marketplace_types: filters.marketplace_types.length > 0 ? filters.marketplace_types : undefined,
    warehouse_ids: filters.warehouse_ids.length > 0 ? filters.warehouse_ids : undefined,
    search: filters.search || undefined,
    sort_by: 'completed_at',
    sort_desc: true,
  };
  const { data: completedData } = useQuery({
    queryKey: ['orders-completed', completedParams],
    queryFn: () => ordersApi.listCompleted(completedParams),
  });
  const completedOrders = completedData?.items ?? [];

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

  const { data: kizScansData } = useQuery({
    queryKey: ['kiz-scans-count'],
    queryFn: () => ordersApi.getKizScansCount(),
  });
  const kizScansCount = kizScansData?.count ?? 0;

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

  const clearKizMutation = useMutation({
    mutationFn: () => ordersApi.clearKizScans(),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['kiz-scans-count'] });
      setKizClearConfirm(false);
      setSnackbar({ message: `Таблица очищена. Удалено записей: ${res.deleted}` });
    },
    onError: () => {
      setSnackbar({ message: 'Ошибка очистки таблицы КИЗ' });
    },
  });

  const handleClearKiz = () => {
    if (kizClearConfirm) {
      clearKizMutation.mutate();
    } else {
      setKizClearConfirm(true);
      setSnackbar({ message: 'Нажмите ещё раз для подтверждения очистки' });
      setTimeout(() => setKizClearConfirm(false), 3000);
    }
  };

  const labelPrintScale = printSettings?.label_print_mode === 'as_is_fit' ? 'fit' as const : 'noscale' as const;
  // Для печати FBS этикеток через агент: поворачиваем содержимое, чтобы оно занимало весь стикер.
  const labelPrintSettingsAgent = labelPrintScale === 'noscale' ? 'noscale,landscape' : 'fit,landscape';
  const printBlob = async (
    blob: Blob,
    options?: {
      noFallback?: boolean;
      printScale?:
        | 'fit'
        | 'noscale'
        | 'fit,landscape'
        | 'noscale,landscape'
        | 'fit,portrait'
        | 'noscale,portrait';
    },
  ) => {
    const scale = options?.printScale ?? 'noscale';
    if (agentAvailable) {
      const ok = await printViaAgent(blob, printSettings?.default_printer || undefined, scale);
      if (ok) return;
    }
    openBlobInNewWindow(blob);
  };

  const handleOrderClick = async (order: Order) => {
    if (order.is_locked_by_other) return;
    if (order.status === 'completed') {
      setSelectedOrder(order);
      return;
    }

    const shouldAutoPrint = printSettings?.auto_print_on_click !== false;

    try {
      await ordersApi.claim(order.id);
      setSelectedOrder(order);
      // ТЗ: при клике печатать 2 этикетки (если включено в диспетчере)
      if (shouldAutoPrint) {
        // PDF при агенте — точный размер 58×40 мм, печать 100% (noscale)
        const labelFormat = agentAvailable ? 'pdf' : (order.marketplace_type === 'ozon' ? 'pdf' : 'svg');
        const ozonWidth = printSettings?.ozon_labels?.width_mm ?? (printSettings?.label_format === '80mm' ? 80 : 58);
        const wbWidth = printSettings?.wb_labels?.width_mm ?? (printSettings?.label_format === '80mm' ? 80 : 58);
        const wbHeight = printSettings?.wb_labels?.height_mm ?? 40;
        try {
          const labelWidthForBarcode =
            order.marketplace_type === 'ozon' ? ozonWidth : wbWidth;
          // Загружаем оба blob одновременно; при выключенном агенте открываем окна синхронно
          const [barcodesBlob, labelBlob] = await Promise.all([
            ordersApi.getBarcodesPdfBlob(order.id, labelWidthForBarcode).catch(() => null),
            ordersApi.getLabelBlob(
              order.id,
              labelFormat,
              order.marketplace_type === 'wildberries' ? wbWidth : undefined,
              order.marketplace_type === 'wildberries' ? wbHeight : undefined,
            ),
          ]);
          if (agentAvailable) {
            if (barcodesBlob) await printBlob(barcodesBlob, { printScale: 'noscale' });
            await printBlob(labelBlob, { noFallback: !!barcodesBlob, printScale: labelPrintSettingsAgent });
          } else {
            if (barcodesBlob) openBlobInNewWindow(barcodesBlob);
            if (labelBlob) openBlobInSameTab(labelBlob);
            else {
              setSnackbar({ message: 'ФБС этикетка не сформировалась (labelBlob пустой)' });
            }
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
            disabled={kizScansCount === 0}
          >
            Скачать КИЗ {kizScansCount > 0 && `(${kizScansCount})`}
          </Button>
          <Button
            startIcon={<DeleteSweep />}
            onClick={handleClearKiz}
            disabled={kizScansCount === 0 || clearKizMutation.isPending}
            color={kizClearConfirm ? 'error' : 'inherit'}
          >
            Очистить таблицу
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
          <OrderCardGrid
            orders={orders}
            completedOrders={completedOrders}
            onOrderClick={handleOrderClick}
          />
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
        labelPrintMode={printSettings?.label_print_mode}
        agentAvailable={agentAvailable}
        defaultPrinter={printSettings?.default_printer}
        onClose={handleModalClose}
        onComplete={() => {
          refetch();
          queryClient.invalidateQueries({ queryKey: ['orders-completed'] });
          queryClient.invalidateQueries({ queryKey: ['kiz-scans-count'] });
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
