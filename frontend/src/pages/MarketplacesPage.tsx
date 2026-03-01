import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Box,
  Typography,
  Card,
  CardContent,
  CardActionArea,
  Button,
  Snackbar,
  Alert,
  Avatar,
  IconButton,
  Chip,
} from '@mui/material';
import Settings from '@mui/icons-material/Settings';
import DeleteOutline from '@mui/icons-material/DeleteOutline';
import { marketplacesApi } from '../api/marketplaces';
import { ordersApi } from '../api/orders';
import AddMarketplaceModal from '../features/marketplaces/AddMarketplaceModal';
import MarketplaceSettingsModal from '../features/marketplaces/MarketplaceSettingsModal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import LoadingSpinner from '../components/common/LoadingSpinner';
import ErrorAlert from '../components/common/ErrorAlert';
import type { Marketplace } from '../types/api';

const MARKETPLACE_OPTIONS = [
  { type: 'ozon', label: 'OZON', color: '#005BFF', bg: '#ffffff', disabled: false },
  {
    type: 'wildberries',
    label: 'WILDBERRIES',
    color: '#ffffff',
    bg: 'linear-gradient(135deg, #8B5CF6 0%, #A855F7 50%, #7C3AED 100%)',
    disabled: false,
  },
];

function getTypeLabel(type: string): string {
  const map: Record<string, string> = {
    ozon: 'Ozon',
    wildberries: 'Wildberries',
    yandex: 'Яндекс.Маркет',
    sber: 'СберМегаМаркет',
  };
  return map[type] ?? type;
}

function getTypeColor(type: string): string {
  const map: Record<string, string> = {
    ozon: '#005BFF',
    wildberries: '#8B5CF6',
  };
  return map[type] ?? '#4a5568';
}

export default function MarketplacesPage() {
  const queryClient = useQueryClient();
  const [addModalType, setAddModalType] = useState<string | null>(null);
  const [settingsId, setSettingsId] = useState<number | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<{ id: number; name: string } | null>(null);
  const [snackbar, setSnackbar] = useState<{ message: string; severity: 'success' | 'error' } | null>(null);

  const { data: marketplaces = [], isLoading, error, refetch } = useQuery({
    queryKey: ['marketplaces'],
    queryFn: () => marketplacesApi.list(),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => marketplacesApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['marketplaces'] });
      setDeleteConfirm(null);
      setSnackbar({ message: 'Маркетплейс удалён', severity: 'success' });
    },
    onError: () => setSnackbar({ message: 'Ошибка удаления', severity: 'error' }),
  });

  const handleAdd = () => {
    setAddModalType(null);
    refetch();
    setSnackbar({ message: 'Маркетплейс подключён', severity: 'success' });
  };

  const handleSettingsClose = () => {
    setSettingsId(null);
    refetch();
  };

  return (
    <Box>
      <Typography variant="h4" fontWeight={600} gutterBottom>
        Маркетплейсы
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Подключите аккаунты маркетплейсов для синхронизации заказов
      </Typography>

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
          <Typography variant="subtitle2" sx={{ mb: 1.5, color: 'text.secondary' }}>
            Добавить интеграцию
          </Typography>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2, mb: 4 }}>
            {MARKETPLACE_OPTIONS.map((item) => (
              <Card
                key={item.type}
                sx={{
                  width: 220,
                  minHeight: 100,
                  opacity: item.disabled ? 0.5 : 1,
                  cursor: item.disabled ? 'not-allowed' : 'pointer',
                  transition: 'transform 0.2s, box-shadow 0.2s',
                  '&:hover': item.disabled
                    ? {}
                    : { transform: 'translateY(-2px)', boxShadow: 3 },
                }}
                onClick={() => !item.disabled && setAddModalType(item.type)}
              >
                <CardActionArea disabled={item.disabled} sx={{ height: '100%', minHeight: 100 }}>
                  <CardContent
                    sx={{
                      py: 2,
                      px: 2,
                      background: item.bg,
                      color: item.color,
                      height: '100%',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    <Typography variant="h6" fontWeight={700} sx={{ textAlign: 'center' }}>
                      {item.label}
                    </Typography>
                    {item.disabled && (
                      <Chip
                        label="Скоро"
                        size="small"
                        sx={{ position: 'absolute', top: 8, right: 8 }}
                      />
                    )}
                  </CardContent>
                </CardActionArea>
              </Card>
            ))}
          </Box>

          <Typography variant="subtitle2" sx={{ mb: 1.5, color: 'text.secondary' }}>
            Подключённые аккаунты
          </Typography>
          {marketplaces.length === 0 ? (
            <Card sx={{ p: 4, textAlign: 'center' }}>
              <Typography color="text.secondary">
                Нет подключённых маркетплейсов. Нажмите на карточку выше, чтобы добавить.
              </Typography>
            </Card>
          ) : (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {marketplaces.map((mp: Marketplace) => (
                <IntegrationCard
                  key={mp.id}
                  marketplace={mp}
                  onSettings={() => setSettingsId(mp.id)}
                  onDelete={() => setDeleteConfirm({ id: mp.id, name: mp.name })}
                />
              ))}
            </Box>
          )}
        </>
      )}

      {addModalType && (
        <AddMarketplaceModal
          type={addModalType}
          onClose={() => setAddModalType(null)}
          onSuccess={handleAdd}
        />
      )}

      {settingsId && (
        <MarketplaceSettingsModal
          marketplaceId={settingsId}
          onClose={handleSettingsClose}
          onSyncOrders={() => {
            ordersApi.syncMarketplace(settingsId).then(() => {
              setSnackbar({ message: 'Заказы синхронизированы', severity: 'success' });
            });
          }}
        />
      )}

      <ConfirmDialog
        open={!!deleteConfirm}
        title="Удалить маркетплейс?"
        message={`Вы уверены, что хотите удалить "${deleteConfirm?.name}"?`}
        confirmLabel="Удалить"
        confirmColor="error"
        onConfirm={() => deleteConfirm && deleteMutation.mutate(deleteConfirm.id)}
        onCancel={() => setDeleteConfirm(null)}
      />

      <Snackbar
        open={!!snackbar}
        autoHideDuration={4000}
        onClose={() => setSnackbar(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert onClose={() => setSnackbar(null)} severity={snackbar?.severity ?? 'success'}>
          {snackbar?.message}
        </Alert>
      </Snackbar>
    </Box>
  );
}

interface IntegrationCardProps {
  marketplace: Marketplace;
  onSettings: () => void;
  onDelete: () => void;
}

function IntegrationCard({ marketplace, onSettings, onDelete }: IntegrationCardProps) {
  const color = getTypeColor(marketplace.type);

  return (
    <Card
      sx={{
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'center',
        overflow: 'hidden',
      }}
    >
      <Box
        sx={{
          width: 6,
          minHeight: 80,
          bgcolor: color,
        }}
      />
      <Box sx={{ display: 'flex', alignItems: 'center', flex: 1, p: 2, gap: 2 }}>
        <Avatar
          sx={{
            bgcolor: color,
            width: 48,
            height: 48,
          }}
        >
          {marketplace.name.charAt(0).toUpperCase()}
        </Avatar>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="subtitle1" fontWeight={600}>
            {marketplace.name}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {getTypeLabel(marketplace.type)}
          </Typography>
        </Box>
        <Button
          variant="contained"
          size="small"
          startIcon={<Settings />}
          onClick={onSettings}
        >
          Настроить...
        </Button>
        <IconButton color="error" onClick={onDelete} size="small" title="Удалить">
          <DeleteOutline />
        </IconButton>
      </Box>
    </Card>
  );
}
